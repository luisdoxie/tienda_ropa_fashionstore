import 'fake-indexeddb/auto';
import Dexie from 'dexie';
import { BaseOffline } from './db-offline';

let contador = 0;
const nombreUnico = () => `prueba_offline_db_${++contador}_${Date.now()}`;

describe('BaseOffline (esquema de IndexedDB)', () => {
  it('crea todos los almacenes del modo sin conexión', async () => {
    const db = new BaseOffline(nombreUnico());
    await db.open();

    expect(db.tables.map((t) => t.name).sort()).toEqual(
      [
        'categorias',
        'clientes_minimos',
        'colores',
        'meta',
        'operaciones_pendientes',
        'productos',
        'resultados_sync',
        'stock_conocido',
        'sucursales',
        'tallas',
        'variantes',
      ].sort(),
    );
    db.close();
  });

  it('todas las claves y todos los índices empiezan por empresa_id (salvo el contador de intentos)', async () => {
    const db = new BaseOffline(nombreUnico());
    await db.open();

    for (const tabla of db.tables) {
      if (tabla.name === 'resultados_sync') {
        expect(tabla.schema.primKey.auto).toBe(true);
        continue;
      }
      expect(tabla.schema.primKey.keyPath, tabla.name).toEqual(expect.arrayContaining(['empresa_id']));
      expect((tabla.schema.primKey.keyPath as string[])[0], tabla.name).toBe('empresa_id');
      for (const indice of tabla.schema.indexes) {
        expect((indice.keyPath as string[])[0], `${tabla.name}.${indice.name}`).toBe('empresa_id');
      }
    }
    db.close();
  });

  it('declara los índices de búsqueda del plan', async () => {
    const db = new BaseOffline(nombreUnico());
    await db.open();

    const indices = (tabla: string) => db.table(tabla).schema.indexes.map((i) => i.name);
    expect(indices('productos')).toEqual(
      expect.arrayContaining(['[empresa_id+categoria_id]', '[empresa_id+nombre_norm]', '[empresa_id+codigo]']),
    );
    expect(indices('variantes')).toEqual(
      expect.arrayContaining(['[empresa_id+producto_id]', '[empresa_id+sku]', '[empresa_id+codigo_barras]']),
    );
    expect(indices('operaciones_pendientes')).toEqual(
      expect.arrayContaining(['[empresa_id+usuario_id+estado]', '[empresa_id+usuario_id+fecha_operacion]']),
    );
    db.close();
  });

  it('abre una base v1 con una operación y la migra a una v2 de ejemplo sin perderla', async () => {
    const nombre = nombreUnico();
    const v1 = new BaseOffline(nombre);
    await v1.operaciones_pendientes.put({
      empresa_id: 1,
      usuario_id: 7,
      operacion_id: 'aaaa-1111',
      tipo: 'venta_contado',
      estado: 'registrada',
      fecha_operacion: '2026-10-30T10:00:00-04:00',
      total: '149.00',
    });
    v1.close();

    // El patrón para el futuro: una versión nueva DEBAJO de la 1 con su `upgrade`. Aquí una de ejemplo.
    class BaseV2 extends Dexie {
      operaciones_pendientes!: Dexie.Table<Record<string, unknown>, [number, string]>;
      constructor() {
        super(nombre);
        this.version(1).stores({
          operaciones_pendientes:
            '[empresa_id+operacion_id], [empresa_id+usuario_id+estado], [empresa_id+usuario_id+fecha_operacion]',
        });
        this.version(2)
          .stores({
            operaciones_pendientes:
              '[empresa_id+operacion_id], [empresa_id+usuario_id+estado], [empresa_id+usuario_id+fecha_operacion], [empresa_id+tipo]',
          })
          .upgrade((tx) =>
            tx
              .table('operaciones_pendientes')
              .toCollection()
              .modify((operacion) => {
                operacion['migrada'] = true;
              }),
          );
      }
    }
    const v2 = new BaseV2();
    const guardada = await v2.operaciones_pendientes.get([1, 'aaaa-1111']);

    expect(guardada).toMatchObject({ operacion_id: 'aaaa-1111', estado: 'registrada', total: '149.00', migrada: true });
    v2.close();
  });
});
