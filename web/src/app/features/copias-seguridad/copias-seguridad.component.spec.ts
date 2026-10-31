import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Observable, Subject } from 'rxjs';
import { ConectividadService, EstadoConexion } from '../../core/conectividad.service';
import { Copia, CopiaDescargada, CopiaPagina, CopiaTablas } from '../../core/models/copias.models';
import { PlanService } from '../../core/plan.service';
import { CopiasSeguridadComponent, MS_AVISO_COPIADO } from './copias-seguridad.component';
import { CopiasSeguridadService } from './data/copias-seguridad.service';

// ---- Datos de ejemplo --------------------------------------------------------------------------------------------------

const SHA_A = '0123456789abcdef'.repeat(4);
const SHA_B = 'fedcba9876543210'.repeat(4);

function copia(id: number, extra: Partial<Copia> = {}): Copia {
  return {
    id,
    estado: 'completada',
    usuario_id: 1,
    usuario_nombre: 'Ana Paz',
    tamano_bytes: 1_572_864,
    total_filas: 12_345,
    tablas_incluidas: { producto: 100 },
    version_esquema: 'a9d3f5c27e84',
    checksum: SHA_A,
    motivo_fallo: null,
    creado_en: '2026-10-30T14:05:00',
    terminado_en: '2026-10-30T14:05:30',
    ...extra,
  };
}

function pagina(items: Copia[], extra: Partial<CopiaPagina> = {}): CopiaPagina {
  return { total: items.length, pagina: 1, tamanio: 20, items, ...extra };
}

const TABLAS: CopiaTablas = {
  incluidas: ['producto', 'orden_compra', 'venta'],
  referencias: ['permiso', 'metodo_pago'],
  excluidas: [
    { tabla: 'bitacora', motivo: 'Es el registro de auditoría: no forma parte de los datos de negocio.' },
    { tabla: 'transaccion_pasarela', motivo: 'Datos de pagos de la pasarela.' },
  ],
  columnas_excluidas: { usuario: ['password_hash', 'token_reset'] },
};

function descargada(extra: Partial<CopiaDescargada> = {}): CopiaDescargada {
  return {
    blob: new Blob(['zip-zip']),
    nombre: 'fashionstore-boutique-20261030-1405.zip',
    copiaId: 7,
    checksum: SHA_B,
    ...extra,
  };
}

/** Un error de `POST /copias-seguridad`: el cuerpo llega como Blob porque la petición pide `responseType: 'blob'`. */
function errorBlob(status: number, cuerpo: unknown): HttpErrorResponse {
  return new HttpErrorResponse({ status, statusText: 'x', error: new Blob([JSON.stringify(cuerpo)]) });
}

/** Un error de una lectura JSON (historial o "Qué incluye"). */
function errorJson(status: number, cuerpo: unknown = {}): HttpErrorResponse {
  return new HttpErrorResponse({ status, statusText: 'x', error: cuerpo });
}

// ---- Servicio falso: cada llamada es un Subject que la prueba resuelve cuando quiere ----------------------------------

function crearServicioFalso() {
  const colas = {
    crear: [] as Subject<CopiaDescargada>[],
    listar: [] as Subject<CopiaPagina>[],
    tablas: [] as Subject<CopiaTablas>[],
  };
  const nuevo = <T>(lista: Subject<T>[]): Observable<T> => {
    const s = new Subject<T>();
    lista.push(s);
    return s.asObservable();
  };
  const servicio = {
    crear: vi.fn(() => nuevo(colas.crear)),
    listar: vi.fn((_pagina?: number, _tamanio?: number) => nuevo(colas.listar)),
    tablas: vi.fn(() => nuevo(colas.tablas)),
  };
  return { colas, servicio };
}

function responder<T>(cola: Subject<T>[], valor: T, indice = cola.length - 1): void {
  cola[indice].next(valor);
  cola[indice].complete();
}

function fallar<T>(cola: Subject<T>[], error: HttpErrorResponse, indice = cola.length - 1): void {
  cola[indice].error(error);
}

// ---- Pruebas -------------------------------------------------------------------------------------------------------------

describe('CopiasSeguridadComponent', () => {
  let fixture: ComponentFixture<CopiasSeguridadComponent>;
  let falso: ReturnType<typeof crearServicioFalso>;
  let incluye: ReturnType<typeof signal<boolean>>;
  let conexion: ReturnType<typeof signal<EstadoConexion>>;
  let plan: { incluye: () => boolean; cargar: ReturnType<typeof vi.fn>; marcarBloqueada: ReturnType<typeof vi.fn> };
  let descargas: string[];
  let portapapeles: ReturnType<typeof vi.fn>;
  let comp: any;
  let el: HTMLElement;

  // PrimeNG observa su tamaño con ResizeObserver, y la descarga usa URL.createObjectURL: jsdom no trae ninguno.
  beforeAll(() => {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    };
    URL.createObjectURL = vi.fn(() => 'blob:copia');
    URL.revokeObjectURL = vi.fn();
  });

  function montar(opciones: { incluye?: boolean; conexion?: EstadoConexion } = {}): void {
    falso = crearServicioFalso();
    incluye = signal(opciones.incluye ?? true);
    conexion = signal<EstadoConexion>(opciones.conexion ?? 'en_linea');
    plan = { incluye: () => incluye(), cargar: vi.fn(), marcarBloqueada: vi.fn() };
    TestBed.configureTestingModule({
      imports: [CopiasSeguridadComponent],
      providers: [
        provideRouter([]),
        { provide: CopiasSeguridadService, useValue: falso.servicio },
        { provide: PlanService, useValue: plan },
        { provide: ConectividadService, useValue: { estado: conexion } },
      ],
    });
    fixture = TestBed.createComponent(CopiasSeguridadComponent);
    el = fixture.nativeElement as HTMLElement;
    comp = fixture.componentInstance;
    fixture.detectChanges();
    fixture.detectChanges();
  }

  /** Responde a las dos consultas de apertura. */
  function responderApertura(items: Copia[] = [copia(1)], tablas: CopiaTablas = TABLAS): void {
    responder(falso.colas.listar, pagina(items));
    responder(falso.colas.tablas, tablas);
    fixture.detectChanges();
  }

  const q = (selector: string) => el.querySelector(selector) as HTMLElement | null;
  const qa = (selector: string) => Array.from(el.querySelectorAll(selector)) as HTMLElement[];
  const texto = (nodo: Element | null | undefined) => nodo?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
  const boton = () => q('[data-accion="crear"]') as HTMLButtonElement;
  const hayLlamadas = () =>
    falso.servicio.crear.mock.calls.length + falso.servicio.listar.mock.calls.length + falso.servicio.tablas.mock.calls.length;

  /** Los errores llegan como Blob y se leen de forma asíncrona: se espera a que la pantalla los muestre. */
  async function esperar(condicion: () => boolean): Promise<void> {
    await vi.waitFor(() => {
      fixture.detectChanges();
      expect(condicion()).toBe(true);
    });
  }

  /** Crea una copia y devuelve cuando la pantalla ya muestra el resultado. */
  function pulsarCrear(): void {
    boton().click();
    fixture.detectChanges();
  }

  async function abrirPanel(): Promise<void> {
    (q('[data-accion="alternar-panel"]') as HTMLButtonElement).click();
    fixture.detectChanges();
  }

  beforeEach(() => {
    descargas = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      descargas.push(this.download);
    });
    portapapeles = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: portapapeles } });
  });

  afterEach(() => {
    fixture.destroy();
    TestBed.resetTestingModule();
    vi.restoreAllMocks();
    delete (navigator as { clipboard?: unknown }).clipboard;
  });

  describe('al abrir', () => {
    it('muestra el título, el aviso de "una sola vez" y la nota de alcance con la restauración aún no disponible', () => {
      montar();
      responderApertura();

      expect(texto(q('h1'))).toBe('Copias de seguridad');
      expect(texto(q('[data-aviso="una-vez"]'))).toBe(
        'La copia se descarga una vez y no se guarda en el servidor. Guarda el archivo en un lugar seguro.',
      );
      const nota = texto(q('[data-aviso="alcance"]'));
      expect(nota).toContain('datos de tu empresa');
      expect(nota).toContain('sin contraseñas ni datos de pagos de la pasarela');
      expect(nota).toContain('la restauración desde la pantalla todavía no está disponible');
    });

    it('pide la página 1 del historial (20 por página) y qué incluye la copia; no crea nada', () => {
      montar();

      expect(falso.servicio.listar).toHaveBeenCalledTimes(1);
      expect(falso.servicio.listar).toHaveBeenCalledWith(1, 20);
      expect(falso.servicio.tablas).toHaveBeenCalledTimes(1);
      expect(falso.servicio.crear).not.toHaveBeenCalled();
      expect(boton().disabled).toBe(false);
      expect(boton().textContent).toContain('Crear y descargar copia');
    });

    it('no guarda nada en el navegador', () => {
      montar();
      responderApertura();
      pulsarCrear();
      responder(falso.colas.crear, descargada());
      fixture.detectChanges();

      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
    });
  });

  describe('crear y descargar', () => {
    it('llama una vez, deshabilita el botón y avisa que puede tardar hasta un minuto', () => {
      montar();
      responderApertura();

      pulsarCrear();
      expect(falso.servicio.crear).toHaveBeenCalledTimes(1);
      expect(boton().disabled).toBe(true);
      expect(boton().getAttribute('aria-busy')).toBe('true');
      expect(boton().textContent).toContain('Creando la copia');
      expect(texto(q('[data-estado="creando"]'))).toBe('Puede tardar hasta un minuto');

      // Un segundo clic (o Enter) mientras trabaja no repite la petición.
      comp.crear();
      expect(falso.servicio.crear).toHaveBeenCalledTimes(1);
    });

    it('al terminar descarga el ZIP con el nombre del servidor y muestra el checksum', () => {
      montar();
      responderApertura();
      pulsarCrear();
      responder(falso.colas.crear, descargada());
      fixture.detectChanges();

      expect(descargas).toEqual(['fashionstore-boutique-20261030-1405.zip']);
      expect(q('[data-estado="copia-creada"]')).not.toBeNull();
      expect(texto(q('[data-estado="copia-creada"]'))).toContain('Copia creada y descargada');
      expect(texto(q('[data-descarga-nombre]'))).toContain('fashionstore-boutique-20261030-1405.zip');
      expect(texto(q('[data-checksum]'))).toBe(SHA_B);
      expect(boton().disabled).toBe(false);
      expect(q('[data-estado="creando"]')).toBeNull();
    });

    it('recarga el historial desde la página 1 tras crear', () => {
      montar();
      responderApertura([copia(1)]);
      comp.alPaginar({ first: 20, rows: 20 });
      expect(falso.servicio.listar).toHaveBeenLastCalledWith(2, 20);
      responder(falso.colas.listar, pagina([copia(1)], { total: 30, pagina: 2 }));

      pulsarCrear();
      responder(falso.colas.crear, descargada());
      fixture.detectChanges();

      expect(falso.servicio.listar).toHaveBeenCalledTimes(3);
      expect(falso.servicio.listar).toHaveBeenLastCalledWith(1, 20);
      responder(falso.colas.listar, pagina([copia(8), copia(1)]));
      fixture.detectChanges();
      expect(qa('[data-copia]').map((f) => f.dataset['copia'])).toEqual(['8', '1']);
    });

    it('"Copiar" copia el checksum completo y dice "Copiado" un momento', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      try {
        montar();
        responderApertura();
        pulsarCrear();
        responder(falso.colas.crear, descargada());
        fixture.detectChanges();

        const copiar = q('[data-accion="copiar-checksum"]') as HTMLButtonElement;
        expect(texto(copiar)).toBe('Copiar');
        copiar.click();
        await vi.advanceTimersByTimeAsync(0);
        fixture.detectChanges();

        expect(portapapeles).toHaveBeenCalledWith(SHA_B);
        expect(texto(q('[data-accion="copiar-checksum"]'))).toBe('Copiado');

        await vi.advanceTimersByTimeAsync(MS_AVISO_COPIADO + 1);
        fixture.detectChanges();
        expect(texto(q('[data-accion="copiar-checksum"]'))).toBe('Copiar');
      } finally {
        vi.useRealTimers();
      }
    });

    it('si el servidor no manda el checksum lo dice y no ofrece copiar', () => {
      montar();
      responderApertura();
      pulsarCrear();
      responder(falso.colas.crear, descargada({ checksum: null }));
      fixture.detectChanges();

      expect(q('[data-checksum]')).toBeNull();
      expect(q('[data-accion="copiar-checksum"]')).toBeNull();
      expect(texto(q('[data-sin-checksum]'))).toContain('no informó el checksum');
    });

    it('si el portapapeles falla, avisa que se copie a mano', async () => {
      montar();
      responderApertura();
      pulsarCrear();
      responder(falso.colas.crear, descargada());
      fixture.detectChanges();
      portapapeles.mockRejectedValue(new Error('denegado'));

      (q('[data-accion="copiar-checksum"]') as HTMLButtonElement).click();
      await esperar(() => q('[data-estado="error-copiar"]') !== null);
      expect(texto(q('[data-estado="error-copiar"]'))).toContain('cópialo a mano');
    });

    it('explica cómo verificar el archivo con PowerShell y con sha256sum, en un bloque plegable', () => {
      montar();
      responderApertura();

      expect(q('[data-panel="verificacion"]')).toBeNull();
      (q('[data-accion="alternar-verificacion"]') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(texto(q('[data-comando="powershell"]'))).toBe('Get-FileHash .\\fashionstore-copia.zip -Algorithm SHA256');
      expect(texto(q('[data-comando="linux"]'))).toBe('sha256sum fashionstore-copia.zip');

      pulsarCrear();
      responder(falso.colas.crear, descargada());
      fixture.detectChanges();
      expect(texto(q('[data-comando="powershell"]'))).toContain('fashionstore-boutique-20261030-1405.zip');
      expect(texto(q('[data-comando="linux"]'))).toBe('sha256sum fashionstore-boutique-20261030-1405.zip');
    });
  });

  describe('errores al crear (llegan como Blob)', () => {
    const CASOS: { nombre: string; status: number; cuerpo: unknown; clase: string; mensaje: string; reintentar: boolean }[] = [
      {
        nombre: '409 copia_en_curso',
        status: 409,
        cuerpo: { detail: 'copia_en_curso', codigo: 'copia_en_curso', mensaje: 'Ya hay una copia en curso' },
        clase: 'en_curso',
        mensaje: 'Ya hay una copia en curso; espera a que termine.',
        reintentar: false,
      },
      {
        nombre: '413 copia_demasiado_grande',
        status: 413,
        cuerpo: { codigo: 'copia_demasiado_grande', mensaje: 'Demasiado grande', limite_bytes: 104_857_600 },
        clase: 'demasiado_grande',
        mensaje: 'Los datos de tu empresa superan el tamaño máximo de una copia (el límite es 100,0 MB).',
        reintentar: false,
      },
      {
        nombre: '429',
        status: 429,
        cuerpo: { detail: 'Too Many Requests' },
        clase: 'limite',
        mensaje: 'Pediste demasiadas copias seguidas; espera un momento e inténtalo de nuevo.',
        reintentar: false,
      },
      {
        nombre: '503 servidor_ocupado',
        status: 503,
        cuerpo: { codigo: 'servidor_ocupado', mensaje: 'Ocupado' },
        clase: 'ocupado',
        mensaje: 'El servidor está ocupado en este momento. Inténtalo de nuevo en unos minutos.',
        reintentar: true,
      },
      {
        nombre: '504 copia_tiempo_agotado',
        status: 504,
        cuerpo: { codigo: 'copia_tiempo_agotado', mensaje: 'Tiempo agotado' },
        clase: 'tiempo',
        mensaje: 'La copia tardó más de lo permitido y se canceló. Inténtalo de nuevo.',
        reintentar: true,
      },
      {
        nombre: '500 copia_fallida',
        status: 500,
        cuerpo: { codigo: 'copia_fallida', mensaje: 'Falló' },
        clase: 'fallida',
        mensaje: 'No se pudo crear la copia por un error del servidor. Inténtalo de nuevo.',
        reintentar: true,
      },
    ];

    for (const caso of CASOS) {
      it(`${caso.nombre}: muestra su mensaje${caso.reintentar ? ' con [Reintentar]' : ' sin [Reintentar]'} y vuelve a habilitar el botón`, async () => {
        montar();
        responderApertura();
        pulsarCrear();
        fallar(falso.colas.crear, errorBlob(caso.status, caso.cuerpo));
        await esperar(() => q('[data-estado="error-crear"]') !== null);

        const aviso = q('[data-estado="error-crear"]') as HTMLElement;
        expect(aviso.dataset['errorClase']).toBe(caso.clase);
        expect(texto(aviso)).toContain(caso.mensaje);
        expect(q('[data-accion="reintentar-crear"]') !== null).toBe(caso.reintentar);
        expect(boton().disabled).toBe(false);
        // La pantalla sigue en pie: el historial no se tocó.
        expect(q('[data-bloqueo]')).toBeNull();
        expect(q('[data-seccion="historial"]')).not.toBeNull();
      });
    }

    it('[Reintentar] vuelve a pedir la copia y limpia el error', async () => {
      montar();
      responderApertura();
      pulsarCrear();
      fallar(falso.colas.crear, errorBlob(503, { codigo: 'servidor_ocupado' }));
      await esperar(() => q('[data-accion="reintentar-crear"]') !== null);

      (q('[data-accion="reintentar-crear"]') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(falso.servicio.crear).toHaveBeenCalledTimes(2);
      expect(q('[data-estado="error-crear"]')).toBeNull();
      expect(boton().disabled).toBe(true);
    });

    it('un 413 sin limite_bytes sigue dando un mensaje claro', async () => {
      montar();
      responderApertura();
      pulsarCrear();
      fallar(falso.colas.crear, errorBlob(413, { codigo: 'copia_demasiado_grande' }));
      await esperar(() => q('[data-estado="error-crear"]') !== null);

      expect(texto(q('[data-estado="error-crear"]'))).toContain('superan el tamaño máximo de una copia.');
    });

    it('sin respuesta del servidor (estado 0) dice que se revise la conexión', async () => {
      montar();
      responderApertura();
      pulsarCrear();
      fallar(falso.colas.crear, new HttpErrorResponse({ status: 0, error: new ProgressEvent('error') }));
      await esperar(() => q('[data-estado="error-crear"]') !== null);

      expect(texto(q('[data-estado="error-crear"]'))).toContain('No se pudo conectar con el servidor. Revisa tu conexión.');
      expect(q('[data-accion="reintentar-crear"]')).not.toBeNull();
    });
  });

  describe('plan, suscripción y rol', () => {
    it('plan sin copias_seguridad: tarjeta con candado, [Ver mi plan] a /mi-empresa, botón apagado y ninguna llamada', () => {
      montar({ incluye: false });

      expect(q('[data-bloqueo="plan"]')).not.toBeNull();
      expect(texto(q('[data-bloqueo="plan"] h2'))).toBe('Tu plan no incluye copias de seguridad');
      expect(q('[data-bloqueo="plan"] fs-icono')).not.toBeNull();
      const ver = q('[data-accion="ver-plan"]') as HTMLAnchorElement;
      expect(texto(ver)).toBe('Ver mi plan');
      expect(ver.getAttribute('href')).toBe('/mi-empresa');
      expect(boton().disabled).toBe(true);
      expect(q('[data-seccion="historial"]')).toBeNull();
      expect(q('[data-seccion="incluye"]')).toBeNull();
      expect(hayLlamadas()).toBe(0);

      comp.crear();
      expect(hayLlamadas()).toBe(0);
    });

    it('403 plan_no_incluye_funcionalidad al crear: aparece la misma tarjeta y no se vuelve a llamar', async () => {
      montar();
      responderApertura();
      pulsarCrear();
      fallar(
        falso.colas.crear,
        errorBlob(403, { detail: 'plan_no_incluye_funcionalidad', codigo: 'plan_no_incluye_funcionalidad', mensaje: 'Tu plan no la incluye' }),
      );
      await esperar(() => q('[data-bloqueo="plan"]') !== null);

      expect(q('[data-estado="error-crear"]')).toBeNull();
      expect(boton().disabled).toBe(true);
      expect(q('[data-seccion="historial"]')).toBeNull();
      expect(falso.servicio.crear).toHaveBeenCalledTimes(1);
      expect(falso.servicio.listar).toHaveBeenCalledTimes(1);
    });

    it('403 plan_no_incluye_funcionalidad al leer el historial: tarjeta de plan sin pedir nada más', async () => {
      montar();
      fallar(falso.colas.listar, errorJson(403, { codigo: 'plan_no_incluye_funcionalidad' }));
      await esperar(() => q('[data-bloqueo="plan"]') !== null);

      expect(boton().disabled).toBe(true);
      expect(falso.servicio.crear).not.toHaveBeenCalled();
    });

    it('403 suscripcion_no_activa: mensaje equivalente con [Ver mi plan] y avisa al plan', async () => {
      montar();
      responderApertura();
      pulsarCrear();
      fallar(falso.colas.crear, errorBlob(403, { codigo: 'suscripcion_no_activa', estado: 'suspendida', mensaje: 'Suscripción suspendida' }));
      await esperar(() => q('[data-bloqueo="suscripcion"]') !== null);

      expect(texto(q('[data-bloqueo="suscripcion"] h2'))).toBe('Tu suscripción no está activa');
      expect(q('[data-accion="ver-plan"]')).not.toBeNull();
      expect(plan.marcarBloqueada).toHaveBeenCalledWith('suspendida');
      expect(boton().disabled).toBe(true);
    });

    it('403 sin código de plan: "Solo el administrador de la empresa puede crear copias"', async () => {
      montar();
      responderApertura();
      pulsarCrear();
      fallar(falso.colas.crear, errorBlob(403, { detail: 'No tienes permiso para esta acción' }));
      await esperar(() => q('[data-bloqueo="rol"]') !== null);

      expect(texto(q('[data-bloqueo="rol"] h2'))).toBe('Solo el administrador de la empresa puede crear copias');
      expect(q('[data-accion="ver-plan"]')).toBeNull();
      expect(boton().disabled).toBe(true);
      expect(q('[data-seccion="historial"]')).toBeNull();
    });
  });

  describe('sin conexión', () => {
    it('deshabilita el botón, dice "Necesitas conexión a Internet" y no llama a nada', () => {
      montar({ conexion: 'sin_conexion' });

      expect(boton().disabled).toBe(true);
      expect(texto(q('[data-estado="necesita-conexion"]'))).toBe('Necesitas conexión a Internet');
      expect(q('[data-aviso="sin-conexion"]')).not.toBeNull();
      expect(hayLlamadas()).toBe(0);

      comp.crear();
      expect(falso.servicio.crear).not.toHaveBeenCalled();
    });

    it('al volver la conexión se habilita y carga el historial', () => {
      montar({ conexion: 'sin_conexion' });

      conexion.set('en_linea');
      fixture.detectChanges();
      fixture.detectChanges();

      expect(boton().disabled).toBe(false);
      expect(q('[data-aviso="sin-conexion"]')).toBeNull();
      expect(falso.servicio.listar).toHaveBeenCalledTimes(1);
      expect(falso.servicio.tablas).toHaveBeenCalledTimes(1);
    });

    it('servidor que no responde también deshabilita el botón', () => {
      montar({ conexion: 'servidor_no_responde' });
      expect(boton().disabled).toBe(true);
      expect(hayLlamadas()).toBe(0);
    });
  });

  describe('historial', () => {
    it('muestra "Cargando" antes de la primera respuesta, nunca una pantalla en blanco ni "Aún no hay copias"', () => {
      montar();

      expect(q('[data-estado="cargando-historial"]')).not.toBeNull();
      expect(q('[data-estado="historial-vacio"]')).toBeNull();
    });

    it('sin copias dice "Aún no hay copias"', () => {
      montar();
      responderApertura([]);

      expect(texto(q('[data-estado="historial-vacio"]'))).toContain('Aún no hay copias');
      expect(q('[data-copia]')).toBeNull();
    });

    it('un error del historial se explica en su bloque con [Reintentar] y no tapa el resto', async () => {
      montar();
      fallar(falso.colas.listar, errorJson(500, { detail: 'boom' }));
      responder(falso.colas.tablas, TABLAS);
      await esperar(() => q('[data-estado="error-historial"]') !== null);

      expect(texto(q('[data-estado="error-historial"]'))).toContain('No pudimos cargar el historial.');
      expect(boton().disabled).toBe(false);
      expect(q('[data-seccion="incluye"]')).not.toBeNull();
      await abrirPanel();
      expect(q('[data-lista="incluidas"]')).not.toBeNull();

      (q('[data-accion="reintentar-historial"]') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(falso.servicio.listar).toHaveBeenCalledTimes(2);
      responder(falso.colas.listar, pagina([copia(1)]));
      fixture.detectChanges();
      expect(q('[data-estado="error-historial"]')).toBeNull();
      expect(qa('[data-copia]').length).toBe(1);
    });

    it('cada fila muestra fecha local, quién la pidió, estado, tamaño legible, filas y checksum corto', () => {
      montar();
      responderApertura([copia(1)]);

      const fila = q('[data-copia="1"]') as HTMLElement;
      const fecha = new Date('2026-10-30T14:05:00Z');
      const dos = (n: number) => String(n).padStart(2, '0');
      const esperada = `${dos(fecha.getDate())}/${dos(fecha.getMonth() + 1)}/${fecha.getFullYear()} ${dos(fecha.getHours())}:${dos(fecha.getMinutes())}`;
      expect(texto(fila.querySelector('[data-celda="fecha"]'))).toBe(esperada);
      expect(texto(fila.querySelector('[data-celda="usuario"]'))).toBe('Ana Paz');
      expect(texto(fila.querySelector('[data-celda="estado"]'))).toBe('Completada');
      expect(texto(fila.querySelector('[data-celda="tamano"]'))).toMatch(/^1[,.]5 MB$/);
      expect(texto(fila.querySelector('[data-celda="filas"]')).replace(/\D/g, '')).toBe('12345');
      expect(texto(fila.querySelector('[data-checksum-corto]'))).toBe(SHA_A.slice(0, 12));
      expect(texto(fila.querySelector('[data-checksum-corto]'))).toHaveLength(12);
    });

    it('el chip de cada estado lleva su clase, ícono y texto; la fallida explica el motivo en lenguaje claro', () => {
      montar();
      responderApertura([
        copia(1),
        copia(2, { estado: 'en_proceso', checksum: null, tamano_bytes: null, total_filas: null }),
        copia(3, { estado: 'fallida', checksum: null, motivo_fallo: 'copia_demasiado_grande' }),
        copia(4, { estado: 'fallida', checksum: null, motivo_fallo: 'copia_tiempo_agotado' }),
        copia(5, { estado: 'fallida', checksum: null, motivo_fallo: 'servidor_ocupado' }),
        copia(6, { estado: 'fallida', checksum: null, motivo_fallo: 'abandonada' }),
        copia(7, { estado: 'fallida', checksum: null, motivo_fallo: 'error_interno' }),
        copia(8, { estado: 'fallida', checksum: null, motivo_fallo: 'algo_nuevo' }),
      ]);

      const chip = (id: number) => q(`[data-copia="${id}"] [data-estado-copia]`) as HTMLElement;
      const motivo = (id: number) => texto(q(`[data-copia="${id}"] [data-motivo]`));

      expect(chip(1).classList).toContain('fs-chip--exito');
      expect(texto(chip(1))).toBe('Completada');
      expect(chip(1).querySelector('fs-icono')).not.toBeNull();
      expect(q('[data-copia="1"] [data-motivo]')).toBeNull();

      expect(chip(2).classList).toContain('fs-chip--advertencia');
      expect(texto(chip(2))).toBe('En curso');
      expect(texto(q('[data-copia="2"] [data-celda="tamano"]'))).toBe('—');

      for (const id of [3, 4, 5, 6, 7, 8]) {
        expect(chip(id).classList).toContain('fs-chip--error');
        expect(texto(chip(id))).toBe('Fallida');
      }
      expect(motivo(3)).toBe('Los datos superaron el tamaño máximo permitido para una copia.');
      expect(motivo(4)).toBe('Tardó más de lo permitido y se canceló.');
      expect(motivo(5)).toBe('El servidor estaba ocupado en ese momento.');
      expect(motivo(6)).toBe('Se interrumpió antes de terminar.');
      expect(motivo(7)).toBe('Ocurrió un error en el servidor.');
      expect(motivo(8)).toBe('No se pudo completar la copia.');
      // Una copia sin checksum no ofrece copiarlo.
      expect(q('[data-copia="3"] [data-accion="copiar-fila"]')).toBeNull();
    });

    it('"Copiar" de una fila copia el checksum completo', async () => {
      montar();
      responderApertura([copia(1), copia(2, { checksum: SHA_B })]);

      const botones = qa('[data-accion="copiar-fila"]');
      expect(botones).toHaveLength(2);
      botones[1].click();
      await esperar(() => texto(qa('[data-accion="copiar-fila"]')[1]) === 'Copiado');

      expect(portapapeles).toHaveBeenCalledWith(SHA_B);
      expect(texto(qa('[data-accion="copiar-fila"]')[0])).toBe('Copiar');
    });

    it('pagina en el servidor: pide la página que corresponde a la fila inicial', () => {
      montar();
      responder(falso.colas.listar, pagina([copia(1)], { total: 45 }));
      fixture.detectChanges();

      comp.alPaginar({ first: 40, rows: 20 });
      expect(falso.servicio.listar).toHaveBeenLastCalledWith(3, 20);

      // Repetir la misma página no vuelve a pedirla.
      const llamadas = falso.servicio.listar.mock.calls.length;
      comp.alPaginar({ first: 40, rows: 20 });
      expect(falso.servicio.listar).toHaveBeenCalledTimes(llamadas);
    });
  });

  describe('qué incluye y qué no', () => {
    it('arranca plegado y al abrirlo muestra incluidas, referencias, excluidas con su motivo y columnas excluidas', async () => {
      montar();
      responderApertura();

      expect(q('[data-panel="incluye"]')).toBeNull();
      expect((q('[data-accion="alternar-panel"]') as HTMLElement).getAttribute('aria-expanded')).toBe('false');
      await abrirPanel();
      expect((q('[data-accion="alternar-panel"]') as HTMLElement).getAttribute('aria-expanded')).toBe('true');

      expect(qa('[data-lista="incluidas"] li').map((li) => texto(li))).toEqual(['Producto', 'Orden compra', 'Venta']);
      expect(qa('[data-lista="referencias"] li').map((li) => texto(li))).toEqual(['Permiso', 'Metodo pago']);
      const par = (li: HTMLElement) => [texto(li.querySelector('strong')), texto(li.querySelector('.tenue'))];
      expect(qa('[data-lista="excluidas"] li').map(par)).toEqual([
        ['Bitacora', 'Es el registro de auditoría: no forma parte de los datos de negocio.'],
        ['Transaccion pasarela', 'Datos de pagos de la pasarela.'],
      ]);
      expect(qa('[data-lista="columnas"] li').map(par)).toEqual([['Usuario', 'Password hash, Token reset']]);

      await abrirPanel();
      expect(q('[data-panel="incluye"]')).toBeNull();
    });

    it('mientras carga dice que está leyendo y nunca queda en blanco', async () => {
      montar();
      responder(falso.colas.listar, pagina([copia(1)]));
      await abrirPanel();

      expect(texto(q('[data-estado="cargando-tablas"]'))).toContain('Leyendo qué incluye la copia');
    });

    it('un error propio no afecta al historial y se puede reintentar', async () => {
      montar();
      responder(falso.colas.listar, pagina([copia(1)]));
      fallar(falso.colas.tablas, errorJson(500, {}));
      await abrirPanel();
      await esperar(() => q('[data-estado="error-tablas"]') !== null);

      expect(texto(q('[data-estado="error-tablas"]'))).toContain('No pudimos leer qué incluye la copia.');
      expect(q('[data-estado="error-historial"]')).toBeNull();
      expect(qa('[data-copia]').length).toBe(1);

      (q('[data-accion="reintentar-tablas"]') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(falso.servicio.tablas).toHaveBeenCalledTimes(2);
      responder(falso.colas.tablas, TABLAS);
      fixture.detectChanges();
      expect(q('[data-lista="incluidas"]')).not.toBeNull();
    });

    it('sin referencias, excluidas ni columnas no dibuja esas secciones vacías', async () => {
      montar();
      responderApertura([copia(1)], { incluidas: ['producto'], referencias: [], excluidas: [], columnas_excluidas: {} });
      await abrirPanel();

      expect(q('[data-lista="incluidas"]')).not.toBeNull();
      expect(q('[data-lista="referencias"]')).toBeNull();
      expect(q('[data-lista="excluidas"]')).toBeNull();
      expect(q('[data-lista="columnas"]')).toBeNull();
    });
  });

  describe('al destruir', () => {
    it('cancela las consultas en curso y la copia en curso', () => {
      montar();
      pulsarCrear();
      const { crear, listar, tablas } = falso.colas;
      expect(crear).toHaveLength(1);

      fixture.destroy();
      // Resolver después de destruir no rompe nada ni descarga el archivo.
      expect(() => {
        crear[0].next(descargada());
        listar[0].next(pagina([copia(1)]));
        tablas[0].next(TABLAS);
      }).not.toThrow();
      expect(descargas).toEqual([]);
    });

    it('no deja el aviso "Copiado" pendiente', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      try {
        montar();
        responderApertura();
        (q('[data-accion="copiar-fila"]') as HTMLButtonElement).click();
        await vi.advanceTimersByTimeAsync(0);
        expect(vi.getTimerCount()).toBeGreaterThan(0);

        fixture.destroy();
        expect(vi.getTimerCount()).toBe(0);
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
