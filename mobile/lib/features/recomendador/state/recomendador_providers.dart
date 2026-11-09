import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/conectividad/reconexiones.dart';
import '../../../core/network/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../../cliente_offline/state/cliente_offline_providers.dart';
import '../data/recomendador_repository.dart';
import '../models/recomendacion_item.dart';

/// Sin sesión usa la ruta pública de la tienda elegida; con sesión, la empresa sale del token.
final recomendadorRepositoryProvider = Provider<RecomendadorRepository>((ref) {
  final invitado = !ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
  return RecomendadorRepository(
    ref.watch(apiClientProvider),
    invitado: invitado,
    cache: ref.watch(cacheCatalogoClienteProvider),
  );
});

/// Carrusel del home: recomendaciones generales del cliente (o de
/// popularidad, si es anónimo/nuevo).
///
/// Se vuelve a pedir sola cuando la app recupera la conexión (si abrió sin red, el carrusel no se veía hasta cerrar la app).
final recomendacionesHomeProvider = FutureProvider<List<RecomendacionItem>>((ref) {
  ref.watch(reconexionesProvider);
  return ref.watch(recomendadorRepositoryProvider).obtenerRecomendaciones();
});

/// Carrusel del detalle de una prenda: mismas recomendaciones, excluyendo
/// el producto que se está viendo.
final recomendacionesDetalleProvider = FutureProvider.family<List<RecomendacionItem>, int>((ref, productoId) {
  ref.watch(reconexionesProvider);
  return ref.watch(recomendadorRepositoryProvider).obtenerRecomendaciones(excluirProductoId: productoId);
});
