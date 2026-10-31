import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NO_ERRORS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { ChartModule } from 'primeng/chart';
import { Observable, of, throwError } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ConectividadService } from '../../core/conectividad.service';
import {
  ArchivoDescargado,
  FiltroCatalogo,
  ReporteCatalogo,
  ReporteEjecutado,
  ReporteGenerativoRespuesta,
  SolicitudResuelta,
} from '../../core/models/reportes-ia.models';
import { PlanService } from '../../core/plan.service';
import { VozService } from '../../core/voz.service';
import { formatearCelda } from '../../shared/graficos/formato-reporte';
import { ReportesIaService } from './data/reportes-ia.service';
import { solicitudDesdeResuelta } from './data/solicitud-reporte';
import { ESPERA_LIMITE_MS, ReportesIaComponent } from './reportes-ia.component';
import { ResultadoReporteComponent } from './resultado-reporte.component';

const API = environment.apiUrl;
const URL_SUCURSALES = `${API}/sucursales?pagina=1&tamanio=100`;
const URL_CATEGORIAS = `${API}/categorias?pagina=1&tamanio=100`;
const URL_EMPLEADO = `${API}/empleados/yo`;

// ---- Datos de prueba ------------------------------------------------------------------------------------------------

function filtro(tipo: FiltroCatalogo['tipo'], extra: Partial<FiltroCatalogo> = {}): FiltroCatalogo {
  return { tipo, descripcion: '', obligatorio: false, defecto: null, minimo: null, maximo: null, valores: [], ...extra };
}

const CATALOGO: ReporteCatalogo[] = [
  {
    codigo: 'ventas_por_sucursal',
    titulo: 'Ventas por sucursal',
    descripcion: 'Total vendido por cada sucursal.',
    ejemplos: ['Muéstrame las ventas de septiembre por sucursal', 'Ventas por sucursal de este mes'],
    filtros: {
      periodo: filtro('periodo', { obligatorio: true }),
      sucursales: filtro('lista_nombres'),
      categorias: filtro('lista_nombres'),
      canal: filtro('enum', { valores: ['digital', 'presencial'] }),
      limite: filtro('entero', { minimo: 1, maximo: 50 }),
    },
    columnas: [],
    grafico: { tipo: 'barras', eje_x: 'sucursal', eje_y: 'total_ventas', serie: null },
  },
  {
    codigo: 'productos_menor_existencia',
    titulo: 'Productos con menor existencia',
    descripcion: 'Las prendas con menos unidades.',
    ejemplos: ['Productos con menor existencia'],
    filtros: { limite: filtro('entero', { minimo: 1, maximo: 50 }) },
    columnas: [],
    grafico: { tipo: 'tabla', eje_x: null, eje_y: null, serie: null },
  },
];

const SOLICITUD: SolicitudResuelta = {
  tipo_reporte: 'ventas_por_sucursal',
  periodo: { desde: '2026-09-01', hasta: '2026-09-30', etiqueta: 'septiembre de 2026' },
  sucursales: [],
  categorias: [],
  productos: [],
  canal: null,
  agrupacion: null,
  orden: null,
  limite: null,
  horizonte_semanas: null,
};

const REPORTE: ReporteEjecutado = {
  codigo: 'ventas_por_sucursal',
  titulo: 'Ventas por sucursal',
  columnas: [
    { clave: 'sucursal', titulo: 'Sucursal', tipo: 'texto' },
    { clave: 'total_ventas', titulo: 'Ventas (Bs)', tipo: 'moneda' },
    { clave: 'transacciones', titulo: 'Transacciones', tipo: 'entero' },
  ],
  filas: [
    { sucursal: 'Sucursal Centro', total_ventas: 2500, transacciones: 20 },
    { sucursal: 'Sucursal Norte', total_ventas: 1500, transacciones: 12 },
    { sucursal: 'Sucursal Sur', total_ventas: 500, transacciones: 8 },
  ],
  resumen: { total_ventas: 4500, transacciones: 40 },
  grafico_sugerido: { tipo: 'barras', eje_x: 'sucursal', eje_y: 'total_ventas', serie: null },
  truncado: false,
  generado_en: new Date(2026, 9, 30, 9, 5).toISOString(),
};

function ok(extra: Partial<ReporteGenerativoRespuesta> = {}): ReporteGenerativoRespuesta {
  return {
    estado: 'ok',
    mensaje: '',
    sugerencias: [],
    avisos: [],
    interprete: 'groq',
    solicitud: SOLICITUD,
    reporte: REPORTE,
    narrativa: 'Septiembre cerró con Bs 4.500 vendidos en tres sucursales.',
    ...extra,
  };
}

function noOk(estado: ReporteGenerativoRespuesta['estado'], mensaje: string, sugerencias: string[] = []): ReporteGenerativoRespuesta {
  return { estado, mensaje, sugerencias, avisos: [], interprete: 'groq', solicitud: null, reporte: null, narrativa: null };
}

const falla = (status: number, error: unknown = null) => throwError(() => new HttpErrorResponse({ status, error }));

// ---- Pruebas ----------------------------------------------------------------------------------------------------------

describe('ReportesIaComponent', () => {
  let fixture: ComponentFixture<ReportesIaComponent>;
  let http: HttpTestingController;
  let el: HTMLElement;
  let comp: any;

  let servicio: { catalogo: ReturnType<typeof vi.fn>; ejecutar: ReturnType<typeof vi.fn>; exportar: ReturnType<typeof vi.fn> };
  let incluye: ReturnType<typeof signal<boolean>>;
  let enLinea: ReturnType<typeof signal<boolean>>;
  let escuchar: ReturnType<typeof vi.fn>;

  // PrimeNG observa tamaños con ResizeObserver, que jsdom no trae.
  beforeAll(() => {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    };
  });

  interface Opciones {
    plan?: boolean;
    conexion?: boolean;
    voz?: boolean;
    catalogo?: Observable<ReporteCatalogo[]>;
    sucursalDelEmpleado?: number | null;
    sucursalesFallan?: boolean;
  }

  function montar(o: Opciones = {}): void {
    incluye = signal(o.plan ?? true);
    enLinea = signal(o.conexion ?? true);
    escuchar = vi.fn(() => of('ventas de septiembre por sucursal'));
    servicio = {
      catalogo: vi.fn(() => o.catalogo ?? of(CATALOGO)),
      ejecutar: vi.fn(() => of(ok())),
      exportar: vi.fn(() => of({ blob: new Blob(['x']), nombre: 'reporte.xlsx' } as ArchivoDescargado)),
    };
    TestBed.configureTestingModule({
      imports: [ReportesIaComponent],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ReportesIaService, useValue: servicio },
        { provide: VozService, useValue: { disponible: o.voz ?? true, escuchar } },
        { provide: PlanService, useValue: { incluye: () => incluye(), cargar: vi.fn(), cargando: signal(false) } },
        { provide: ConectividadService, useValue: { enLinea } },
      ],
    });
    // Chart.js necesita un canvas real: aquí solo se prueba la pantalla.
    TestBed.overrideComponent(ResultadoReporteComponent, {
      remove: { imports: [ChartModule] },
      add: { schemas: [NO_ERRORS_SCHEMA] },
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ReportesIaComponent);
    el = fixture.nativeElement as HTMLElement;
    comp = fixture.componentInstance;
    fixture.detectChanges();
    if (incluye() && enLinea()) responderApoyo(o);
    fixture.detectChanges();
  }

  /** Las tres listas de apoyo (sucursales, categorías y la sucursal del usuario). */
  function responderApoyo(o: Opciones = {}): void {
    const sucursales = http.expectOne(URL_SUCURSALES);
    if (o.sucursalesFallan) sucursales.flush('x', { status: 500, statusText: 'Error' });
    else sucursales.flush([{ id: 1, nombre: 'Sucursal Centro', activo: true }, { id: 2, nombre: 'Sucursal Norte', activo: true }]);
    http.expectOne(URL_CATEGORIAS).flush([{ id: 1, nombre: 'Poleras', activo: true }]);
    http.expectOne(URL_EMPLEADO).flush({ id: 1, sucursal_id: o.sucursalDelEmpleado ?? null });
  }

  /** Deja que terminen las promesas pendientes (ngModel, lectura de Blob) y vuelve a pintar. */
  async function asentar(): Promise<void> {
    await Promise.resolve();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  const q = <T extends HTMLElement = HTMLElement>(selector: string) => el.querySelector(selector) as T | null;
  const qa = (selector: string) => Array.from(el.querySelectorAll(selector)) as HTMLElement[];
  const texto = (nodo: Element | null | undefined) => nodo?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
  const boton = (accion: string) => q<HTMLButtonElement>(`[data-accion="${accion}"]`)!;

  function escribir(valor: string): void {
    const campo = q<HTMLInputElement>('[data-campo="pedido"]')!;
    campo.value = valor;
    campo.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  /** Escribe un pedido y pulsa [Generar reporte]. */
  function generar(valor = 'ventas de septiembre por sucursal'): void {
    escribir(valor);
    boton('generar').click();
    fixture.detectChanges();
  }

  /** Cambia el valor de un filtro como lo hace el usuario (el control emite `ngModelChange`). */
  function cambiarFiltro(nombre: string, valor: unknown): void {
    fixture.debugElement.query(By.css(`[data-filtro="${nombre}"]`)).triggerEventHandler('ngModelChange', valor);
    fixture.detectChanges();
  }

  /** Cambia a la vista Tabla (el reporte de prueba sugiere un gráfico y arranca en Gráfico). */
  function verTabla(): void {
    fixture.debugElement.query(By.css('[data-control="vista"]')).triggerEventHandler('ngModelChange', 'tabla');
    fixture.detectChanges();
  }

  const llamadasConTexto = () => servicio.ejecutar.mock.calls.filter(([entrada]) => 'texto' in entrada).length;

  beforeEach(() => {
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = vi.fn(() => 'blob:prueba');
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    try {
      http.verify();
    } finally {
      fixture.destroy();
      TestBed.resetTestingModule();
    }
  });

  // ---- Pedir ---------------------------------------------------------------------------------------------------------

  describe('pedir un reporte', () => {
    it('Generar llama a ejecutar con la frase y el origen, y muestra "entendí esto" y la tabla', () => {
      montar();
      generar();

      expect(servicio.ejecutar).toHaveBeenCalledTimes(1);
      expect(servicio.ejecutar).toHaveBeenCalledWith({ texto: 'ventas de septiembre por sucursal', origen: 'texto' });

      expect(texto(q('[data-seccion="entendi"] .fs-eyebrow'))).toBe('Entendí esto');
      expect(texto(q('[data-dato="tipo"]'))).toBe('Ventas por sucursal');
      expect(texto(q('[data-chip="periodo"]'))).toContain('septiembre de 2026');
      expect(texto(q('[data-dato="interprete"]'))).toBe('Interpretado con IA');
      expect(texto(q('[data-seccion="resultado"] h2'))).toBe('Ventas por sucursal');
      verTabla();
      expect(qa('tr[data-fila]')).toHaveLength(3);
      expect(texto(qa('tr[data-fila]')[0])).toContain('Sucursal Centro');
    });

    it('muestra "Generado el" en la hora local del navegador', () => {
      montar();
      generar();
      expect(texto(q('[data-dato="generado"]'))).toBe('Generado el 30/10/2026 09:05');
    });

    it('Enter envía y un campo vacío no envía nada', () => {
      montar();
      expect(boton('generar').disabled).toBe(true);
      boton('generar').click();
      expect(servicio.ejecutar).not.toHaveBeenCalled();

      escribir('productos con menor existencia');
      q('[data-campo="pedido"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
      expect(servicio.ejecutar).toHaveBeenCalledWith({ texto: 'productos con menor existencia', origen: 'texto' });
    });

    it('indica cuando el intérprete fue el de reglas porque la IA no respondió', () => {
      montar();
      servicio.ejecutar.mockReturnValue(of(ok({ interprete: 'reglas' })));
      generar();
      expect(texto(q('[data-dato="interprete"]'))).toBe('Interpretado con reglas: la IA no respondió');
    });

    it('los atajos salen del primer ejemplo de cada reporte del catálogo y un clic llena el campo y genera', async () => {
      montar();
      expect(qa('[data-atajo]').map(texto)).toEqual([
        'Muéstrame las ventas de septiembre por sucursal',
        'Productos con menor existencia',
      ]);
      (qa('[data-atajo]')[1] as HTMLButtonElement).click();
      fixture.detectChanges();
      await asentar();
      expect(servicio.ejecutar).toHaveBeenCalledWith({ texto: 'Productos con menor existencia', origen: 'texto' });
      expect(q<HTMLInputElement>('[data-campo="pedido"]')!.value).toBe('Productos con menor existencia');
    });

    it('si el catálogo falla usa los 6 ejemplos de respaldo', () => {
      montar({ catalogo: falla(500) });
      expect(qa('[data-atajo]')).toHaveLength(6);
      expect(texto(qa('[data-atajo]')[0])).toBe('Muéstrame las ventas de septiembre por sucursal');
    });
  });

  // ---- Voz -----------------------------------------------------------------------------------------------------------

  describe('dictado', () => {
    it('dictar rellena el campo y genera con origen "voz"', async () => {
      montar();
      boton('dictar').click();
      fixture.detectChanges();
      await asentar();

      expect(escuchar).toHaveBeenCalledTimes(1);
      expect(servicio.ejecutar).toHaveBeenCalledWith({ texto: 'ventas de septiembre por sucursal', origen: 'voz' });
      expect(q<HTMLInputElement>('[data-campo="pedido"]')!.value).toBe('ventas de septiembre por sucursal');
      expect(q('[data-estado="escuchando"]')).toBeNull();
    });

    it('mientras escucha avisa "Escuchando… habla ahora"', () => {
      montar();
      escuchar.mockReturnValue(new Observable<string>(() => undefined));
      boton('dictar').click();
      fixture.detectChanges();
      expect(texto(q('[data-estado="escuchando"]'))).toBe('Escuchando… habla ahora');
      expect(boton('generar').disabled).toBe(true);
    });

    it('un error del micrófono se explica en la pantalla', () => {
      montar();
      escuchar.mockReturnValue(throwError(() => new Error('No se encontró un micrófono.')));
      boton('dictar').click();
      fixture.detectChanges();
      expect(texto(q('[data-estado="error-voz"]'))).toBe('No se encontró un micrófono.');
      expect(servicio.ejecutar).not.toHaveBeenCalled();
    });

    it('sin soporte de voz el micrófono está deshabilitado y se explica por qué', () => {
      montar({ voz: false });
      expect(boton('dictar').disabled).toBe(true);
      expect(texto(q('[data-ayuda="sin-voz"]'))).toBe('Tu navegador no permite dictar (usa Chrome o Edge). Puedes escribir tu pedido.');
      generar();
      expect(servicio.ejecutar).toHaveBeenCalledTimes(1);
    });
  });

  // ---- Filtros editables ---------------------------------------------------------------------------------------------

  describe('filtros editables', () => {
    it('se generan desde el catálogo del tipo de reporte', () => {
      montar();
      generar();
      const campos = qa('app-filtros-reporte [data-campo]').map((c) => c.getAttribute('data-campo'));
      expect(campos).toEqual(['periodo', 'sucursales', 'categorias', 'canal', 'limite']);
    });

    it('editar un filtro y [Actualizar reporte] llama SOLO a ejecutar con la solicitud, sin texto ni IA', () => {
      montar();
      generar();
      expect(llamadasConTexto()).toBe(1);

      cambiarFiltro('canal', 'digital');
      cambiarFiltro('limite', 5);
      cambiarFiltro('sucursales', ['Sucursal Norte']);
      boton('actualizar').click();
      fixture.detectChanges();

      expect(servicio.ejecutar).toHaveBeenCalledTimes(2);
      const entrada = servicio.ejecutar.mock.calls[1][0];
      expect(entrada).not.toHaveProperty('texto');
      expect(entrada).not.toHaveProperty('origen');
      expect(entrada.solicitud).toEqual({
        tipo_reporte: 'ventas_por_sucursal',
        periodo: { tipo: 'rango_fechas', desde: { dia: 1, mes: 9, anio: 2026 }, hasta: { dia: 30, mes: 9, anio: 2026 } },
        sucursales: ['Sucursal Norte'],
        canal: 'digital',
        limite: 5,
      });
      expect(llamadasConTexto()).toBe(1);
    });

    it('con fechas al revés el botón queda deshabilitado y explica por qué', () => {
      montar();
      generar();
      cambiarFiltro('desde', new Date(2026, 9, 15));
      expect(boton('actualizar').disabled).toBe(true);
      expect(texto(q('[data-estado="filtros-invalidos"]'))).toBe('La fecha Desde no puede ser posterior a Hasta.');
      boton('actualizar').click();
      expect(servicio.ejecutar).toHaveBeenCalledTimes(1);
    });

    it('[Restablecer] vuelve a la solicitud de la primera respuesta, sin texto', () => {
      montar();
      generar();
      cambiarFiltro('limite', 5);
      boton('restablecer').click();
      fixture.detectChanges();

      expect(servicio.ejecutar).toHaveBeenCalledTimes(2);
      expect(servicio.ejecutar.mock.calls[1][0]).toEqual({ solicitud: solicitudDesdeResuelta(SOLICITUD) });
      expect(llamadasConTexto()).toBe(1);
    });

    it('si la lista de sucursales no se pudo cargar, el filtro queda de solo lectura', () => {
      montar({ sucursalesFallan: true });
      servicio.ejecutar.mockReturnValue(of(ok({ solicitud: { ...SOLICITUD, sucursales: [{ id: 1, nombre: 'Sucursal Centro' }] } })));
      generar();
      expect(q('[data-filtro="sucursales"]')).toBeNull();
      expect(texto(q('[data-campo="sucursales"] .chip'))).toBe('Sucursal Centro');
      expect(q('[data-filtro="categorias"]')).not.toBeNull();
    });

    it('si el usuario tiene sucursal asignada no puede cambiarla y ve el aviso del servidor', () => {
      montar({ sucursalDelEmpleado: 1 });
      servicio.ejecutar.mockReturnValue(
        of(
          ok({
            avisos: ['Solo puedes ver tu sucursal: Sucursal Centro.'],
            solicitud: { ...SOLICITUD, sucursales: [{ id: 1, nombre: 'Sucursal Centro' }] },
          }),
        ),
      );
      generar();
      expect(q('[data-filtro="sucursales"]')).toBeNull();
      expect(texto(q('[data-campo="sucursales"]'))).toContain('Tu usuario ve solo su sucursal.');
      expect(texto(q('[data-dato="aviso"]'))).toBe('Solo puedes ver tu sucursal: Sucursal Centro.');
    });

    it('un reporte sin filtros declarados no muestra el formulario', () => {
      montar();
      servicio.ejecutar.mockReturnValue(
        of(ok({ solicitud: { ...SOLICITUD, tipo_reporte: 'productos_menor_existencia', periodo: null }, reporte: { ...REPORTE, codigo: 'productos_menor_existencia' } })),
      );
      generar();
      expect(qa('app-filtros-reporte [data-campo]').map((c) => c.getAttribute('data-campo'))).toEqual(['limite']);
    });
  });

  // ---- Mensajes ------------------------------------------------------------------------------------------------------

  describe('mensajes', () => {
    it.each(['incompleta', 'ambigua', 'invalida', 'no_soportada', 'no_disponible'] as const)(
      'estado %s: tarjeta con el mensaje, sugerencias y la lista de lo que se puede pedir',
      (estado) => {
        montar();
        servicio.ejecutar.mockReturnValue(of(noOk(estado, 'No pude armar ese reporte.', ['Ventas de la sucursal Centro'])));
        generar('algo raro');

        const tarjeta = q('[data-estado="no-ok"]')!;
        expect(tarjeta.getAttribute('data-estado-reporte')).toBe(estado);
        expect(texto(q('[data-dato="mensaje"]'))).toBe('No pude armar ese reporte.');
        expect(texto(tarjeta)).toContain('Prueba con:');
        expect(texto(tarjeta)).toContain('Puedo ayudarte con:');
        expect(texto(q('[data-dato="tipos"]'))).toContain('Ventas por sucursal: Total vendido por cada sucursal.');
        expect(texto(q('[data-dato="tipos"]'))).toContain('Productos con menor existencia');
        expect(q('[data-seccion="resultado"]')).toBeNull();
        expect(q('[data-estado="problema-servidor"]')).toBeNull();
      },
    );

    it('un clic en una sugerencia genera con ese texto', () => {
      montar();
      servicio.ejecutar.mockReturnValueOnce(of(noOk('ambigua', 'No encontré esa sucursal.', ['Ventas de la sucursal Centro'])));
      generar('ventas de la sucursal Centr');
      (q('[data-sugerencia]') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(servicio.ejecutar).toHaveBeenCalledTimes(2);
      expect(servicio.ejecutar.mock.calls[1][0]).toEqual({ texto: 'Ventas de la sucursal Centro', origen: 'texto' });
      expect(q('[data-estado="no-ok"]')).toBeNull();
      expect(q('[data-seccion="resultado"]')).not.toBeNull();
    });

    it('sin filas muestra el mensaje de vacío con los filtros a la vista', () => {
      montar();
      servicio.ejecutar.mockReturnValue(of(ok({ reporte: { ...REPORTE, filas: [], resumen: {} }, narrativa: null })));
      generar();

      const vacio = q('[data-estado="sin-filas"]')!;
      expect(texto(vacio)).toContain('No hay datos para esos filtros.');
      expect(texto(vacio)).toContain('Prueba con otro rango de fechas o con todas las sucursales.');
      expect(texto(q('[data-dato="filtros-aplicados"]'))).toContain('septiembre de 2026');
      expect(q('tr[data-fila]')).toBeNull();
      expect(boton('exportar-xlsx').disabled).toBe(true);
    });

    it('un fallo de red muestra el mensaje y [Reintentar] repite la última acción', () => {
      montar();
      servicio.ejecutar.mockReturnValueOnce(falla(0));
      generar();

      expect(texto(q('[data-estado="problema-red"]'))).toContain('No se pudo conectar con el servidor.');
      expect(q('[data-seccion="resultado"]')).toBeNull();

      boton('reintentar').click();
      fixture.detectChanges();
      expect(servicio.ejecutar).toHaveBeenCalledTimes(2);
      expect(servicio.ejecutar.mock.calls[1][0]).toEqual({ texto: 'ventas de septiembre por sucursal', origen: 'texto' });
      expect(q('[data-estado="problema-red"]')).toBeNull();
      expect(q('[data-seccion="resultado"]')).not.toBeNull();
    });

    it('un error del servidor también ofrece reintentar, sin pantalla en blanco', () => {
      montar();
      servicio.ejecutar.mockReturnValueOnce(falla(500, { detail: 'boom' }));
      generar();
      expect(texto(q('[data-estado="problema-servidor"]'))).toContain('Algo salió mal al preparar el reporte.');
      expect(boton('reintentar')).not.toBeNull();
    });

    it('un 403 por alcance explica el motivo, sin botón de reintentar', () => {
      montar();
      servicio.ejecutar.mockReturnValueOnce(falla(403, { detail: 'Prohibido', mensaje: 'Este reporte es solo para quien ve todas las sucursales.' }));
      generar();
      expect(texto(q('[data-estado="problema-permiso"]'))).toContain('Este reporte es solo para quien ve todas las sucursales.');
      expect(q('[data-accion="reintentar"]')).toBeNull();
    });

    it('un 429 muestra el límite y bloquea Generar unos 10 segundos', () => {
      montar();
      servicio.ejecutar.mockReturnValueOnce(falla(429));
      vi.useFakeTimers();
      generar();

      expect(texto(q('[data-estado="problema-limite"]'))).toContain('demasiadas consultas');
      expect(boton('generar').disabled).toBe(true);
      escribir('otro pedido');
      expect(boton('generar').disabled).toBe(true);

      vi.advanceTimersByTime(ESPERA_LIMITE_MS - 1);
      fixture.detectChanges();
      expect(boton('generar').disabled).toBe(true);

      vi.advanceTimersByTime(1);
      fixture.detectChanges();
      expect(boton('generar').disabled).toBe(false);
    });

    it('al destruir la pantalla se limpia el temporizador del límite', () => {
      montar();
      servicio.ejecutar.mockReturnValueOnce(falla(429));
      vi.useFakeTimers();
      generar();
      const antes = vi.getTimerCount();
      expect(antes).toBeGreaterThan(0);
      fixture.destroy();
      expect(vi.getTimerCount()).toBeLessThan(antes);
    });
  });

  // ---- Exportar ------------------------------------------------------------------------------------------------------

  describe('exportar', () => {
    it('Excel y PDF llaman a exportar con la solicitud resuelta y el gráfico incluido', () => {
      montar();
      generar();

      boton('exportar-xlsx').click();
      fixture.detectChanges();
      expect(servicio.exportar).toHaveBeenLastCalledWith({ formato: 'xlsx', resuelta: SOLICITUD, incluir_grafico: true });
      expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);

      boton('exportar-pdf').click();
      fixture.detectChanges();
      expect(servicio.exportar).toHaveBeenLastCalledWith({ formato: 'pdf', resuelta: SOLICITUD, incluir_grafico: true });
    });

    it('exporta con la solicitud de la ÚLTIMA respuesta (filtros actuales), no con la original', () => {
      montar();
      generar();
      const actual: SolicitudResuelta = { ...SOLICITUD, limite: 5, canal: 'digital' };
      servicio.ejecutar.mockReturnValueOnce(of(ok({ solicitud: actual, interprete: null })));
      cambiarFiltro('limite', 5);
      boton('actualizar').click();
      fixture.detectChanges();

      boton('exportar-xlsx').click();
      expect(servicio.exportar).toHaveBeenCalledTimes(1);
      const entrada = servicio.exportar.mock.calls[0][0];
      expect(entrada.resuelta).toEqual(actual);
      expect(entrada).not.toHaveProperty('texto');
      // La insignia del intérprete sigue siendo la del pedido original.
      expect(texto(q('[data-dato="interprete"]'))).toBe('Interpretado con IA');
    });

    it('mientras prepara el archivo deshabilita los dos botones', () => {
      montar();
      generar();
      servicio.exportar.mockReturnValue(new Observable<ArchivoDescargado>(() => undefined));
      boton('exportar-xlsx').click();
      fixture.detectChanges();
      expect(texto(boton('exportar-xlsx'))).toBe('Preparando…');
      expect(boton('exportar-xlsx').disabled).toBe(true);
      expect(boton('exportar-pdf').disabled).toBe(true);
    });

    it('un 422 con el cuerpo en Blob se lee y se muestra con sus sugerencias', async () => {
      montar();
      generar();
      const cuerpo = new Blob([JSON.stringify({ codigo: 'reporte_no_exportable', mensaje: 'Este reporte no se puede exportar.', sugerencias: ['Pide otro rango de fechas'] })]);
      servicio.exportar.mockReturnValue(falla(422, cuerpo));
      boton('exportar-pdf').click();
      fixture.detectChanges();

      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(q('[data-estado="error-exportacion"]')).not.toBeNull();
      });
      const aviso = texto(q('[data-estado="error-exportacion"]'));
      expect(aviso).toContain('Este reporte no se puede exportar.');
      expect(aviso).toContain('Pide otro rango de fechas');
      expect(boton('exportar-pdf').disabled).toBe(false);
    });

    it('un 429 al exportar pide esperar', async () => {
      montar();
      generar();
      servicio.exportar.mockReturnValue(falla(429, new Blob(['{}'])));
      boton('exportar-xlsx').click();
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(q('[data-estado="error-exportacion"]')).not.toBeNull();
      });
      expect(texto(q('[data-estado="error-exportacion"]'))).toContain('demasiadas exportaciones seguidas');
    });
  });

  // ---- Gráfico y tabla -----------------------------------------------------------------------------------------------

  describe('resultado', () => {
    it('cambiar el tipo de gráfico o la medida no consulta al servidor', () => {
      montar();
      generar();
      const llamadas = servicio.ejecutar.mock.calls.length;

      // El reporte sugiere barras y se puede: arranca en Gráfico.
      expect(q('[data-dato="grafico"]')).not.toBeNull();
      expect(q('[data-tipo-grafico="barras"]')!.getAttribute('aria-checked')).toBe('true');
      expect(q('[data-dato="grafico"]')!.getAttribute('aria-label')).toContain('Barras: Ventas (Bs) por Sucursal');

      (q('[data-tipo-grafico="barras_horizontales"]') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(q('[data-tipo-grafico="barras_horizontales"]')!.getAttribute('aria-checked')).toBe('true');
      expect(q('[data-dato="grafico"]')!.getAttribute('aria-label')).toContain('Barras horizontales');

      fixture.debugElement.query(By.css('[data-control="medida"]')).triggerEventHandler('ngModelChange', 'transacciones');
      fixture.detectChanges();
      expect(q('[data-dato="grafico"]')!.getAttribute('aria-label')).toContain('Transacciones por Sucursal');

      expect(servicio.ejecutar).toHaveBeenCalledTimes(llamadas);
      expect(servicio.catalogo).toHaveBeenCalledTimes(1);
    });

    it('las opciones imposibles aparecen deshabilitadas con su razón visible', () => {
      montar();
      generar();

      const lineas = q<HTMLButtonElement>('[data-tipo-grafico="linea"]')!;
      expect(lineas.disabled).toBe(true);
      expect(lineas.getAttribute('title')).toBe('Las líneas necesitan una columna de fechas o periodos.');
      const agrupadas = q<HTMLButtonElement>('[data-tipo-grafico="barras_agrupadas"]')!;
      expect(agrupadas.disabled).toBe(true);
      expect(agrupadas.getAttribute('title')).toBe('Necesita comparar dos o más series.');
      expect(q<HTMLButtonElement>('[data-tipo-grafico="barras"]')!.disabled).toBe(false);
      expect(q<HTMLButtonElement>('[data-tipo-grafico="torta"]')!.disabled).toBe(false);

      const razones = texto(q('[data-dato="razones-grafico"]'));
      expect(razones).toContain('Líneas: Las líneas necesitan una columna de fechas o periodos.');
      expect(razones).toContain('Barras agrupadas: Necesita comparar dos o más series.');
    });

    it('un clic en una opción deshabilitada no cambia el gráfico', () => {
      montar();
      generar();
      (q('[data-tipo-grafico="linea"]') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(q('[data-tipo-grafico="barras"]')!.getAttribute('aria-checked')).toBe('true');
    });

    it('un reporte sin gráfico sugerido arranca en Tabla con filas, totales y números alineados', () => {
      montar();
      servicio.ejecutar.mockReturnValue(
        of(ok({ reporte: { ...REPORTE, grafico_sugerido: { tipo: 'tabla', eje_x: null, eje_y: null, serie: null } } })),
      );
      generar();

      expect(q('[data-dato="grafico"]')).toBeNull();
      const filas = qa('tr[data-fila]');
      expect(filas).toHaveLength(3);
      expect(texto(filas[0].querySelectorAll('td')[1])).toBe(formatearCelda(2500, 'moneda'));
      expect(filas[0].querySelectorAll('td')[1].classList.contains('fs-num')).toBe(true);
      expect(filas[0].querySelectorAll('td')[0].classList.contains('fs-num')).toBe(false);

      const total = texto(q('tr[data-fila-total]'));
      expect(total).toContain('Total');
      expect(total).toContain(formatearCelda(4500, 'moneda'));
      expect(total).toContain(formatearCelda(40, 'entero'));
    });

    it('pasar de Tabla a Gráfico y volver es instantáneo y no consulta', () => {
      montar();
      servicio.ejecutar.mockReturnValue(
        of(ok({ reporte: { ...REPORTE, grafico_sugerido: { tipo: 'tabla', eje_x: null, eje_y: null, serie: null } } })),
      );
      generar();
      const llamadas = servicio.ejecutar.mock.calls.length;
      const vista = fixture.debugElement.query(By.css('[data-control="vista"]'));
      vista.triggerEventHandler('ngModelChange', 'grafico');
      fixture.detectChanges();
      expect(q('[data-dato="grafico"]')).not.toBeNull();
      vista.triggerEventHandler('ngModelChange', 'tabla');
      fixture.detectChanges();
      expect(q('[data-dato="grafico"]')).toBeNull();
      expect(servicio.ejecutar).toHaveBeenCalledTimes(llamadas);
    });

    it('con más de 20 filas la tabla se pagina', () => {
      montar();
      const filas = Array.from({ length: 25 }, (_, i) => ({ sucursal: `Sucursal ${i + 1}`, total_ventas: 100 + i, transacciones: i + 1 }));
      servicio.ejecutar.mockReturnValue(
        of(ok({ reporte: { ...REPORTE, filas, grafico_sugerido: { tipo: 'tabla', eje_x: null, eje_y: null, serie: null } } })),
      );
      generar();
      expect(qa('tr[data-fila]')).toHaveLength(20);
      expect(q('.p-paginator')).not.toBeNull();
    });

    it('un reporte recortado avisa y no lleva fila de totales', () => {
      montar();
      servicio.ejecutar.mockReturnValue(
        of(ok({ reporte: { ...REPORTE, truncado: true, grafico_sugerido: { tipo: 'tabla', eje_x: null, eje_y: null, serie: null } } })),
      );
      generar();
      expect(q('[data-dato="truncado"]')).not.toBeNull();
      expect(q('tr[data-fila-total]')).toBeNull();
    });

    it('muestra el resumen automático con su nota de cautela, solo si viene narrativa', () => {
      montar();
      generar();
      const resumen = q('[data-seccion="narrativa"]')!;
      expect(texto(resumen)).toContain('Septiembre cerró con Bs 4.500');
      expect(texto(resumen)).toContain('Revisa las cifras en la tabla; el resumen es automático y puede equivocarse.');

      servicio.ejecutar.mockReturnValue(of(ok({ narrativa: null })));
      boton('restablecer').click();
      fixture.detectChanges();
      expect(q('[data-seccion="narrativa"]')).toBeNull();
    });

    it('enlaza a los reportes convencionales', () => {
      montar();
      expect(q('[data-accion="ver-convencionales"]')!.getAttribute('href')).toBe('/reportes');
    });
  });

  // ---- Plan y conexión -----------------------------------------------------------------------------------------------

  describe('plan y conexión', () => {
    it('un plan sin reportes con IA explica qué incluye, no llama a /reportes-ia y deshabilita los controles', async () => {
      montar({ plan: false });
      await asentar();

      const tarjeta = q('[data-estado="sin-plan"]')!;
      expect(texto(tarjeta)).toContain('Tu plan no incluye reportes con IA');
      expect(texto(tarjeta)).toContain('Con el plan Profesional puedes pedir reportes con tu voz, ver gráficos y exportarlos.');
      expect(q('[data-accion="ver-plan"]')!.getAttribute('href')).toBe('/mi-empresa');
      expect(q('[data-accion="ir-reportes"]')!.getAttribute('href')).toBe('/reportes');

      expect(servicio.catalogo).not.toHaveBeenCalled();
      expect(servicio.ejecutar).not.toHaveBeenCalled();
      http.expectNone(URL_SUCURSALES);

      expect(q<HTMLInputElement>('[data-campo="pedido"]')!.disabled).toBe(true);
      expect(boton('dictar').disabled).toBe(true);
      expect(boton('generar').disabled).toBe(true);
      expect(qa('[data-atajo]').every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
      boton('generar').click();
      expect(servicio.ejecutar).not.toHaveBeenCalled();
    });

    it('un 403 plan_no_incluye_funcionalidad al generar muestra la misma tarjeta', () => {
      montar();
      servicio.ejecutar.mockReturnValueOnce(falla(403, { detail: 'plan_no_incluye_funcionalidad', codigo: 'plan_no_incluye_funcionalidad', mensaje: 'x' }));
      generar();
      expect(q('[data-estado="sin-plan"]')).not.toBeNull();
      expect(q('[data-estado="problema-permiso"]')).toBeNull();
      expect(boton('generar').disabled).toBe(true);
    });

    it('un 403 plan_no_incluye_funcionalidad en el catálogo muestra la tarjeta de plan', () => {
      montar({ catalogo: falla(403, { detail: 'plan_no_incluye_funcionalidad', codigo: 'plan_no_incluye_funcionalidad' }) });
      expect(q('[data-estado="sin-plan"]')).not.toBeNull();
    });

    it('un 403 plan_no_incluye_funcionalidad al exportar muestra la tarjeta de plan', async () => {
      montar();
      generar();
      const cuerpo = new Blob([JSON.stringify({ codigo: 'plan_no_incluye_funcionalidad', detail: 'plan_no_incluye_funcionalidad' })]);
      servicio.exportar.mockReturnValue(falla(403, cuerpo));
      boton('exportar-xlsx').click();
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(q('[data-estado="sin-plan"]')).not.toBeNull();
      });
    });

    it('sin conexión avisa y deshabilita los controles, sin llamar al servidor', async () => {
      montar({ conexion: false });
      await asentar();
      expect(texto(q('[data-estado="sin-conexion"]'))).toBe('Los reportes con IA necesitan conexión a Internet.');
      expect(q<HTMLInputElement>('[data-campo="pedido"]')!.disabled).toBe(true);
      expect(boton('dictar').disabled).toBe(true);
      expect(boton('generar').disabled).toBe(true);
      expect(servicio.catalogo).not.toHaveBeenCalled();
      expect(q('[data-estado="sin-plan"]')).toBeNull();
    });

    it('al volver la conexión se habilitan los controles y se carga el catálogo', async () => {
      montar({ conexion: false });
      enLinea.set(true);
      fixture.detectChanges();
      responderApoyo();
      await asentar();

      expect(servicio.catalogo).toHaveBeenCalledTimes(1);
      expect(q('[data-estado="sin-conexion"]')).toBeNull();
      expect(q<HTMLInputElement>('[data-campo="pedido"]')!.disabled).toBe(false);
      expect(qa('[data-atajo]')).toHaveLength(2);
    });

    it('los textos de la pantalla usan tuteo', () => {
      montar();
      generar();
      const todo = texto(el);
      expect(todo).not.toMatch(/\b(escribí|podés|tenés|elegí|probá|revisá)\b/i);
    });
  });
});
