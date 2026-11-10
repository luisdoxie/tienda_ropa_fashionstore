/// Migraciones de la base local del cliente: versión destino → sentencias que la construyen a partir de la anterior.
///
/// Una versión nueva se AGREGA aquí (y se sube `versionEsquemaCliente`); jamás se edita el DDL de `esquema_cliente.dart`.
/// Las migraciones no pueden borrar pedidos sin enviar: un pedido en cola es una compra que la persona ya aceptó.
///
/// - Versión 1: se crea completa en `onCreate`.
/// - Versión 2: `cli_cache` admite el tipo `recomendaciones` (el carrusel "Para vos" del inicio). SQLite no permite
///   cambiar un CHECK, así que la tabla se reconstruye copiando TODAS sus filas (prendas, detalles y referencias ya
///   guardados se conservan). Las demás tablas, y con ellas los pedidos sin enviar, no se tocan.
/// - Versión 3: `cli_cache` admite el tipo `disponibilidad` (el stock por sucursal de la última vez que se vio una variante
///   con conexión). Misma reconstrucción que la versión 2: se copian TODAS las filas y no se tocan las demás tablas.
const Map<int, List<String>> migracionesCliente = {
  2: [
    'ALTER TABLE cli_cache RENAME TO cli_cache_v1',
    '''
CREATE TABLE cli_cache (
  tienda TEXT NOT NULL,
  tipo TEXT NOT NULL CHECK (tipo IN ('item', 'detalle', 'talla', 'color', 'sucursal', 'recomendaciones')),
  clave TEXT NOT NULL,
  orden INTEGER,
  json TEXT NOT NULL,
  guardado_en TEXT NOT NULL,
  PRIMARY KEY (tienda, tipo, clave)
)''',
    'INSERT INTO cli_cache (tienda, tipo, clave, orden, json, guardado_en) '
        'SELECT tienda, tipo, clave, orden, json, guardado_en FROM cli_cache_v1',
    // Al borrar la tabla vieja se va también su índice (que conservaba el nombre): recién entonces se crea el nuevo.
    'DROP TABLE cli_cache_v1',
    'CREATE INDEX ix_cli_cache_orden ON cli_cache (tienda, tipo, orden)',
  ],
  3: [
    'ALTER TABLE cli_cache RENAME TO cli_cache_v2',
    '''
CREATE TABLE cli_cache (
  tienda TEXT NOT NULL,
  tipo TEXT NOT NULL CHECK (tipo IN ('item', 'detalle', 'talla', 'color', 'sucursal', 'recomendaciones', 'disponibilidad')),
  clave TEXT NOT NULL,
  orden INTEGER,
  json TEXT NOT NULL,
  guardado_en TEXT NOT NULL,
  PRIMARY KEY (tienda, tipo, clave)
)''',
    'INSERT INTO cli_cache (tienda, tipo, clave, orden, json, guardado_en) '
        'SELECT tienda, tipo, clave, orden, json, guardado_en FROM cli_cache_v2',
    'DROP TABLE cli_cache_v2',
    'CREATE INDEX ix_cli_cache_orden ON cli_cache (tienda, tipo, orden)',
  ],
};
