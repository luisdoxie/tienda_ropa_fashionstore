import '../../../core/network/api_client.dart';
import '../../cliente_offline/data/cache_catalogo_cliente.dart';
import '../models/disponibilidad_sucursal.dart';

class DisponibilidadRepository {
  /// Con un [cache], cada consulta que sale bien deja guardado el stock por sucursal de esa variante, para poder mostrar "lo
  /// último que se vio" cuando no hay conexión. Fallar al guardarlo nunca falla la consulta.
  DisponibilidadRepository(this._api, {this._cache});

  final ApiClient _api;
  final CacheCatalogoCliente? _cache;

  /// Endpoint público de la tienda elegida: no requiere sesión de cliente.
  Future<List<DisponibilidadSucursal>> porVariante(int varianteId) async {
    final crudos = <Map<String, dynamic>>[];
    final lista = await _api.getLista<DisponibilidadSucursal>(
      '/inventario/disponibilidad',
      query: {'variante_id': varianteId},
      desde: (json) {
        crudos.add(json);
        return DisponibilidadSucursal.fromJson(json);
      },
      publica: true,
    );
    try {
      await _cache?.guardarDisponibilidad(varianteId, crudos);
    } catch (_) {
      // Lo recordado es un extra.
    }
    return lista;
  }
}
