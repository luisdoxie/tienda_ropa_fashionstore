import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/main.dart';

import 'helpers/token_storage_falso.dart';

void main() {
  testWidgets('sin sesión guardada, la app termina en el catálogo (invitado)', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [tokenStorageProvider.overrideWithValue(TokenStorageFalso())],
        child: const FashionStoreApp(),
      ),
    );

    // No hay token guardado, así que restaurarSesion() resuelve a "no
    // autenticado" y el router redirige de /splash a /home: el catálogo es
    // público para invitados (ver app_router.dart). El splash se queda 3 s a
    // propósito para que se vea el logo; se espera ese tiempo y luego la
    // transición. No se usa pumpAndSettle porque el spinner del splash anima
    // indefinidamente.
    await tester.pump(const Duration(seconds: 3));
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }

    expect(find.byTooltip('Probador virtual'), findsOneWidget);
  });
}
