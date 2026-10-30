// Debe ir ANTES de importar Dexie: simula IndexedDB en memoria (jsdom no la trae).
import 'fake-indexeddb/auto';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import Dexie from 'dexie';
import { environment } from '../../../environments/environment';
import { ConectividadService, EstadoConexion } from '../conectividad.service';
import { SIN_TOAST_ERROR } from '../http-contexts';
import { PlanService } from '../plan.service';
import { BaseOffline } from './db-offline';
import { UMBRAL_DESACTUALIZADO_HORAS } from './offline.config';
import type { AlcanceOffline, PaqueteLocal } from './offline.models';
import { PaqueteOfflineService } from './paquete-offline.service';
import { RepositorioLocal } from './repositorio-local';
import { SesionOfflineService } from './sesion-offline.service';

const API = environment.apiUrl;
const HORA_MS = 3_600_000;

/** `generado_en` que el servidor pone en el CATÁLOGO: es el que debe quedar como "última descarga". */
const GENERADO_CATALOGO = '2026-10-30T10:00:00Z';
const T0 = Date.parse(GENERADO_CATALOGO);
const ANTERIOR_GENERADO = '2026-10-29T08:00:00Z';

Dexie.dependencies.indexedDB = indexedDB;
Dexie.dependencies.IDBKeyRange = IDBKeyRange;

// ---- Un servidor de mentira ---------------------------------------------------------------------------------------------

interface Escenario {
  totalCatalogo: number;
  totalClientes: number;
  avisoHoras: number;
  /** Cambia la respuesta de una petición: un fallo HTTP, una caída de red o un cuerpo propio. */
  falla?: (ruta: string, desde: string | null) => { status: number; cuerpo?: unknown } | 'red' | null;
  /** El catálogo siempre dice que la siguiente página empieza en la misma clave. */
  cursorQueNoAvanza?: boolean;
}

interface Peticion {
  ruta: string;
  params: Record<string, string | null>;
  sinToast: boolean;
}

const escenarioBase = (): Escenario => ({ totalCatalogo: 3, totalClientes: 2, avisoHoras: 12 });

const variante = (id: number) => ({
  id,
  talla_id: 1,
  color_id: 1,
  sku: `SKU-${id}`,
  codigo_barras: null,
  precio: '149.00',
  descuento_unitario: '0.00',
});

const producto = (id: number, nombre: string, variantes: number[]) => ({
  id,
  codigo: `P-${id}`,
  nombre,
  categoria_id: 1,
  genero: 'masculino',
  temporada_id: null,
  imagen_principal: null,
  variantes: variantes.map(variante),
});

const PRODUCTOS = [
  producto(10, 'Polera básica', [100, 101]),
  producto(20, 'Camisa lino', [200]),
  producto(30, 'Chamarra', [300]),
];

/** Stock de mentira: `sucursal * 1000 + variante`, así se ve de dónde salió cada número. */
const stockItem = (sucursalId: number, varianteId: number) => ({
  variante_id: varianteId,
  cantidad_disponible: sucursalId * 1000 + varianteId,
  actualizado_en: '2026-10-30T09:00:00Z',
});

const MANIFIESTO = (aviso: number) => ({
  version_contrato: '1',
  generado_en: '2026-10-30T09:59:58Z',
  aviso_desactualizado_horas: aviso,
  empresa: { id: 1, codigo: 'fashionstore', nombre: 'FashionStore' },
  sucursales: [
    { id: 1, codigo: 'CEN', nombre: 'Central', direccion: 'Av. 1', es_deposito: false, horarios: [] },
    { id: 2, codigo: 'DEP', nombre: 'Depósito', direccion: 'Av. 2', es_deposito: true, horarios: [] },
  ],
  referencia: {
    categorias: [{ id: 1, nombre: 'Poleras', categoria_padre_id: null }],
    tallas: [{ id: 1, codigo: 'M', orden: 2 }],
    colores: [{ id: 1, nombre: 'Negro', codigo_hex: '#000000' }],
  },
  reglas: {
    metodos_pago_offline: ['efectivo'],
    max_operaciones_por_lote: 50,
    plazo_cambio_horas: 24,
    cambios_y_devoluciones: 'solo_en_linea',
    reservas_offline: 'sin_conflicto',
  },
});

function cuerpoDe(ruta: string, params: Record<string, string | null>, esc: Escenario): object {
  const desde = params['desde_id'] ?? params['desde_variante_id'] ?? null;
  switch (ruta) {
    case '/sincronizacion/paquete':
      return MANIFIESTO(esc.avisoHoras);
    case '/sincronizacion/paquete/catalogo': {
      const primera = desde === null;
      return {
        version_contrato: '1',
        generado_en: GENERADO_CATALOGO,
        total: esc.totalCatalogo,
        siguiente_desde_id: primera ? 20 : esc.cursorQueNoAvanza ? 20 : null,
        items: primera ? PRODUCTOS.slice(0, 2) : PRODUCTOS.slice(2),
      };
    }
    case '/sincronizacion/paquete/stock': {
      const sucursal = Number(params['sucursal_id']);
      // La sucursal 1 llega en dos páginas; la 2 (el depósito), en una.
      const dosPaginas = sucursal === 1;
      const primera = desde === null;
      const items = dosPaginas
        ? primera
          ? [stockItem(1, 100), stockItem(1, 101)]
          : [stockItem(1, 200), stockItem(1, 300)]
        : [stockItem(2, 100)];
      return {
        version_contrato: '1',
        generado_en: '2026-10-30T10:00:05Z',
        sucursal_id: sucursal,
        incremental: false,
        siguiente_desde_variante_id: dosPaginas && primera ? 101 : null,
        items,
      };
    }
    case '/sincronizacion/paquete/clientes':
      return {
        version_contrato: '1',
        generado_en: '2026-10-30T10:00:06Z',
        total: esc.totalClientes,
        siguiente_desde_id: null,
        items: [
          { id: 7, nombre: 'Ana', apellido: 'Paz', ci_nit: '1234567' },
          { id: 8, nombre: 'Luis', apellido: 'Rojas', ci_nit: null },
        ],
      };
    default:
      throw new Error(`Ruta inesperada en la prueba: ${ruta}`);
  }
}

// ---- Fixtures de la base ------------------------------------------------------------------------------------------------

function paqueteAnterior(): PaqueteLocal {
  return {
    empresa: { id: 1, codigo: 'fashionstore', nombre: 'FashionStore' },
    generadoEn: ANTERIOR_GENERADO,
    avisoDesactualizadoHoras: 12,
    sucursales: [{ id: 1, codigo: 'CEN', nombre: 'Central', direccion: 'Av. 1', es_deposito: false, horarios: [] }],
    categorias: [{ id: 1, nombre: 'Poleras', categoria_padre_id: null }],
    tallas: [{ id: 1, codigo: 'M', orden: 2 }],
    colores: [{ id: 1, nombre: 'Negro', codigo_hex: '#000000' }],
    productos: [producto(999, 'Anterior', [9990])],
    stock: [{ sucursalId: 1, generadoEn: ANTERIOR_GENERADO, items: [stockItem(0, 9990)] }],
    clientes: [{ id: 99, nombre: 'Vieja', apellido: 'Clienta', ci_nit: null }],
    reglas: MANIFIESTO(12).reglas,
  };
}

describe('PaqueteOfflineService', () => {
  let http: HttpTestingController;
  let servicio: PaqueteOfflineService;
  let base: BaseOffline;
  let repo: RepositorioLocal;
  let nombreBase: string;
  let alcance: ReturnType<typeof signal<AlcanceOffline | null>>;
  let estadoConexion: ReturnType<typeof signal<EstadoConexion>>;
  let planIncluye: boolean;
  let peticiones: Peticion[];
  let escenario: Escenario;
  let contador = 0;

  beforeEach(() => {
    // Solo la fecha y los intervalos son falsos: fake-indexeddb necesita los temporizadores de verdad.
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] });
    vi.setSystemTime(T0 + HORA_MS);

    nombreBase = `paquete_offline_prueba_${++contador}_${Math.random().toString(36).slice(2)}`;
    base = new BaseOffline(nombreBase);
    alcance = signal<AlcanceOffline | null>({ empresaId: 1, usuarioId: 5 });
    estadoConexion = signal<EstadoConexion>('en_linea');
    planIncluye = true;
    peticiones = [];
    escenario = escenarioBase();
    repo = new RepositorioLocal(base, { empresaId: 1, usuarioId: 5 });

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: SesionOfflineService,
          useValue: {
            alcance,
            repositorio: () => (alcance() === null ? null : new RepositorioLocal(base, alcance()!)),
          },
        },
        { provide: ConectividadService, useValue: { estado: estadoConexion } },
        { provide: PlanService, useValue: { estadoActivo: signal(true), incluye: () => planIncluye } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    servicio = TestBed.inject(PaqueteOfflineService);
  });

  afterEach(async () => {
    TestBed.resetTestingModule();
    vi.useRealTimers();
    base.close();
    await Dexie.delete(nombreBase);
  });

  const esperar = () => new Promise<void>((resolver) => setTimeout(resolver, 0));

  function atender(req: TestRequest): void {
    const ruta = req.request.url.replace(API, '');
    const params = Object.fromEntries(req.request.params.keys().map((k) => [k, req.request.params.get(k)]));
    peticiones.push({ ruta, params, sinToast: req.request.context.get(SIN_TOAST_ERROR) });
    const desde = params['desde_id'] ?? params['desde_variante_id'] ?? null;
    const falla = escenario.falla?.(ruta, desde) ?? null;
    if (falla === 'red') {
      req.error(new ProgressEvent('error'));
    } else if (falla !== null) {
      req.flush((falla.cuerpo ?? { detail: 'falla de prueba' }) as object,{ status: falla.status, statusText: 'Falla' });
    } else {
      req.flush(cuerpoDe(ruta, params, escenario));
    }
  }

  /** Atiende las peticiones a medida que el servicio las va pidiendo, hasta que su promesa termina. */
  async function conServidor<T>(promesa: Promise<T>): Promise<T> {
    let terminada = false;
    void promesa.finally(() => (terminada = true));
    for (let vuelta = 0; !terminada && vuelta < 2000; vuelta++) {
      for (const req of http.match(() => true)) atender(req);
      await esperar();
    }
    return promesa;
  }

  const rutas = () => peticiones.map((p) => p.ruta);

  async function sembrarPaqueteAnterior(): Promise<void> {
    await repo.reemplazarReferencia(paqueteAnterior());
    await servicio.cargarEstado();
    expect(servicio.ultimaDescarga()).toBe(ANTERIOR_GENERADO);
  }

  async function expectAnteriorIntacto(): Promise<void> {
    expect((await repo.buscarProductos('')).map((p) => p.nombre)).toEqual(['Anterior']);
    expect(await repo.stockDeVariante(9990)).toEqual({ 1: 9990 });
    expect((await repo.clientes('')).map((c) => c.id)).toEqual([99]);
    expect(await repo.ultimaDescarga()).toBe(ANTERIOR_GENERADO);
    expect(servicio.ultimaDescarga()).toBe(ANTERIOR_GENERADO);
  }

  // ---- Descarga completa ----------------------------------------------------------------------------------------------------

  describe('descarga completa', () => {
    it('pide manifiesto, catálogo, stock de cada sucursal y clientes, todo paginado y sin toast de error', async () => {
      const ok = await conServidor(servicio.descargar());

      expect(ok).toBe(true);
      expect(peticiones.map((p) => [p.ruta, p.params])).toEqual([
        ['/sincronizacion/paquete', {}],
        ['/sincronizacion/paquete/catalogo', { limite: '200' }],
        ['/sincronizacion/paquete/catalogo', { limite: '200', desde_id: '20' }],
        ['/sincronizacion/paquete/stock', { limite: '500', sucursal_id: '1' }],
        ['/sincronizacion/paquete/stock', { limite: '500', sucursal_id: '1', desde_variante_id: '101' }],
        ['/sincronizacion/paquete/stock', { limite: '500', sucursal_id: '2' }],
        ['/sincronizacion/paquete/clientes', { limite: '500' }],
      ]);
      // Cada petición lleva SIN_TOAST_ERROR (un fallo de red no debe abrir el toast rojo).
      expect(peticiones.every((p) => p.sinToast)).toBe(true);
    });

    it('guarda todo, también el stock de los depósitos, y deja ultimaDescarga con el generado_en del servidor', async () => {
      await conServidor(servicio.descargar());

      const productos = await repo.buscarProductos('');
      expect(productos.map((p) => p.nombre).sort()).toEqual(['Camisa lino', 'Chamarra', 'Polera básica']);
      const polera = productos.find((p) => p.id === 10)!;
      expect(polera.variantes.map((v) => v.id).sort()).toEqual([100, 101]);
      expect(polera.categoria).toBe('Poleras');
      expect(polera.variantes[0].talla).toBe('M');
      expect(polera.variantes[0].precio).toBe('149.00');

      // Stock de las dos sucursales (la 2 es depósito) y de las dos páginas de la primera.
      expect(await repo.stockDeVariante(100)).toEqual({ 1: 1100, 2: 2100 });
      expect(await repo.stockDeVariante(101)).toEqual({ 1: 1101 });
      expect(await repo.stockDeVariante(300)).toEqual({ 1: 1300 });
      const filasStock = await base.stock_conocido.toArray();
      expect(filasStock).toHaveLength(5);
      expect(filasStock.every((f) => f.generado_en === '2026-10-30T10:00:05Z')).toBe(true);

      expect((await repo.sucursales()).map((s) => [s.id, s.es_deposito]).sort()).toEqual([
        [1, false],
        [2, true],
      ]);
      expect((await repo.clientes('')).map((c) => c.id).sort()).toEqual([7, 8]);
      expect((await repo.categorias()).map((c) => c.id)).toEqual([1]);

      // Del catálogo (10:00:00), no del manifiesto (09:59:58) ni de los clientes.
      expect(servicio.ultimaDescarga()).toBe(GENERADO_CATALOGO);
      expect(await repo.ultimaDescarga()).toBe(GENERADO_CATALOGO);
      expect(servicio.estadoDatos()).toBe('vigentes');
      expect(servicio.errorDescarga()).toBeNull();
      expect(servicio.descargando()).toBe(false);
    });

    it('reemplaza el paquete anterior (lo que ya no llega desaparece)', async () => {
      await sembrarPaqueteAnterior();

      expect(await conServidor(servicio.descargar())).toBe(true);

      const nombres = (await repo.buscarProductos('')).map((p) => p.nombre);
      expect(nombres).not.toContain('Anterior');
      expect(nombres).toHaveLength(3);
      expect(await repo.stockDeVariante(9990)).toEqual({});
      expect((await repo.clientes('')).map((c) => c.id)).not.toContain(99);
    });

    it('marca descargando mientras corre y lo apaga al terminar', async () => {
      const promesa = servicio.descargar();
      expect(servicio.descargando()).toBe(true);
      await conServidor(promesa);
      expect(servicio.descargando()).toBe(false);
    });
  });

  // ---- Fallos: el paquete anterior queda intacto -------------------------------------------------------------------------

  describe('si algo falla no se reemplaza nada', () => {
    it.each([
      ['el total del catálogo no coincide con lo recibido', { totalCatalogo: 5 }],
      ['el total de clientes no coincide con lo recibido', { totalClientes: 9 }],
    ])('%s: error y queda lo anterior', async (_nombre, cambio) => {
      await sembrarPaqueteAnterior();
      escenario = { ...escenarioBase(), ...cambio };

      const ok = await conServidor(servicio.descargar());

      expect(ok).toBe(false);
      expect(servicio.errorDescarga()).toBe('error');
      expect(servicio.descargando()).toBe(false);
      await expectAnteriorIntacto();
    });

    it('un total que no coincide sin paquete previo no deja nada guardado', async () => {
      escenario.totalCatalogo = 99;

      expect(await conServidor(servicio.descargar())).toBe(false);

      expect(await repo.hayCatalogo()).toBe(false);
      expect(await repo.ultimaDescarga()).toBeUndefined();
      expect(servicio.estadoDatos()).toBe('sin_datos');
    });

    it('si falla la segunda página del catálogo, el paquete anterior queda intacto', async () => {
      await sembrarPaqueteAnterior();
      escenario.falla = (ruta, desde) => (ruta.endsWith('/catalogo') && desde === '20' ? { status: 500 } : null);

      expect(await conServidor(servicio.descargar())).toBe(false);

      expect(servicio.errorDescarga()).toBe('error');
      // Se pidió la segunda página y se detuvo ahí: ni stock ni clientes.
      expect(rutas()).toEqual(['/sincronizacion/paquete', '/sincronizacion/paquete/catalogo', '/sincronizacion/paquete/catalogo']);
      await expectAnteriorIntacto();
    });

    it('si falla la segunda página del stock (ya bajado todo el catálogo), el paquete anterior queda intacto', async () => {
      await sembrarPaqueteAnterior();
      escenario.falla = (ruta, desde) => (ruta.endsWith('/stock') && desde === '101' ? { status: 500 } : null);

      expect(await conServidor(servicio.descargar())).toBe(false);

      expect(servicio.errorDescarga()).toBe('error');
      expect(rutas()).not.toContain('/sincronizacion/paquete/clientes');
      await expectAnteriorIntacto();
    });

    it('un cursor que no avanza corta la descarga en vez de dar vueltas', async () => {
      await sembrarPaqueteAnterior();
      escenario.cursorQueNoAvanza = true;

      expect(await conServidor(servicio.descargar())).toBe(false);

      expect(servicio.errorDescarga()).toBe('error');
      expect(rutas().filter((r) => r.endsWith('/catalogo'))).toHaveLength(2);
      await expectAnteriorIntacto();
    });

    it('sin red (status 0) a mitad de la descarga: sin_conexion y lo anterior intacto', async () => {
      await sembrarPaqueteAnterior();
      escenario.falla = (ruta, desde) => (ruta.endsWith('/stock') && desde === '101' ? 'red' : null);

      expect(await conServidor(servicio.descargar())).toBe(false);

      expect(servicio.errorDescarga()).toBe('sin_conexion');
      await expectAnteriorIntacto();
    });

    it('sin red desde la primera petición: sin_conexion', async () => {
      escenario.falla = () => 'red';

      expect(await conServidor(servicio.descargar())).toBe(false);

      expect(servicio.errorDescarga()).toBe('sin_conexion');
      expect(rutas()).toEqual(['/sincronizacion/paquete']);
    });

    it('403 de plan_no_incluye_funcionalidad: plan_sin_offline y no guarda nada', async () => {
      escenario.falla = () => ({
        status: 403,
        cuerpo: { detail: 'x', codigo: 'plan_no_incluye_funcionalidad', mensaje: 'Tu plan no lo incluye' },
      });

      expect(await conServidor(servicio.descargar())).toBe(false);

      expect(servicio.errorDescarga()).toBe('plan_sin_offline');
      expect(await repo.hayCatalogo()).toBe(false);
      expect(await repo.ultimaDescarga()).toBeUndefined();
      expect(servicio.ultimaDescarga()).toBeNull();
      expect(rutas()).toEqual(['/sincronizacion/paquete']);
    });

    it('403 de suscripcion_no_activa: suscripcion', async () => {
      escenario.falla = () => ({ status: 403, cuerpo: { detail: 'x', codigo: 'suscripcion_no_activa' } });

      expect(await conServidor(servicio.descargar())).toBe(false);

      expect(servicio.errorDescarga()).toBe('suscripcion');
    });

    it('un 403 sin código funcional (u otro código) es un error común', async () => {
      escenario.falla = () => ({ status: 403, cuerpo: { detail: 'Sin permiso' } });

      expect(await conServidor(servicio.descargar())).toBe(false);

      expect(servicio.errorDescarga()).toBe('error');
    });

    it('después de un fallo, una descarga buena limpia el error', async () => {
      escenario.falla = () => ({ status: 500 });
      await conServidor(servicio.descargar());
      expect(servicio.errorDescarga()).toBe('error');

      escenario.falla = undefined;
      expect(await conServidor(servicio.descargar())).toBe(true);

      expect(servicio.errorDescarga()).toBeNull();
      expect(servicio.ultimaDescarga()).toBe(GENERADO_CATALOGO);
    });
  });

  // ---- Descargas simultáneas ---------------------------------------------------------------------------------------------------

  describe('descargas simultáneas', () => {
    it('dos llamadas a la vez hacen UNA sola ronda de peticiones', async () => {
      const primera = servicio.descargar();
      const segunda = servicio.descargar();
      expect(segunda).toBe(primera);

      const [a, b] = await conServidor(Promise.all([primera, segunda]));

      expect([a, b]).toEqual([true, true]);
      expect(rutas().filter((r) => r === '/sincronizacion/paquete')).toHaveLength(1);
      expect(rutas()).toHaveLength(7);
    });

    it('terminada la descarga, una nueva llamada vuelve a pedir todo', async () => {
      await conServidor(servicio.descargar());
      await conServidor(servicio.descargar());

      expect(rutas().filter((r) => r === '/sincronizacion/paquete')).toHaveLength(2);
    });
  });

  // ---- Sin sesión --------------------------------------------------------------------------------------------------------------

  describe('sin sesión', () => {
    it('sin empresa ni usuario no pide nada y deja un error claro', async () => {
      alcance.set(null);

      const ok = await servicio.descargar();

      expect(ok).toBe(false);
      expect(servicio.errorDescarga()).toBe('error');
      expect(servicio.descargando()).toBe(false);
      http.verify();
      expect(peticiones).toEqual([]);
    });

    it('descargarSiHaceFalta tampoco pide nada sin sesión', async () => {
      alcance.set(null);

      expect(await servicio.descargarSiHaceFalta()).toBe(false);

      http.verify();
    });

    it('si cambia el usuario mientras se descarga, el resultado no pisa las señales del nuevo', async () => {
      const promesa = servicio.descargar();
      alcance.set({ empresaId: 2, usuarioId: 6 });
      await conServidor(promesa);

      expect(servicio.ultimaDescarga()).toBeNull();
      expect(servicio.estadoDatos()).toBe('sin_datos');
    });
  });

  // ---- cargarEstado ------------------------------------------------------------------------------------------------------------

  describe('cargarEstado', () => {
    it('sin nada guardado queda en sin_datos', async () => {
      await servicio.cargarEstado();

      expect(servicio.ultimaDescarga()).toBeNull();
      expect(servicio.estadoDatos()).toBe('sin_datos');
    });

    it('lee de IndexedDB la última descarga y el umbral guardados', async () => {
      await repo.reemplazarReferencia({ ...paqueteAnterior(), generadoEn: GENERADO_CATALOGO, avisoDesactualizadoHoras: 3 });

      await servicio.cargarEstado();

      expect(servicio.ultimaDescarga()).toBe(GENERADO_CATALOGO);
      expect(servicio.umbralHoras()).toBe(3);
      expect(servicio.estadoDatos()).toBe('vigentes');
    });

    it('lo guardado de otra empresa no cuenta', async () => {
      const otra = new RepositorioLocal(base, { empresaId: 2, usuarioId: 9 });
      await otra.reemplazarReferencia(paqueteAnterior());

      await servicio.cargarEstado();

      expect(servicio.ultimaDescarga()).toBeNull();
      expect(servicio.estadoDatos()).toBe('sin_datos');
    });

    it('nunca lanza: si la base no se puede leer queda en sin_datos', async () => {
      await repo.reemplazarReferencia(paqueteAnterior());
      const roto = {
        ultimaDescarga: () => Promise.reject(new Error('IndexedDB no disponible')),
        umbralHoras: () => Promise.reject(new Error('IndexedDB no disponible')),
      };
      const sesion = TestBed.inject(SesionOfflineService) as unknown as { repositorio: () => unknown };
      sesion.repositorio = () => roto;

      await expect(servicio.cargarEstado()).resolves.toBeUndefined();

      expect(servicio.estadoDatos()).toBe('sin_datos');
    });
  });

  // ---- estadoDatos -------------------------------------------------------------------------------------------------------------

  describe('estadoDatos', () => {
    const horasDespues = (h: number) => {
      vi.setSystemTime(T0 + h * HORA_MS);
      servicio.recalcular();
    };

    it('usa el umbral por defecto (offline.config) si el servidor no manda uno válido', async () => {
      escenario.avisoHoras = 0;
      await conServidor(servicio.descargar());

      expect(servicio.umbralHoras()).toBe(UMBRAL_DESACTUALIZADO_HORAS);
      horasDespues(UMBRAL_DESACTUALIZADO_HORAS - 0.01);
      expect(servicio.estadoDatos()).toBe('vigentes');
      horasDespues(UMBRAL_DESACTUALIZADO_HORAS + 0.01);
      expect(servicio.estadoDatos()).toBe('desactualizados');
    });

    it('respeta aviso_desactualizado_horas del servidor', async () => {
      escenario.avisoHoras = 2;
      await conServidor(servicio.descargar());

      expect(servicio.umbralHoras()).toBe(2);
      horasDespues(1.99);
      expect(servicio.estadoDatos()).toBe('vigentes');
      horasDespues(2.01);
      expect(servicio.estadoDatos()).toBe('desactualizados');
      // Con el umbral por defecto (12 h) a las 2,01 h todavía estarían vigentes: la prueba falla si se ignora el del servidor.
      expect(UMBRAL_DESACTUALIZADO_HORAS).toBeGreaterThan(2.01);
    });

    it('pasa a desactualizados sin que nadie lo pida, con el intervalo de 1 minuto', async () => {
      escenario.avisoHoras = 2;
      await conServidor(servicio.descargar());
      expect(servicio.estadoDatos()).toBe('vigentes');

      // Pasa el tiempo (solo cambia el reloj): hasta que corre el intervalo, el valor no se recalcula.
      vi.setSystemTime(T0 + 3 * HORA_MS);
      expect(servicio.estadoDatos()).toBe('vigentes');

      vi.advanceTimersByTime(60_000);
      expect(servicio.estadoDatos()).toBe('desactualizados');
    });

    it('al destruirse el servicio limpia el intervalo', () => {
      expect(vi.getTimerCount()).toBeGreaterThan(0);

      TestBed.resetTestingModule();

      expect(vi.getTimerCount()).toBe(0);
    });

    it('una fecha ilegible cuenta como desactualizada, no como vigente', async () => {
      await repo.reemplazarReferencia({ ...paqueteAnterior(), generadoEn: 'no es una fecha' });

      await servicio.cargarEstado();

      expect(servicio.estadoDatos()).toBe('desactualizados');
    });
  });

  // ---- descargarSiHaceFalta ----------------------------------------------------------------------------------------------------

  describe('descargarSiHaceFalta', () => {
    it('sin datos y con conexión descarga', async () => {
      await servicio.cargarEstado();

      expect(await conServidor(servicio.descargarSiHaceFalta())).toBe(true);

      expect(rutas()[0]).toBe('/sincronizacion/paquete');
    });

    it('con datos vigentes no pide nada', async () => {
      await repo.reemplazarReferencia({ ...paqueteAnterior(), generadoEn: GENERADO_CATALOGO });
      await servicio.cargarEstado();
      expect(servicio.estadoDatos()).toBe('vigentes');

      expect(await servicio.descargarSiHaceFalta()).toBe(false);

      http.verify();
      expect(peticiones).toEqual([]);
    });

    it('con datos desactualizados descarga', async () => {
      await repo.reemplazarReferencia({ ...paqueteAnterior(), generadoEn: GENERADO_CATALOGO });
      await servicio.cargarEstado();
      vi.setSystemTime(T0 + 13 * HORA_MS);
      servicio.recalcular();
      expect(servicio.estadoDatos()).toBe('desactualizados');

      expect(await conServidor(servicio.descargarSiHaceFalta())).toBe(true);

      expect(servicio.ultimaDescarga()).toBe(GENERADO_CATALOGO);
      expect(rutas()).toContain('/sincronizacion/paquete/catalogo');
    });

    it('sin conexión no pide nada', async () => {
      estadoConexion.set('sin_conexion');

      expect(await servicio.descargarSiHaceFalta()).toBe(false);

      http.verify();
    });

    it('si el plan no incluye operación sin conexión no pide nada', async () => {
      planIncluye = false;

      expect(await servicio.descargarSiHaceFalta()).toBe(false);

      http.verify();
    });
  });
});
