import 'fake-indexeddb/auto';
import { BaseOffline } from './db-offline';
import { META_ULTIMA_DESCARGA } from './offline.config';
import type { PaqueteLocal } from './offline.models';
import { RepositorioLocal } from './repositorio-local';

let contador = 0;
const crearBase = () => new BaseOffline(`prueba_offline_repo_${++contador}_${Date.now()}`);

/** Un paquete pequeño pero completo. `marca` distingue a una empresa de otra. */
function paquete(marca: string, generadoEn = '2026-10-30T10:00:00Z'): PaqueteLocal {
  return {
    empresa: { id: 1, codigo: marca.toLowerCase(), nombre: marca },
    generadoEn,
    avisoDesactualizadoHoras: 12,
    sucursales: [
      { id: 10, codigo: 'SC-CENTRO', nombre: `${marca} Centro`, direccion: 'Calle 1', es_deposito: false, horarios: [] },
      { id: 11, codigo: 'SC-DEPOSITO', nombre: `${marca} Depósito`, direccion: 'Calle 2', es_deposito: true, horarios: [] },
    ],
    categorias: [
      { id: 1, nombre: 'Poleras', categoria_padre_id: null },
      { id: 2, nombre: 'Chamarras', categoria_padre_id: null },
    ],
    tallas: [
      { id: 1, codigo: 'M', orden: 2 },
      { id: 2, codigo: 'L', orden: 3 },
    ],
    colores: [{ id: 1, nombre: 'Negro', codigo_hex: '#000000' }],
    productos: [
      {
        id: 100,
        codigo: 'FS-10005',
        nombre: `Polera ${marca} Estampada`,
        categoria_id: 1,
        genero: 'hombre',
        temporada_id: null,
        imagen_principal: null,
        variantes: [
          { id: 1000, talla_id: 1, color_id: 1, sku: `${marca}-POL-M`, codigo_barras: '7770001', precio: '149.00', descuento_unitario: '0.00' },
          { id: 1001, talla_id: 2, color_id: 1, sku: `${marca}-POL-L`, codigo_barras: null, precio: '149.00', descuento_unitario: '14.90' },
        ],
      },
      {
        id: 101,
        codigo: 'FS-20001',
        nombre: `Chamarra ${marca}`,
        categoria_id: 2,
        genero: 'unisex',
        temporada_id: null,
        imagen_principal: null,
        variantes: [{ id: 1100, talla_id: 1, color_id: 1, sku: `${marca}-CHA-M`, codigo_barras: '7770002', precio: '399.00', descuento_unitario: '0.00' }],
      },
    ],
    stock: [
      {
        sucursalId: 10,
        generadoEn,
        items: [
          { variante_id: 1000, cantidad_disponible: 5, actualizado_en: generadoEn },
          { variante_id: 1001, cantidad_disponible: 0, actualizado_en: generadoEn },
        ],
      },
      { sucursalId: 11, generadoEn, items: [{ variante_id: 1000, cantidad_disponible: 30, actualizado_en: generadoEn }] },
    ],
    clientes: [
      { id: 1, nombre: 'María', apellido: 'Pérez', ci_nit: '1234567' },
      { id: 2, nombre: 'José', apellido: 'Gómez', ci_nit: null },
    ],
    reglas: {
      metodos_pago_offline: ['efectivo'],
      max_operaciones_por_lote: 50,
      plazo_cambio_horas: 24,
      cambios_y_devoluciones: 'solo_en_linea',
      reservas_offline: 'permitidas',
    },
  };
}

describe('RepositorioLocal', () => {
  it('se construye solo con una empresa y un usuario válidos', () => {
    const db = crearBase();
    expect(() => new RepositorioLocal(db, { empresaId: undefined as unknown as number, usuarioId: 1 })).toThrow();
    expect(() => new RepositorioLocal(db, { empresaId: 1, usuarioId: null as unknown as number })).toThrow();
    db.close();
  });

  it('guarda el paquete y lo devuelve con tallas, colores y stock por sucursal', async () => {
    const db = crearBase();
    const repo = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });

    await repo.reemplazarReferencia(paquete('Alfa'));
    const productos = await repo.buscarProductos();

    expect(productos.map((p) => p.nombre)).toEqual(['Chamarra Alfa', 'Polera Alfa Estampada']);
    const polera = productos.find((p) => p.codigo === 'FS-10005')!;
    expect(polera.categoria).toBe('Poleras');
    expect(polera.variantes.map((v) => [v.talla, v.color, v.stock])).toEqual([
      ['M', 'Negro', { 10: 5, 11: 30 }],
      ['L', 'Negro', { 10: 0 }],
    ]);
    expect(await repo.ultimaDescarga()).toBe('2026-10-30T10:00:00Z');
    expect(await repo.umbralHoras()).toBe(12);
    expect(await repo.hayCatalogo()).toBe(true);
    db.close();
  });

  it('busca por nombre sin tildes ni mayúsculas, por código, por SKU y por código de barras', async () => {
    const db = crearBase();
    const repo = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
    await repo.reemplazarReferencia(paquete('Alfa'));

    expect((await repo.buscarProductos('POLERA')).map((p) => p.codigo)).toEqual(['FS-10005']);
    expect((await repo.buscarProductos('chámarra')).map((p) => p.codigo)).toEqual(['FS-20001']);
    expect((await repo.buscarProductos('fs-2000')).map((p) => p.codigo)).toEqual(['FS-20001']);
    expect((await repo.buscarProductos('alfa-pol-l')).map((p) => p.codigo)).toEqual(['FS-10005']);
    expect((await repo.buscarProductos('7770002')).map((p) => p.codigo)).toEqual(['FS-20001']);
    expect(await repo.buscarProductos('sombrero')).toEqual([]);
    db.close();
  });

  it('filtra por categoría y respeta el límite', async () => {
    const db = crearBase();
    const repo = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
    await repo.reemplazarReferencia(paquete('Alfa'));

    expect((await repo.buscarProductos('', 2)).map((p) => p.codigo)).toEqual(['FS-20001']);
    expect(await repo.buscarProductos('', null, 1)).toHaveLength(1);
    db.close();
  });

  it('busca clientes sin tildes por nombre o por CI/NIT', async () => {
    const db = crearBase();
    const repo = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
    await repo.reemplazarReferencia(paquete('Alfa'));

    expect((await repo.clientes('maria')).map((c) => c.id)).toEqual([1]);
    expect((await repo.clientes('gomez')).map((c) => c.id)).toEqual([2]);
    expect((await repo.clientes('1234')).map((c) => c.id)).toEqual([1]);
    db.close();
  });

  it('NO MEZCLA: los datos de la empresa A no aparecen con el alcance de la empresa B', async () => {
    const db = crearBase();
    const a = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
    const b = new RepositorioLocal(db, { empresaId: 2, usuarioId: 8 });
    await a.reemplazarReferencia(paquete('Alfa'));
    await b.reemplazarReferencia(paquete('Beta', '2026-10-30T11:00:00Z'));

    expect((await a.buscarProductos()).every((p) => p.nombre.includes('Alfa'))).toBe(true);
    expect((await b.buscarProductos()).every((p) => p.nombre.includes('Beta'))).toBe(true);
    expect(await a.buscarProductos('beta')).toEqual([]);
    expect((await a.sucursales()).every((s) => s.nombre.startsWith('Alfa'))).toBe(true);
    expect(await a.ultimaDescarga()).toBe('2026-10-30T10:00:00Z');
    expect(await b.ultimaDescarga()).toBe('2026-10-30T11:00:00Z');
    expect(await a.stockDeVariante(1000)).toEqual({ 10: 5, 11: 30 });

    // Reemplazar los datos de B NO borra los de A.
    await b.vaciarReferencia();
    expect(await b.hayCatalogo()).toBe(false);
    expect(await a.hayCatalogo()).toBe(true);
    db.close();
  });

  it('el perfil guardado es de cada usuario y de su empresa', async () => {
    const db = crearBase();
    const uno = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
    const otro = new RepositorioLocal(db, { empresaId: 1, usuarioId: 8 });
    const ajeno = new RepositorioLocal(db, { empresaId: 2, usuarioId: 7 });
    await uno.guardarPerfil({ id: 7, email: 'cajero@a.bo' });

    expect(await uno.perfilGuardado()).toEqual({ id: 7, email: 'cajero@a.bo' });
    expect(await otro.perfilGuardado()).toBeUndefined();
    expect(await ajeno.perfilGuardado()).toBeUndefined();
    await uno.borrarPerfil();
    expect(await uno.perfilGuardado()).toBeUndefined();
    db.close();
  });

  it('reemplaza de forma ATÓMICA: si la escritura falla a la mitad, queda el paquete anterior', async () => {
    const db = crearBase();
    const repo = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
    await repo.reemplazarReferencia(paquete('Alfa'));

    const roto = paquete('Nuevo', '2026-10-31T10:00:00Z');
    // Un cliente con un nombre que no se puede normalizar rompe el armado; para romper la ESCRITURA, un producto con
    // una variante cuyo id es inválido como clave de IndexedDB.
    roto.productos[0].variantes[0].id = undefined as unknown as number;

    await expect(repo.reemplazarReferencia(roto)).rejects.toBeDefined();

    expect((await repo.buscarProductos()).map((p) => p.nombre)).toEqual(['Chamarra Alfa', 'Polera Alfa Estampada']);
    expect(await repo.ultimaDescarga()).toBe('2026-10-30T10:00:00Z');
    expect((await repo.clientes()).length).toBe(2);
    db.close();
  });

  it('un paquete nuevo reemplaza al anterior sin dejar filas viejas', async () => {
    const db = crearBase();
    const repo = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
    await repo.reemplazarReferencia(paquete('Alfa'));
    const nuevo = paquete('Alfa', '2026-10-31T09:00:00Z');
    nuevo.productos = nuevo.productos.slice(0, 1);
    nuevo.clientes = [];

    await repo.reemplazarReferencia(nuevo);

    expect((await repo.buscarProductos()).map((p) => p.codigo)).toEqual(['FS-10005']);
    expect(await repo.clientes()).toEqual([]);
    expect(await repo.ultimaDescarga()).toBe('2026-10-31T09:00:00Z');
    expect(await db.meta.get([1, META_ULTIMA_DESCARGA])).toBeDefined();
    db.close();
  });

  it('vaciar la referencia no toca las operaciones del equipo', async () => {
    const db = crearBase();
    const repo = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
    await repo.reemplazarReferencia(paquete('Alfa'));
    await db.operaciones_pendientes.put({
      empresa_id: 1,
      usuario_id: 7,
      operacion_id: 'op-1',
      tipo: 'venta_contado',
      estado: 'registrada',
      fecha_operacion: '2026-10-30T10:00:00-04:00',
    });

    await repo.vaciarReferencia();
    await repo.vaciarClientes();

    expect(await db.operaciones_pendientes.count()).toBe(1);
    db.close();
  });

  it('no expone ninguna forma de borrar operaciones (D13): ver también repositorio-operaciones.spec.ts', () => {
    const metodos = Object.getOwnPropertyNames(RepositorioLocal.prototype);
    expect(metodos.filter((m) => /(borrar|eliminar|remove|delete).*(operacion|intento)|(operacion|intento).*(borrar|eliminar|remove|delete)/i.test(m))).toEqual([]);
  });
});
