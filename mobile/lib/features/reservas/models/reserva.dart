import '../../../core/utils/fecha_servidor.dart';

class ReservaDetalle {
  const ReservaDetalle({
    required this.id,
    required this.varianteId,
    required this.cantidad,
    required this.seleccionada,
    required this.preparada,
  });

  factory ReservaDetalle.fromJson(Map<String, dynamic> json) => ReservaDetalle(
    id: json['id'] as int,
    varianteId: json['variante_id'] as int,
    cantidad: json['cantidad'] as int,
    seleccionada: json['seleccionada'] as bool?,
    preparada: json['preparada'] as bool,
  );

  final int id;
  final int varianteId;
  final int cantidad;
  // NULL = aún no probada. TRUE = el cliente la compra. FALSE = se libera.
  final bool? seleccionada;
  final bool preparada;
}

class ReservaHistorialItem {
  const ReservaHistorialItem({required this.id, required this.estado, required this.comentario, required this.creadoEn});

  factory ReservaHistorialItem.fromJson(Map<String, dynamic> json) => ReservaHistorialItem(
    id: json['id'] as int,
    estado: json['estado'] as String,
    comentario: json['comentario'] as String?,
    creadoEn: fechaDelServidor(json['creado_en'] as String),
  );

  final int id;
  final String estado;
  final String? comentario;
  final DateTime creadoEn;
}

class Reserva {
  const Reserva({
    required this.id,
    required this.codigo,
    required this.sucursalId,
    required this.estado,
    required this.fechaVisita,
    required this.horaVisitaDesde,
    required this.horaVisitaHasta,
    required this.fechaExpiracion,
    required this.observacion,
    required this.detalle,
    required this.historial,
  });

  factory Reserva.fromJson(Map<String, dynamic> json) => Reserva(
    id: json['id'] as int,
    codigo: json['codigo'] as String,
    sucursalId: json['sucursal_id'] as int,
    estado: json['estado'] as String,
    fechaVisita: json['fecha_visita'] as String,
    horaVisitaDesde: json['hora_visita_desde'] as String,
    horaVisitaHasta: json['hora_visita_hasta'] as String,
    fechaExpiracion: fechaDelServidor(json['fecha_expiracion'] as String),
    observacion: json['observacion'] as String?,
    detalle: (json['detalle'] as List).map((d) => ReservaDetalle.fromJson(d as Map<String, dynamic>)).toList(),
    historial: (json['historial'] as List)
        .map((h) => ReservaHistorialItem.fromJson(h as Map<String, dynamic>))
        .toList(),
  );

  final int id;
  final String codigo;
  final int sucursalId;
  final String estado;
  final String fechaVisita;
  final String horaVisitaDesde;
  final String horaVisitaHasta;
  final DateTime fechaExpiracion;
  final String? observacion;
  final List<ReservaDetalle> detalle;
  final List<ReservaHistorialItem> historial;

  bool get esCancelable => estado == 'pendiente' || estado == 'preparada';
}

const etiquetasEstadoReserva = {
  'pendiente': 'Pendiente',
  'preparada': 'Preparada',
  'en_prueba': 'En prueba',
  'completada': 'Completada',
  'cancelada': 'Cancelada',
  'expirada': 'Expirada',
};
