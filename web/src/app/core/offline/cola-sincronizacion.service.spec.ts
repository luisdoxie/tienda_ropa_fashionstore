import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import Dexie from 'dexie';
import { Subject } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ConectividadService } from '../conectividad.service';
import { SIN_TOAST_ERROR } from '../http-contexts';
import { PlanService } from '../plan.service';
import {
  ColaSincronizacionService,
  MENSAJE_ERROR_FORMATO,
  MOTIVO_DETENIDA,
  esperaBackoffMs,
  leerRetryAfterMs,
} from './cola-sincronizacion.service';
import { BaseOffline } from './db-offline';
import {
  BACKOFF_BASE_MS,
  BACKOFF_TOPE_MS,
  INTENTOS_AUTOMATICOS_MAX,
  INTERVALO_COLA_MS,
  META_REGLAS,
  TAM_LOTE,
} from './offline.config';
import type { AlcanceOffline, EstadoOperacion, OperacionOffline, TipoOperacion } from './offline.models';
import { RepositorioLocal } from './repositorio-local';
import { SesionOfflineService } from './sesion-offline.service';

const API = environment.apiUrl;
const T0 = Date.parse('2026-10-30T12:00:00Z');
const USUARIO = 5;
const OTRO_USUARIO = 6;
const EMPRESA = 1;
const SEG = 1000;

/** Respuesta de mentira del servidor a una petición. */
type Falsa = { status?: number; cuerpo?: unknown; headers?: Record<string, string> } | 'red' | 'colgar';

interface Peticion {
  metodo: string;
  ruta: string;
  cuerpo: any;
  sinToast: boolean;
}

const uuid = (n: number): string => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

/** Una venta de contado lista para enviar; `n` define el id y la fecha (más baja = más antigua). */
function venta(n: number, extra: Partial<OperacionOffline> = {}): OperacionOffline {
  return {
    empresa_id: EMPRESA,
    usuario_id: USUARIO,
    operacion_id: uuid(n),
    tipo: 'venta_contado',
    estado: 'registrada',
    fecha_operacion: new Date(T0 - 3_600_000 + n * 60_000).toISOString(),
    sucursal_id: 1,
    cliente_id: 7,
    cliente_nombre: 'Ana Paz',
    lineas: [
      {
        variante_id: 100 + n,
        producto_nombre: 'Polera básica',
        sku: `SKU-${n}`,
        talla: 'M',
        color: 'Negro',
        cantidad: 2,
        precio_unitario: '149.00',
        descuento_unitario: '10.00',
        subtotal: '278.00',
      },
    ],
    total: '278.00',
    pago: { metodo: 'efectivo', monto_recibido: '300.00', cambio: '22.00' },
    reserva: null,
    codigo_local: `OFF-${n}`,
    creada_en: new Date(T0 - 3_600_000 + n * 60_000).toISOString(),
    dispositivo: 'dispositivo-prueba',
    intentos: 0,
    ultimo_intento_en: null,
    proximo_intento_en: null,
    ultimo_error: null,
    bloqueada: false,
    motivo: null,
    mensaje: null,
    resultado: null,
    ...extra,
  };
}

function reserva(n: number, extra: Partial<OperacionOffline> = {}): OperacionOffline {
  return venta(n, {
    tipo: 'reserva' as TipoOperacion,
    pago: null,
    total: '298.00',
    reserva: { fecha_visita: '2026-11-02', hora_visita_desde: '10:00', hora_visita_hasta: '11:00', observacion: 'Probar talla' },
    lineas: [
      {
        variante_id: 200 + n,
        producto_nombre: 'Camisa lino',
        sku: `SKU-R${n}`,
        talla: 'M',
        color: 'Negro',
        cantidad: 2,
        precio_unitario: '149.00',
        descuento_unitario: '0.00',
        subtotal: '298.00',
      },
    ],
    ...extra,
  });
}

/** El resultado que el servidor da a una operación. */
function resultado(operacionId: string, estado: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    operacion_id: operacionId,
    estado,
    motivo: null,
    mensaje: null,
    duplicada: false,
    procesada_en: '2026-10-30T12:00:01Z',
    recurso: estado === 'confirmada' ? { tipo: 'venta', id: 900, codigo: 'V-0900', total: '278.00' } : null,
    cambio: null,
    avisos: [],
    faltantes: [],
    ...extra,
  };
}

const respuestaLote = (resultados: Record<string, unknown>[]) => ({
  version_contrato: '1.0',
  procesado_en: '2026-10-30T12:00:01Z',
  resumen: { total: resultados.length, confirmadas: 0, rechazadas: 0, en_conflicto: 0, errores_temporales: 0, duplicadas: 0 },
  resultados,
});

describe('ColaSincronizacionService', () => {
  let http: HttpTestingController;
  let servicio: ColaSincronizacionService;
  let base: BaseOffline;
  let repo: RepositorioLocal;
  let nombreBase: string;
  let alcance: ReturnType<typeof signal<AlcanceOffline | null>>;
  let enLinea: ReturnType<typeof signal<boolean>>;
  let volvio: Subject<void>;
  let planIncluye: ReturnType<typeof signal<boolean>>;
  let planActivo: ReturnType<typeof signal<boolean>>;
  let peticiones: Peticion[];
  let alLote: (cuerpo: any, n: number) => Falsa;
  let alConsulta: (operacionId: string) => Falsa;
  let contador = 0;
  let timersAntes = 0;

  const confirmarTodo = (cuerpo: any): Falsa => ({
    cuerpo: respuestaLote(cuerpo.operaciones.map((o: any) => resultado(o.operacion_id, 'confirmada'))),
  });

  beforeEach(async () => {
    // Fechas y temporizadores falsos; los de IndexedDB usan setImmediate (no se falsea), así la base sigue funcionando.
    vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
    vi.setSystemTime(T0);
    // Sin variación en las esperas: 5 s, 10 s, 20 s... exactos.
    vi.spyOn(Math, 'random').mockReturnValue(0.5);

    nombreBase = `cola_sync_prueba_${++contador}_${Math.random().toString(36).slice(2)}`;
    base = new BaseOffline(nombreBase);
    repo = new RepositorioLocal(base, { empresaId: EMPRESA, usuarioId: USUARIO });
    alcance = signal<AlcanceOffline | null>({ empresaId: EMPRESA, usuarioId: USUARIO });
    enLinea = signal(true);
    volvio = new Subject<void>();
    planIncluye = signal(true);
    planActivo = signal(true);
    peticiones = [];
    alLote = confirmarTodo;
    alConsulta = (id) => ({ cuerpo: { operacion_id: id, estado: 'en_conflicto', motivo: 'stock_insuficiente', faltantes: [] } });
    timersAntes = vi.getTimerCount();

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: SesionOfflineService,
          useValue: {
            alcance,
            repositorio: () => (alcance() === null ? null : new RepositorioLocal(base, alcance()!)),
            dispositivoId: () => 'dispositivo-prueba',
          },
        },
        {
          provide: ConectividadService,
          useValue: { enLinea, estado: signal('en_linea'), volvioConexion$: volvio.asObservable() },
        },
        { provide: PlanService, useValue: { estadoActivo: planActivo, incluye: () => planIncluye() } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    servicio = TestBed.inject(ColaSincronizacionService);
    TestBed.tick();
    await reposo();
  });

  afterEach(async () => {
    TestBed.resetTestingModule();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    base.close();
    await Dexie.delete(nombreBase);
  });

  // ---- Un servidor de mentira ----------------------------------------------------------------------------------------------

  // `setImmediate` no se falsea (como en IndexedDB falso): sirve para ceder el turno aunque setTimeout sea falso.
  const inmediato = (globalThis as unknown as { setImmediate: (tarea: () => void) => void }).setImmediate;
  const ceder = () => new Promise<void>((resolver) => inmediato(resolver));
  const lotes = () => peticiones.filter((p) => p.metodo === 'POST');
  const consultas = () => peticiones.filter((p) => p.metodo === 'GET');
  const ciclo = () => (servicio as unknown as { cicloEnCurso: Promise<void> | null }).cicloEnCurso;

  function atender(req: TestRequest): void {
    const ruta = req.request.url.replace(API, '');
    const cuerpo = req.request.body;
    peticiones.push({ metodo: req.request.method, ruta, cuerpo, sinToast: req.request.context.get(SIN_TOAST_ERROR) });
    let falsa: Falsa;
    if (req.request.method === 'POST' && ruta === '/sincronizacion/lote') {
      falsa = alLote(cuerpo, lotes().length);
    } else if (req.request.method === 'GET' && ruta.startsWith('/sincronizacion/operaciones/')) {
      falsa = alConsulta(decodeURIComponent(ruta.split('/').pop()!));
    } else {
      throw new Error(`Petición inesperada en la prueba: ${req.request.method} ${ruta}`);
    }
    if (falsa === 'colgar') return;
    if (falsa === 'red') {
      req.error(new ProgressEvent('error'));
    } else if (falsa.status && falsa.status >= 400) {
      req.flush(falsa.cuerpo ?? { detail: 'falla de prueba' }, { status: falsa.status, statusText: 'Falla', headers: falsa.headers });
    } else {
      req.flush(falsa.cuerpo as object);
    }
  }

  const atenderPendientes = () => {
    for (const req of http.match(() => true)) atender(req);
  };

  /** Atiende peticiones hasta que la cola descanse: sin ciclo en curso (y unos turnos de gracia para los disparos pendientes). */
  async function reposo(minimo = 25): Promise<void> {
    for (let i = 0; i < 6000; i++) {
      atenderPendientes();
      if (i >= minimo && ciclo() === null) break;
      await ceder();
    }
    atenderPendientes();
  }

  /** Atiende peticiones mientras la promesa no termine. */
  async function conServidor<T>(promesa: Promise<T>): Promise<T> {
    let terminada = false;
    void promesa.then(
      () => (terminada = true),
      () => (terminada = true),
    );
    for (let i = 0; i < 6000 && !terminada; i++) {
      atenderPendientes();
      await ceder();
    }
    const valor = await promesa;
    await reposo(5);
    return valor;
  }

  /** Toma el próximo POST sin responderlo (para cambiar algo mientras el envío está en el aire). */
  async function tomarLote(): Promise<TestRequest> {
    for (let i = 0; i < 3000; i++) {
      const [req] = http.match((r) => r.method === 'POST' && r.url === `${API}/sincronizacion/lote`);
      if (req) {
        peticiones.push({ metodo: 'POST', ruta: '/sincronizacion/lote', cuerpo: req.request.body, sinToast: req.request.context.get(SIN_TOAST_ERROR) });
        return req;
      }
      await ceder();
    }
    throw new Error('El servicio nunca envió el lote.');
  }

  async function avanzar(ms: number): Promise<void> {
    await vi.advanceTimersByTimeAsync(ms);
    await reposo();
  }

  const sembrar = async (...ops: OperacionOffline[]) => {
    for (const op of ops) {
      await new RepositorioLocal(base, { empresaId: op.empresa_id, usuarioId: op.usuario_id }).registrarOperacion(op);
    }
  };
  const estados = async (): Promise<Record<string, EstadoOperacion>> =>
    Object.fromEntries((await repo.misOperaciones()).map((o) => [o.operacion_id, o.estado]));
  const una = async (n: number): Promise<OperacionOffline> => (await repo.operacion(uuid(n)))!;
  const enSegundos = (s: number) => new Date(Date.now() + s * SEG).toISOString();

  // ---- Funciones puras -----------------------------------------------------------------------------------------------------

  describe('esperaBackoffMs y leerRetryAfterMs', () => {
    it('duplica desde 5 s hasta el tope de 300 s', () => {
      const medio = () => 0.5;
      expect([1, 2, 3, 4, 5, 6, 7, 8, 30].map((n) => esperaBackoffMs(n, medio) / SEG)).toEqual([5, 10, 20, 40, 80, 160, 300, 300, 300]);
      expect(BACKOFF_BASE_MS).toBe(5000);
      expect(BACKOFF_TOPE_MS).toBe(300_000);
    });

    it('varía ±20 % y nunca pasa del tope', () => {
      expect(esperaBackoffMs(1, () => 0)).toBe(4000);
      expect(esperaBackoffMs(1, () => 1)).toBe(6000);
      expect(esperaBackoffMs(2, () => 0)).toBe(8000);
      expect(esperaBackoffMs(20, () => 1)).toBe(BACKOFF_TOPE_MS);
      expect(esperaBackoffMs(0, () => 0.5)).toBe(5000);
    });

    it('Retry-After en segundos o en fecha, entre 1 s y 1 h; ilegible = null', () => {
      expect(leerRetryAfterMs('60', 0)).toBe(60_000);
      expect(leerRetryAfterMs('0', 0)).toBe(1000);
      expect(leerRetryAfterMs('999999', 0)).toBe(3_600_000);
      expect(leerRetryAfterMs(new Date(90_000).toUTCString(), 0)).toBe(90_000);
      expect(leerRetryAfterMs('mañana', 0)).toBeNull();
      expect(leerRetryAfterMs(null)).toBeNull();
    });
  });

  // ---- Registrar sin conexión y enviar al volver la red ------------------------------------------------------------------------

  describe('registrar sin conexión, volver la red y enviar', () => {
    it('sin red la operación espera; al volver la red se envía y queda confirmada SIN borrarse de IndexedDB', async () => {
      enLinea.set(false);
      await sembrar(venta(1));
      servicio.notificarNuevaOperacion();
      await reposo();

      expect(lotes()).toHaveLength(0);
      expect(servicio.estadoCola()).toBe('sin_conexion');
      expect(servicio.pendientes()).toBe(1);
      expect((await una(1)).estado).toBe('registrada');
      expect((await una(1)).intentos).toBe(0);

      enLinea.set(true);
      volvio.next();
      await reposo();

      expect(lotes()).toHaveLength(1);
      const guardada = await una(1);
      expect(guardada).toBeDefined();
      expect(guardada.estado).toBe('confirmada');
      expect(guardada.intentos).toBe(1);
      expect(guardada.resultado?.recurso?.codigo).toBe('V-0900');
      expect(guardada.proximo_intento_en).toBeNull();
      expect(await repo.intentosDe(uuid(1))).toHaveLength(1);
      expect((await repo.misOperaciones()).map((o) => o.operacion_id)).toEqual([uuid(1)]);
      expect(servicio.pendientes()).toBe(0);
      expect(servicio.confirmadas()).toBe(1);
      expect(servicio.estadoCola()).toBe('inactiva');
      expect(servicio.proximoIntentoEn()).toBeNull();
    });

    it('notificarNuevaOperacion con red envía enseguida', async () => {
      await sembrar(venta(1));
      servicio.notificarNuevaOperacion();
      await reposo();

      expect(lotes()).toHaveLength(1);
      expect((await una(1)).estado).toBe('confirmada');
    });

    it('al iniciar con sesión y pendientes en la base, las envía sin que nadie lo pida', async () => {
      // Se vuelve a crear el servicio con la base ya cargada (como al reabrir la app).
      TestBed.resetTestingModule();
      peticiones = [];
      await sembrar(venta(1), venta(2));
      TestBed.configureTestingModule({
        providers: [
          provideHttpClient(),
          provideHttpClientTesting(),
          {
            provide: SesionOfflineService,
            useValue: {
              alcance,
              repositorio: () => (alcance() === null ? null : new RepositorioLocal(base, alcance()!)),
              dispositivoId: () => 'dispositivo-prueba',
            },
          },
          { provide: ConectividadService, useValue: { enLinea, estado: signal('en_linea'), volvioConexion$: volvio.asObservable() } },
          { provide: PlanService, useValue: { estadoActivo: planActivo, incluye: () => planIncluye() } },
        ],
      });
      http = TestBed.inject(HttpTestingController);
      servicio = TestBed.inject(ColaSincronizacionService);
      TestBed.tick();
      await reposo();

      expect(lotes()).toHaveLength(1);
      expect(lotes()[0].cuerpo.operaciones.map((o: any) => o.operacion_id)).toEqual([uuid(1), uuid(2)]);
      expect(await estados()).toEqual({ [uuid(1)]: 'confirmada', [uuid(2)]: 'confirmada' });
    });
  });

  // ---- Contrato -----------------------------------------------------------------------------------------------------------

  describe('cuerpo enviado (contrato v1)', () => {
    it('venta y reserva con la forma exacta del contrato: precios en texto, sin empresa_id, versión 1.0 y dispositivo', async () => {
      await sembrar(venta(1), reserva(2));
      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(1);
      const cuerpo = lotes()[0].cuerpo;
      expect(Object.keys(cuerpo).sort()).toEqual(['dispositivo', 'operaciones', 'version_contrato']);
      expect(cuerpo.version_contrato).toBe('1.0');
      expect(cuerpo.dispositivo).toBe('dispositivo-prueba');
      expect(JSON.stringify(cuerpo)).not.toContain('empresa_id');
      expect(cuerpo.operaciones).toEqual([
        {
          operacion_id: uuid(1),
          tipo: 'venta_contado',
          sucursal_id: 1,
          fecha_operacion: (await una(1)).fecha_operacion,
          payload: {
            cliente_id: 7,
            lineas: [{ variante_id: 101, cantidad: 2, precio_unitario: '149.00', descuento_unitario: '10.00' }],
            total: '278.00',
            pago: { metodo: 'efectivo', monto_recibido: '300.00' },
          },
        },
        {
          operacion_id: uuid(2),
          tipo: 'reserva',
          sucursal_id: 1,
          fecha_operacion: (await una(2)).fecha_operacion,
          payload: {
            cliente_id: 7,
            fecha_visita: '2026-11-02',
            hora_visita_desde: '10:00',
            hora_visita_hasta: '11:00',
            observacion: 'Probar talla',
            lineas: [{ variante_id: 202, cantidad: 2 }],
          },
        },
      ]);
      const linea = cuerpo.operaciones[0].payload.lineas[0];
      expect(typeof linea.precio_unitario).toBe('string');
      expect(typeof linea.descuento_unitario).toBe('string');
      expect(typeof cuerpo.operaciones[0].payload.total).toBe('string');
    });

    it('la fecha de la operación es la del registro (no la del envío) y lleva zona horaria', async () => {
      await sembrar(venta(3));
      vi.setSystemTime(T0 + 24 * 3_600_000);
      await conServidor(servicio.enviarAhora());

      const enviada = lotes()[0].cuerpo.operaciones[0].fecha_operacion as string;
      expect(enviada).toBe((await una(3)).fecha_operacion);
      expect(enviada).toMatch(/Z$|[+-]\d{2}:\d{2}$/);
      expect(Date.parse(enviada)).toBeLessThan(T0);
    });

    it('las peticiones al servidor llevan SIN_TOAST_ERROR (lote y consulta de conflictos)', async () => {
      await sembrar(venta(1), venta(2, { estado: 'en_conflicto' }));
      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(1);
      expect(consultas()).toHaveLength(1);
      expect(peticiones.every((p) => p.sinToast)).toBe(true);
    });

    it('una venta sin pago (algo que el servidor exige) no se envía ni se pierde: queda bloqueada', async () => {
      await sembrar(venta(1, { pago: null }), venta(2));
      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(1);
      expect(lotes()[0].cuerpo.operaciones.map((o: any) => o.operacion_id)).toEqual([uuid(2)]);
      const mala = await una(1);
      expect(mala.estado).toBe('registrada');
      expect(mala.bloqueada).toBe(true);
      expect(mala.ultimo_error).toBe('operacion_invalida');
    });
  });

  // ---- Respuestas ---------------------------------------------------------------------------------------------------------

  describe('respuesta del servidor por operación', () => {
    it('mixta: confirmada, rechazada, en conflicto, ausente y error temporal; ninguna se pierde y las dudosas se reintentan', async () => {
      await sembrar(venta(1), venta(2), venta(3), venta(4), venta(5));
      alLote = (cuerpo, n) => {
        if (n === 1) {
          return {
            cuerpo: respuestaLote([
              resultado(uuid(1), 'confirmada'),
              resultado(uuid(2), 'rechazada', { motivo: 'variante_inexistente', mensaje: 'La prenda ya no existe.' }),
              resultado(uuid(3), 'en_conflicto', {
                motivo: 'stock_insuficiente',
                faltantes: [{ variante_id: 103, solicitado: 2, disponible: 1 }],
              }),
              // La 4 no viene en la respuesta.
              resultado(uuid(5), 'error_temporal', { motivo: 'error_interno' }),
            ]),
          };
        }
        return confirmarTodo(cuerpo);
      };

      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(1);
      expect(await estados()).toEqual({
        [uuid(1)]: 'confirmada',
        [uuid(2)]: 'rechazada',
        [uuid(3)]: 'en_conflicto',
        [uuid(4)]: 'registrada',
        [uuid(5)]: 'registrada',
      });
      const rechazada = await una(2);
      expect(rechazada.motivo).toBe('variante_inexistente');
      expect(rechazada.mensaje).toBe('La prenda ya no existe.');
      expect((await una(3)).resultado?.faltantes).toEqual([{ variante_id: 103, solicitado: 2, disponible: 1 }]);
      const ausente = await una(4);
      expect(ausente.ultimo_error).toBe('sin_respuesta');
      expect(ausente.proximo_intento_en).toBe(enSegundos(5));
      const temporal = await una(5);
      expect(temporal.ultimo_error).toBe('error_interno');
      expect(temporal.proximo_intento_en).toBe(enSegundos(5));
      expect(temporal.resultado).toBeNull();

      expect(servicio.pendientes()).toBe(2);
      expect(servicio.confirmadas()).toBe(1);
      expect(servicio.rechazadas()).toBe(1);
      expect(servicio.enConflicto()).toBe(1);
      expect(servicio.estadoCola()).toBe('esperando_reintento');
      expect(servicio.proximoIntentoEn()).toBe(enSegundos(5));
      // Cada intento quedó anotado, también el de la que no vino.
      expect((await repo.intentosDe(uuid(4))).map((i) => i.motivo)).toEqual(['sin_respuesta']);

      // A los 5 s se reintentan SOLO las dos que no quedaron en firme, con las mismas operacion_id.
      await avanzar(5 * SEG + 100);

      expect(lotes()).toHaveLength(2);
      expect(lotes()[1].cuerpo.operaciones.map((o: any) => o.operacion_id)).toEqual([uuid(4), uuid(5)]);
      expect((await una(4)).estado).toBe('confirmada');
      expect((await una(5)).estado).toBe('confirmada');
      expect((await una(4)).intentos).toBe(2);
      expect(servicio.estadoCola()).toBe('inactiva');
    });

    it('duplicada:true cuenta como éxito, sin segundo registro ni segundo envío', async () => {
      await sembrar(venta(1));
      alLote = () => ({ cuerpo: respuestaLote([resultado(uuid(1), 'confirmada', { duplicada: true })]) });

      await conServidor(servicio.enviarAhora());

      const guardada = await una(1);
      expect(guardada.estado).toBe('confirmada');
      expect(guardada.resultado?.duplicada).toBe(true);
      expect(lotes()).toHaveLength(1);
      expect(await repo.misOperaciones()).toHaveLength(1);
      expect(await repo.intentosDe(uuid(1))).toHaveLength(1);
      expect(servicio.estadoCola()).toBe('inactiva');
      expect(servicio.pendientes()).toBe(0);
    });

    it('se pierde la respuesta del primer envío: el reenvío usa la MISMA operacion_id y el servidor responde duplicada', async () => {
      await sembrar(venta(1));
      alLote = (_c, n) => (n === 1 ? 'red' : { cuerpo: respuestaLote([resultado(uuid(1), 'confirmada', { duplicada: true })]) });

      await conServidor(servicio.enviarAhora());
      expect((await una(1)).estado).toBe('registrada');
      await avanzar(5 * SEG + 100);

      expect(lotes()).toHaveLength(2);
      expect(lotes()[0].cuerpo.operaciones[0].operacion_id).toBe(lotes()[1].cuerpo.operaciones[0].operacion_id);
      expect((await una(1)).estado).toBe('confirmada');
      expect(await repo.misOperaciones()).toHaveLength(1);
    });

    it('rechazo POR OPERACIÓN por suscripción: queda rechazada con su motivo y la cola NO se pausa', async () => {
      await sembrar(venta(1), venta(2));
      alLote = () => ({
        cuerpo: respuestaLote([
          resultado(uuid(1), 'rechazada', { motivo: 'suscripcion_no_activa', mensaje: 'La suscripción no está activa.' }),
          resultado(uuid(2), 'rechazada', { motivo: 'plan_sin_operacion_offline' }),
        ]),
      });

      await conServidor(servicio.enviarAhora());

      expect((await una(1)).estado).toBe('rechazada');
      expect((await una(1)).motivo).toBe('suscripcion_no_activa');
      expect((await una(2)).motivo).toBe('plan_sin_operacion_offline');
      expect(servicio.estadoCola()).toBe('inactiva');
      expect(servicio.motivoPausa()).toBeNull();
      expect(servicio.rechazadas()).toBe(2);
      expect(servicio.pendientes()).toBe(0);

      // Es final: no se vuelve a enviar ni por la fuerza.
      await conServidor(servicio.enviarAhora());
      expect(lotes()).toHaveLength(1);
    });

    it('un 200 sin la lista de resultados es un fallo: las operaciones siguen guardadas y se reintentan', async () => {
      await sembrar(venta(1));
      alLote = () => ({ cuerpo: '<html>Bad gateway</html>' });

      await conServidor(servicio.enviarAhora());

      expect((await una(1)).estado).toBe('registrada');
      expect((await una(1)).ultimo_error).toBe('respuesta_invalida');
      expect(servicio.estadoCola()).toBe('esperando_reintento');
    });

    it('si NINGUNA operación queda en firme el ciclo termina (no reenvía en bucle)', async () => {
      await sembrar(venta(1), venta(2));
      alLote = () => ({ cuerpo: respuestaLote([]) });

      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(1);
      expect(await estados()).toEqual({ [uuid(1)]: 'registrada', [uuid(2)]: 'registrada' });
      expect((await una(1)).ultimo_error).toBe('sin_respuesta');
      expect(servicio.estadoCola()).toBe('esperando_reintento');
    });
  });

  // ---- Fallos del lote ------------------------------------------------------------------------------------------------------

  describe('fallos del envío: nada se pierde y se reintenta con espera', () => {
    const casos: { nombre: string; falsa: Falsa; error: string; espera: number }[] = [
      { nombre: '500', falsa: { status: 500, cuerpo: { detail: 'Error interno' } }, error: 'http_500', espera: 5 },
      { nombre: '503', falsa: { status: 503, cuerpo: 'no disponible' }, error: 'http_503', espera: 5 },
      { nombre: 'caída de la red con el navegador en línea', falsa: 'red', error: 'sin_conexion', espera: 5 },
      { nombre: '429 sin Retry-After', falsa: { status: 429, cuerpo: { detail: 'Demasiadas' } }, error: 'http_429', espera: 5 },
      { nombre: '429 con Retry-After de 60 s', falsa: { status: 429, cuerpo: {}, headers: { 'Retry-After': '60' } }, error: 'http_429', espera: 60 },
      { nombre: '403 que no es de plan ni suscripción', falsa: { status: 403, cuerpo: { detail: 'Sin permiso' } }, error: 'http_403', espera: 5 },
      { nombre: '409', falsa: { status: 409, cuerpo: { detail: 'x' } }, error: 'http_409', espera: 5 },
    ];

    it.each(casos)('$nombre: todas vuelven a registrada con espera de $espera s', async ({ falsa, error, espera }) => {
      await sembrar(venta(1), venta(2), venta(3));
      alLote = () => falsa;

      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(1);
      expect(await estados()).toEqual({ [uuid(1)]: 'registrada', [uuid(2)]: 'registrada', [uuid(3)]: 'registrada' });
      for (const n of [1, 2, 3]) {
        const op = await una(n);
        expect(op.ultimo_error).toBe(error);
        expect(op.proximo_intento_en).toBe(enSegundos(espera));
        expect(op.bloqueada).toBe(false);
        expect(op.resultado).toBeNull();
        expect(op.intentos).toBe(1);
      }
      expect(servicio.pendientes()).toBe(3);
      expect(servicio.estadoCola()).toBe('esperando_reintento');
      expect(servicio.proximoIntentoEn()).toBe(enSegundos(espera));
      expect(servicio.motivoPausa()).toBeNull();
    });

    it('si el servidor no responde en 30 s, las operaciones vuelven a la cola', async () => {
      await sembrar(venta(1));
      alLote = () => 'colgar';
      const envio = servicio.enviarAhora();
      await tomarLote().then((r) => void r);
      await vi.advanceTimersByTimeAsync(30 * SEG + 100);
      await conServidor(envio);

      expect((await una(1)).estado).toBe('registrada');
      expect((await una(1)).ultimo_error).toBe('timeout');
      expect(servicio.estadoCola()).toBe('esperando_reintento');
    });

    it('espera creciente 5, 10, 20, 40, 80, 160 y 300 s (tope); no reintenta antes de tiempo y tras el último intento automático se detiene', async () => {
      await sembrar(venta(1), venta(2));
      alLote = () => ({ status: 500, cuerpo: { detail: 'caído' } });

      await conServidor(servicio.enviarAhora());
      const esperas = [5, 10, 20, 40, 80, 160, 300];
      expect(INTENTOS_AUTOMATICOS_MAX).toBe(esperas.length + 1);

      for (const espera of esperas) {
        expect(servicio.estadoCola()).toBe('esperando_reintento');
        expect(servicio.proximoIntentoEn()).toBe(enSegundos(espera));
        expect((await una(1)).proximo_intento_en).toBe(enSegundos(espera));
        const antes = lotes().length;

        await avanzar(espera * SEG - 1000);
        expect(lotes()).toHaveLength(antes); // todavía no toca
        await avanzar(1000 + 200);
        expect(lotes()).toHaveLength(antes + 1);
        // Nunca se pierde nada.
        expect(await repo.misOperaciones()).toHaveLength(2);
        expect(await estados()).toEqual({ [uuid(1)]: 'registrada', [uuid(2)]: 'registrada' });
      }

      // Fallo número 8: se detiene.
      expect(lotes()).toHaveLength(INTENTOS_AUTOMATICOS_MAX);
      expect(servicio.estadoCola()).toBe('detenida_por_fallos');
      expect(servicio.motivoPausa()).toBe(MOTIVO_DETENIDA);
      expect(servicio.motivoPausa()).toBe('No se pudo enviar. Reintenta manualmente.');
      expect(servicio.proximoIntentoEn()).toBeNull();

      // Ni el temporizador de 60 s, ni la pestaña, ni una operación nueva la despiertan.
      await avanzar(20 * 60 * SEG);
      document.dispatchEvent(new Event('visibilitychange'));
      await sembrar(venta(9));
      servicio.notificarNuevaOperacion();
      await reposo();
      expect(lotes()).toHaveLength(INTENTOS_AUTOMATICOS_MAX);
      expect(servicio.estadoCola()).toBe('detenida_por_fallos');
      expect((await una(1)).estado).toBe('registrada');

      // El botón "Enviar ahora" sí: ignora la espera, levanta la detención y, si el servidor ya responde, todo sale.
      alLote = confirmarTodo;
      await conServidor(servicio.enviarAhora());
      expect(lotes()).toHaveLength(INTENTOS_AUTOMATICOS_MAX + 1);
      expect(await estados()).toEqual({ [uuid(1)]: 'confirmada', [uuid(2)]: 'confirmada', [uuid(9)]: 'confirmada' });
      expect(servicio.estadoCola()).toBe('inactiva');
      expect(servicio.motivoPausa()).toBeNull();
    });

    it('un envío con éxito reinicia la cuenta de fallos seguidos', async () => {
      await sembrar(venta(1));
      alLote = () => ({ status: 500, cuerpo: {} });
      await conServidor(servicio.enviarAhora()); // fallo 1 (5 s)
      await avanzar(5 * SEG + 100); // fallo 2 (10 s)
      expect(servicio.proximoIntentoEn()).toBe(enSegundos(10));

      alLote = confirmarTodo;
      await avanzar(10 * SEG + 100); // éxito
      expect((await una(1)).estado).toBe('confirmada');

      await sembrar(venta(2));
      alLote = () => ({ status: 500, cuerpo: {} });
      await conServidor(servicio.enviarAhora());
      // Empieza otra vez en 5 s, no en 20 s.
      expect(servicio.proximoIntentoEn()).toBe(enSegundos(5));
    });

    it('sin conexión a mitad del envío no es un fallo del servidor: espera sin gastar fallos y al volver la red sale enseguida', async () => {
      await sembrar(venta(1));
      alLote = () => {
        enLinea.set(false);
        return 'red';
      };
      await conServidor(servicio.enviarAhora());

      const espera = await una(1);
      expect(espera.estado).toBe('registrada');
      expect(espera.ultimo_error).toBe('sin_conexion');
      expect(espera.proximo_intento_en).toBeNull();
      expect(servicio.estadoCola()).toBe('sin_conexion');
      expect(servicio.proximoIntentoEn()).toBeNull();

      alLote = confirmarTodo;
      enLinea.set(true);
      volvio.next();
      await reposo();

      expect(lotes()).toHaveLength(2);
      expect((await una(1)).estado).toBe('confirmada');
    });
  });

  // ---- Pausas -------------------------------------------------------------------------------------------------------------

  describe('pausas', () => {
    it('401 (el interceptor ya no pudo renovar): pausada por sesión, las operaciones siguen guardadas', async () => {
      await sembrar(venta(1), venta(2));
      alLote = () => ({ status: 401, cuerpo: { detail: 'No autenticado' } });

      await conServidor(servicio.enviarAhora());

      expect(servicio.estadoCola()).toBe('pausada_sesion');
      expect(servicio.motivoPausa()).toBe('Inicia sesión para enviar tus 2 operaciones pendientes. Siguen guardadas.');
      expect(await estados()).toEqual({ [uuid(1)]: 'registrada', [uuid(2)]: 'registrada' });
      expect((await una(1)).ultimo_error).toBe('sesion_vencida');
      expect((await una(1)).proximo_intento_en).toBeNull();
      expect(servicio.proximoIntentoEn()).toBeNull();

      // Nada la despierta sola.
      await avanzar(5 * 60 * SEG);
      expect(lotes()).toHaveLength(1);
    });

    it('al volver a iniciar sesión el MISMO usuario, la cola se reanuda; otro usuario NO envía las de la primera persona', async () => {
      await sembrar(venta(1));
      alLote = () => ({ status: 401, cuerpo: { detail: 'No autenticado' } });
      await conServidor(servicio.enviarAhora());
      expect(servicio.estadoCola()).toBe('pausada_sesion');

      // El interceptor cierra la sesión.
      alcance.set(null);
      TestBed.tick();
      await reposo();
      expect(servicio.estadoCola()).toBe('pausada_sesion');
      expect(lotes()).toHaveLength(1);

      // Entra OTRA persona: no envía las ajenas.
      alLote = confirmarTodo;
      alcance.set({ empresaId: EMPRESA, usuarioId: OTRO_USUARIO });
      TestBed.tick();
      await reposo();
      expect(lotes()).toHaveLength(1);
      expect((await una(1)).estado).toBe('registrada');
      expect(servicio.estadoCola()).toBe('inactiva');
      expect(servicio.pendientes()).toBe(0);
      expect(servicio.pendientesDeOtros()).toBe(1);

      // Vuelve la primera persona: se envía lo suyo.
      alcance.set(null);
      TestBed.tick();
      alcance.set({ empresaId: EMPRESA, usuarioId: USUARIO });
      TestBed.tick();
      await reposo();
      expect(lotes()).toHaveLength(2);
      expect((await una(1)).estado).toBe('confirmada');
      expect(servicio.estadoCola()).toBe('inactiva');
      expect(servicio.motivoPausa()).toBeNull();
    });

    it('el mismo usuario que vuelve tras pausa por sesión reanuda aunque la pausa fuera por 401', async () => {
      await sembrar(venta(1));
      alLote = () => ({ status: 401, cuerpo: {} });
      await conServidor(servicio.enviarAhora());
      alLote = confirmarTodo;

      alcance.set(null);
      TestBed.tick();
      await reposo();
      alcance.set({ empresaId: EMPRESA, usuarioId: USUARIO });
      TestBed.tick();
      await reposo();

      expect((await una(1)).estado).toBe('confirmada');
      expect(servicio.estadoCola()).toBe('inactiva');
    });

    it.each([
      ['plan_no_incluye_funcionalidad', 'Tu plan no incluye operar sin conexión. Tus 2 operaciones pendientes siguen guardadas.'],
      ['suscripcion_no_activa', 'La suscripción de tu empresa no está activa. Tus 2 operaciones pendientes siguen guardadas.'],
    ])('403 de cuerpo completo (%s): pausada por plan y NADA se marca rechazado', async (codigo, mensaje) => {
      await sembrar(venta(1), venta(2));
      alLote = () => ({ status: 403, cuerpo: { detail: codigo, codigo, mensaje: 'x' } });

      await conServidor(servicio.enviarAhora());

      expect(servicio.estadoCola()).toBe('pausada_plan');
      expect(servicio.motivoPausa()).toBe(mensaje);
      expect(await estados()).toEqual({ [uuid(1)]: 'registrada', [uuid(2)]: 'registrada' });
      expect((await una(1)).ultimo_error).toBe(codigo);
      expect((await una(1)).proximo_intento_en).toBeNull();
      expect((await una(1)).resultado).toBeNull();
      expect(servicio.rechazadas()).toBe(0);

      // No se insiste solo; el botón sí lo intenta de nuevo.
      await avanzar(5 * 60 * SEG);
      expect(lotes()).toHaveLength(1);
      alLote = confirmarTodo;
      await conServidor(servicio.enviarAhora());
      expect(lotes()).toHaveLength(2);
      expect(servicio.estadoCola()).toBe('inactiva');
      expect((await una(1)).estado).toBe('confirmada');
    });

    it('el código funcional también se reconoce dentro de `detail` (compatibilidad)', async () => {
      await sembrar(venta(1));
      alLote = () => ({ status: 403, cuerpo: { detail: { codigo: 'suscripcion_no_activa' } } });

      await conServidor(servicio.enviarAhora());

      expect(servicio.estadoCola()).toBe('pausada_plan');
      expect(servicio.motivoPausa()).toContain('suscripción');
    });

    it('si PlanService ya sabe que el plan no lo incluye, no se envía; al cambiar el plan se reanuda', async () => {
      await sembrar(venta(1));
      planIncluye.set(false);

      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(0);
      expect(servicio.estadoCola()).toBe('pausada_plan');
      expect(servicio.motivoPausa()).toBe('Tu plan no incluye operar sin conexión. Tu operación pendiente sigue guardada.');
      expect((await una(1)).estado).toBe('registrada');
      expect((await una(1)).intentos).toBe(0);

      planIncluye.set(true);
      await avanzar(INTERVALO_COLA_MS + 100);

      expect(lotes()).toHaveLength(1);
      expect((await una(1)).estado).toBe('confirmada');
      expect(servicio.estadoCola()).toBe('inactiva');
      expect(servicio.motivoPausa()).toBeNull();
    });

    it('suscripción inactiva según PlanService: pausada por plan con su propio texto', async () => {
      await sembrar(venta(1));
      planActivo.set(false);

      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(0);
      expect(servicio.estadoCola()).toBe('pausada_plan');
      expect(servicio.motivoPausa()).toContain('suscripción');
    });
  });

  // ---- Error de formato -------------------------------------------------------------------------------------------------------

  describe('400 y 422: error de formato', () => {
    it('422 que señala una operación: solo esa queda bloqueada; las demás se reenvían en el mismo ciclo', async () => {
      await sembrar(venta(1), venta(2), venta(3));
      alLote = (cuerpo, n) =>
        n === 1
          ? { status: 422, cuerpo: { detail: [{ loc: ['body', 'operaciones', 1, 'payload', 'total'], msg: 'inválido', type: 'x' }] } }
          : confirmarTodo(cuerpo);

      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(2);
      expect(lotes()[1].cuerpo.operaciones.map((o: any) => o.operacion_id)).toEqual([uuid(1), uuid(3)]);
      expect(await estados()).toEqual({ [uuid(1)]: 'confirmada', [uuid(2)]: 'registrada', [uuid(3)]: 'confirmada' });
      const mala = await una(2);
      expect(mala.bloqueada).toBe(true);
      expect(mala.ultimo_error).toBe('error_formato');
      expect(mala.mensaje).toBe(MENSAJE_ERROR_FORMATO);
      expect(mala.mensaje).toBe('No se pudo enviar por un error de formato. Avisa a soporte.');
      expect(servicio.pendientes()).toBe(1);
      expect(servicio.estadoCola()).toBe('inactiva');
    });

    it('sin reintento automático: ni el temporizador, ni la red, ni "Enviar ahora" reenvían una bloqueada', async () => {
      await sembrar(venta(1));
      alLote = () => ({ status: 422, cuerpo: { detail: 'Unprocessable' } });

      await conServidor(servicio.enviarAhora());
      expect(lotes()).toHaveLength(1);
      expect((await una(1)).bloqueada).toBe(true);
      expect((await una(1)).estado).toBe('registrada');
      expect(servicio.proximoIntentoEn()).toBeNull();

      await avanzar(15 * 60 * SEG);
      volvio.next();
      await reposo();
      await conServidor(servicio.enviarAhora());
      servicio.notificarNuevaOperacion();
      await reposo();

      expect(lotes()).toHaveLength(1);
      expect((await una(1)).estado).toBe('registrada');
      expect((await una(1)).bloqueada).toBe(true);
    });

    it('400 marca bloqueadas todas las del lote (no se sabe cuál falló) y no las pierde', async () => {
      await sembrar(venta(1), venta(2));
      alLote = () => ({ status: 400, cuerpo: { detail: 'Solicitud incorrecta' } });

      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(1);
      expect((await una(1)).bloqueada).toBe(true);
      expect((await una(2)).bloqueada).toBe(true);
      expect(await repo.misOperaciones()).toHaveLength(2);
    });
  });

  // ---- Orden, tamaño de lote y otros usuarios ---------------------------------------------------------------------------------

  describe('orden, lotes y alcance', () => {
    it(`envía por fecha_operacion ascendente en lotes de ${TAM_LOTE}`, async () => {
      const ids = Array.from({ length: 45 }, (_, i) => i + 1);
      // Se guardan en desorden: el orden de envío NO es el de registro.
      const desordenados = [...ids].sort((a, b) => ((a * 7) % 45) - ((b * 7) % 45));
      await sembrar(...desordenados.map((n) => venta(n)));

      await conServidor(servicio.enviarAhora());

      expect(lotes().map((l) => l.cuerpo.operaciones.length)).toEqual([20, 20, 5]);
      const enviados = lotes().flatMap((l) => l.cuerpo.operaciones.map((o: any) => o.operacion_id));
      expect(enviados).toEqual(ids.map(uuid));
      const fechas = lotes().flatMap((l) => l.cuerpo.operaciones.map((o: any) => Date.parse(o.fecha_operacion)));
      expect(fechas).toEqual([...fechas].sort((a, b) => a - b));
      expect(new Set(enviados).size).toBe(45);
      expect(Object.values(await estados()).every((e) => e === 'confirmada')).toBe(true);
      expect(servicio.confirmadas()).toBe(45);
    }, 30_000);

    it('el tamaño del lote es el menor entre el nuestro y el máximo que dijo el servidor', async () => {
      await repo.guardarMeta(META_REGLAS, { max_operaciones_por_lote: 5 });
      await sembrar(...[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((n) => venta(n)));

      await conServidor(servicio.enviarAhora());

      expect(lotes().map((l) => l.cuerpo.operaciones.length)).toEqual([5, 5, 2]);
    });

    it('solo envía las operaciones de MI usuario; las de otro usuario del mismo equipo no se tocan', async () => {
      await sembrar(venta(1), venta(2, { usuario_id: OTRO_USUARIO }));
      await servicio.refrescarConteos();
      expect(servicio.pendientesDeOtros()).toBe(1);

      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(1);
      expect(lotes()[0].cuerpo.operaciones.map((o: any) => o.operacion_id)).toEqual([uuid(1)]);
      const ajena = await new RepositorioLocal(base, { empresaId: EMPRESA, usuarioId: OTRO_USUARIO }).operacion(uuid(2));
      expect(ajena?.estado).toBe('registrada');
      expect(ajena?.intentos).toBe(0);
      expect(servicio.pendientes()).toBe(0);
      expect(servicio.pendientesDeOtros()).toBe(1);
    });

    it('nunca envía las de otra empresa', async () => {
      await sembrar(venta(1), venta(2, { empresa_id: 99 }));

      await conServidor(servicio.enviarAhora());

      expect(lotes()[0].cuerpo.operaciones.map((o: any) => o.operacion_id)).toEqual([uuid(1)]);
    });

    it('sin sesión (o superadministrador) no envía nada', async () => {
      await sembrar(venta(1));
      alcance.set(null);
      TestBed.tick();
      await reposo();

      await conServidor(servicio.enviarAhora());
      await avanzar(INTERVALO_COLA_MS * 3);

      expect(lotes()).toHaveLength(0);
      expect((await una(1))?.estado ?? 'registrada').toBe('registrada');
      expect(servicio.pendientes()).toBe(0);
    });

    it('si cambia la sesión a mitad del envío, el resultado se guarda para su dueño y la otra persona NO queda sin enviar', async () => {
      await sembrar(venta(1), venta(2, { usuario_id: OTRO_USUARIO }));
      const envio = servicio.enviarAhora();
      const lote = await tomarLote();

      alcance.set({ empresaId: EMPRESA, usuarioId: OTRO_USUARIO });
      TestBed.tick();
      lote.flush(respuestaLote([resultado(uuid(1), 'confirmada')]));
      await conServidor(envio);
      await reposo();

      // Lo de la primera persona quedó confirmado en SU base; lo de la segunda se envió después, con SU sesión.
      expect((await una(1)).estado).toBe('confirmada');
      expect(lotes()).toHaveLength(2);
      expect(lotes()[1].cuerpo.operaciones.map((o: any) => o.operacion_id)).toEqual([uuid(2)]);
      const de6 = await new RepositorioLocal(base, { empresaId: EMPRESA, usuarioId: OTRO_USUARIO }).operacion(uuid(2));
      expect(de6?.estado).toBe('confirmada');
    });

    it('una operación "enviada" huérfana (cierre brusco) se recupera; una enviada hace segundos no se reenvía', async () => {
      const hace = (ms: number) => new Date(T0 - ms).toISOString();
      await sembrar(
        venta(1, { estado: 'enviada', intentos: 1, ultimo_intento_en: hace(5 * 60_000) }),
        venta(2, { estado: 'enviada', intentos: 1, ultimo_intento_en: hace(10_000) }),
      );

      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(1);
      expect(lotes()[0].cuerpo.operaciones.map((o: any) => o.operacion_id)).toEqual([uuid(1)]);
      expect((await una(1)).estado).toBe('confirmada');
      expect((await una(1)).intentos).toBe(2);
      expect((await una(2)).estado).toBe('enviada');
    });
  });

  // ---- Disparadores -------------------------------------------------------------------------------------------------------

  describe('disparadores', () => {
    it('"Enviar ahora" ignora la espera del reintento; el temporizador y la red la respetan', async () => {
      await sembrar(venta(1, { proximo_intento_en: new Date(T0 + 3_600_000).toISOString(), intentos: 3, ultimo_error: 'http_500' }));

      await avanzar(INTERVALO_COLA_MS * 2 + 100);
      volvio.next();
      await reposo();
      expect(lotes()).toHaveLength(0);
      expect(servicio.estadoCola()).toBe('esperando_reintento');
      expect(servicio.proximoIntentoEn()).toBe(new Date(T0 + 3_600_000).toISOString());

      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(1);
      expect((await una(1)).estado).toBe('confirmada');
      expect((await una(1)).proximo_intento_en).toBeNull();
    });

    it('dos disparos simultáneos hacen UN solo envío', async () => {
      await sembrar(venta(1), venta(2));

      const a = servicio.enviarAhora();
      const b = servicio.enviarAhora();
      servicio.notificarNuevaOperacion();
      volvio.next();
      await conServidor(Promise.all([a, b]));

      expect(lotes()).toHaveLength(1);
      expect(lotes()[0].cuerpo.operaciones).toHaveLength(2);
      expect(await estados()).toEqual({ [uuid(1)]: 'confirmada', [uuid(2)]: 'confirmada' });
      expect(await repo.intentosDe(uuid(1))).toHaveLength(1);
    });

    it('una operación registrada mientras otra se envía sale al terminar ese envío', async () => {
      await sembrar(venta(1));
      const envio = servicio.enviarAhora();
      const lote = await tomarLote();

      await sembrar(venta(2));
      servicio.notificarNuevaOperacion();
      lote.flush(respuestaLote([resultado(uuid(1), 'confirmada')]));
      await conServidor(envio);
      await reposo();

      expect(lotes()).toHaveLength(2);
      expect(lotes()[1].cuerpo.operaciones.map((o: any) => o.operacion_id)).toEqual([uuid(2)]);
      expect((await una(2)).estado).toBe('confirmada');
    });

    it('con un reintento ya programado, una operación nueva no martilla al servidor: sale con el siguiente intento', async () => {
      await sembrar(venta(1));
      alLote = () => ({ status: 500, cuerpo: {} });
      await conServidor(servicio.enviarAhora());
      expect(servicio.estadoCola()).toBe('esperando_reintento');

      await sembrar(venta(2));
      servicio.notificarNuevaOperacion();
      await reposo();
      expect(lotes()).toHaveLength(1);

      alLote = confirmarTodo;
      await avanzar(5 * SEG + 100);
      expect(lotes()).toHaveLength(2);
      expect(lotes()[1].cuerpo.operaciones.map((o: any) => o.operacion_id)).toEqual([uuid(1), uuid(2)]);
    });

    it('el temporizador de 60 s revisa la cola con la pestaña abierta y con red; sin red no', async () => {
      await sembrar(venta(1));
      enLinea.set(false);
      await avanzar(INTERVALO_COLA_MS + 100);
      expect(lotes()).toHaveLength(0);

      enLinea.set(true);
      await avanzar(INTERVALO_COLA_MS);
      expect(lotes()).toHaveLength(1);
      expect((await una(1)).estado).toBe('confirmada');
    });

    it('al volver a la pestaña envía solo si hay pendientes', async () => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
      try {
        document.dispatchEvent(new Event('visibilitychange'));
        await reposo();
        expect(lotes()).toHaveLength(0);

        await sembrar(venta(1));
        await servicio.refrescarConteos();
        expect(servicio.pendientes()).toBe(1);
        document.dispatchEvent(new Event('visibilitychange'));
        await reposo();

        expect(lotes()).toHaveLength(1);
        expect((await una(1)).estado).toBe('confirmada');
      } finally {
        delete (document as unknown as Record<string, unknown>)['visibilityState'];
      }
    });

    it('con Web Locks, si otra pestaña tiene el candado "fs-sync" no se envía; con el candado sí', async () => {
      await sembrar(venta(1));
      const request = vi.fn((_nombre: string, _opciones: unknown, tarea: (candado: unknown) => Promise<void>) => tarea(null));
      vi.stubGlobal('navigator', Object.assign(Object.create(navigator), { locks: { request } }));

      await conServidor(servicio.enviarAhora());
      expect(request).toHaveBeenCalledWith('fs-sync', { ifAvailable: true }, expect.any(Function));
      expect(lotes()).toHaveLength(0);
      expect((await una(1)).estado).toBe('registrada');

      request.mockImplementation((_n, _o, tarea) => tarea({ name: 'fs-sync' }));
      await conServidor(servicio.enviarAhora());
      expect(lotes()).toHaveLength(1);
      expect((await una(1)).estado).toBe('confirmada');
    });

    it('al destruir el servicio se limpian el temporizador de 60 s y el reintento programado', async () => {
      await sembrar(venta(1));
      alLote = () => ({ status: 500, cuerpo: {} });
      await conServidor(servicio.enviarAhora());
      expect(servicio.estadoCola()).toBe('esperando_reintento');
      expect(vi.getTimerCount()).toBeGreaterThan(timersAntes);

      TestBed.resetTestingModule();

      expect(vi.getTimerCount()).toBe(timersAntes);
      const antes = peticiones.length;
      await vi.advanceTimersByTimeAsync(10 * 60 * SEG);
      expect(peticiones).toHaveLength(antes);
    });
  });

  // ---- Conflictos -------------------------------------------------------------------------------------------------------

  describe('operaciones en conflicto', () => {
    it('si un encargado la resolvió, la copia local pasa a confirmada o rechazada; las que siguen en conflicto no cambian', async () => {
      await sembrar(
        venta(1, { estado: 'en_conflicto', motivo: 'stock_insuficiente', intentos: 1 }),
        venta(2, { estado: 'en_conflicto', motivo: 'stock_insuficiente', intentos: 1 }),
        venta(3, { estado: 'en_conflicto', motivo: 'stock_insuficiente', intentos: 1 }),
        venta(4, { estado: 'en_conflicto', motivo: 'stock_insuficiente', intentos: 1 }),
      );
      alConsulta = (id) => {
        if (id === uuid(1)) {
          return {
            cuerpo: {
              operacion_id: id,
              estado: 'confirmada',
              motivo: null,
              mensaje: 'Confirmada por el encargado.',
              recurso: { tipo: 'venta', id: 55, codigo: 'V-0055', total: '278.00' },
              cambio: '22.00',
              avisos: [],
              faltantes: [],
              resolucion: { accion: 'forzar', por_usuario_id: 2 },
            },
          };
        }
        if (id === uuid(2)) {
          return { cuerpo: { operacion_id: id, estado: 'rechazada', motivo: 'rechazada_por_encargado', mensaje: 'No había la prenda.', resolucion: { accion: 'rechazar', motivo: 'sin stock' } } };
        }
        if (id === uuid(3)) return { cuerpo: { operacion_id: id, estado: 'en_conflicto' } };
        return { status: 500, cuerpo: {} };
      };

      await conServidor(servicio.enviarAhora());

      expect(lotes()).toHaveLength(0);
      expect(new Set(consultas().map((c) => c.ruta))).toEqual(new Set([1, 2, 3, 4].map((n) => `/sincronizacion/operaciones/${uuid(n)}`)));
      const confirmada = await una(1);
      expect(confirmada.estado).toBe('confirmada');
      expect(confirmada.resultado?.recurso?.codigo).toBe('V-0055');
      expect(confirmada.resultado?.cambio).toBe('22.00');
      const rechazada = await una(2);
      expect(rechazada.estado).toBe('rechazada');
      expect(rechazada.motivo).toBe('rechazada_por_encargado');
      expect((await una(3)).estado).toBe('en_conflicto');
      expect((await una(4)).estado).toBe('en_conflicto'); // el error de la consulta se ignora
      expect(servicio.confirmadas()).toBe(1);
      expect(servicio.rechazadas()).toBe(1);
      expect(servicio.enConflicto()).toBe(2);
      expect(servicio.estadoCola()).toBe('inactiva');
    });

    it('no pregunta en cada vuelta del temporizador: espera 2 minutos cuando no hubo nada que enviar', async () => {
      await sembrar(venta(1, { estado: 'en_conflicto', intentos: 1 }));
      await conServidor(servicio.enviarAhora());
      expect(consultas()).toHaveLength(1);

      await avanzar(INTERVALO_COLA_MS + 100);
      expect(consultas()).toHaveLength(1);
      await avanzar(INTERVALO_COLA_MS * 2);
      expect(consultas().length).toBeGreaterThanOrEqual(2);
    });

    it('una operación en conflicto NO se reenvía como lote', async () => {
      await sembrar(venta(1, { estado: 'en_conflicto', intentos: 1 }));

      await conServidor(servicio.enviarAhora());
      volvio.next();
      await reposo();

      expect(lotes()).toHaveLength(0);
    });

    it('tras un ciclo fallido no consulta conflictos (el servidor no está en condiciones)', async () => {
      await sembrar(venta(1), venta(2, { estado: 'en_conflicto', intentos: 1 }));
      alLote = () => ({ status: 500, cuerpo: {} });

      await conServidor(servicio.enviarAhora());

      expect(consultas()).toHaveLength(0);
    });
  });
});
