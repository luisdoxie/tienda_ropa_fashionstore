import { TestBed } from '@angular/core/testing';
import { SwUpdate } from '@angular/service-worker';
import { environment } from '../../environments/environment';
import { ConectividadService, TIMEOUT_VERIFICACION_MS } from './conectividad.service';

const URL_SALUD = `${new URL(environment.apiUrl).origin}/health?ngsw-bypass=true`;

function fijarOnLine(valor: boolean): void {
  Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => valor });
}

/** Un fetch que contesta enseguida (ok o con error de servidor). */
function fetchQueResponde(ok: boolean) {
  return vi.fn((_url: string, _init?: RequestInit) => Promise.resolve({ ok } as Response));
}

/** Un fetch que falla de inmediato, como cuando no hay red. */
function fetchQueFalla() {
  return vi.fn((_url: string, _init?: RequestInit) => Promise.reject(new TypeError('Failed to fetch')));
}

/** Un fetch que nunca contesta y solo termina cuando se aborta su señal. */
function fetchColgado() {
  return vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolver, rechazar) => {
        init?.signal?.addEventListener('abort', () => rechazar(new DOMException('Aborted', 'AbortError')));
      }),
  );
}

describe('ConectividadService', () => {
  afterEach(() => {
    delete (navigator as { onLine?: boolean }).onLine;
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function crear(opciones: { swActivo?: boolean } = {}): ConectividadService {
    if (opciones.swActivo !== undefined) {
      TestBed.configureTestingModule({ providers: [{ provide: SwUpdate, useValue: { isEnabled: opciones.swActivo } }] });
    }
    return TestBed.inject(ConectividadService);
  }

  /** Espera a que termine la verificación que disparó un evento (el fetch simulado ya contestó). */
  async function terminarVerificaciones(): Promise<void> {
    for (let i = 0; i < 10; i++) await Promise.resolve();
  }

  it('el estado inicial sale de navigator.onLine: con red es en_linea', () => {
    fijarOnLine(true);
    const servicio = crear();

    expect(servicio.enLinea()).toBe(true);
    expect(servicio.estado()).toBe('en_linea');
    expect(servicio.servidorAlcanzable()).toBeNull();
    expect(servicio.desde()).toBeNull();
  });

  it('el estado inicial sale de navigator.onLine: sin red es sin_conexion y ya tiene "desde"', () => {
    fijarOnLine(false);
    const servicio = crear();

    expect(servicio.enLinea()).toBe(false);
    expect(servicio.estado()).toBe('sin_conexion');
    expect(servicio.desde()).toBeInstanceOf(Date);
  });

  it('el evento offline pasa a sin_conexion y anota desde cuándo', () => {
    fijarOnLine(true);
    const servicio = crear();
    expect(servicio.desde()).toBeNull();

    window.dispatchEvent(new Event('offline'));

    expect(servicio.enLinea()).toBe(false);
    expect(servicio.estado()).toBe('sin_conexion');
    expect(servicio.desde()).toBeInstanceOf(Date);
  });

  it('online con /health correcto vuelve a en_linea y emite volvioConexion$ una sola vez', async () => {
    const fetchSimulado = fetchQueResponde(true);
    vi.stubGlobal('fetch', fetchSimulado);
    fijarOnLine(true);
    const servicio = crear();
    let emisiones = 0;
    servicio.volvioConexion$.subscribe(() => emisiones++);

    window.dispatchEvent(new Event('offline'));
    expect(servicio.estado()).toBe('sin_conexion');
    expect(emisiones).toBe(0);

    window.dispatchEvent(new Event('online'));
    await terminarVerificaciones();

    expect(fetchSimulado).toHaveBeenCalledTimes(1);
    expect(servicio.estado()).toBe('en_linea');
    expect(servicio.servidorAlcanzable()).toBe(true);
    expect(emisiones).toBe(1);

    // Otra comprobación con todo en orden no es una "vuelta": no emite de nuevo.
    expect(await servicio.verificarServidor()).toBe(true);
    expect(emisiones).toBe(1);
  });

  it('online con /health caído queda en servidor_no_responde y no emite; al responder después, sí emite', async () => {
    const fetchSimulado = fetchQueFalla();
    vi.stubGlobal('fetch', fetchSimulado);
    fijarOnLine(true);
    const servicio = crear();
    let emisiones = 0;
    servicio.volvioConexion$.subscribe(() => emisiones++);

    window.dispatchEvent(new Event('offline'));
    window.dispatchEvent(new Event('online'));
    await terminarVerificaciones();

    expect(servicio.enLinea()).toBe(true);
    expect(servicio.servidorAlcanzable()).toBe(false);
    expect(servicio.estado()).toBe('servidor_no_responde');
    expect(emisiones).toBe(0);

    // El servidor vuelve: la recuperación pendiente se confirma y se avisa una vez.
    vi.stubGlobal('fetch', fetchQueResponde(true));
    expect(await servicio.verificarServidor()).toBe(true);
    expect(servicio.estado()).toBe('en_linea');
    expect(emisiones).toBe(1);
  });

  it('un /health que contesta con error (500) cuenta como servidor caído', async () => {
    vi.stubGlobal('fetch', fetchQueResponde(false));
    fijarOnLine(true);
    const servicio = crear();

    expect(await servicio.verificarServidor()).toBe(false);
    expect(servicio.estado()).toBe('servidor_no_responde');
  });

  it('verificarServidor aborta a los 4 s y no antes', async () => {
    vi.useFakeTimers();
    const fetchSimulado = fetchColgado();
    vi.stubGlobal('fetch', fetchSimulado);
    fijarOnLine(true);
    const servicio = crear();

    let resultado: boolean | null = null;
    void servicio.verificarServidor().then((r) => (resultado = r));

    await vi.advanceTimersByTimeAsync(TIMEOUT_VERIFICACION_MS - 1);
    expect(resultado).toBeNull();
    expect((fetchSimulado.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(false);
    expect(servicio.estado()).toBe('en_linea');

    await vi.advanceTimersByTimeAsync(1);
    expect(TIMEOUT_VERIFICACION_MS).toBe(4_000);
    expect((fetchSimulado.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
    expect(resultado).toBe(false);
    expect(servicio.estado()).toBe('servidor_no_responde');
  });

  it('pide /health al origen del servidor, sin caché y esquivando el Service Worker', async () => {
    const fetchSimulado = fetchQueResponde(true);
    vi.stubGlobal('fetch', fetchSimulado);
    fijarOnLine(true);
    const servicio = crear();

    await servicio.verificarServidor();

    const [url, init] = fetchSimulado.mock.calls[0];
    expect(url).toBe(URL_SALUD);
    expect(url).toContain('/health?ngsw-bypass=true');
    expect(url).not.toContain('/api/v1');
    expect(init?.cache).toBe('no-store');
  });

  it('dos comprobaciones a la vez comparten una sola petición', async () => {
    const fetchSimulado = fetchQueResponde(true);
    vi.stubGlobal('fetch', fetchSimulado);
    fijarOnLine(true);
    const servicio = crear();

    const [a, b] = await Promise.all([servicio.verificarServidor(), servicio.verificarServidor()]);

    expect(a).toBe(true);
    expect(b).toBe(true);
    expect(fetchSimulado).toHaveBeenCalledTimes(1);
  });

  it('una respuesta correcta prueba que hay red aunque el navegador diga que no', async () => {
    vi.stubGlobal('fetch', fetchQueResponde(true));
    fijarOnLine(false);
    const servicio = crear();
    let emisiones = 0;
    servicio.volvioConexion$.subscribe(() => emisiones++);
    expect(servicio.estado()).toBe('sin_conexion');

    await servicio.verificarServidor();

    expect(servicio.estado()).toBe('en_linea');
    expect(emisiones).toBe(1);
  });

  it('sin red, una comprobación fallida no cambia el estado: sigue sin_conexion', async () => {
    vi.stubGlobal('fetch', fetchQueFalla());
    fijarOnLine(false);
    const servicio = crear();

    expect(await servicio.verificarServidor()).toBe(false);
    expect(servicio.estado()).toBe('sin_conexion');
  });

  describe('al abrir la app', () => {
    it('con Service Worker activo comprueba el servidor una vez, sin sondeo continuo', async () => {
      vi.useFakeTimers();
      const fetchSimulado = fetchQueResponde(true);
      vi.stubGlobal('fetch', fetchSimulado);
      fijarOnLine(true);
      crear({ swActivo: true });

      await vi.advanceTimersByTimeAsync(10 * 60_000);

      expect(fetchSimulado).toHaveBeenCalledTimes(1);
    });

    it('sin Service Worker (desarrollo y pruebas) no hace ninguna petición', async () => {
      const fetchSimulado = fetchQueResponde(true);
      vi.stubGlobal('fetch', fetchSimulado);
      fijarOnLine(true);
      crear({ swActivo: false });
      await terminarVerificaciones();

      expect(fetchSimulado).not.toHaveBeenCalled();
    });
  });
});
