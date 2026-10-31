/**
 * Contrato real de `/api/v1/analitica` (CU-24, E11/E12). Refleja `inteligencia/schemas.py`.
 * Las respuestas vienen listas para dibujar: traen `interpretacion` (frases en español), `supuestos` y
 * `grafico_sugerido`. Los datos de la demostración son sintéticos y el "rango estimado" no es un intervalo de confianza.
 */
import { GraficoSugerido } from './reportes-ia.models';

export type TipoModeloAnalitico = 'demanda_semanal' | 'segmentos_rfm' | 'anomalias_ventas';
export type EstadoVigenciaModelo = 'sin_entrenar' | 'vigente' | 'desactualizado' | 'obsoleto';
export type EstadoEntrenamiento = 'entrenado' | 'datos_insuficientes';
export type SeveridadAnomalia = 'leve' | 'fuerte';
export type EstadoReposicion = 'critico' | 'atencion' | 'ok';

/** Un punto de una serie. `etiqueta` es la fecha ISO del lunes de la semana (o el valor de k en las curvas). */
export interface PuntoSerie {
  etiqueta: string;
  valor: number;
  minimo: number | null;
  maximo: number | null;
  es_prediccion: boolean;
}

export interface KpiAnalitico {
  clave: string;
  titulo: string;
  valor: number | string | null;
  unidad: string | null;
  interpretacion: string | null;
}

export interface EstadoModelo {
  tipo: TipoModeloAnalitico;
  titulo: string;
  entrenado: boolean;
  estado: EstadoVigenciaModelo;
  version: number | null;
  entrenado_en: string | null;
  filas_entrenamiento: number | null;
  datos_desde: string | null;
  datos_hasta: string | null;
  metricas: Record<string, unknown>;
  mensaje: string;
}

export interface DatosDisponibles {
  semanas_con_ventas: number;
  categorias_con_ventas: number;
  clientes_con_compras: number;
}

export interface EstadoAnalitica {
  modelos: EstadoModelo[];
  datos: DatosDisponibles;
  puede_entrenar: Record<string, boolean>;
  interpretacion: string[];
}

export interface ResultadoEntrenamiento {
  tipo: TipoModeloAnalitico;
  estado: EstadoEntrenamiento;
  version: number | null;
  metricas: Record<string, unknown>;
  avisos: string[];
  motivo: string | null;
  duracion_ms: number;
}

export interface EntrenarRespuesta {
  resultados: ResultadoEntrenamiento[];
}

export interface DemandaCategoria {
  /** null = el total de la empresa. */
  categoria_id: number | null;
  categoria: string;
  /** Las últimas 12 semanas reales. */
  historico: PuntoSerie[];
  prediccion: PuntoSerie[];
  total_predicho: number;
  variacion_pct_vs_ultimas_semanas: number | null;
}

export interface MetricasDemanda {
  mae: number | null;
  rmse: number | null;
  r2: number | null;
  mae_base: number | null;
  rmse_base: number | null;
  r2_base: number | null;
  mejora_mae_pct: number | null;
  modelo_elegido: string | null;
}

export interface DemandaRespuesta {
  horizonte_semanas: number;
  modelo: EstadoModelo;
  categorias: DemandaCategoria[];
  total_empresa: DemandaCategoria;
  metricas: MetricasDemanda;
  supuestos: string[];
  interpretacion: string[];
  grafico_sugerido: GraficoSugerido;
  avisos: string[];
}

export interface SegmentoCliente {
  id: number;
  nombre: string;
  descripcion: string;
  accion_sugerida: string;
  clientes: number;
  porcentaje_clientes: number;
  recencia_media_dias: number;
  frecuencia_media: number;
  monto_medio: number;
  monto_total: number;
  porcentaje_monto: number;
}

/** Un cliente anónimo en el gráfico de dispersión: nunca lleva su id. */
export interface PuntoDispersion {
  segmento_id: number;
  frecuencia: number;
  monto: number;
}

export interface SegmentosRespuesta {
  modelo: EstadoModelo;
  k: number;
  silhouette: number | null;
  clientes_segmentados: number;
  segmentos: SegmentoCliente[];
  dispersion: PuntoDispersion[];
  curva_silhouette: PuntoSerie[];
  curva_codo: PuntoSerie[];
  supuestos: string[];
  interpretacion: string[];
  grafico_sugerido: GraficoSugerido;
  avisos: string[];
}

/** `desviacion_pct` es positiva si el día vendió más de lo esperado y negativa si vendió menos. */
export interface AnomaliaVenta {
  fecha: string;
  sucursal_id: number;
  sucursal: string;
  total_ventas: number;
  esperado: number;
  desviacion_pct: number;
  severidad: SeveridadAnomalia;
}

export interface AnomaliasRespuesta {
  modelo: EstadoModelo;
  dias: number;
  desde: string;
  hasta: string;
  anomalias: AnomaliaVenta[];
  total: number;
  fuertes: number;
  supuestos: string[];
  interpretacion: string[];
  grafico_sugerido: GraficoSugerido;
  avisos: string[];
}

export interface ItemReposicion {
  categoria_id: number;
  categoria: string;
  disponible: number;
  demanda_semanal_promedio: number;
  /** null = sin demanda prevista (no se agota). */
  semanas_cobertura: number | null;
  agotado_en_semana: number | null;
  estado: EstadoReposicion;
  /** Orientativa, con 10 % de colchón. */
  sugerencia_unidades: number;
}

export interface ReposicionRespuesta {
  modelo: EstadoModelo;
  semanas: number;
  items: ItemReposicion[];
  criticos: number;
  supuestos: string[];
  interpretacion: string[];
  grafico_sugerido: GraficoSugerido;
  avisos: string[];
}

/** Todo junto para el dashboard. Un bloque es null si su modelo aún no está entrenado (su aviso va en `avisos`). */
export interface PanelAnalitico {
  estado: EstadoAnalitica;
  kpis: KpiAnalitico[];
  demanda: DemandaRespuesta | null;
  segmentos: SegmentosRespuesta | null;
  anomalias: AnomaliasRespuesta | null;
  reposicion: ReposicionRespuesta | null;
  avisos: string[];
}

/** Códigos con que el servidor rechaza una consulta de analítica (HTTP 409). */
export type CodigoErrorAnalitica = 'modelo_no_entrenado' | 'modelo_obsoleto' | 'entrenamiento_en_curso';
