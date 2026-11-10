import 'package:mobile/features/catalogo/models/catalogo_detalle.dart';
import 'package:mobile/features/catalogo/models/catalogo_item.dart';
import 'package:mobile/features/cliente_offline/data/cache_catalogo_cliente.dart';
import 'package:mobile/features/cliente_offline/models/stock_guardado.dart';

/// Doble de [CacheCatalogoCliente] en memoria, sin SQLite: para las pruebas de pantallas que no necesitan la base real.
/// Solo el stock por sucursal es configurable; lo demás está vacío y lo que se "guarda" se descarta.
class CacheCatalogoFalso implements CacheCatalogoCliente {
  CacheCatalogoFalso({this.stock = const {}});

  /// Lo que "se vio" por variante.
  final Map<int, StockGuardado> stock;

  @override
  Future<Map<int, StockGuardado>> leerDisponibilidades(Iterable<int> varianteIds) async => {
    for (final id in varianteIds)
      if (stock[id] != null) id: stock[id]!,
  };

  @override
  Future<void> guardarDisponibilidad(int varianteId, List<Map<String, dynamic>> crudos) async {}

  @override
  Future<void> guardarItems(List<Map<String, dynamic>> crudos, {int? primeraPosicion}) async {}

  @override
  Future<List<CatalogoItem>> leerItems({String? texto}) async => [];

  @override
  Future<void> guardarDetalle(int productoId, Map<String, dynamic> crudo) async {}

  @override
  Future<CatalogoDetalle?> leerDetalle(int productoId) async => null;

  @override
  Future<void> guardarReferencias(String tipo, List<Map<String, dynamic>> crudos) async {}

  @override
  Future<List<Map<String, dynamic>>> leerReferencias(String tipo) async => [];

  @override
  Future<void> guardarRecomendaciones(List<Map<String, dynamic>> crudos) async {}

  @override
  Future<List<Map<String, dynamic>>> leerRecomendaciones() async => [];
}
