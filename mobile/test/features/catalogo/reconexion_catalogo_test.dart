import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/conectividad/reconexiones.dart';
import 'package:mobile/features/catalogo/data/catalogo_repository.dart';
import 'package:mobile/features/catalogo/models/catalogo_item.dart';
import 'package:mobile/features/catalogo/state/catalogo_controller.dart';
import 'package:mobile/features/catalogo/state/catalogo_providers.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/conectividad_falsa.dart';

CatalogoItem _item(int id) => CatalogoItem(
  id: id,
  codigo: 'P$id',
  nombre: 'Prenda $id',
  categoriaId: 1,
  genero: 'unisex',
  precioBase: 100,
  admiteProbador: false,
  imagenPrincipal: null,
);

/// Un catálogo que, mientras [sinRed] sea cierto, solo conoce lo "guardado" (las primeras [guardadas] prendas) y, con
/// red, sirve las [enServidor] prendas.
class _CatalogoFalso extends CatalogoRepository {
  _CatalogoFalso({required this.guardadas, required this.enServidor}) : super(ApiClientFalso());

  final int guardadas;
  final int enServidor;
  bool sinRed = false;
  bool falla = false;

  @override
  Future<List<CatalogoItem>> listar({required int pagina, required int tamanio}) async {
    if (falla) throw Exception('servidor caído');
    final total = sinRed ? guardadas : enServidor;
    final desde = (pagina - 1) * tamanio;
    if (desde >= total) return const [];
    final hasta = desde + tamanio > total ? total : desde + tamanio;
    return [for (var i = desde + 1; i <= hasta; i++) _item(i)];
  }
}

ProviderContainer _contenedor(ConectividadFalsa conectividad, _CatalogoFalso repositorio) {
  final contenedor = ProviderContainer(
    overrides: [
      conectividadServiceProvider.overrideWithValue(conectividad),
      catalogoRepositoryProvider.overrideWithValue(repositorio),
      tiendaCodigoProvider.overrideWithValue('alpha'),
    ],
  );
  addTearDown(contenedor.dispose);
  return contenedor;
}

void main() {
  group('reconexionesProvider', () {
    test('cuenta cada vez que la conexión vuelve, y solo entonces', () async {
      final conectividad = ConectividadFalsa(enLinea: true);
      final contenedor = _contenedor(conectividad, _CatalogoFalso(guardadas: 0, enServidor: 0));
      contenedor.listen(enLineaProvider, (_, _) {});
      contenedor.listen(reconexionesProvider, (_, _) {});
      await pumpEventQueue();
      expect(contenedor.read(reconexionesProvider), 0);

      conectividad.emitir(false);
      await pumpEventQueue();
      expect(contenedor.read(reconexionesProvider), 0, reason: 'perder la conexión no es reconectar');

      conectividad.emitir(true);
      await pumpEventQueue();
      expect(contenedor.read(reconexionesProvider), 1);

      conectividad.emitir(false);
      conectividad.emitir(true);
      await pumpEventQueue();
      expect(contenedor.read(reconexionesProvider), 2);
    });
  });

  group('CatalogoController - al volver la conexión', () {
    test('pone al día la lista que salió de lo guardado y permite seguir paginando', () async {
      final conectividad = ConectividadFalsa(enLinea: true);
      final repositorio = _CatalogoFalso(guardadas: 20, enServidor: 60)..sinRed = true;
      final contenedor = _contenedor(conectividad, repositorio);
      contenedor.listen(enLineaProvider, (_, _) {});
      contenedor.listen(catalogoControllerProvider, (_, _) {});
      await pumpEventQueue();

      // Abrió sin red: solo lo guardado (una página).
      expect(contenedor.read(catalogoControllerProvider).items, hasLength(20));

      conectividad.emitir(false);
      await pumpEventQueue();
      repositorio.sinRed = false;
      conectividad.emitir(true);
      await pumpEventQueue();

      final estado = contenedor.read(catalogoControllerProvider);
      expect(estado.items.map((i) => i.id), [for (var i = 1; i <= 20; i++) i]);
      expect(estado.hayMas, isTrue);
      expect(estado.cargandoPrimeraPagina, isFalse);
      expect(estado.error, isFalse);
    });

    test('no tapa la lista con el indicador de carga mientras se actualiza', () async {
      final conectividad = ConectividadFalsa(enLinea: true);
      final repositorio = _CatalogoFalso(guardadas: 20, enServidor: 20);
      final contenedor = _contenedor(conectividad, repositorio);
      contenedor.listen(enLineaProvider, (_, _) {});
      final estados = <bool>[];
      contenedor.listen(catalogoControllerProvider, (_, nuevo) => estados.add(nuevo.cargandoPrimeraPagina));
      await pumpEventQueue();
      estados.clear();

      conectividad.emitir(false);
      conectividad.emitir(true);
      await pumpEventQueue();

      expect(estados, isNot(contains(true)));
      expect(contenedor.read(catalogoControllerProvider).items, hasLength(20));
    });

    test('conserva las páginas que ya se habían desplazado y no repite prendas', () async {
      final conectividad = ConectividadFalsa(enLinea: true);
      final repositorio = _CatalogoFalso(guardadas: 60, enServidor: 60);
      final contenedor = _contenedor(conectividad, repositorio);
      contenedor.listen(enLineaProvider, (_, _) {});
      contenedor.listen(catalogoControllerProvider, (_, _) {});
      await pumpEventQueue();
      await contenedor.read(catalogoControllerProvider.notifier).cargarSiguientePagina();
      await contenedor.read(catalogoControllerProvider.notifier).cargarSiguientePagina();
      expect(contenedor.read(catalogoControllerProvider).items, hasLength(60));

      conectividad.emitir(false);
      conectividad.emitir(true);
      await pumpEventQueue();

      final ids = contenedor.read(catalogoControllerProvider).items.map((i) => i.id).toList();
      expect(ids, hasLength(60));
      expect(ids.toSet(), hasLength(60));
    });

    test('si volver a pedir falla, la lista que se veía se queda como estaba', () async {
      final conectividad = ConectividadFalsa(enLinea: true);
      final repositorio = _CatalogoFalso(guardadas: 20, enServidor: 20);
      final contenedor = _contenedor(conectividad, repositorio);
      contenedor.listen(enLineaProvider, (_, _) {});
      contenedor.listen(catalogoControllerProvider, (_, _) {});
      await pumpEventQueue();

      repositorio.falla = true;
      await contenedor.read(catalogoControllerProvider.notifier).actualizarAlVolverConexion();

      final estado = contenedor.read(catalogoControllerProvider);
      expect(estado.items, hasLength(20));
      expect(estado.error, isFalse);
    });
  });
}
