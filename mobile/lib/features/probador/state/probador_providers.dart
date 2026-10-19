import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/mensaje_error.dart';
import '../../../core/network/providers.dart';
import '../../catalogo/state/catalogo_providers.dart';
import '../data/probador_repository.dart';
import '../models/activo_probador.dart';

final probadorRepositoryProvider = Provider<ProbadorRepository>(
  (ref) => ProbadorRepository(ref.watch(dioProvider)),
);

class PrendaProbador {
  const PrendaProbador({
    required this.varianteId,
    required this.productoId,
    required this.nombre,
    required this.assets,
  });

  final int varianteId;
  final int productoId;
  final String nombre;
  final AssetsVariante assets;
}

/// Recorre el catálogo buscando productos que admiten probador Y que ya
/// tienen un overlay validado: `admite_probador` es a nivel de producto,
/// pero el asset se sube por variante, así que no todo lo que admite
/// probador tiene ya la imagen lista. Lo que sí tiene se usa para llenar
/// el selector horizontal de la pantalla del probador.
final prendasProbadorProvider = FutureProvider<List<PrendaProbador>>((ref) async {
  final catalogoRepo = ref.watch(catalogoRepositoryProvider);
  final probadorRepo = ref.watch(probadorRepositoryProvider);

  final items = await catalogoRepo.listar(pagina: 1, tamanio: 50);
  final candidatos = items.where((i) => i.admiteProbador);

  // Un detalle() + un obtenerAssets() por candidato, EN PARALELO: antes iban
  // uno detrás de otro en un for, así que con 10 candidatos eran ~20
  // round-trips secuenciales a Railway antes de que este provider
  // resolviera -- justo lo que alimenta el selector de "otras prendas",
  // no la prenda que el cliente ya eligió (ver prendaProbadorPorVarianteProvider).
  final resultados = await Future.wait(
    candidatos.map((item) async {
      try {
        final detalle = await catalogoRepo.detalle(item.id);
        if (detalle.variantes.isEmpty) return null;
        final varianteId = detalle.variantes.first.id;
        final assets = await probadorRepo.obtenerAssets(varianteId);
        return PrendaProbador(varianteId: varianteId, productoId: item.id, nombre: item.nombre, assets: assets);
      } catch (_) {
        // Sin overlay validado todavía para esta variante: no aparece en el selector.
        return null;
      }
    }),
  );
  return resultados.whereType<PrendaProbador>().toList();
});

/// Los assets del probador de una variante, o null si todavía no tiene un overlay validado (el backend responde 404).
/// Los botones "Probar" del detalle y del carrito la usan para decidir si se muestran. Cualquier otro error (red,
/// sesión) se propaga: el botón simplemente no aparece.
final assetsProbadorProvider = FutureProvider.autoDispose.family<AssetsVariante?, int>((ref, varianteId) async {
  try {
    return await ref.watch(probadorRepositoryProvider).obtenerAssets(varianteId);
  } catch (e) {
    if (esNoEncontrado(e)) return null;
    rethrow;
  }
});

/// La prenda de una variante concreta lista para el probador (nombre incluido), o null si no tiene overlay validado.
final prendaProbadorPorVarianteProvider = FutureProvider.autoDispose.family<PrendaProbador?, int>((
  ref,
  varianteId,
) async {
  // Los dos pedidos no dependen entre sí: arrancan juntos (no uno después
  // del otro) para que la prenda que el cliente ya eligió se vea lo antes
  // posible al entrar al probador.
  final futureAssets = ref.watch(assetsProbadorProvider(varianteId).future);
  final futureDatos = ref.watch(catalogoRepositoryProvider).detallePorVariantes([varianteId]);
  final assets = await futureAssets;
  if (assets == null) return null;
  final datos = await futureDatos;
  if (datos.isEmpty) return null;
  return PrendaProbador(
    varianteId: varianteId,
    productoId: datos.first.productoId,
    nombre: datos.first.productoNombre,
    assets: assets,
  );
});

/// La lista que muestra el probador. Con [varianteInicial] (la prenda que el cliente acaba de elegir en el detalle o
/// en el carrito) esa prenda va primera -y por eso el probador abre con ella puesta- y se quitan las demás variantes
/// de su mismo producto para no repetirlo. Sin inicial, o si esa variante no tiene overlay, es la lista de siempre.
final prendasParaProbadorProvider = FutureProvider.autoDispose.family<List<PrendaProbador>, int?>((
  ref,
  varianteInicial,
) async {
  // futureBase arranca ya mismo: antes se esperaba primero TODA la lista
  // base (el N+1 de prendasProbadorProvider) para recién después pedir la
  // prenda inicial, cuando en realidad son independientes. Este provider
  // sigue tardando lo que tarde la lista completa (la usa el selector de
  // "otras prendas"), pero eso ya no bloquea nada más: ver
  // prendaProbadorPorVarianteProvider, que la pantalla también observa por
  // separado para mostrar la prenda elegida sin esperar acá.
  final futureBase = ref.watch(prendasProbadorProvider.future);
  if (varianteInicial == null) return futureBase;

  PrendaProbador? inicial;
  try {
    inicial = await ref.watch(prendaProbadorPorVarianteProvider(varianteInicial).future);
  } catch (_) {
    // Sin red o sin sesión para resolver la inicial: el probador abre con su lista habitual.
    return futureBase;
  }
  final base = await futureBase;
  if (inicial == null) return base;
  final elegida = inicial;
  return [elegida, ...base.where((p) => p.productoId != elegida.productoId)];
});
