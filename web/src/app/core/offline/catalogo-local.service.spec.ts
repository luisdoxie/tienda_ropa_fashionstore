import 'fake-indexeddb/auto';
import { TestBed } from '@angular/core/testing';
import { CatalogoLocalService } from './catalogo-local.service';
import { BaseOffline } from './db-offline';
import type { PaqueteLocal } from './offline.models';
import { RepositorioLocal } from './repositorio-local';
import { SesionOfflineService } from './sesion-offline.service';

let contador = 0;
const crearBase = () => new BaseOffline(`prueba_catalogo_local_${++contador}_${Date.now()}`);

/** Un paquete pequeño pero completo. `marca` distingue a una empresa de otra. */
function paquete(marca: string, extra: Partial<PaqueteLocal> = {}): PaqueteLocal {
  const generadoEn = '2026-10-30T10:00:00Z';
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
        variantes: [{ id: 1100, talla_id: 1, color_id: 1, sku: `${marca}-CHA-M`, codigo_barras: '7770002', precio: '399.5', descuento_unitario: '0.00' }],
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
    ...extra,
  };
}

describe('CatalogoLocalService', () => {
  let db: BaseOffline;
  /** Lo que la sesión entrega: null = sin alcance (sin sesión o superadministrador). */
  let repoDeLaSesion: RepositorioLocal | null;
  let servicio: CatalogoLocalService;

  const repoDe = (empresaId: number, usuarioId = 7) => new RepositorioLocal(db, { empresaId, usuarioId });

  beforeEach(async () => {
    db = crearBase();
    TestBed.configureTestingModule({
      providers: [{ provide: SesionOfflineService, useValue: { repositorio: () => repoDeLaSesion } }],
    });
    servicio = TestBed.inject(CatalogoLocalService);
    // Dos empresas en la MISMA base: la A (1) y la B (2) con datos solapados en nombre, SKU y barras.
    await repoDe(1).reemplazarReferencia(paquete('Alfa'));
    await repoDe(2).reemplazarReferencia(paquete('Beta'));
    repoDeLaSesion = repoDe(1);
  });

  afterEach(() => db.close());

  describe('buscarProductos', () => {
    it('"polera" (sin tildes ni mayúsculas) encuentra "Polera Alfa Estampada" con variantes, tallas, colores y stock', async () => {
      const [polera, ...otros] = await servicio.buscarProductos('POLERA');

      expect(otros).toEqual([]);
      expect(polera.nombre).toBe('Polera Alfa Estampada');
      expect(polera.categoria).toBe('Poleras');
      expect(polera.variantes.map((v) => [v.talla, v.color, v.stock])).toEqual([
        ['M', 'Negro', { 10: 5, 11: 30 }],
        ['L', 'Negro', { 10: 0 }],
      ]);
    });

    it('busca por SKU y por código de barras', async () => {
      expect((await servicio.buscarProductos('alfa-cha-m')).map((p) => p.codigo)).toEqual(['FS-20001']);
      expect((await servicio.buscarProductos('7770001')).map((p) => p.codigo)).toEqual(['FS-10005']);
    });

    it('filtra por categoría y sin texto devuelve todos ordenados por nombre', async () => {
      expect((await servicio.buscarProductos('')).map((p) => p.nombre)).toEqual(['Chamarra Alfa', 'Polera Alfa Estampada']);
      expect((await servicio.buscarProductos('', 2)).map((p) => p.nombre)).toEqual(['Chamarra Alfa']);
      expect((await servicio.buscarProductos('polera', 2)).map((p) => p.nombre)).toEqual([]);
      expect((await servicio.buscarProductos('', null)).length).toBe(2);
    });

    it('no ve nada de otra empresa: ni en productos ni por SKU ni por nombre', async () => {
      const nombres = (await servicio.buscarProductos('')).map((p) => p.nombre);
      expect(nombres.some((n) => n.includes('Beta'))).toBe(false);
      expect(await servicio.buscarProductos('beta-pol-m')).toEqual([]);
      expect(await servicio.buscarProductos('Beta')).toEqual([]);

      // Y desde la otra empresa se ve lo suyo y nada de Alfa.
      repoDeLaSesion = repoDe(2);
      expect((await servicio.buscarProductos('')).map((p) => p.nombre)).toEqual(['Chamarra Beta', 'Polera Beta Estampada']);
      expect(await servicio.buscarProductos('Alfa')).toEqual([]);
    });
  });

  describe('buscarVariantes (la búsqueda de Caja)', () => {
    it('por nombre sin tildes devuelve una fila por variante con la forma de VarianteBusqueda', async () => {
      const filas = await servicio.buscarVariantes('polera');

      expect(filas).toEqual([
        {
          variante_id: 1000,
          producto_id: 100,
          producto_nombre: 'Polera Alfa Estampada',
          producto_codigo: 'FS-10005',
          talla_codigo: 'M',
          color_nombre: 'Negro',
          sku: 'Alfa-POL-M',
          codigo_barras: '7770001',
          precio_efectivo: 149,
          descuento_unitario: 0,
        },
        {
          variante_id: 1001,
          producto_id: 100,
          producto_nombre: 'Polera Alfa Estampada',
          producto_codigo: 'FS-10005',
          talla_codigo: 'L',
          color_nombre: 'Negro',
          sku: 'Alfa-POL-L',
          codigo_barras: null,
          precio_efectivo: 149,
          descuento_unitario: 14.9,
        },
      ]);
    });

    it('por SKU o por código de barras devuelve SOLO esa variante (no todas las del producto)', async () => {
      expect((await servicio.buscarVariantes('ALFA-POL-L')).map((v) => v.variante_id)).toEqual([1001]);
      expect((await servicio.buscarVariantes('7770001')).map((v) => v.variante_id)).toEqual([1000]);
    });

    it('el código de barras es exacto: un pedazo no encuentra nada', async () => {
      expect(await servicio.buscarVariantes('77700')).toEqual([]);
    });

    it('por código de producto devuelve todas sus variantes', async () => {
      expect((await servicio.buscarVariantes('fs-10005')).map((v) => v.variante_id)).toEqual([1000, 1001]);
    });

    it('el precio llega como texto decimal y sale como número de 2 decimales', async () => {
      const [chamarra] = await servicio.buscarVariantes('chamarra');
      expect(chamarra.precio_efectivo).toBe(399.5);
      expect(typeof chamarra.precio_efectivo).toBe('number');
    });

    it('redondea a 2 decimales un precio con más (sin errores de coma flotante)', async () => {
      await repoDe(1).reemplazarReferencia(
        paquete('Alfa', {
          productos: [
            {
              id: 100,
              codigo: 'FS-1',
              nombre: 'Polera Redonda',
              categoria_id: 1,
              genero: 'hombre',
              temporada_id: null,
              imagen_principal: null,
              variantes: [{ id: 1, talla_id: 1, color_id: 1, sku: 'RED-1', codigo_barras: null, precio: '10.005', descuento_unitario: '0.1' }],
            },
          ],
        }),
      );

      const [fila] = await servicio.buscarVariantes('redonda');
      expect(fila.precio_efectivo).toBe(10.01);
      expect(fila.descuento_unitario).toBe(0.1);
    });

    it('una variante con precio que no es número no se ofrece (no se vende en cero)', async () => {
      await repoDe(1).reemplazarReferencia(
        paquete('Alfa', {
          productos: [
            {
              id: 100,
              codigo: 'FS-1',
              nombre: 'Polera Rota',
              categoria_id: 1,
              genero: 'hombre',
              temporada_id: null,
              imagen_principal: null,
              variantes: [
                { id: 1, talla_id: 1, color_id: 1, sku: 'ROTA-1', codigo_barras: null, precio: 'abc', descuento_unitario: '0.00' },
                { id: 2, talla_id: 2, color_id: 1, sku: 'ROTA-2', codigo_barras: null, precio: '80.00', descuento_unitario: '0.00' },
              ],
            },
          ],
        }),
      );

      expect((await servicio.buscarVariantes('rota')).map((v) => v.variante_id)).toEqual([2]);
    });

    it('un texto vacío no devuelve el catálogo entero', async () => {
      expect(await servicio.buscarVariantes('')).toEqual([]);
      expect(await servicio.buscarVariantes('   ')).toEqual([]);
    });

    it('otra empresa no se ve: el SKU de la B no aparece en la A', async () => {
      expect(await servicio.buscarVariantes('BETA-POL-M')).toEqual([]);
      expect(await servicio.buscarVariantes('beta')).toEqual([]);
    });
  });

  describe('stock, clientes, categorías y sucursales', () => {
    it('stockPorSucursal devuelve las unidades conocidas por sucursal', async () => {
      expect(await servicio.stockPorSucursal(1000)).toEqual({ 10: 5, 11: 30 });
      expect(await servicio.stockPorSucursal(1001)).toEqual({ 10: 0 });
      expect(await servicio.stockPorSucursal(999999)).toEqual({});
    });

    it('clientes busca por nombre sin tildes y por CI/NIT', async () => {
      expect((await servicio.clientes('maria')).map((c) => c.id)).toEqual([1]);
      expect((await servicio.clientes('1234567')).map((c) => c.id)).toEqual([1]);
      expect((await servicio.clientes('')).map((c) => c.id)).toEqual([2, 1]);
    });

    it('categorías y sucursales son las de la empresa de la sesión', async () => {
      expect((await servicio.categorias()).map((c) => c.nombre).sort()).toEqual(['Chamarras', 'Poleras']);
      expect((await servicio.sucursales()).map((s) => s.nombre).sort()).toEqual(['Alfa Centro', 'Alfa Depósito']);
      repoDeLaSesion = repoDe(2);
      expect((await servicio.sucursales()).map((s) => s.nombre).sort()).toEqual(['Beta Centro', 'Beta Depósito']);
    });
  });

  describe('sin alcance (sin sesión o superadministrador)', () => {
    beforeEach(() => (repoDeLaSesion = null));

    it('todas las consultas devuelven vacío y ninguna lanza', async () => {
      await expect(servicio.buscarProductos('polera')).resolves.toEqual([]);
      await expect(servicio.buscarVariantes('polera')).resolves.toEqual([]);
      await expect(servicio.variantesDeProducto(100)).resolves.toEqual([]);
      await expect(servicio.stockPorSucursal(1000)).resolves.toEqual({});
      await expect(servicio.clientes('maria')).resolves.toEqual([]);
      await expect(servicio.categorias()).resolves.toEqual([]);
      await expect(servicio.sucursales()).resolves.toEqual([]);
    });
  });

  it('variantesDeProducto devuelve las variantes del producto y vacío si no existe', async () => {
    expect((await servicio.variantesDeProducto(100)).map((v) => v.id)).toEqual([1000, 1001]);
    expect(await servicio.variantesDeProducto(555)).toEqual([]);
  });
});
