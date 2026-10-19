import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/features/auth/data/auth_repository.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';

import '../../helpers/token_storage_falso.dart';

/// Repositorio sin red: el login guarda tokens en el almacenamiento falso y `/auth/yo` devuelve un usuario con los
/// roles dados (o falla, para simular credenciales inválidas).
class _RepositorioFalso extends AuthRepository {
  _RepositorioFalso(this.roles, this.almacenamiento, {this.falla = false, this.errorAlObtenerUsuario})
    : super(dio: Dio(), tokenStorage: almacenamiento);

  final List<String> roles;
  final TokenStorageFalso almacenamiento;
  final bool falla;

  /// Si se da, `/auth/yo` falla con este error (p. ej. un DioException de red o un 500).
  final Object? errorAlObtenerUsuario;

  @override
  Future<void> login({required String email, required String password}) async {
    if (falla) throw Exception('401');
    await almacenamiento.guardar(accessToken: 'ACCESS', refreshToken: 'REFRESH');
  }

  @override
  Future<Usuario> obtenerUsuarioActual() async {
    if (errorAlObtenerUsuario != null) throw errorAlObtenerUsuario!;
    if (falla) throw Exception('401');
    return Usuario(
      id: 1,
      nombre: 'Prueba',
      apellido: 'Rol',
      email: 'prueba@example.com',
      telefono: null,
      activo: true,
      roles: roles,
      permisos: const [],
    );
  }
}

ProviderContainer _contenedor(
  List<String> roles,
  TokenStorageFalso almacenamiento, {
  bool falla = false,
  Object? errorAlObtenerUsuario,
}) {
  final contenedor = ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(almacenamiento),
      authRepositoryProvider.overrideWithValue(
        _RepositorioFalso(roles, almacenamiento, falla: falla, errorAlObtenerUsuario: errorAlObtenerUsuario),
      ),
    ],
  );
  addTearDown(contenedor.dispose);
  return contenedor;
}

void main() {
  group('AuthController.login - solo clientes', () {
    test('un cliente inicia sesión', () async {
      final almacenamiento = TokenStorageFalso();
      final contenedor = _contenedor(['cliente'], almacenamiento);

      await contenedor.read(authControllerProvider.notifier).login(email: 'a@b.com', password: 'clave12345');

      final estado = contenedor.read(authControllerProvider);
      expect(estado.estaAutenticado, isTrue);
      expect(estado.error, isNull);
      expect(almacenamiento.accessToken, 'ACCESS');
    });

    test('quien tiene el rol cliente y además otro también entra', () async {
      final contenedor = _contenedor(['administrador', 'cliente'], TokenStorageFalso());

      await contenedor.read(authControllerProvider.notifier).login(email: 'a@b.com', password: 'clave12345');

      expect(contenedor.read(authControllerProvider).estaAutenticado, isTrue);
    });

    for (final roles in [
      ['administrador'],
      ['encargado_sucursal'],
      ['cajero'],
      ['proveedor'],
      <String>[],
    ]) {
      test('el personal ($roles) no entra: se cierra la sesión y se explica por qué', () async {
        final almacenamiento = TokenStorageFalso();
        final contenedor = _contenedor(roles, almacenamiento);

        await expectLater(
          contenedor.read(authControllerProvider.notifier).login(email: 'a@b.com', password: 'clave12345'),
          throwsA(isA<AccesoSoloClientesException>()),
        );

        final estado = contenedor.read(authControllerProvider);
        expect(estado.estado, EstadoSesion.noAutenticado);
        expect(estado.usuario, isNull);
        expect(estado.error, mensajeSoloClientes);
        expect(almacenamiento.accessToken, isNull, reason: 'los tokens que guardó el login se limpian');
        expect(almacenamiento.vecesLimpiado, greaterThanOrEqualTo(1));
      });
    }

    test('credenciales inválidas siguen mostrando el mensaje de siempre', () async {
      final contenedor = _contenedor(['cliente'], TokenStorageFalso(), falla: true);

      await expectLater(
        contenedor.read(authControllerProvider.notifier).login(email: 'a@b.com', password: 'mala'),
        throwsA(isA<Exception>()),
      );

      expect(contenedor.read(authControllerProvider).error, 'Email o contraseña incorrectos.');
    });
  });

  group('AuthController.restaurarSesion - solo clientes', () {
    test('restaura la sesión guardada de un cliente', () async {
      final almacenamiento = TokenStorageFalso()..accessToken = 'ACCESS';
      final contenedor = _contenedor(['cliente'], almacenamiento);

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      expect(contenedor.read(authControllerProvider).estaAutenticado, isTrue);
    });

    test('una sesión guardada de personal no se restaura y se limpian los tokens', () async {
      final almacenamiento = TokenStorageFalso()
        ..accessToken = 'ACCESS'
        ..refreshToken = 'REFRESH';
      final contenedor = _contenedor(['encargado_sucursal'], almacenamiento);

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      expect(contenedor.read(authControllerProvider).estado, EstadoSesion.noAutenticado);
      expect(almacenamiento.accessToken, isNull);
      expect(almacenamiento.refreshToken, isNull);
    });

    DioException errorDio(DioExceptionType tipo, {int? estado}) {
      final opciones = RequestOptions(path: '/auth/yo');
      return DioException(
        requestOptions: opciones,
        type: tipo,
        response: estado == null ? null : Response(requestOptions: opciones, statusCode: estado),
      );
    }

    final fallosQueNoInvalidanLaSesion = {
      'sin conexión': errorDio(DioExceptionType.connectionError),
      'timeout': errorDio(DioExceptionType.connectionTimeout),
      'error 500': errorDio(DioExceptionType.badResponse, estado: 500),
    };
    fallosQueNoInvalidanLaSesion.forEach((nombre, error) {
      test('$nombre al verificar la sesión: se conservan los tokens y no se cierra la sesión guardada', () async {
        final almacenamiento = TokenStorageFalso()
          ..accessToken = 'ACCESS'
          ..refreshToken = 'REFRESH';
        final contenedor = _contenedor(['cliente'], almacenamiento, errorAlObtenerUsuario: error);

        await contenedor.read(authControllerProvider.notifier).restaurarSesion();

        expect(contenedor.read(authControllerProvider).estado, EstadoSesion.noAutenticado);
        expect(almacenamiento.accessToken, 'ACCESS');
        expect(almacenamiento.refreshToken, 'REFRESH');
        expect(almacenamiento.vecesLimpiado, 0);
      });
    });

    test('un 401 al verificar la sesión (token inválido) sí limpia los tokens', () async {
      final almacenamiento = TokenStorageFalso()
        ..accessToken = 'ACCESS'
        ..refreshToken = 'REFRESH';
      final contenedor = _contenedor(
        ['cliente'],
        almacenamiento,
        errorAlObtenerUsuario: errorDio(DioExceptionType.badResponse, estado: 401),
      );

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      expect(contenedor.read(authControllerProvider).estado, EstadoSesion.noAutenticado);
      expect(almacenamiento.accessToken, isNull);
      expect(almacenamiento.refreshToken, isNull);
    });
  });
}
