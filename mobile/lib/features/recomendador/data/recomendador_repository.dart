import 'package:dio/dio.dart';
import '../models/recomendacion_item.dart';

class RecomendadorRepository {
  RecomendadorRepository(this._dio);

  final Dio _dio;

  Future<List<RecomendacionItem>> obtenerRecomendaciones({int? excluirProductoId}) async {
    final respuesta = await _dio.post<Map<String, dynamic>>(
      '/ia/recomendaciones',
      queryParameters: {'excluir_producto_id': ?excluirProductoId},
    );
    final filas = respuesta.data!['recomendaciones'] as List<dynamic>;
    return filas.map((e) => RecomendacionItem.fromJson(e as Map<String, dynamic>)).toList();
  }
}
