import Dexie, { type Table } from 'dexie';
import { NOMBRE_BASE_OFFLINE } from './offline.config';
import type {
  FilaCategoria,
  FilaCliente,
  FilaColor,
  FilaMeta,
  FilaProducto,
  FilaStock,
  FilaSucursal,
  FilaTalla,
  FilaVariante,
  OperacionLocal,
  ResultadoSync,
} from './offline.models';

/**
 * La base IndexedDB del modo sin conexión. Una sola, versionada. TODA fila lleva `empresa_id` (y las de operaciones,
 * además, `usuario_id`) y todos los índices empiezan por él: así ninguna consulta puede tocar datos de otra empresa sin
 * haberlo pedido. Solo `RepositorioLocal` usa esta clase; ningún componente recibe una tabla.
 *
 * Para cambiar el esquema: agregar `this.version(2).stores({...}).upgrade(...)` DEBAJO de la versión 1 (nunca editarla).
 */
export class BaseOffline extends Dexie {
  meta!: Table<FilaMeta, [number, string]>;
  sucursales!: Table<FilaSucursal, [number, number]>;
  categorias!: Table<FilaCategoria, [number, number]>;
  tallas!: Table<FilaTalla, [number, number]>;
  colores!: Table<FilaColor, [number, number]>;
  productos!: Table<FilaProducto, [number, number]>;
  variantes!: Table<FilaVariante, [number, number]>;
  stock_conocido!: Table<FilaStock, [number, number, number]>;
  clientes_minimos!: Table<FilaCliente, [number, number]>;
  operaciones_pendientes!: Table<OperacionLocal, [number, string]>;
  resultados_sync!: Table<ResultadoSync, number>;

  constructor(nombre: string = NOMBRE_BASE_OFFLINE) {
    super(nombre);
    this.version(1).stores({
      meta: '[empresa_id+clave]',
      sucursales: '[empresa_id+id]',
      categorias: '[empresa_id+id]',
      tallas: '[empresa_id+id]',
      colores: '[empresa_id+id]',
      productos: '[empresa_id+id], [empresa_id+categoria_id], [empresa_id+nombre_norm], [empresa_id+codigo]',
      variantes: '[empresa_id+id], [empresa_id+producto_id], [empresa_id+sku], [empresa_id+codigo_barras]',
      stock_conocido: '[empresa_id+variante_id+sucursal_id], [empresa_id+sucursal_id]',
      clientes_minimos: '[empresa_id+id], [empresa_id+nombre_norm], [empresa_id+ci_nit]',
      // Guarda TODAS las operaciones del equipo, también las confirmadas (D13: nunca se borran por enviarse).
      operaciones_pendientes:
        '[empresa_id+operacion_id], [empresa_id+usuario_id+estado], [empresa_id+usuario_id+fecha_operacion]',
      // Un registro por intento de envío.
      resultados_sync: '++id, [empresa_id+operacion_id]',
    });
  }
}
