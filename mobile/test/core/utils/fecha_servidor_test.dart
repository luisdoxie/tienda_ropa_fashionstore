import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/utils/fecha_servidor.dart';
import 'package:mobile/features/compras/models/pago.dart';
import 'package:mobile/features/favoritos/models/favorito.dart';
import 'package:mobile/features/reservas/models/reserva.dart';

void main() {
  group('fechaDelServidor', () {
    test('una fecha sin zona se toma como UTC, no como hora local', () {
      expect(fechaDelServidor('2026-09-20T16:52:29').toUtc(), DateTime.utc(2026, 9, 20, 16, 52, 29));
    });

    test('una fecha con Z o con desfase conserva su instante', () {
      expect(fechaDelServidor('2026-09-20T16:52:29Z').toUtc(), DateTime.utc(2026, 9, 20, 16, 52, 29));
      expect(fechaDelServidor('2026-09-20T12:52:29-04:00').toUtc(), DateTime.utc(2026, 9, 20, 16, 52, 29));
    });
  });

  test('formatearFechaHora da dd/MM/yyyy HH:mm con ceros a la izquierda', () {
    expect(formatearFechaHora(DateTime(2026, 3, 5, 7, 4)), '05/03/2026 07:04');
    expect(formatearFechaHora(DateTime(2026, 12, 31, 23, 59)), '31/12/2026 23:59');
  });

  group('los modelos leen las fechas del backend como UTC', () {
    final esperado = DateTime.utc(2026, 9, 20, 16, 52, 29);

    test('Pago', () {
      final pago = Pago.fromJson({
        'id': 1,
        'venta_id': 2,
        'monto': '10.00',
        'fecha': '2026-09-20T16:52:29',
        'metodo_pago': 'paypal',
        'estado': 'aprobado',
      });
      expect(pago.fecha.toUtc(), esperado);
    });

    test('Favorito', () {
      final favorito = Favorito.fromJson({
        'variante_id': 1,
        'producto_id': 2,
        'nombre_producto': 'Polera',
        'sku': 'P-1',
        'creado_en': '2026-09-20T16:52:29',
      });
      expect(favorito.creadoEn.toUtc(), esperado);
    });

    test('ReservaHistorialItem', () {
      final item = ReservaHistorialItem.fromJson({
        'id': 1,
        'estado': 'pendiente',
        'comentario': null,
        'creado_en': '2026-09-20T16:52:29',
      });
      expect(item.creadoEn.toUtc(), esperado);
    });
  });
}
