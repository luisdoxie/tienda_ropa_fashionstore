/**
 * Operaciones sincronizadas tal como las guardó el servidor (E07/E08, `backend/app/sincronizacion/schemas.py`).
 * Los montos llegan como TEXTO decimal ("120.00") y las fechas en UTC con "Z".
 */

export type TipoOperacionSync = 'venta_contado' | 'reserva';

/** Los tres estados que el servidor guarda y deja filtrar. */
export type EstadoOperacionSync = 'confirmada' | 'rechazada' | 'en_conflicto';

export interface RecursoCreadoSync {
  tipo: 'venta' | 'reserva';
  id: number;
  codigo: string;
  total: string | null;
  fecha_expiracion: string | null;
}

/** D17: el servidor acepta el precio de la operación y avisa si el actual es otro. */
export interface AvisoPrecioSync {
  codigo: 'precio_distinto';
  variante_id: number;
  precio_operacion: string;
  precio_actual: string;
}

/** D15: por cada prenda que no alcanzó. */
export interface FaltanteSync {
  variante_id: number;
  solicitado: number;
  disponible: number;
}

export interface AjusteResolucionSync {
  variante_id: number;
  cantidad: number;
  movimiento_id: number;
}

/** Cómo se cerró una operación que estaba en conflicto. */
export interface ResolucionConflictoSync {
  accion: 'forzar' | 'rechazar';
  por_usuario_id: number;
  en: string;
  motivo: string | null;
  ajustes: AjusteResolucionSync[];
}

/** Una fila de la lista (sin el payload). */
export interface OperacionSync {
  operacion_id: string;
  tipo: TipoOperacionSync | string;
  estado: EstadoOperacionSync | string;
  motivo: string | null;
  mensaje: string | null;
  sucursal_id: number | null;
  usuario_id: number;
  fecha_operacion: string;
  recibida_en: string;
  procesada_en: string | null;
  intentos: number;
  dispositivo: string | null;
  recurso: RecursoCreadoSync | null;
  cambio: string | null;
  avisos: AvisoPrecioSync[];
  faltantes: FaltanteSync[];
  resolucion: ResolucionConflictoSync | null;
}

export interface LineaPayloadSync {
  variante_id: number;
  cantidad: number;
  precio_unitario?: string | number;
  descuento_unitario?: string | number;
}

/** Lo que mandó el dispositivo. Solo lo ve quien supervisa. */
export interface PayloadOperacionSync {
  cliente_id?: number | null;
  lineas?: LineaPayloadSync[];
  total?: string | number;
  pago?: { metodo: string; monto_recibido: string | number };
  fecha_visita?: string;
  hora_visita_desde?: string;
  hora_visita_hasta?: string;
  observacion?: string | null;
}

export interface OperacionSyncDetalle extends OperacionSync {
  payload: PayloadOperacionSync | null;
}

export interface OperacionSyncPagina {
  total: number;
  pagina: number;
  tamanio: number;
  items: OperacionSync[];
}

/** Filtros y paginación de `GET /sincronizacion/operaciones` (fechas `AAAA-MM-DD`, inclusivas). */
export interface ConsultaOperacionesSync {
  pagina?: number;
  tamanio?: number;
  estado?: EstadoOperacionSync | null;
  tipo?: TipoOperacionSync | null;
  sucursal_id?: number | null;
  usuario_id?: number | null;
  desde?: string | null;
  hasta?: string | null;
}

export type AccionResolucionSync = 'forzar' | 'rechazar';

/** Cuerpo de `POST /sincronizacion/operaciones/{id}/resolver`. */
export interface ResolverOperacionEntrada {
  accion: AccionResolucionSync;
  motivo: string;
}
