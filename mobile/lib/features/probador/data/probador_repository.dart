import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:path_provider/path_provider.dart';

import '../models/activo_probador.dart';
import '../models/generacion_probador.dart';

class ProbadorRepository {
  ProbadorRepository(this._dio);

  final Dio _dio;

  Future<AssetsVariante> obtenerAssets(int varianteId) async {
    final r = await _dio.get<Map<String, dynamic>>('/probador/variante/$varianteId/assets');
    return AssetsVariante.fromJson(r.data!);
  }

  /// Bytes del PNG del overlay, con caché en disco por `public_id`: si ya
  /// se descargó antes (mismo activo validado, no cambió), no se vuelve a
  /// pedir a Cloudinary. Si un admin re-sube el overlay, `public_id`
  /// cambia y la caché vieja queda simplemente sin usar.
  Future<Uint8List> obtenerImagenOverlay(ActivoProbador activo) async {
    final archivo = await _archivoCache(activo.publicId);
    if (await archivo.exists()) {
      return archivo.readAsBytes();
    }
    final r = await _dio.get<List<int>>(activo.url, options: Options(responseType: ResponseType.bytes));
    final bytes = Uint8List.fromList(r.data!);
    await archivo.writeAsBytes(bytes);
    return bytes;
  }

  Future<File> _archivoCache(String publicId) async {
    final dir = await getTemporaryDirectory();
    final carpeta = Directory('${dir.path}/probador');
    if (!await carpeta.exists()) {
      await carpeta.create(recursive: true);
    }
    final nombre = publicId.replaceAll('/', '_');
    return File('${carpeta.path}/$nombre.png');
  }

  Future<void> registrarSesion({required int varianteId, required String modo, int? duracionSeg}) {
    return _dio.post<void>(
      '/probador/sesion',
      data: {'variante_id': varianteId, 'modo': modo, 'duracion_seg': ?duracionSeg},
    );
  }

  /// POST /probador/generar. Una sola imagen por pedido; el backend nunca
  /// persiste la foto original (ver P4.3), solo su hash.
  Future<GeneracionEstado> iniciarGeneracion({
    required int varianteId,
    required Uint8List fotoBytes,
    required String nombreArchivo,
    required DioMediaType contentType,
  }) async {
    final formData = FormData.fromMap({
      'variante_id': varianteId,
      'archivo': MultipartFile.fromBytes(fotoBytes, filename: nombreArchivo, contentType: contentType),
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
