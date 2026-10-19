import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../models/activo_probador.dart';
import '../models/generacion_probador.dart';

class ProbadorRepository {
  ProbadorRepository(this._dio);

  final Dio _dio;

  Future<AssetsVariante> obtenerAssets(int varianteId) async {
    final r = await _dio.get<Map<String, dynamic>>('/probador/variante/$varianteId/assets');
    return AssetsVariante.fromJson(r.data!);
  }

  /// POST /probador/generar. Una sola imagen por pedido; el backend nunca
  /// persiste la foto original (ver P4.3), solo su hash. La foto va siempre como JPEG: así la pantalla no necesita
  /// conocer a Dio.
  Future<GeneracionEstado> iniciarGeneracion({
    required int varianteId,
    required Uint8List fotoBytes,
    required String nombreArchivo,
  }) async {
    final formData = FormData.fromMap({
      'variante_id': varianteId,
      'archivo': MultipartFile.fromBytes(
        fotoBytes,
        filename: nombreArchivo,
        contentType: DioMediaType('image', 'jpeg'),
      ),
    });
    final r = await _dio.post<Map<String, dynamic>>('/probador/generar', data: formData);
    return GeneracionEstado.fromJson(r.data!);
  }

  Future<GeneracionEstado> consultarGeneracion(int id) async {
    final r = await _dio.get<Map<String, dynamic>>('/probador/generar/$id');
    return GeneracionEstado.fromJson(r.data!);
  }

  /// Descarga genérica de bytes desde una URL absoluta (el resultado
  /// generado, en Cloudinary): sin caché, cada generación es una imagen
  /// distinta.
  Future<Uint8List> descargarBytes(String url) async {
    final r = await _dio.get<List<int>>(url, options: Options(responseType: ResponseType.bytes));
    return Uint8List.fromList(r.data!);
  }
}
