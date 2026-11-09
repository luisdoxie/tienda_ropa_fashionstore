import '../../../core/network/api_client.dart';
import '../../catalogo/data/catalogo_repository.dart' show esFalloDeRedOServidor;
import '../../cliente_offline/config/cliente_offline_config.dart';
import '../../cliente_offline/data/cache_catalogo_cliente.dart';
import '../models/recomendacion_item.dart';

class RecomendadorRepository {
  /// [invitado]: sin sesión se usa la ruta pública de la tienda elegida (`/public/{codigo}/ia/recomendaciones`); con
  /// sesión, la empresa sale del token.
  ///
  /// Con un [cache], el carrusel del INICIO se recuerda en el teléfono y, sin conexión, se muestra lo recordado. Lo que se
  /// guarda no lleva el motivo personal de cada recomendación (podría contar lo que la persona vio o compró): solo la
  /// prenda y un texto general. Guardar o leer del cache nunca hace fallar la consulta.
  RecomendadorRepository(this._api, {this._invitado = false, this._cache});

  final ApiClient _api;
  final bool _invitado;
  final CacheCatalogoCliente? _cache;

  Future<List<RecomendacionItem>> obtenerRecomendaciones({int? excluirProductoId}) async {
    // Solo el carrusel del inicio se guarda: el del detalle depende de la prenda que se mira.
    final esInicio = excluirProductoId == null;
    List<dynamic> crudas = const [];
    try {
      final respuesta = await _api.postObjeto<List<RecomendacionItem>>(
        '/ia/recomendaciones',
        query: {'excluir_producto_id': ?excluirProductoId},
        desde: (json) {
          crudas = json['recomendaciones'] as List<dynamic>;
          return crudas.map((e) => RecomendacionItem.fromJson(e as Map<String, dynamic>)).toList();
        },
        publica: _invitado,
      );
      if (esInicio) await _guardar(crudas);
      return respuesta;
    } catch (error) {
      if (!esInicio || !esFalloDeRedOServidor(error)) rethrow;
      final guardadas = await _leer();
      if (guardadas.isEmpty) rethrow;
      return guardadas;
    }
  }

  Future<void> _guardar(List<dynamic> crudas) async {
    try {
      final sinMotivoPersonal = [
        for (final c in crudas) {...(c as Map<String, dynamic>), 'motivo': motivoRecomendacionGuardada},
      ];
      await _cache?.guardarRecomendaciones(sinMotivoPersonal);
    } catch (_) {
      // El cache es un extra: si falla, la consulta sigue valiendo.
    }
  }

  Future<List<RecomendacionItem>> _leer() async {
    try {
      final crudas = await _cache?.leerRecomendaciones() ?? const [];
      return [for (final c in crudas) RecomendacionItem.fromJson(c)];
    } catch (_) {
      return const [];
    }
  }
}
