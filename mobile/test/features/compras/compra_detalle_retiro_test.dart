import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/compras/models/venta.dart';
import 'package:mobile/features/compras/presentation/compra_detalle_screen.dart';
import 'package:mobile/features/compras/state/compras_providers.dart';

import '../../helpers/solicitudes_cambio_falsas.dart';

const _retiro = 'Retira en Centro (Av. Uno 123): el martes 10/11, desde las 09:00 hasta las 19:00.';

Venta _venta({String estado = 'pagada', Object? retiro}) => Venta.fromJson({
  'id': 7,
  'codigo': 'V-0007',
  'estado': estado,
  'fecha': '2026-11-04T10:00:00',
  'subtotal': '100.00',
  'descuento': '0.00',
  'costo_envio': '0.00',
  'total': '100.00',
  'detalle': [
    {'id': 1, 'variante_id': 3, 'cantidad': 1, 'precio_unitario': '100.00', 'subtotal': '100.00'},
  ],
  'retiro': ?retiro,
});

Widget _pantalla(Venta venta) => ProviderScope(
  overrides: [
    compraDetalleProvider(7).overrideWith((ref) async => venta),
    plazoCambioProvider(7).overrideWith((ref) async => null),
    envioDeCompraProvider(7).overrideWith((ref) async => null),
    ...solicitudesCambioFalsas(7),
  ],
  child: const MaterialApp(home: CompraDetalleScreen(ventaId: 7)),
);

void main() {
  testWidgets('una compra de retiro pagada dice dónde y desde qué hora pasar, tal como lo arma el servidor', (tester) async {
    await tester.pumpWidget(_pantalla(_venta(retiro: _retiro)));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('retiro-compra')), findsOneWidget);
    expect(find.text(_retiro), findsOneWidget);
  });

  testWidgets('sin horario de retiro (envío, venta en caja o ya entregada) no se dibuja el bloque', (tester) async {
    await tester.pumpWidget(_pantalla(_venta()));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('retiro-compra')), findsNothing);
    expect(find.text('V-0007'), findsOneWidget);
  });

  test('Venta.fromJson lee el retiro y descarta un texto vacío o que no es texto', () {
    expect(_venta(retiro: _retiro).retiro, _retiro);
    expect(_venta(retiro: '   ').retiro, isNull);
    expect(_venta(retiro: 5).retiro, isNull);
    expect(_venta().retiro, isNull);
  });

  test('conDetalle conserva el retiro', () {
    final venta = _venta(retiro: _retiro);

    expect(venta.conDetalle(venta.detalle).retiro, _retiro);
  });
}
