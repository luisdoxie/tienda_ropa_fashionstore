import '../../../core/utils/fecha_servidor.dart';

class Envio {
  const Envio({
    required this.id,
    required this.ventaId,
    required this.direccionId,
    required this.zonaEnvioId,
    required this.costo,
    required this.estado,
    this.repartidor,
    this.fechaEntrega,
  });

  factory Envio.fromJson(Map<String, dynamic> json) => Envio(
    id: json['id'] as int,
    ventaId: json['venta_id'] as int,
    direccionId: json['direccion_id'] as int,
    zonaEnvioId: json['zona_envio_id'] as int,
    costo: double.parse(json['costo'].toString()),
    estado: json['estado'] as String,
    repartidor: json['repartidor'] as String?,
    fechaEntrega: json['fecha_entrega'] is String ? fechaDelServidor(json['fecha_entrega'] as String) : null,
  );

  final int id;
  final int ventaId;
  final int direccionId;
  final int zonaEnvioId;
  final double costo;

  /// programado | en_ruta | entregado | fallido
  final String estado;
  final String? repartidor;
  final DateTime? fechaEntrega;
}

const etiquetasEstadoEnvio = {
  'programado': 'Programado',
  'en_ruta': 'En camino',
  'entregado': 'Entregado',
  'fallido': 'No se pudo entregar',
};
