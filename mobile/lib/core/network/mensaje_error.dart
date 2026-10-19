import 'package:dio/dio.dart';

/// El `detail` que manda el backend (p. ej. "Solo quedan 2 unidades
/// disponibles") si lo hay; si no, el mensaje genérico de quien llama.
String mensajeDeError(Object error, String porDefecto) {
  if (error is DioException) {
    final data = error.response?.data;
    final detalle = data is Map ? data['detail'] : null;
    if (detalle is String && detalle.isNotEmpty) return detalle;
  }
  return porDefecto;
}

bool esConflicto(Object error) => error is DioException && error.response?.statusCode == 409;

/// El backend respondió 404 (p. ej. una variante sin assets del probador).
bool esNoEncontrado(Object error) => error is DioException && error.response?.statusCode == 404;

/// No se pudo hablar con el servidor: sin conexión o timeout (conexión, envío o respuesta).
bool esSinConexion(Object error) {
  if (error is! DioException) return false;
  switch (error.type) {
    case DioExceptionType.connectionError:
    case DioExceptionType.connectionTimeout:
    case DioExceptionType.sendTimeout:
    case DioExceptionType.receiveTimeout:
      return true;
    default:
      return false;
  }
}

/// El backend respondió con un error 5xx.
bool esErrorDeServidor(Object error) {
  final estado = error is DioException ? error.response?.statusCode : null;
  return estado != null && estado >= 500;
}
