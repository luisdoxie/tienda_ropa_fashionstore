import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'conectividad_service.dart';

/// Cuenta las veces que la app volvió a tener conexión después de haberla perdido. Quien muestra datos que pudo haber
/// leído del teléfono (el catálogo, el carrusel, una foto que falló) escucha este número y se vuelve a pedir solo, sin
/// que la persona tenga que cerrar la app.
class ReconexionesNotifier extends StateNotifier<int> {
  ReconexionesNotifier(Ref ref) : super(0) {
    ref.listen<AsyncValue<bool>>(enLineaProvider, (anterior, actual) {
      if (anterior?.valueOrNull == false && actual.valueOrNull == true) state++;
    });
  }
}

final reconexionesProvider = StateNotifierProvider<ReconexionesNotifier, int>((ref) => ReconexionesNotifier(ref));
