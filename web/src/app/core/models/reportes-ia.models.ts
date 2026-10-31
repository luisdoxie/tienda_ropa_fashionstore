/**
 * Contrato real de `/api/v1/reportes-ia` (CU-23, E09/E10/E12). Refleja `inteligencia/schemas.py`.
 * El web nunca arma consultas: envía una frase o una `SolicitudReporte` y muestra lo que el servidor devuelve.
 */

export type EstadoReporte = 'ok' | 'incompleta' | 'ambigua' | 'invalida' | 'no_soportada' | 'no_disponible';
export type InterpreteUsado = 'groq' | 'reglas';
export type OrigenSolicitud = 'texto' | 'voz';
export type CanalReporte = 'digital' | 'presencial';
export type AgrupacionReporte = 'dia' | 'semana' | 'mes';
export type OrdenReporte = 'mayor_a_menor' | 'menor_a_mayor';
export type FormatoExportacion = 'xlsx' | 'pdf';

export type TipoPeriodo =
  | 'hoy'
  | 'ayer'
  | 'esta_semana'
  | 'semana_pasada'
  | 'este_mes'
  | 'mes_pasado'
  | 'este_anio'
  | 'anio_pasado'
  | 'ultimos_dias'
  | 'ultimas_semanas'
  | 'ultimos_meses'
  | 'mes_calendario'
  | 'rango_fechas';

export type TipoColumna = 'texto' | 'entero' | 'moneda' | 'porcentaje' | 'fecha' | 'booleano';
export type TipoGraficoServidor = 'barras' | 'barras_horizontales' | 'barras_agrupadas' | 'linea' | 'torta' | 'tabla';

export interface FechaParcial {
  dia: number;
  mes: number;
  anio?: number | null;
}

export interface PeriodoSolicitado {
  tipo: TipoPeriodo;
  n?: number | null;
  mes?: number | null;
  anio?: number | null;
  desde?: FechaParcial | null;
  hasta?: FechaParcial | null;
}

/** Lo que el cliente puede mandar ya armado (sin ids): los nombres se resuelven contra la empresa de la sesión. */
export interface SolicitudReporte {
  tipo_reporte: string | null;
  periodo?: PeriodoSolicitado | null;
  sucursales?: string[];
  categorias?: string[];
  productos?: string[];
  canal?: CanalReporte | null;
  agrupacion?: AgrupacionReporte | null;
  orden?: OrdenReporte | null;
  limite?: number | null;
  horizonte_semanas?: number | null;
  solicitud_multiple?: boolean;
}

export interface PeriodoResuelto {
  /** Fecha ISO (aaaa-mm-dd). */
  desde: string;
  hasta: string;
  etiqueta: string;
}

export interface ReferenciaResuelta {
  id: number;
  nombre: string;
}

/** "Entendí esto": la solicitud validada, con fechas e ids ya resueltos. Es lo que se reenvía para exportar. */
export interface SolicitudResuelta {
  tipo_reporte: string;
  periodo: PeriodoResuelto | null;
  sucursales: ReferenciaResuelta[];
  categorias: ReferenciaResuelta[];
  productos: ReferenciaResuelta[];
  canal: CanalReporte | null;
  agrupacion: AgrupacionReporte | null;
  orden: OrdenReporte | null;
  limite: number | null;
  horizonte_semanas: number | null;
}

export interface ColumnaReporte {
  clave: string;
  titulo: string;
  tipo: TipoColumna;
}

export interface GraficoSugerido {
  tipo: TipoGraficoServidor;
  eje_x: string | null;
  eje_y: string | null;
  serie: string | null;
}

/** Valor de una celda: número, texto, booleano o vacío (los decimales de los reportes de ML llegan como texto). */
export type ValorCelda = string | number | boolean | null;
export type FilaReporte = Record<string, ValorCelda>;

export interface ReporteEjecutado {
  codigo: string;
  titulo: string;
  columnas: ColumnaReporte[];
  filas: FilaReporte[];
  resumen: Record<string, ValorCelda>;
  grafico_sugerido: GraficoSugerido;
  truncado: boolean;
  /** Instante UTC en ISO. */
  generado_en: string;
}

/** Respuesta de `/interpretar` y `/ejecutar`. Todo estado de negocio llega con HTTP 200; con estado ≠ ok no hay `reporte`. */
export interface ReporteGenerativoRespuesta {
  estado: EstadoReporte;
  mensaje: string;
  sugerencias: string[];
  avisos: string[];
  interprete: InterpreteUsado | null;
  solicitud: SolicitudResuelta | null;
  reporte: ReporteEjecutado | null;
  narrativa: string | null;
}

/** Cuerpo de `/ejecutar`: exactamente uno de `texto` o `solicitud`. */
export interface EntradaEjecutarReporte {
  texto?: string;
  solicitud?: SolicitudReporte;
  origen?: OrigenSolicitud;
}

/** Cuerpo de `/exportar`: el formato y exactamente uno de `texto`, `solicitud` o `resuelta`. */
export interface EntradaExportarReporte {
  formato: FormatoExportacion;
  incluir_grafico?: boolean;
  texto?: string;
  solicitud?: SolicitudReporte;
  resuelta?: SolicitudResuelta;
}

// ---- Catálogo (GET /reportes-ia/catalogo) -----------------------------------------------------------------------

export type TipoFiltroCatalogo = 'periodo' | 'lista_nombres' | 'enum' | 'entero';

export interface FiltroCatalogo {
  tipo: TipoFiltroCatalogo;
  descripcion: string;
  obligatorio: boolean;
  /** Para `periodo` es un `PeriodoSolicitado`; para `enum` y `entero`, el valor por defecto. */
  defecto: unknown;
  minimo: number | null;
  maximo: number | null;
  valores: string[];
}

/** Un reporte que el plan de la empresa permite. Un tipo nuevo del servidor aparece solo, sin cambiar el web. */
export interface ReporteCatalogo {
  codigo: string;
  titulo: string;
  descripcion: string;
  ejemplos: string[];
  filtros: Record<string, FiltroCatalogo>;
  columnas: ColumnaReporte[];
  grafico: GraficoSugerido;
}

/** Un archivo ya descargado, listo para guardarlo. */
export interface ArchivoDescargado {
  blob: Blob;
  nombre: string;
}
