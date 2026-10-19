import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/pago.dart';
import 'compras_providers.dart';

class EstadoPagoEstado {
  const EstadoPagoEstado({required this.pago, required this.intentos, required this.agotado});

  final AsyncValue<Pago> pago;
  final int intentos;
  // Se agotó el polling sin que la pasarela confirme -- pasa siempre con
  // Libélula en este entorno (es un simulador sin servidor real detrás,
  // ver backend/app/comercial/pasarela.py). No es un error: hay que mostrar "pendiente"
  // con opción de reintentar, nunca dejar la pantalla colgada.
  final bool agotado;
}

/// Polling de GET /pagos/{id}/estado, independiente de si el WebView de la
/// pasarela llega a navegar a la URL de retorno o no -- es la fuente de
/// verdad del estado del pago (ver estado_pago_screen.dart).
class EstadoPagoController extends StateNotifier<EstadoPagoEstado> {
  EstadoPagoController(this._ref, this._pagoId)
    : super(const EstadoPagoEstado(pago: AsyncValue.loading(), intentos: 0, agotado: false)) {
    _consultar();
  }

  static const _maxIntentos = 20;
  static const _intervalo = Duration(seconds: 3);

  final Ref _ref;
  final int _pagoId;
  Timer? _timer;

  Future<void> _consultar() async {
    try {
      final pago = await _ref.read(pagosRepositoryProvider).estado(_pagoId);
      if (!mounted) return;
      state = EstadoPagoEstado(pago: AsyncValue.data(pago), intentos: state.intentos + 1, agotado: false);
      if (pago.aprobado || pago.rechazado) {
        _timer?.cancel();
        return;
      }
    } catch (error, stackTrace) {
      if (!mounted) return;
      state = EstadoPagoEstado(pago: AsyncValue.error(error, stackTrace), intentos: state.intentos + 1, agotado: false);
    }

    if (!mounted) return;
    if (state.intentos >= _maxIntentos) {
      state = EstadoPagoEstado(pago: state.pago, intentos: state.intentos, agotado: true);
      _timer?.cancel();
      return;
    }
    _timer = Timer(_intervalo, _consultar);
  }

  /// La pantalla lo llama cuando el WebView detecta la navegación de
  /// retorno de la pasarela (o falla al cargar): no hace falta esperar el
  /// próximo tick del polling.
  void consultarAhora() {
    _timer?.cancel();
    _consultar();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}

final estadoPagoControllerProvider =
    StateNotifierProvider.family.autoDispose<EstadoPagoController, EstadoPagoEstado, int>(
      (ref, pagoId) => EstadoPagoController(ref, pagoId),
    );
