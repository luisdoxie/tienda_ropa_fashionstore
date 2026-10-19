import '../../../core/utils/fecha_servidor.dart';

class Pago {
  const Pago({
    required this.id,
    required this.ventaId,
    required this.monto,
    required this.fecha,
    required this.metodoPago,
    required this.estado,
  });

  factory Pago.fromJson(Map<String, dynamic> json) => Pago(
    id: json['id'] as int,
    ventaId: json['venta_id'] as int,
    monto: double.parse(json['monto'].toString()),
    fecha: fechaDelServidor(json['fecha'] as String),
    metodoPago: json['metodo_pago'] as String,
    estado: json['estado'] as String,
  );

  final int id;
  final int ventaId;
  final double monto;
  final DateTime fecha;
  final String metodoPago;
  final String estado;

  bool get aprobado => estado == 'aprobado';
  bool get rechazado => estado == 'rechazado';
  bool get pendiente => estado == 'iniciado';
}

/// POST /pagos/iniciar: junto con el pago recién creado, la URL a la que
/// hay que llevar al cliente para completar el pago en la pasarela.
class PagoIniciado {
  const PagoIniciado({required this.pago, required this.urlRedireccion});

  factory PagoIniciado.fromJson(Map<String, dynamic> json) =>
      PagoIniciado(pago: Pago.fromJson(json['pago'] as Map<String, dynamic>), urlRedireccion: json['url_redireccion'] as String);

  final Pago pago;
  final String urlRedireccion;
}
