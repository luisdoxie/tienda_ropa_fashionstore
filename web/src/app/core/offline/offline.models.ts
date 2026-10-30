/**
 * Modelos del modo sin conexión (E14). Dos grupos:
 *  - `Paquete*`: lo que devuelve `GET /sincronizacion/paquete*` (contrato v1 de la E08; los montos llegan como TEXTO).
 *  - `Fila*`: lo que se guarda en IndexedDB. TODA fila lleva `empresa_id`; las de operaciones, además, `usuario_id`.
 */

/** Cada operación local nace `registrada` y solo cambia de estado: nunca se borra (D13). */
export type EstadoOperacion = 'registrada' | 'enviada' | 'confirmada' | 'rechazada' | 'en_conflicto';
export type TipoOperacion = 'venta_contado' | 'reserva';

/** Con quién se opera: toda consulta del repositorio lo aplica (igual que el filtro por empresa del backend). */
export interface AlcanceOffline {
  empresaId: number;
  usuarioId: number;
}

// ---- Lo que manda el servidor (contrato v1) ------------------------------------------------------------------------------

export interface PaqueteBase {
  version_contrato: string;
  /** Instante (ISO, UTC) en que el servidor leyó los datos: con él se decide "información desactualizada". */
  generado_en: string;
}

export interface HorarioPaquete {
  dia_semana: number;
  hora_apertura: string;
  hora_cierre: string;
}

export interface SucursalPaquete {
  id: number;
  codigo: string;
  nombre: string;
  direccion: string;
  es_deposito: boolean;
  horarios: HorarioPaquete[];
}

export interface CategoriaPaquete {
  id: number;
  nombre: string;
  categoria_padre_id: number | null;
}

export interface TallaPaquete {
  id: number;
  codigo: string;
  orden: number;
}

export interface ColorPaquete {
  id: number;
  nombre: string;
  codigo_hex: string | null;
}

export interface PaqueteManifiesto extends PaqueteBase {
  aviso_desactualizado_horas: number;
  empresa: { id: number; codigo: string; nombre: string };
  sucursales: SucursalPaquete[];
  referencia: { categorias: CategoriaPaquete[]; tallas: TallaPaquete[]; colores: ColorPaquete[] };
  reglas: {
    metodos_pago_offline: string[];
    max_operaciones_por_lote: number;
    plazo_cambio_horas: number;
    cambios_y_devoluciones: string;
    reservas_offline: string;
  };
}

export interface VariantePaquete {
  id: number;
  talla_id: number;
  color_id: number;
  sku: string;
  codigo_barras: string | null;
  /** Decimal en texto ("149.00"): el precio efectivo (el de la variante o, si no tiene, el del producto). */
  precio: string;
  /** Decimal en texto: el mayor descuento vigente al `generado_en`. */
  descuento_unitario: string;
}

export interface ProductoPaquete {
  id: number;
  codigo: string;
  nombre: string;
  categoria_id: number;
  genero: string;
  temporada_id: number | null;
  imagen_principal: string | null;
  variantes: VariantePaquete[];
}

export interface PaqueteCatalogo extends PaqueteBase {
  total: number;
  siguiente_desde_id: number | null;
  items: ProductoPaquete[];
}

export interface StockPaquete {
  variante_id: number;
  cantidad_disponible: number;
  actualizado_en: string;
}

export interface PaqueteStock extends PaqueteBase {
  sucursal_id: number;
  incremental: boolean;
  siguiente_desde_variante_id: number | null;
  items: StockPaquete[];
}

export interface ClientePaquete {
  id: number;
  nombre: string;
  apellido: string;
  ci_nit: string | null;
}

export interface PaqueteClientes extends PaqueteBase {
  total: number;
  siguiente_desde_id: number | null;
  items: ClientePaquete[];
}

// ---- Lo que se guarda en IndexedDB ---------------------------------------------------------------------------------------

export interface FilaMeta {
  empresa_id: number;
  clave: string;
  valor: unknown;
}

export interface FilaSucursal extends SucursalPaquete {
  empresa_id: number;
}

export interface FilaCategoria extends CategoriaPaquete {
  empresa_id: number;
}

export interface FilaTalla extends TallaPaquete {
  empresa_id: number;
}

export interface FilaColor extends ColorPaquete {
  empresa_id: number;
}

export interface FilaProducto {
  empresa_id: number;
  id: number;
  codigo: string;
  nombre: string;
  /** Texto en minúsculas y sin tildes, para buscar. */
  nombre_norm: string;
  categoria_id: number;
  genero: string;
  temporada_id: number | null;
  imagen_principal: string | null;
}

export interface FilaVariante {
  empresa_id: number;
  id: number;
  producto_id: number;
  talla_id: number;
  color_id: number;
  sku: string;
  codigo_barras: string | null;
  precio: string;
  descuento_unitario: string;
}

/** El stock que se conocía de una variante en una sucursal, y cuándo lo leyó el servidor. */
export interface FilaStock {
  empresa_id: number;
  variante_id: number;
  sucursal_id: number;
  cantidad: number;
  /** `generado_en` del paquete de stock: las operaciones locales POSTERIORES a este instante se descuentan (E14b). */
  generado_en: string;
}

export interface FilaCliente {
  empresa_id: number;
  id: number;
  nombre: string;
  apellido: string;
  ci_nit: string | null;
  nombre_norm: string;
}

/** Una venta de contado o una reserva hecha en este equipo. La completa la E14b; el esquema ya la contempla. */
export interface OperacionLocal {
  empresa_id: number;
  usuario_id: number;
  operacion_id: string;
  tipo: TipoOperacion;
  estado: EstadoOperacion;
  fecha_operacion: string;
  [campo: string]: unknown;
}

// ---- Operaciones hechas sin conexión (E14b) -----------------------------------------------------------------------------

/** Una línea de una venta o reserva: lo que se usó en el momento (precio y descuento de lo descargado, D17). */
export interface LineaOperacionLocal {
  variante_id: number;
  producto_nombre: string;
  sku: string;
  talla: string | null;
  color: string | null;
  cantidad: number;
  /** Decimales en TEXTO ("149.00"), como en el contrato. */
  precio_unitario: string;
  descuento_unitario: string;
  /** cantidad x (precio - descuento), en texto. */
  subtotal: string;
}

/** Lo que devolvió el servidor para esta operación (`ResultadoOperacion` del contrato v1). */
export interface ResultadoServidor {
  estado: 'confirmada' | 'rechazada' | 'en_conflicto' | 'error_temporal';
  motivo?: string | null;
  mensaje?: string | null;
  duplicada?: boolean;
  procesada_en?: string | null;
  recurso?: { tipo: 'venta' | 'reserva'; id: number; codigo: string; total?: string | null; fecha_expiracion?: string | null } | null;
  cambio?: string | null;
  avisos?: { codigo: string; variante_id: number; precio_operacion: string; precio_actual: string }[];
  faltantes?: { variante_id: number; solicitado: number; disponible: number }[];
}

/**
 * La operación completa, tal como se guarda. Extiende la forma mínima del esquema (`OperacionLocal`) con todo lo que
 * necesitan el registro, la cola de envío y la pantalla de pendientes.
 */
export interface OperacionOffline extends OperacionLocal {
  sucursal_id: number;
  cliente_id: number | null;
  /** Nombre del cliente al registrar (para mostrarlo sin volver a buscarlo). */
  cliente_nombre: string | null;
  lineas: LineaOperacionLocal[];
  /** Venta: total a cobrar. Reserva: valor referencial de las prendas. */
  total: string;
  /** Solo ventas: siempre en efectivo cuando no hay conexión (D18). */
  pago: { metodo: 'efectivo'; monto_recibido: string; cambio: string } | null;
  /** Solo reservas. */
  reserva: { fecha_visita: string; hora_visita_desde: string; hora_visita_hasta: string; observacion: string | null } | null;
  /** 'OFF-' + 6 primeros caracteres del uuid: para mostrar al usuario. */
  codigo_local: string;
  creada_en: string;
  dispositivo: string;
  intentos: number;
  ultimo_intento_en: string | null;
  /** Antes de este instante la cola no la reintenta sola. */
  proximo_intento_en: string | null;
  ultimo_error: string | null;
  /** El servidor la rechazó por formato (400/422): no se reintenta sola; hace falta revisarla. */
  bloqueada: boolean;
  motivo: string | null;
  mensaje: string | null;
  resultado: ResultadoServidor | null;
}

/** Un faltante detectado con el stock local al registrar una operación. */
export interface FaltanteLocal {
  variante_id: number;
  producto_nombre: string;
  talla: string | null;
  color: string | null;
  solicitado: number;
  disponible: number;
}

/** Filtros de la pantalla "Pendientes de envío". */
export interface FiltroOperaciones {
  estado?: EstadoOperacion | null;
  tipo?: TipoOperacion | null;
  sucursalId?: number | null;
  /** Fechas locales (AAAA-MM-DD), inclusivas. */
  desde?: string | null;
  hasta?: string | null;
  /** Busca en el código local y en el nombre del cliente. */
  texto?: string | null;
}

/** Un intento de envío de una operación (para diagnóstico). */
export interface ResultadoSync {
  id?: number;
  empresa_id: number;
  operacion_id: string;
  fecha: string;
  http_status: number | null;
  motivo: string | null;
  respuesta: unknown;
}

/** Todo lo de referencia de una empresa que se reemplaza JUNTO (una sola transacción). */
export interface PaqueteLocal {
  empresa: { id: number; codigo: string; nombre: string };
  /** `generado_en` del servidor (el del catálogo): desde cuándo están al día estos datos. */
  generadoEn: string;
  avisoDesactualizadoHoras: number;
  sucursales: SucursalPaquete[];
  categorias: CategoriaPaquete[];
  tallas: TallaPaquete[];
  colores: ColorPaquete[];
  productos: ProductoPaquete[];
  /** Stock por sucursal (cada elemento es el paquete de UNA sucursal ya completo). */
  stock: { sucursalId: number; generadoEn: string; items: StockPaquete[] }[];
  clientes: ClientePaquete[];
  /** Reglas del servidor (métodos de pago offline, tamaño máximo de lote...). */
  reglas: PaqueteManifiesto['reglas'];
}

/** Un producto con lo que se necesita para mostrarlo en una lista. */
export interface ProductoLocal extends FilaProducto {
  categoria: string | null;
  variantes: VarianteLocal[];
}

export interface VarianteLocal extends FilaVariante {
  talla: string | null;
  color: string | null;
  color_hex: string | null;
  /** Stock conocido por sucursal (`sucursal_id` -> unidades). */
  stock: Record<number, number>;
}
