/** Constantes del modo sin conexión (E14). Un solo lugar para ajustarlas. */

/** Nombre de la base IndexedDB (una por navegador y origen; las filas se separan por empresa y usuario). */
export const NOMBRE_BASE_OFFLINE = 'fashionstore_offline';

/**
 * Pasadas estas horas desde la última descarga se avisa "información desactualizada". Es el valor por defecto: si el
 * servidor manda `aviso_desactualizado_horas` en el paquete, manda ese.
 */
export const UMBRAL_DESACTUALIZADO_HORAS = 12;

/** Tamaño de página al pedir el catálogo y los clientes (el servidor admite hasta 500 y 1000). */
export const PAGINA_CATALOGO = 200;
export const PAGINA_CLIENTES = 500;
export const PAGINA_STOCK = 500;

/** Tope de páginas por descarga: corta un bucle si el servidor nunca dijera "última página". */
export const MAX_PAGINAS_DESCARGA = 200;

/** Cuántos resultados devuelve una búsqueda local. */
export const LIMITE_BUSQUEDA_LOCAL = 100;

/** Claves de la tabla `meta`. */
export const META_ULTIMA_DESCARGA = 'ultima_descarga';
export const META_EMPRESA = 'empresa';
export const META_UMBRAL_HORAS = 'umbral_horas';
export const META_REGLAS = 'reglas';
export const META_SUCURSALES_STOCK = 'sucursales_con_stock';
/** `perfil:<usuario_id>`: el usuario (roles y permisos) para reabrir la app sin red. */
export const metaPerfil = (usuarioId: number): string => `perfil:${usuarioId}`;

/** `caja_sucursal:<usuario_id>`: la sucursal donde cobra esa persona, para reabrir Caja sin red. */
export const metaSucursalCaja = (usuarioId: number): string => `caja_sucursal:${usuarioId}`;

/** localStorage: identificador estable de este equipo (se manda en cada lote para diagnóstico). */
export const CLAVE_DISPOSITIVO = 'fs_dispositivo_id';
/** localStorage: la última empresa que usó este equipo (si cambia, se borra el catálogo de la anterior). */
export const CLAVE_ULTIMA_EMPRESA = 'fs_offline_ultima_empresa';

// ---- Cola de sincronización (E14b) ---------------------------------------------------------------------------------------

/** Máximo de operaciones por lote (el real es el menor entre este y el `max_operaciones_por_lote` del servidor). */
export const TAM_LOTE = 20;
/** Primera espera tras un fallo; después se duplica (5 s, 10 s, 20 s...) hasta `BACKOFF_TOPE_MS`. */
export const BACKOFF_BASE_MS = 5_000;
export const BACKOFF_TOPE_MS = 300_000;
/** Fallos seguidos tras los cuales la cola deja de reintentar sola ("Reintenta manualmente"). */
export const INTENTOS_AUTOMATICOS_MAX = 8;
/** Una operación `enviada` con más de este tiempo es huérfana (un cierre brusco la dejó a medias) y se reenvía. */
export const HUERFANA_ENVIADA_MS = 120_000;
/** Cada cuánto revisa la cola, con la pestaña abierta y con red. */
export const INTERVALO_COLA_MS = 60_000;
/** Cuánto espera la respuesta de un lote antes de darlo por perdido (las operaciones vuelven a la cola). */
export const TIMEOUT_LOTE_MS = 30_000;
/** Cada cuánto pregunta al servidor por las operaciones en conflicto cuando el ciclo no envió nada. */
export const INTERVALO_CONSULTA_CONFLICTOS_MS = 120_000;
