import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/mensaje_error.dart';

DioException _error(DioExceptionType tipo, {int? estado, Object? cuerpo}) {
  final opciones = RequestOptions(path: '/prueba');
  return DioException(
    requestOptions: opciones,
    type: tipo,
    response: estado == null ? null : Response(requestOptions: opciones, statusCode: estado, data: cuerpo),
  );
}

void main() {
  group('esSinConexion', () {
    for (final tipo in [
      DioExceptionType.connectionError,
      DioExceptionType.connectionTimeout,
      DioExceptionType.sendTimeout,
      DioExceptionType.receiveTimeout,
    ]) {
      test('es verdadero para $tipo', () {
        expect(esSinConexion(_error(tipo)), isTrue);
      });
    }

    test('es falso para una respuesta del backend, una cancelación o un error que no es de Dio', () {
      expect(esSinConexion(_error(DioExceptionType.badResponse, estado: 500)), isFalse);
      expect(esSinConexion(_error(DioExceptionType.cancel)), isFalse);
      expect(esSinConexion(Exception('x')), isFalse);
    });
  });

  group('esNoEncontrado', () {
    test('es verdadero solo con un 404 del backend', () {
      expect(esNoEncontrado(_error(DioExceptionType.badResponse, estado: 404)), isTrue);
      expect(esNoEncontrado(_error(DioExceptionType.badResponse, estado: 409)), isFalse);
      expect(esNoEncontrado(_error(DioExceptionType.connectionError)), isFalse);
      expect(esNoEncontrado(Exception('404')), isFalse);
    });
  });

  group('esErrorDeServidor', () {
    test('es verdadero con 5xx y falso con otros estados o sin respuesta', () {
      expect(esErrorDeServidor(_error(DioExceptionType.badResponse, estado: 500)), isTrue);
      expect(esErrorDeServidor(_error(DioExceptionType.badResponse, estado: 503)), isTrue);
      expect(esErrorDeServidor(_error(DioExceptionType.badResponse, estado: 401)), isFalse);
      expect(esErrorDeServidor(_error(DioExceptionType.connectionError)), isFalse);
      expect(esErrorDeServidor(Exception('500')), isFalse);
    });
  });

  group('esConflicto y mensajeDeError', () {
    test('esConflicto reconoce el 409', () {
      expect(esConflicto(_error(DioExceptionType.badResponse, estado: 409)), isTrue);
      expect(esConflicto(_error(DioExceptionType.badResponse, estado: 404)), isFalse);
    });

    test('mensajeDeError usa el detail del backend y, si no hay, el mensaje por defecto', () {
      final conDetalle = _error(DioExceptionType.badResponse, estado: 400, cuerpo: {'detail': 'Solo quedan 2'});
      expect(mensajeDeError(conDetalle, 'por defecto'), 'Solo quedan 2');
      expect(mensajeDeError(_error(DioExceptionType.connectionError), 'por defecto'), 'por defecto');
      expect(mensajeDeError(Exception('x'), 'por defecto'), 'por defecto');
    });
  });
}
