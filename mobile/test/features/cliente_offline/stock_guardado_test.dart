import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/catalogo/models/referencia.dart';
import 'package:mobile/features/cliente_offline/models/stock_guardado.dart';

import '../../helpers/cliente_offline_apoyo.dart';

final _antes = DateTime.utc(2026, 11, 6, 10);
final _despues = DateTime.utc(2026, 11, 6, 14);

StockGuardado _stock(Map<int, int> porSucursal, [DateTime? vistoEn]) =>
    StockGuardado(porSucursal: porSucursal, vistoEn: vistoEn ?? _antes);

const _centro = SucursalRef(id: 1, codigo: 'C', nombre: 'Centro');
const _sur = SucursalRef(id: 2, codigo: 'S', nombre: 'Sur');

void main() {
  group('stockDeSucursal', () {
    test('con stock de todas las prendas en la cantidad pedida: conStock', () {
      final r = stockDeSucursal(
        1,
        [lineaCarrito(varianteId: 10, cantidad: 2), lineaCarrito(varianteId: 11)],
        {
          10: _stock({1: 2}),
          11: _stock({1: 9}),
        },
      );

      expect(r.estado, EstadoStockSucursal.conStock);
    });

    test('una prenda con menos unidades de las pedidas: sinStock', () {
      final r = stockDeSucursal(1, [lineaCarrito(varianteId: 10, cantidad: 3)], {
        10: _stock({1: 2}),
      });

      expect(r.estado, EstadoStockSucursal.sinStock);
    });

    test('una sucursal que no aparece en lo guardado cuenta como 0', () {
      final r = stockDeSucursal(7, [lineaCarrito(varianteId: 10)], {
        10: _stock({1: 5}),
      });

      expect(r.estado, EstadoStockSucursal.sinStock);
    });

    test('si falta ver una prenda: sinDatos', () {
      final r = stockDeSucursal(1, [lineaCarrito(varianteId: 10), lineaCarrito(varianteId: 11)], {
        10: _stock({1: 5}),
      });

      expect(r.estado, EstadoStockSucursal.sinDatos);
    });

    test('si una prenda ya no alcanza, es sinStock aunque de otra falten datos', () {
      final r = stockDeSucursal(1, [lineaCarrito(varianteId: 10), lineaCarrito(varianteId: 11)], {
        10: _stock({1: 0}),
      });

      expect(r.estado, EstadoStockSucursal.sinStock, reason: 'ya es seguro que no alcanza');
    });

    test('el dato más viejo es el que se informa', () {
      final r = stockDeSucursal(1, [lineaCarrito(varianteId: 10), lineaCarrito(varianteId: 11)], {
        10: _stock({1: 5}, _despues),
        11: _stock({1: 5}, _antes),
      });

      expect(r.vistoEn, _antes);
    });

    test('sin prendas o sin nada guardado: sinDatos y sin fecha', () {
      expect(stockDeSucursal(1, const [], const {}).estado, EstadoStockSucursal.sinDatos);
      final r = stockDeSucursal(1, [lineaCarrito(varianteId: 10)], const {});
      expect(r.estado, EstadoStockSucursal.sinDatos);
      expect(r.vistoEn, isNull);
    });
  });

  group('sucursalUnicaConStock', () {
    final lineas = [lineaCarrito(varianteId: 10), lineaCarrito(varianteId: 11)];

    test('la única con todo', () {
      final id = sucursalUnicaConStock(
        const [_centro, _sur],
        lineas,
        {
          10: _stock({1: 0, 2: 3}),
          11: _stock({1: 4, 2: 1}),
        },
      );

      expect(id, 2);
    });

    test('varias con todo: ninguna', () {
      final id = sucursalUnicaConStock(
        const [_centro, _sur],
        lineas,
        {
          10: _stock({1: 3, 2: 3}),
          11: _stock({1: 3, 2: 3}),
        },
      );

      expect(id, isNull);
    });

    test('ninguna con todo, o faltan datos: ninguna', () {
      expect(
        sucursalUnicaConStock(const [_centro, _sur], lineas, {
          10: _stock({1: 3}),
          11: _stock({2: 3}),
        }),
        isNull,
      );
      expect(sucursalUnicaConStock(const [_centro, _sur], lineas, const {}), isNull);
    });
  });

  group('sucursalUnicaConStockDeVariante', () {
    test('la única con stock', () {
      expect(sucursalUnicaConStockDeVariante(const [_centro, _sur], _stock({1: 0, 2: 2}))?.id, 2);
    });

    test('varias, ninguna o nunca vista: null', () {
      expect(sucursalUnicaConStockDeVariante(const [_centro, _sur], _stock({1: 1, 2: 2})), isNull);
      expect(sucursalUnicaConStockDeVariante(const [_centro, _sur], _stock({1: 0, 2: 0})), isNull);
      expect(sucursalUnicaConStockDeVariante(const [_centro, _sur], null), isNull);
    });
  });
}
