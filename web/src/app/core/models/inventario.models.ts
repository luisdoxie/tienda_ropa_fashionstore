/** Fila de GET /inventario/disponibilidad -- público, lo consume el detalle
 * de producto y el checkout para saber qué sucursal tiene stock. */
export interface Disponibilidad {
  variante_id: number;
  sucursal_id: number;
  cantidad_disponible: number;
}

export interface TipoMovimiento {
  id: number;
  codigo: string;
  nombre: string;
  signo: -1 | 1;
  afecta_costo: boolean;
}

export interface Stock {
  id: number;
  variante_id: number;
  sucursal_id: number;
  cantidad_fisica: number;
  cantidad_reservada: number;
  cantidad_disponible: number;
  stock_minimo: number;
  stock_maximo: number | null;
  costo_promedio: number;
  actualizado_en: string;
}

export interface MovimientoInventario {
  id: number;
  variante_id: number;
  sucursal_id: number;
  tipo_movimiento_id: number;
  tipo_movimiento_codigo: string;
  cantidad: number;
  costo_unitario: number | null;
  costo_promedio_post: number | null;
  saldo_post: number;
  referencia_tipo: string | null;
  referencia_id: number | null;
  usuario_id: number | null;
  observacion: string | null;
  creado_en: string;
}

/** Una fila de vw_inventario_consolidado (también la forma de /alertas). */
export interface FilaConsolidado {
  producto_id: number;
  producto: string;
  variante_id: number;
  sku: string;
  talla: string;
  color: string;
  sucursal_id: number;
  sucursal: string;
  cantidad_fisica: number;
  cantidad_reservada: number;
  cantidad_disponible: number;
  stock_minimo: number;
  costo_promedio: number;
  valor_inventario: number;
  /** true: la variante aún no tiene fila de stock en esa sucursal (solo con `incluir_sin_stock`). */
  sin_registro?: boolean;
}

export interface FilaValuacion {
  sucursal_id: number;
  sucursal: string;
  valor_total: number;
}

export interface AjusteCrear {
  variante_id: number;
  sucursal_id: number;
  cantidad: number;
  observacion?: string | null;
}

export interface LimitesActualizar {
  stock_minimo?: number | null;
  stock_maximo?: number | null;
}

export type EstadoTransferencia = 'pendiente' | 'en_transito' | 'recibida' | 'anulada';

export interface TransferenciaDetalle {
  id: number;
  variante_id: number;
  cantidad: number;
}

export interface Transferencia {
  id: number;
  codigo: string;
  sucursal_origen_id: number;
  sucursal_destino_id: number;
  estado: EstadoTransferencia;
  fecha_envio: string | null;
  fecha_recepcion: string | null;
  usuario_id: number | null;
  detalle: TransferenciaDetalle[];
}

export interface TransferenciaDetalleCrear {
  variante_id: number;
  cantidad: number;
}

export interface TransferenciaCrear {
  codigo: string;
  sucursal_origen_id: number;
  sucursal_destino_id: number;
  detalle: TransferenciaDetalleCrear[];
}
