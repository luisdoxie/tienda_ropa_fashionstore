import { HttpErrorResponse } from '@angular/common/http';
import { NO_ERRORS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { ConfirmationService, MessageService } from 'primeng/api';
import { ChartModule } from 'primeng/chart';
import { Observable, Subject } from 'rxjs';
import { EstadoConexion, ConectividadService } from '../../core/conectividad.service';
import {
  AnomaliaVenta,
  AnomaliasRespuesta,
  DemandaCategoria,
  DemandaRespuesta,
  EntrenarRespuesta,
  EstadoAnalitica,
  EstadoModelo,
  PuntoSerie,
  ReposicionRespuesta,
  SegmentosRespuesta,
} from '../../core/models/analitica.models';
import { PlanService } from '../../core/plan.service';
import { reiniciarColores } from '../../shared/graficos/paleta-graficos';
import { AnaliticaComponent } from './analitica.component';
import { AnaliticaService } from './data/analitica.service';
import { WidgetAnomaliasComponent } from './widget-anomalias.component';
import { WidgetDemandaComponent } from './widget-demanda.component';
import { WidgetSegmentosComponent } from './widget-segmentos.component';

// ---- Datos de ejemplo (los de E12_anexo_respuestas_para_E17, ampliados) ------------------------------------------

const GRAFICO = { tipo: 'linea' as const, eje_x: 'semana', eje_y: 'unidades', serie: null };

function modelo(tipo: EstadoModelo['tipo'], extra: Partial<EstadoModelo> = {}): EstadoModelo {
  return {
    tipo,
    titulo: tipo,
    entrenado: true,
    estado: 'vigente',
    version: 1,
    entrenado_en: '2026-10-30T14:30:37Z',
    filas_entrenamiento: 144,
    datos_desde: '2026-01-19',
    datos_hasta: '2026-10-25',
    metricas: {},
    mensaje: 'Vigente: versión 1, entrenado hace 0 días.',
    ...extra,
  };
}

function sinEntrenar(tipo: EstadoModelo['tipo']): EstadoModelo {
  return modelo(tipo, {
    entrenado: false,
    estado: 'sin_entrenar',
    version: null,
    entrenado_en: null,
    filas_entrenamiento: null,
    datos_desde: null,
    datos_hasta: null,
    mensaje: 'Aún no hay un modelo entrenado. Un administrador puede entrenarlo en Analítica.',
  });
}

const DATOS = { semanas_con_ventas: 40, categorias_con_ventas: 4, clientes_con_compras: 78 };

const ESTADO_ENTRENADO: EstadoAnalitica = {
  modelos: [modelo('demanda_semanal'), modelo('segmentos_rfm', { filas_entrenamiento: 78 }), modelo('anomalias_ventas', { filas_entrenamiento: 559 })],
  datos: DATOS,
  puede_entrenar: { demanda_semanal: true, segmentos_rfm: true, anomalias_ventas: true },
  interpretacion: [],
};

const ESTADO_VACIO: EstadoAnalitica = {
  // El ejemplo real del servidor sin entrenar solo trae dos modelos: el tercero se muestra igual.
  modelos: [sinEntrenar('demanda_semanal'), sinEntrenar('segmentos_rfm')],
  datos: DATOS,
  puede_entrenar: { demanda_semanal: true, segmentos_rfm: true, anomalias_ventas: true },
  interpretacion: [],
};

/** 12 semanas reales: los lunes desde el 3 de agosto de 2026. */
function historico(valor: number): PuntoSerie[] {
  return Array.from({ length: 12 }, (_, i) => ({
    etiqueta: new Date(Date.UTC(2026, 7, 3 + i * 7)).toISOString().slice(0, 10),
    valor,
    minimo: null,
    maximo: null,
    es_prediccion: false,
  }));
}

function categoria(id: number | null, nombre: string, valor: number, total: number): DemandaCategoria {
  return {
    categoria_id: id,
    categoria: nombre,
    historico: historico(valor),
    prediccion: [
      { etiqueta: '2026-10-26', valor: 14, minimo: 10, maximo: 18, es_prediccion: true },
      { etiqueta: '2026-11-02', valor: 15, minimo: 11, maximo: 19, es_prediccion: true },
    ],
    total_predicho: total,
    variacion_pct_vs_ultimas_semanas: 19.1,
  };
}

function demanda(extra: Partial<DemandaRespuesta> = {}): DemandaRespuesta {
  return {
    horizonte_semanas: 4,
    modelo: modelo('demanda_semanal'),
    categorias: [categoria(4, 'Camisetas deportivas', 7, 56), categoria(3, 'Chamarras', 5, 33)],
    total_empresa: categoria(null, 'Total de la empresa', 12, 190),
    metricas: {
      mae: 2.8827665061421044,
      rmse: 3.876587823299183,
      r2: -0.00328469130524911,
      mae_base: 3.0416666666666665,
      rmse_base: 4.064262438212704,
      r2_base: -0.10277882414302697,
      mejora_mae_pct: 5.224114866560948,
      modelo_elegido: 'random_forest',
    },
    supuestos: ['El descuento de las semanas futuras se asume igual al promedio de las últimas 4 semanas.'],
    interpretacion: [
      'El modelo se equivoca en promedio 2,88 unidades por categoría y semana; el promedio móvil de 4 semanas se equivoca 3,04: es 5,2% más preciso.',
      'El R2 es negativo (-0,00): el modelo no explica la variación de la demanda mejor que un promedio simple.',
    ],
    grafico_sugerido: GRAFICO,
    avisos: [],
    ...extra,
  };
}

function segmentos(extra: Partial<SegmentosRespuesta> = {}): SegmentosRespuesta {
  return {
    modelo: modelo('segmentos_rfm', { filas_entrenamiento: 78 }),
    k: 3,
    silhouette: 0.553603,
    clientes_segmentados: 78,
    segmentos: [
      {
        id: 0,
        nombre: 'Campeones',
        descripcion: 'Compran seguido, gastan mucho y compraron hace poco.',
        accion_sugerida: 'Cuídalos: acceso anticipado a novedades, programa de recompensas y pídeles reseñas.',
        clientes: 22,
        porcentaje_clientes: 28.21,
        recencia_media_dias: 17,
        frecuencia_media: 15.09,
        monto_medio: 7476.45,
        monto_total: 164481.9,
        porcentaje_monto: 63.51,
      },
      {
        id: 1,
        nombre: 'En riesgo',
        descripcion: 'Fueron buenos clientes, pero hace tiempo que no compran.',
        accion_sugerida: 'Contáctalos pronto con una oferta personalizada antes de perderlos.',
        clientes: 16,
        porcentaje_clientes: 20.51,
        recencia_media_dias: 200.7,
        frecuencia_media: 8.19,
        monto_medio: 3098.36,
        monto_total: 49573.75,
        porcentaje_monto: 19.14,
      },
    ],
    dispersion: [],
    curva_silhouette: [],
    curva_codo: [],
    supuestos: ['La segmentación describe el comportamiento de compra de la ventana indicada; no predice conductas futuras.'],
    interpretacion: ['El 28,2% de tus clientes (Campeones) genera el 63,5% de las ventas.'],
    grafico_sugerido: GRAFICO,
    avisos: [],
    ...extra,
  };
}

function anomalia(i: number, extra: Partial<AnomaliaVenta> = {}): AnomaliaVenta {
  return {
    fecha: `2026-09-${String(i + 1).padStart(2, '0')}`,
    sucursal_id: 2,
    sucursal: 'FashionStore Equipetrol',
    total_ventas: 1000 + i,
    esperado: 300,
    desviacion_pct: 100 + i * 10,
    severidad: 'fuerte',
    ...extra,
  };
}

function anomalias(lista: AnomaliaVenta[], extra: Partial<AnomaliasRespuesta> = {}): AnomaliasRespuesta {
  return {
    modelo: modelo('anomalias_ventas', { filas_entrenamiento: 559 }),
    dias: 90,
    desde: '2026-07-28',
    hasta: '2026-10-25',
    anomalias: lista,
    total: lista.length,
    fuertes: lista.filter((a) => a.severidad === 'fuerte').length,
    supuestos: ['Una anomalía es un día inusual respecto al comportamiento habitual de esa tienda en ese día de la semana.'],
    interpretacion: ['Se detectaron días inusuales de ventas.'],
    grafico_sugerido: { tipo: 'tabla', eje_x: null, eje_y: null, serie: null },
    avisos: [],
    ...extra,
  };
}

function reposicion(extra: Partial<ReposicionRespuesta> = {}): ReposicionRespuesta {
  return {
    modelo: modelo('demanda_semanal'),
    semanas: 4,
    items: [
      { categoria_id: 4, categoria: 'Camisetas deportivas', disponible: 164, demanda_semanal_promedio: 14, semanas_cobertura: 11.71, agotado_en_semana: null, estado: 'ok', sugerencia_unidades: 0 },
      { categoria_id: 3, categoria: 'Chamarras', disponible: 20, demanda_semanal_promedio: 9.5, semanas_cobertura: 2.1, agotado_en_semana: 3, estado: 'critico', sugerencia_unidades: 40 },
      { categoria_id: 6, categoria: 'Bufandas', disponible: 30, demanda_semanal_promedio: 0, semanas_cobertura: null, agotado_en_semana: null, estado: 'ok', sugerencia_unidades: 0 },
    ],
    criticos: 1,
    supuestos: ['La demanda prevista es la del modelo de demanda por categoría; es una estimación, no una promesa de ventas.'],
    interpretacion: ['Con la demanda prevista para las próximas 4 semanas, 1 categoría corre riesgo de agotarse.'],
    grafico_sugerido: { tipo: 'barras', eje_x: 'categoria', eje_y: 'semanas_cobertura', serie: null },
    avisos: [],
    ...extra,
  };
}

const ENTRENAMIENTO_OK: EntrenarRespuesta = {
  resultados: [
    { tipo: 'demanda_semanal', estado: 'entrenado', version: 2, metricas: {}, avisos: [], motivo: null, duracion_ms: 2500 },
    { tipo: 'segmentos_rfm', estado: 'entrenado', version: 2, metricas: {}, avisos: [], motivo: null, duracion_ms: 100 },
  ],
};

function errorHttp(status: number, cuerpo: unknown = {}): HttpErrorResponse {
  return new HttpErrorResponse({ status, error: cuerpo, statusText: 'x' });
}

const ERROR_SIN_MODELO = errorHttp(409, { detail: 'modelo_no_entrenado', codigo: 'modelo_no_entrenado', mensaje: 'Aún no hay un modelo entrenado.' });
const ERROR_PLAN = errorHttp(403, {
  detail: 'plan_no_incluye_funcionalidad',
  codigo: 'plan_no_incluye_funcionalidad',
  mensaje: 'Tu plan no incluye esta funcionalidad.',
});
const ERROR_ALCANCE = errorHttp(403, { detail: 'La analítica es de toda la empresa' });

// ---- Servicio falso: cada llamada es un Subject que la prueba resuelve cuando quiere ----------------------------------

interface Colas {
  estado: Subject<EstadoAnalitica>[];
  entrenar: Subject<EntrenarRespuesta>[];
  demanda: Subject<DemandaRespuesta>[];
  segmentos: Subject<SegmentosRespuesta>[];
  anomalias: Subject<AnomaliasRespuesta>[];
  reposicion: Subject<ReposicionRespuesta>[];
}

function crearServicioFalso() {
  const colas: Colas = { estado: [], entrenar: [], demanda: [], segmentos: [], anomalias: [], reposicion: [] };
  const nuevo = <T>(lista: Subject<T>[]): Observable<T> => {
    const s = new Subject<T>();
    lista.push(s);
    return s.asObservable();
  };
  const servicio = {
    estado: vi.fn(() => nuevo(colas.estado)),
    entrenar: vi.fn((_tipos?: unknown) => nuevo(colas.entrenar)),
    demanda: vi.fn((_semanas?: number, _categoriaId?: number | null) => nuevo(colas.demanda)),
    segmentos: vi.fn(() => nuevo(colas.segmentos)),
    anomalias: vi.fn((_dias?: number) => nuevo(colas.anomalias)),
    reposicion: vi.fn((_semanas?: number) => nuevo(colas.reposicion)),
    panel: vi.fn(),
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

function totalLlamadas(servicio: ReturnType<typeof crearServicioFalso>['servicio']): number {
  return (
    servicio.estado.mock.calls.length +
    servicio.entrenar.mock.calls.length +
    servicio.demanda.mock.calls.length +
    servicio.segmentos.mock.calls.length +
    servicio.anomalias.mock.calls.length +
    servicio.reposicion.mock.calls.length +
    servicio.panel.mock.calls.length
  );
}

// ---- Pruebas ------------------------------------------------------------------------------------------------------------

describe('AnaliticaComponent', () => {
  let fixture: ComponentFixture<AnaliticaComponent>;
  let falso: ReturnType<typeof crearServicioFalso>;
  let incluye: ReturnType<typeof signal<boolean>>;
  let conexion: ReturnType<typeof signal<EstadoConexion>>;
  let avisos: ReturnType<typeof vi.spyOn>;
  let comp: any;
  let el: HTMLElement;

  // PrimeNG observa su tamaño con ResizeObserver, que jsdom no trae.
  beforeAll(() => {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    };
  });

  function montar(opciones: { incluye?: boolean; conexion?: EstadoConexion } = {}): void {
    reiniciarColores();
    falso = crearServicioFalso();
    incluye = signal(opciones.incluye ?? true);
    conexion = signal<EstadoConexion>(opciones.conexion ?? 'en_linea');
    TestBed.configureTestingModule({
      imports: [AnaliticaComponent],
      providers: [
        provideRouter([]),
        MessageService,
        { provide: AnaliticaService, useValue: falso.servicio },
        { provide: PlanService, useValue: { incluye: () => incluye(), cargar: vi.fn() } },
        { provide: ConectividadService, useValue: { estado: conexion } },
      ],
    });
    // Chart.js necesita un canvas real: aquí se prueban los datos que se le entregan, no su dibujo.
    for (const widget of [WidgetDemandaComponent, WidgetSegmentosComponent]) {
      TestBed.overrideComponent(widget, { remove: { imports: [ChartModule] }, add: { schemas: [NO_ERRORS_SCHEMA] } });
    }
    avisos = vi.spyOn(TestBed.inject(MessageService), 'add');
    fixture = TestBed.createComponent(AnaliticaComponent);
    el = fixture.nativeElement as HTMLElement;
    comp = fixture.componentInstance;
    fixture.detectChanges();
    fixture.detectChanges();
  }

  /** Responde a las 5 consultas de apertura; cada argumento puede cambiar lo que se responde. */
  function responderApertura(
    datos: {
      estado?: EstadoAnalitica;
      demanda?: DemandaRespuesta;
      segmentos?: SegmentosRespuesta;
      anomalias?: AnomaliasRespuesta;
      reposicion?: ReposicionRespuesta;
    } = {},
  ): void {
    responder(falso.colas.estado, datos.estado ?? ESTADO_ENTRENADO);
    responder(falso.colas.demanda, datos.demanda ?? demanda());
    responder(falso.colas.segmentos, datos.segmentos ?? segmentos());
    responder(falso.colas.anomalias, datos.anomalias ?? anomalias([anomalia(0), anomalia(1, { desviacion_pct: -45.2, severidad: 'leve' })]));
    responder(falso.colas.reposicion, datos.reposicion ?? reposicion());
    fixture.detectChanges();
  }

  const q = (selector: string) => el.querySelector(selector) as HTMLElement | null;
  const qa = (selector: string) => Array.from(el.querySelectorAll(selector)) as HTMLElement[];
  const texto = (nodo: Element | null | undefined) => nodo?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
  const boton = () => q('[data-accion="entrenar"]') as HTMLButtonElement;
  const widget = <T>(tipo: new (...args: never[]) => T): T => fixture.debugElement.query(By.directive(tipo)).componentInstance as T;

  /** Reemplaza la confirmación de PrimeNG: guarda lo que se pidió y deja a la prueba aceptar. */
  function espiarConfirmacion() {
    const servicioConfirmacion = fixture.debugElement.injector.get(ConfirmationService);
    const pedidas: { header?: string; message?: string; accept?: () => void }[] = [];
    vi.spyOn(servicioConfirmacion, 'confirm').mockImplementation((c) => {
      pedidas.push(c);
      return servicioConfirmacion;
    });
    return pedidas;
  }

  afterEach(() => {
    fixture.destroy();
    TestBed.resetTestingModule();
    vi.restoreAllMocks();
  });

  describe('al abrir', () => {
    it('pide estado, demanda (4 semanas), grupos, días inusuales (90) y reposición (4): cinco consultas, ninguna a /panel', () => {
      montar();

      expect(falso.servicio.estado).toHaveBeenCalledTimes(1);
      expect(falso.servicio.demanda).toHaveBeenCalledTimes(1);
      expect(falso.servicio.demanda.mock.calls[0][0]).toBe(4);
      expect(falso.servicio.segmentos).toHaveBeenCalledTimes(1);
      expect(falso.servicio.anomalias).toHaveBeenCalledTimes(1);
      expect(falso.servicio.anomalias.mock.calls[0][0]).toBe(90);
      expect(falso.servicio.reposicion).toHaveBeenCalledTimes(1);
      expect(falso.servicio.reposicion.mock.calls[0][0]).toBe(4);
      expect(falso.servicio.panel).not.toHaveBeenCalled();
      expect(falso.servicio.entrenar).not.toHaveBeenCalled();
      expect(totalLlamadas(falso.servicio)).toBe(5);
    });

    it('mientras espera, cada bloque dice que está cargando', () => {
      montar();
      expect(qa('[data-estado="cargando"]').length).toBe(4);
      expect(q('[data-estado="cargando-estado"]')).not.toBeNull();
    });

    it('la tarjeta de datos sintéticos está siempre visible (cargando, con datos, con error y sin plan)', () => {
      montar();
      const aviso = () => texto(q('[data-aviso="datos-sinteticos"]'));
      expect(aviso()).toContain('Datos de demostración');
      expect(aviso()).toContain('el historial de ventas es sintético');
      expect(aviso()).toContain('no el comportamiento de clientes reales');

      responderApertura();
      expect(aviso()).toContain('sintético');
    });

    it('la tarjeta de datos sintéticos sigue visible aunque un bloque falle', () => {
      montar();
      fallar(falso.colas.demanda, errorHttp(500));
      fixture.detectChanges();
      expect(q('[data-bloque="demanda"] [data-estado="error"]')).not.toBeNull();
      expect(texto(q('[data-aviso="datos-sinteticos"]'))).toContain('sintético');
    });

    it('la tarjeta de datos sintéticos también se ve sin plan y sin conexión', () => {
      montar({ incluye: false });
      expect(texto(q('[data-aviso="datos-sinteticos"]'))).toContain('sintético');
      fixture.destroy();
      TestBed.resetTestingModule();
      montar({ conexion: 'sin_conexion' });
      expect(texto(q('[data-aviso="datos-sinteticos"]'))).toContain('sintético');
    });

    it('con todo cargado nunca aparece la frase "intervalo de confianza"', () => {
      montar();
      responderApertura();
      const todo = `${el.textContent} ${document.body.textContent}`.toLowerCase();
      expect(todo).not.toContain('intervalo de confianza');
      expect(todo).toContain('rango estimado');
    });

    it('no guarda nada en el navegador', () => {
      const guardar = vi.spyOn(Storage.prototype, 'setItem');
      montar();
      responderApertura();
      expect(guardar).not.toHaveBeenCalled();
    });
  });

  describe('estado de los modelos', () => {
    it('cada modelo muestra su etiqueta, "Entrenado el dd/mm/aaaa con N filas · versión V" y el mensaje del servidor', () => {
      montar();
      responderApertura();

      const demandaModelo = q('[data-modelo="demanda_semanal"]')!;
      expect(texto(demandaModelo.querySelector('[data-modelo-etiqueta]'))).toBe('Vigente');
      expect(texto(demandaModelo.querySelector('[data-modelo-detalle]'))).toBe('Entrenado el 30/10/2026 con 144 filas · versión 1');
      expect(texto(demandaModelo.querySelector('[data-modelo-mensaje]'))).toBe('Vigente: versión 1, entrenado hace 0 días.');
      expect(texto(q('[data-modelo="segmentos_rfm"] [data-modelo-detalle]'))).toContain('con 78 filas');
      expect(qa('[data-modelo]').length).toBe(3);
      expect(demandaModelo.querySelector('fs-icono')).not.toBeNull();
    });

    it('sin entrenar es gris, desactualizado ámbar y obsoleto rojo; el tercer modelo se muestra aunque el servidor no lo mande', () => {
      montar();
      responderApertura({
        estado: {
          ...ESTADO_ENTRENADO,
          modelos: [
            sinEntrenar('demanda_semanal'),
            modelo('segmentos_rfm', { estado: 'desactualizado', mensaje: 'Desactualizado: entrenado hace 40 días.' }),
            modelo('anomalias_ventas', { estado: 'obsoleto', mensaje: 'Obsoleto: otra versión de scikit-learn.' }),
          ],
        },
      });
      const clase = (tipo: string) => q(`[data-modelo="${tipo}"] [data-modelo-etiqueta]`)!;
      expect(texto(clase('demanda_semanal'))).toBe('Sin entrenar');
      expect(clase('demanda_semanal').className).not.toMatch(/fs-chip--(exito|advertencia|error)/);
      expect(clase('segmentos_rfm').className).toContain('fs-chip--advertencia');
      expect(clase('anomalias_ventas').className).toContain('fs-chip--error');
      expect(q('[data-modelo="demanda_semanal"] [data-modelo-detalle]')).toBeNull();

      fixture.destroy();
      TestBed.resetTestingModule();
      montar();
      responderApertura({ estado: ESTADO_VACIO });
      expect(qa('[data-modelo]').length).toBe(3);
      expect(texto(q('[data-modelo="anomalias_ventas"] [data-modelo-etiqueta]'))).toBe('Sin entrenar');
    });

    it('el botón dice "Entrenar modelos" si no hay ninguno entrenado y "Reentrenar" si ya hay alguno', () => {
      montar();
      responderApertura({ estado: ESTADO_VACIO });
      expect(texto(boton())).toBe('Entrenar modelos');

      fixture.destroy();
      TestBed.resetTestingModule();
      montar();
      responderApertura();
      expect(texto(boton())).toBe('Reentrenar');
    });

    it('si el estado no se puede leer lo explica con [Reintentar] y los demás bloques siguen funcionando', () => {
      montar();
      fallar(falso.colas.estado, errorHttp(500, { detail: 'Error interno' }));
      responder(falso.colas.demanda, demanda());
      fixture.detectChanges();

      expect(texto(q('[data-estado="error-estado"]'))).toContain('No pudimos leer el estado de los modelos');
      expect(q('[data-demanda="resumen"]')).not.toBeNull();
      (q('[data-accion="reintentar-estado"]') as HTMLButtonElement).click();
      expect(falso.servicio.estado).toHaveBeenCalledTimes(2);
    });
  });

  describe('entrenar', () => {
    function entrenarConfirmando(): { pedidas: ReturnType<typeof espiarConfirmacion> } {
      const pedidas = espiarConfirmacion();
      boton().click();
      return { pedidas };
    }

    it('pide confirmación con el aviso de que puede tardar, y no entrena hasta aceptar', () => {
      montar();
      responderApertura();
      const { pedidas } = entrenarConfirmando();

      expect(pedidas.length).toBe(1);
      expect(pedidas[0].message).toBe('Se entrenarán los modelos con los datos de tu empresa. Puede tardar unos segundos.');
      expect(falso.servicio.entrenar).not.toHaveBeenCalled();
    });

    it('al aceptar llama a entrenar UNA vez, deshabilita el botón con "Entrenando…" y no se puede pedir otra vez', () => {
      montar();
      responderApertura();
      const { pedidas } = entrenarConfirmando();
      pedidas[0].accept!();
      fixture.detectChanges();

      expect(falso.servicio.entrenar).toHaveBeenCalledTimes(1);
      expect(boton().disabled).toBe(true);
      expect(texto(boton())).toBe('Entrenando…');
      expect(boton().getAttribute('aria-busy')).toBe('true');
      // Mientras espera, ni el botón ni los accesos de los bloques vuelven a pedir confirmación.
      comp.pedirEntrenar();
      expect(pedidas.length).toBe(1);
      expect(falso.servicio.entrenar).toHaveBeenCalledTimes(1);
    });

    it('al terminar avisa por cada modelo, libera el botón y vuelve a pedir estado y los cuatro bloques', () => {
      montar();
      responderApertura();
      const { pedidas } = entrenarConfirmando();
      pedidas[0].accept!();
      responder(falso.colas.entrenar, ENTRENAMIENTO_OK);
      fixture.detectChanges();

      expect(avisos).toHaveBeenCalledWith(expect.objectContaining({ severity: 'success', summary: 'Demanda semanal por categoría: entrenado' }));
      expect(avisos).toHaveBeenCalledWith(expect.objectContaining({ severity: 'success', summary: 'Grupos de clientes: entrenado' }));
      expect(boton().disabled).toBe(false);
      expect(texto(boton())).toBe('Reentrenar');

      expect(falso.servicio.estado).toHaveBeenCalledTimes(2);
      expect(falso.servicio.demanda).toHaveBeenCalledTimes(2);
      expect(falso.servicio.segmentos).toHaveBeenCalledTimes(2);
      expect(falso.servicio.anomalias).toHaveBeenCalledTimes(2);
      expect(falso.servicio.reposicion).toHaveBeenCalledTimes(2);
      expect(falso.servicio.entrenar).toHaveBeenCalledTimes(1);
    });

    it('datos_insuficientes muestra el motivo que dio el servidor', () => {
      montar();
      responderApertura({ estado: ESTADO_VACIO });
      const { pedidas } = entrenarConfirmando();
      pedidas[0].accept!();
      responder(falso.colas.entrenar, {
        resultados: [
          {
            tipo: 'demanda_semanal',
            estado: 'datos_insuficientes',
            version: null,
            metricas: {},
            avisos: [],
            motivo: 'Se necesitan al menos 26 semanas con ventas (hay 10).',
            duracion_ms: 5,
          },
        ],
      });
      fixture.detectChanges();

      expect(avisos).toHaveBeenCalledWith(
        expect.objectContaining({
          severity: 'warn',
          summary: 'Demanda semanal por categoría: no se pudo entrenar',
          detail: 'Se necesitan al menos 26 semanas con ventas (hay 10).',
        }),
      );
      expect(boton().disabled).toBe(false);
    });

    it('409 entrenamiento_en_curso: "Otra persona ya está entrenando; vuelve a intentarlo en un momento"', () => {
      montar();
      responderApertura();
      const { pedidas } = entrenarConfirmando();
      pedidas[0].accept!();
      fallar(falso.colas.entrenar, errorHttp(409, { detail: 'entrenamiento_en_curso', codigo: 'entrenamiento_en_curso', mensaje: 'x' }));
      fixture.detectChanges();

      expect(avisos).toHaveBeenCalledWith(
        expect.objectContaining({ severity: 'warn', detail: 'Otra persona ya está entrenando; vuelve a intentarlo en un momento.' }),
      );
      expect(boton().disabled).toBe(false);
      // No recarga nada: no cambió ningún modelo.
      expect(falso.servicio.demanda).toHaveBeenCalledTimes(1);
    });

    it('429: "Puedes entrenar hasta 3 veces por minuto"', () => {
      montar();
      responderApertura();
      const { pedidas } = entrenarConfirmando();
      pedidas[0].accept!();
      fallar(falso.colas.entrenar, errorHttp(429, { detail: 'Too many requests' }));
      fixture.detectChanges();

      expect(avisos).toHaveBeenCalledWith(expect.objectContaining({ severity: 'warn', detail: expect.stringContaining('Puedes entrenar hasta 3 veces por minuto') }));
      expect(boton().disabled).toBe(false);
    });

    it('otro error: avisa con el mensaje del servidor y libera el botón', () => {
      montar();
      responderApertura();
      const { pedidas } = entrenarConfirmando();
      pedidas[0].accept!();
      fallar(falso.colas.entrenar, errorHttp(500, { detail: 'Fallo interno' }));
      fixture.detectChanges();

      expect(avisos).toHaveBeenCalledWith(expect.objectContaining({ severity: 'error', summary: 'No se pudo entrenar', detail: 'Fallo interno' }));
      expect(boton().disabled).toBe(false);
    });
  });

  describe('sin modelos entrenados', () => {
    function abrirSinModelos(): void {
      montar();
      responder(falso.colas.estado, ESTADO_VACIO);
      fallar(falso.colas.demanda, ERROR_SIN_MODELO);
      fallar(falso.colas.segmentos, ERROR_SIN_MODELO);
      fallar(falso.colas.anomalias, ERROR_SIN_MODELO);
      fallar(falso.colas.reposicion, ERROR_SIN_MODELO);
      fixture.detectChanges();
    }

    it('cada bloque dice "Todavía no hay predicciones. Entrena los modelos para verlas." con su botón', () => {
      abrirSinModelos();

      const mensajes = qa('[data-estado="sin-modelo"]');
      expect(mensajes.length).toBe(4);
      for (const m of mensajes) {
        expect(texto(m)).toContain('Todavía no hay predicciones. Entrena los modelos para verlas.');
        expect(texto(m.querySelector('[data-accion="entrenar-vacio"]'))).toBe('Entrenar modelos');
      }
      expect(texto(q('[data-metricas="vacio"]'))).toContain('Las métricas aparecen cuando hay modelos entrenados.');
      // No es un error: no hay [Reintentar] ni alertas.
      expect(q('[data-estado="error"]')).toBeNull();
    });

    it('el botón del bloque pide la misma confirmación que el de la cabecera', () => {
      abrirSinModelos();
      const pedidas = espiarConfirmacion();
      (q('[data-bloque="segmentos"] [data-accion="entrenar-vacio"]') as HTMLButtonElement).click();

      expect(pedidas.length).toBe(1);
      expect(pedidas[0].message).toContain('Puede tardar unos segundos');
      pedidas[0].accept!();
      expect(falso.servicio.entrenar).toHaveBeenCalledTimes(1);
    });

    it('409 modelo_obsoleto pide reentrenar', () => {
      montar();
      responder(falso.colas.estado, ESTADO_ENTRENADO);
      fallar(falso.colas.demanda, errorHttp(409, { detail: 'modelo_obsoleto', codigo: 'modelo_obsoleto', mensaje: 'El modelo se entrenó con otra versión.' }));
      fixture.detectChanges();

      const obsoleto = q('[data-bloque="demanda"] [data-estado="obsoleto"]')!;
      expect(texto(obsoleto)).toContain('obsoleto');
      expect(texto(obsoleto.querySelector('[data-accion="reentrenar-vacio"]'))).toBe('Reentrenar');
    });

    it('409 entrenamiento_en_curso en un bloque sugiere reintentar en un momento', () => {
      montar();
      fallar(falso.colas.demanda, errorHttp(409, { detail: 'entrenamiento_en_curso', codigo: 'entrenamiento_en_curso' }));
      fixture.detectChanges();

      const enCurso = q('[data-bloque="demanda"] [data-estado="en-curso"]')!;
      expect(texto(enCurso)).toContain('vuelve a intentarlo en un momento');
      (enCurso.querySelector('[data-accion="reintentar"]') as HTMLButtonElement).click();
      expect(falso.servicio.demanda).toHaveBeenCalledTimes(2);
    });
  });

  describe('bloques independientes', () => {
    it('si fallan los grupos de clientes, la demanda, los días inusuales y la reposición siguen visibles', () => {
      montar();
      responder(falso.colas.estado, ESTADO_ENTRENADO);
      responder(falso.colas.demanda, demanda());
      fallar(falso.colas.segmentos, errorHttp(500, { detail: 'Error interno' }));
      responder(falso.colas.anomalias, anomalias([anomalia(0)]));
      responder(falso.colas.reposicion, reposicion());
      fixture.detectChanges();

      expect(texto(q('[data-bloque="segmentos"] [data-estado="error"]'))).toContain('Error interno');
      expect(q('[data-bloque="demanda"] [data-demanda="resumen"]')).not.toBeNull();
      expect(q('[data-bloque="demanda"] [data-estado="error"]')).toBeNull();
      expect(qa('[data-bloque="anomalias"] tr[data-anomalia]').length).toBe(1);
      expect(qa('[data-bloque="reposicion"] tr[data-categoria]').length).toBe(3);
      // Las métricas usan lo que sí llegó.
      expect(q('[data-metrica="mae"]')).not.toBeNull();
      expect(q('[data-metrica="silhouette"]')).toBeNull();
    });

    it('[Reintentar] vuelve a pedir SOLO ese bloque y recupera sus datos', () => {
      montar();
      responder(falso.colas.estado, ESTADO_ENTRENADO);
      responder(falso.colas.demanda, demanda());
      fallar(falso.colas.segmentos, errorHttp(500, { detail: 'x' }));
      responder(falso.colas.anomalias, anomalias([]));
      responder(falso.colas.reposicion, reposicion());
      fixture.detectChanges();

      (q('[data-bloque="segmentos"] [data-accion="reintentar"]') as HTMLButtonElement).click();
      expect(falso.servicio.segmentos).toHaveBeenCalledTimes(2);
      expect(falso.servicio.demanda).toHaveBeenCalledTimes(1);
      responder(falso.colas.segmentos, segmentos());
      fixture.detectChanges();

      expect(q('[data-bloque="segmentos"] [data-estado="error"]')).toBeNull();
      expect(qa('[data-segmento]').length).toBe(2);
    });

    it('una respuesta vieja nunca pisa a la nueva (cambiar de horizonte rápido)', () => {
      montar();
      responderApertura();
      comp.cambiarSemanas(8);
      fixture.detectChanges();
      comp.cambiarSemanas(12);
      fixture.detectChanges();
      expect(falso.colas.demanda.length).toBe(3);

      responder(falso.colas.demanda, demanda({ horizonte_semanas: 12 }), 2);
      fixture.detectChanges();
      // La del horizonte 8 quedó cancelada: nadie la escucha.
      expect(falso.colas.demanda[1].observed).toBe(false);
      expect(texto(q('[data-demanda="resumen"]'))).toContain('próximas 12 semanas');
    });
  });

  describe('predicción de demanda', () => {
    function chart(): { data: { labels: string[]; datasets: Record<string, any>[] }; options: any; type?: string } {
      return q('[data-bloque="demanda"] p-chart') as never;
    }

    it('dibuja el histórico sólido, la predicción punteada del mismo tono y la banda del rango estimado', () => {
      montar();
      responderApertura();

      const { data } = chart();
      const porNombre = (n: string) => data.datasets.find((d) => d['label'] === n)!;
      expect(data.datasets.length).toBe(4);
      expect(data.labels.length).toBe(14); // 12 semanas reales + 2 previstas
      expect(porNombre('Ventas reales')['borderDash']).toBeUndefined();
      expect(porNombre('Predicción')['borderDash']).toEqual([6, 4]);
      expect(porNombre('Predicción')['borderColor']).toBe(porNombre('Ventas reales')['borderColor']);
      expect(porNombre('Rango estimado')['fill']).toBe('+1');
      expect(porNombre('Rango estimado (mínimo)')).toBeDefined();
      expect(q('[data-demanda="grafico"]')!.getAttribute('aria-label')).toContain('Total de la empresa');
      expect(q('[data-bloque="demanda"] p-chart')!.getAttribute('type')).toBe('line');
    });

    it('la leyenda de texto nombra las tres líneas y la frase resumen usa el total y la variación', () => {
      montar();
      responderApertura();

      const leyenda = texto(q('[data-bloque="demanda"] .leyenda'));
      expect(leyenda).toContain('Ventas reales');
      expect(leyenda).toContain('Predicción (línea punteada)');
      expect(leyenda).toContain('Rango estimado');
      expect(texto(q('[data-demanda="resumen"]'))).toBe(
        'En toda la empresa se prevén 190 unidades en las próximas 4 semanas: 19,1 % más que el promedio de las últimas 4 semanas.',
      );
    });

    it('muestra la interpretación del servidor y los supuestos desplegables, sin inventar frases', () => {
      montar();
      responderApertura();

      expect(texto(q('[data-demanda="interpretacion"]'))).toContain('el promedio móvil de 4 semanas se equivoca 3,04');
      const supuestos = q('[data-demanda="supuestos"]') as HTMLDetailsElement;
      expect(supuestos.tagName).toBe('DETAILS');
      expect(supuestos.open).toBe(false);
      expect(texto(supuestos)).toContain('Cómo se calcula');
      expect(texto(supuestos)).toContain('El descuento de las semanas futuras');
    });

    it('el selector de categoría sale de la misma respuesta e incluye "Toda la empresa"', () => {
      montar();
      responderApertura();
      const instancia = widget(WidgetDemandaComponent) as any;

      expect(instancia.opciones().map((o: { etiqueta: string }) => o.etiqueta)).toEqual(['Toda la empresa', 'Camisetas deportivas', 'Chamarras']);
      expect(q('[data-bloque="demanda"] p-select')).not.toBeNull();
    });

    it('cambiar de categoría NO hace una llamada nueva: cambia el gráfico con lo que ya llegó', () => {
      montar();
      responderApertura();
      const instancia = widget(WidgetDemandaComponent) as any;
      const antes = totalLlamadas(falso.servicio);

      instancia.elegirCategoria(3);
      fixture.detectChanges();

      expect(totalLlamadas(falso.servicio)).toBe(antes);
      expect(texto(q('[data-demanda="resumen"]'))).toContain('En Chamarras se prevén 33 unidades');
      expect(q('[data-demanda="grafico"]')!.getAttribute('aria-label')).toContain('Chamarras');
      const reales = chart().data.datasets.find((d) => d['label'] === 'Ventas reales')!;
      expect(reales['data'][0]).toBe(5);

      instancia.elegirCategoria(null);
      fixture.detectChanges();
      expect(totalLlamadas(falso.servicio)).toBe(antes);
      expect(texto(q('[data-demanda="resumen"]'))).toContain('En toda la empresa');
    });

    it('cambiar el horizonte vuelve a pedir demanda y reposición, y nada más', () => {
      montar();
      responderApertura();

      comp.cambiarSemanas(8);
      fixture.detectChanges();

      expect(falso.servicio.demanda).toHaveBeenCalledTimes(2);
      expect(falso.servicio.demanda.mock.calls[1][0]).toBe(8);
      expect(falso.servicio.reposicion).toHaveBeenCalledTimes(2);
      expect(falso.servicio.reposicion.mock.calls[1][0]).toBe(8);
      expect(falso.servicio.segmentos).toHaveBeenCalledTimes(1);
      expect(falso.servicio.anomalias).toHaveBeenCalledTimes(1);
      expect(falso.servicio.estado).toHaveBeenCalledTimes(1);

      // Elegir el mismo horizonte otra vez no pide nada.
      comp.cambiarSemanas(8);
      fixture.detectChanges();
      expect(falso.servicio.demanda).toHaveBeenCalledTimes(2);
    });

    it('el horizonte por defecto es 4 y se ofrecen 4, 8 y 12 semanas', () => {
      montar();
      responderApertura();
      expect(comp.semanas()).toBe(4);
      expect(comp.horizontes.map((h: { valor: number }) => h.valor)).toEqual([4, 8, 12]);
      expect(qa('p-selectbutton .p-togglebutton').length).toBe(3);
    });

    it('un modelo "desactualizado" (HTTP 200) muestra su aviso', () => {
      montar();
      responderApertura({
        demanda: demanda({
          modelo: modelo('demanda_semanal', { estado: 'desactualizado', mensaje: 'Desactualizado: entrenado hace 40 días.' }),
          avisos: ['Los datos del modelo tienen más de 4 semanas.'],
        }),
      });

      const avisosDemanda = qa('[data-bloque="demanda"] [data-demanda="aviso"]').map((a) => texto(a));
      expect(avisosDemanda).toContain('Los datos del modelo tienen más de 4 semanas.');
      expect(avisosDemanda).toContain('Desactualizado: entrenado hace 40 días.');
    });

    it('una variación nula o negativa se escribe con honestidad', () => {
      montar();
      const base = demanda();
      responderApertura({
        demanda: demanda({ total_empresa: { ...base.total_empresa, variacion_pct_vs_ultimas_semanas: -8.25 } }),
      });
      expect(texto(q('[data-demanda="resumen"]'))).toContain('8,3 % menos que el promedio de las últimas 4 semanas');

      (widget(WidgetDemandaComponent) as any).elegirCategoria(4);
      fixture.detectChanges();
      expect(texto(q('[data-demanda="resumen"]'))).toContain('19,1 % más');
    });
  });

  describe('grupos de clientes', () => {
    it('una tarjeta por grupo con sus cifras, su descripción y qué hacer', () => {
      montar();
      responderApertura();

      expect(texto(q('[data-segmentos="analizados"]'))).toBe('Clientes analizados: 78');
      const campeones = q('[data-segmento="Campeones"]')!;
      const t = texto(campeones);
      expect(t).toContain('Campeones');
      expect(t).toContain('22 (28,2 %)');
      expect(t).toContain('hace 17 días');
      expect(t).toContain('15,1');
      expect(t).toContain('63,5 %');
      expect(t).toContain('Compran seguido, gastan mucho y compraron hace poco.');
      expect(t).toContain('Qué hacer: Cuídalos');
      expect(qa('[data-segmento]').length).toBe(2);
    });

    it('el anillo lleva el tamaño de cada grupo y una leyenda de texto con las cantidades', () => {
      montar();
      responderApertura();
      const anillo = q('[data-bloque="segmentos"] p-chart') as unknown as { data: { labels: string[]; datasets: { data: number[] }[] } };

      expect(anillo.data.labels).toEqual(['Campeones', 'En riesgo']);
      expect(anillo.data.datasets[0].data).toEqual([22, 16]);
      expect(q('[data-bloque="segmentos"] p-chart')!.getAttribute('type')).toBe('doughnut');
      const leyenda = texto(q('[data-segmentos="leyenda"]'));
      expect(leyenda).toContain('Campeones 22 clientes · 28,2 %');
      expect(leyenda).toContain('En riesgo 16 clientes · 20,5 %');
      expect(q('[data-segmentos="grafico"]')!.getAttribute('aria-label')).toContain('Campeones 22 clientes');
    });

    it('muestra la interpretación y los supuestos del servidor', () => {
      montar();
      responderApertura();
      expect(texto(q('[data-segmentos="interpretacion"]'))).toContain('genera el 63,5% de las ventas');
      expect(texto(q('[data-segmentos="supuestos"]'))).toContain('no predice conductas futuras');
    });
  });

  describe('métricas en lenguaje simple', () => {
    it('cada ficha trae valor, frase, etiqueta de calidad y ayuda; las flojas se muestran tal cual', () => {
      montar();
      responderApertura();

      const ficha = (n: string) => q(`[data-metrica="${n}"]`)!;
      expect(qa('[data-metrica]').length).toBe(5);

      // R² casi cero: Débil y sin adornos.
      expect(texto(ficha('r2').querySelector('[data-metrica-calidad]'))).toBe('Débil');
      expect(texto(ficha('r2').querySelector('[data-metrica-frase]'))).toBe('Todavía no explica la demanda mejor que un promedio simple.');
      // Mejora de 5,2 %: Aceptable.
      expect(texto(ficha('mejora_mae_pct').querySelector('[data-metrica-calidad]'))).toBe('Aceptable');
      expect(texto(ficha('mejora_mae_pct').querySelector('[data-metrica-frase]'))).toBe('El modelo mejora en 5,2 % al promedio móvil simple.');
      // Silhouette 0,55: Buena.
      expect(texto(ficha('silhouette').querySelector('[data-metrica-calidad]'))).toBe('Buena');
      // MAE 2,88 sobre un promedio de 6 unidades por categoría y semana: Débil, y lo dice.
      expect(texto(ficha('mae').querySelector('[data-metrica-calidad]'))).toBe('Débil');
      expect(texto(ficha('mae').querySelector('[data-metrica-frase]'))).toContain('2,9 unidades por categoría y semana');
      // RMSE: sin etiqueta.
      expect(ficha('rmse').querySelector('[data-metrica-calidad]')).toBeNull();
      expect(texto(ficha('rmse').querySelector('[data-metrica-valor]'))).toBe('3,88');
      // Cada ficha tiene su ayuda accesible.
      for (const f of qa('[data-metrica]')) {
        expect(f.querySelector('button.ficha__ayuda')!.getAttribute('aria-label')).toContain('Qué significa');
      }
    });

    it('una mejora negativa dice "todavía no supera al promedio móvil"', () => {
      montar();
      const base = demanda();
      responderApertura({ demanda: demanda({ metricas: { ...base.metricas, mejora_mae_pct: -3.2 } }) });

      const ficha = q('[data-metrica="mejora_mae_pct"]')!;
      expect(texto(ficha.querySelector('[data-metrica-frase]'))).toMatch(/^Todavía no supera al promedio móvil/);
      expect(texto(ficha.querySelector('[data-metrica-calidad]'))).toBe('Débil');
    });
  });

  describe('días de ventas inusuales', () => {
    it('ordena por la desviación más grande, con signo, color y texto, y la severidad con etiqueta', () => {
      montar();
      responderApertura({
        anomalias: anomalias([
          anomalia(0, { desviacion_pct: 120.5, severidad: 'leve' }),
          anomalia(1, { desviacion_pct: -340.2, severidad: 'fuerte', sucursal: 'FashionStore Centro' }),
          anomalia(2, { desviacion_pct: 594.5, severidad: 'fuerte' }),
        ]),
      });

      const filas = qa('[data-bloque="anomalias"] tr[data-anomalia]');
      expect(filas.length).toBe(3);
      expect(texto(filas[0].querySelector('[data-desviacion]'))).toBe('+594,5 % vendió de más');
      expect(texto(filas[1].querySelector('[data-desviacion]'))).toBe('−340,2 % vendió de menos');
      expect(texto(filas[2].querySelector('[data-desviacion]'))).toBe('+120,5 % vendió de más');
      expect(filas[0].querySelector('.desviacion--mas')).not.toBeNull();
      expect(filas[1].querySelector('.desviacion--menos')).not.toBeNull();
      expect(texto(filas[0].querySelector('[data-severidad]'))).toBe('Fuerte');
      expect(texto(filas[2].querySelector('[data-severidad]'))).toBe('Leve');
      expect(filas[0].querySelector('[data-severidad] fs-icono')).not.toBeNull();
      // Fecha dd/mm/aaaa, ventas y esperado en Bs.
      expect(texto(filas[0])).toContain('03/09/2026');
      expect(texto(filas[0])).toMatch(/Bs 1\.?002,00/);
      expect(texto(filas[0])).toContain('Bs 300,00');
    });

    it('dice cuántos días inusuales hay y cuántos son fuertes, y avisa que no es necesariamente un error', () => {
      montar();
      responderApertura({
        anomalias: anomalias([anomalia(0), anomalia(1, { severidad: 'leve' }), anomalia(2)], { interpretacion: ['La sucursal con más días inusuales es Equipetrol (3).'] }),
      });

      expect(texto(q('[data-anomalias="totales"]'))).toBe('3 días inusuales, 2 fuertes en los últimos 90 días.');
      expect(texto(q('[data-anomalias="aviso-no-error"]'))).toBe('Un día inusual no es necesariamente un error.');
      expect(texto(q('[data-anomalias="interpretacion"]'))).toContain('La sucursal con más días inusuales es Equipetrol (3).');
    });

    it('pagina de a 10 cuando hay más de 10; con 10 o menos no hay paginador', () => {
      montar();
      responderApertura({ anomalias: anomalias(Array.from({ length: 12 }, (_, i) => anomalia(i))) });

      expect(qa('[data-bloque="anomalias"] tr[data-anomalia]').length).toBe(10);
      expect(q('[data-bloque="anomalias"] .p-paginator')).not.toBeNull();
      // La primera es la de mayor desviación (la fila 11 del servidor: 100 + 11 * 10 = 210 %).
      expect(texto(q('[data-bloque="anomalias"] tr[data-anomalia] [data-desviacion]'))).toContain('+210,0 %');

      fixture.destroy();
      TestBed.resetTestingModule();
      montar();
      responderApertura({ anomalias: anomalias(Array.from({ length: 10 }, (_, i) => anomalia(i))) });
      expect(qa('[data-bloque="anomalias"] tr[data-anomalia]').length).toBe(10);
      expect(q('[data-bloque="anomalias"] .p-paginator')).toBeNull();
    });

    it('el periodo por defecto es 90 días; cambiarlo vuelve a pedir SOLO las anomalías', () => {
      montar();
      responderApertura();
      const instancia = widget(WidgetAnomaliasComponent) as any;

      expect(instancia.periodos.map((p: { valor: number }) => p.valor)).toEqual([30, 90, 180, 365]);
      expect(instancia.dias()).toBe(90);

      instancia.cambiarDias(30);
      expect(falso.servicio.anomalias).toHaveBeenCalledTimes(2);
      expect(falso.servicio.anomalias.mock.calls[1][0]).toBe(30);
      expect(falso.servicio.demanda).toHaveBeenCalledTimes(1);
      expect(falso.servicio.segmentos).toHaveBeenCalledTimes(1);
      expect(falso.servicio.reposicion).toHaveBeenCalledTimes(1);
    });

    it('sin días inusuales lo dice con claridad', () => {
      montar();
      responderApertura({ anomalias: anomalias([]) });
      expect(texto(q('[data-anomalias="vacio"]'))).toContain('No se detectaron días inusuales en este periodo.');
      expect(q('[data-bloque="anomalias"] table')).toBeNull();
    });
  });

  describe('reposición sugerida', () => {
    it('lista cada categoría con su estado en color Y texto, lo crítico primero', () => {
      montar();
      responderApertura();

      const filas = qa('[data-bloque="reposicion"] tr[data-categoria]');
      expect(filas.length).toBe(3);
      expect(texto(filas[0])).toContain('Chamarras');
      expect(texto(filas[0].querySelector('[data-estado-reposicion]'))).toBe('Crítico');
      expect(filas[0].querySelector('[data-estado-reposicion]')!.className).toContain('fs-chip--error');
      expect(filas[0].querySelector('[data-estado-reposicion] fs-icono')).not.toBeNull();
      expect(texto(filas[0])).toContain('20 unidades');
      expect(texto(filas[0])).toContain('9,5 por semana');
      expect(texto(filas[0])).toContain('2,1 semanas');
      expect(texto(filas[0])).toContain('Se agotaría en la semana 3');
      expect(texto(filas[0])).toContain('40 unidades (orientativo)');
      expect(texto(filas[1].querySelector('[data-estado-reposicion]'))).toBe('Con stock');
    });

    it('semanas_cobertura nulo se escribe "Sin demanda prevista" y va al final', () => {
      montar();
      responderApertura();
      const filas = qa('[data-bloque="reposicion"] tr[data-categoria]');
      expect(texto(filas[2])).toContain('Bufandas');
      expect(texto(filas[2])).toContain('Sin demanda prevista');
    });

    it('aclara que es orientativa y por categoría, y enlaza al inventario', () => {
      montar();
      responderApertura();

      expect(texto(q('[data-reposicion="nota"]'))).toContain('guía por categoría');
      expect(texto(q('[data-bloque="reposicion"] .bloque__sub'))).toContain('orientativo');
      const enlace = q('[data-bloque="reposicion"] [data-accion="ver-inventario"]') as HTMLAnchorElement;
      expect(texto(enlace)).toBe('Ver inventario');
      expect(enlace.getAttribute('href')).toBe('/inventario');
      expect(texto(q('[data-reposicion="resumen"]'))).toContain('1 categoría corre riesgo de agotarse');
    });
  });

  describe('enlace a Reportes', () => {
    it('hay un enlace discreto a ventas, inventario y reservas', () => {
      montar();
      responderApertura();
      const enlace = q('[data-accion="ver-reportes"]') as HTMLAnchorElement;
      expect(texto(enlace)).toBe('Ver ventas, inventario y reservas');
      expect(enlace.getAttribute('href')).toBe('/reportes');
    });
  });

  describe('plan, rol y conexión', () => {
    it('un plan sin analitica_ml muestra la tarjeta del plan, apaga los bloques y NO llama a /analitica', () => {
      montar({ incluye: false });

      expect(totalLlamadas(falso.servicio)).toBe(0);
      const tarjeta = q('[data-bloqueo="plan"]')!;
      expect(texto(tarjeta)).toContain('Tu plan no incluye la analítica con Machine Learning');
      expect(texto(tarjeta)).toContain('Con el plan Profesional puedes ver la predicción de demanda, los grupos de clientes y las alertas de reposición');
      expect(tarjeta.querySelector('fs-icono')).not.toBeNull();
      expect((tarjeta.querySelector('[data-accion="ver-plan"]') as HTMLAnchorElement).getAttribute('href')).toBe('/mi-empresa');
      expect(texto(tarjeta.querySelector('[data-accion="ver-plan"]'))).toBe('Ver mi plan');
      expect((tarjeta.querySelector('[data-accion="ir-reportes"]') as HTMLAnchorElement).getAttribute('href')).toBe('/reportes');
      expect(qa('.bloque--deshabilitado').length).toBe(5);
      expect(boton().disabled).toBe(true);
      expect(q('[data-seccion="modelos"]')).toBeNull();
    });

    it('si el plan cambia mientras la pantalla está abierta, deja de consultar', () => {
      montar();
      responderApertura();
      incluye.set(false);
      fixture.detectChanges();

      expect(q('[data-bloqueo="plan"]')).not.toBeNull();
      comp.cambiarSemanas(8);
      fixture.detectChanges();
      expect(falso.servicio.demanda).toHaveBeenCalledTimes(1);
    });

    it('un 403 plan_no_incluye_funcionalidad (quien no conoce su plan) muestra la tarjeta del plan y no se vuelve a llamar', () => {
      montar();
      fallar(falso.colas.estado, ERROR_PLAN);
      fallar(falso.colas.demanda, ERROR_PLAN);
      fallar(falso.colas.segmentos, ERROR_PLAN);
      fallar(falso.colas.anomalias, ERROR_PLAN);
      fallar(falso.colas.reposicion, ERROR_PLAN);
      fixture.detectChanges();

      expect(texto(q('[data-bloqueo="plan"]'))).toContain('Tu plan no incluye la analítica con Machine Learning');
      expect(q('[data-bloqueo="alcance"]')).toBeNull();
      expect(qa('.bloque--deshabilitado').length).toBe(5);
      expect(q('[data-estado="error"]')).toBeNull();

      const llamadas = totalLlamadas(falso.servicio);
      comp.cambiarSemanas(8);
      comp.pedirEntrenar();
      fixture.detectChanges();
      expect(totalLlamadas(falso.servicio)).toBe(llamadas);
      expect(boton().disabled).toBe(true);
    });

    it('el 403 de un solo bloque basta para explicar todo y detener a los demás', () => {
      montar();
      fallar(falso.colas.demanda, ERROR_PLAN);
      fixture.detectChanges();

      expect(q('[data-bloqueo="plan"]')).not.toBeNull();
      // Las consultas que seguían en espera se cancelaron.
      expect(falso.colas.segmentos[0].observed).toBe(false);
      expect(falso.colas.anomalias[0].observed).toBe(false);
    });

    it('un 403 de alcance (el usuario tiene sucursal) muestra "La analítica es solo para administradores de la empresa"', () => {
      montar();
      fallar(falso.colas.estado, ERROR_ALCANCE);
      fallar(falso.colas.demanda, ERROR_ALCANCE);
      fixture.detectChanges();

      const tarjeta = q('[data-bloqueo="alcance"]')!;
      expect(texto(tarjeta)).toContain('La analítica es solo para administradores de la empresa');
      expect(tarjeta.querySelector('[data-accion="ir-reportes"]')).not.toBeNull();
      expect(q('[data-bloqueo="plan"]')).toBeNull();
      expect(qa('.bloque--deshabilitado').length).toBe(5);
    });

    it('sin conexión: lo dice, deshabilita los controles y no llama a nada; al volver, carga', () => {
      montar({ conexion: 'sin_conexion' });

      expect(totalLlamadas(falso.servicio)).toBe(0);
      expect(texto(q('[data-aviso="sin-conexion"]'))).toContain('La analítica necesita conexión a Internet');
      expect(boton().disabled).toBe(true);
      expect(qa('.bloque--deshabilitado').length).toBe(5);
      expect(q('[data-bloque="anomalias"] p-select .p-disabled, [data-bloque="anomalias"] p-select.p-disabled')).not.toBeNull();
      expect(q('p-selectbutton .p-togglebutton.p-disabled, p-selectbutton .p-togglebutton[disabled], p-selectbutton[disabled]')).not.toBeNull();

      conexion.set('en_linea');
      fixture.detectChanges();
      expect(q('[data-aviso="sin-conexion"]')).toBeNull();
      expect(falso.servicio.estado).toHaveBeenCalledTimes(1);
      expect(falso.servicio.demanda).toHaveBeenCalledTimes(1);
      expect(boton().disabled).toBe(false);
    });

    it('si el servidor no responde también se frena (no solo sin red)', () => {
      montar({ conexion: 'servidor_no_responde' });
      expect(totalLlamadas(falso.servicio)).toBe(0);
      expect(q('[data-aviso="sin-conexion"]')).not.toBeNull();
    });
  });

  describe('limpieza', () => {
    it('al destruir la pantalla no queda ninguna consulta escuchando', () => {
      montar();
      const pendientes = [...falso.colas.estado, ...falso.colas.demanda, ...falso.colas.segmentos, ...falso.colas.anomalias, ...falso.colas.reposicion];
      expect(pendientes.some((s) => s.observed)).toBe(true);

      fixture.destroy();
      expect(pendientes.every((s) => !s.observed)).toBe(true);
    });

    it('un entrenamiento pendiente tampoco queda escuchando', () => {
      montar();
      responderApertura();
      const pedidas = espiarConfirmacion();
      boton().click();
      pedidas[0].accept!();
      expect(falso.colas.entrenar[0].observed).toBe(true);

      fixture.destroy();
      expect(falso.colas.entrenar[0].observed).toBe(false);
    });
  });
});
