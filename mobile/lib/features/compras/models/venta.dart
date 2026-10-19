import '../../../core/utils/fecha_servidor.dart';
import 'linea_con_exhibicion.dart';

/// Línea de una venta (comprobante/historial), más los campos de
/// exhibición resueltos aparte -- mismo motivo que CarritoLinea: el
/// backend solo conoce variante_id.
class VentaLinea implements LineaConExhibicion<VentaLinea> {
  const VentaLinea({
    required this.id,
    required this.varianteId,
    required this.cantidad,
    required this.precioUnitario,
    required this.subtotal,
    this.productoNombre,
    this.imagenPrincipal,
    this.tallaCodigo,
    this.colorNombre,
  });

  factory VentaLinea.fromJson(Map<String, dynamic> json) => VentaLinea(
    id: json['id'] as int,
    varianteId: json['variante_id'] as int,
    cantidad: json['cantidad'] as int,
    precioUnitario: double.parse(json['precio_unitario'].toString()),
    subtotal: double.parse(json['subtotal'].toString()),
  );

  final int id;
  @override
  final int varianteId;
  final int cantidad;
  final double precioUnitario;
  final double subtotal;
  final String? productoNombre;
  final String? imagenPrincipal;
  final String? tallaCodigo;
  final String? colorNombre;

  @override
  VentaLinea conExhibicion({
    required String? productoNombre,
    required String? imagenPrincipal,
    required String? tallaCodigo,
    required String? colorNombre,
  }) {
    return VentaLinea(
      id: id,
      varianteId: varianteId,
      cantidad: cantidad,
      precioUnitario: precioUnitario,
      subtotal: subtotal,
      productoNombre: productoNombre,
      imagenPrincipal: imagenPrincipal,
      tallaCodigo: tallaCodigo,
      colorNombre: colorNombre,
    );
  }
}

class Venta {
  const Venta({
    required this.id,
    required this.codigo,
    required this.estado,
    required this.fecha,
    required this.subtotal,
    required this.descuento,
    required this.costoEnvio,
    required this.total,
    required this.detalle,
  });

  factory Venta.fromJson(Map<String, dynamic> json) => Venta(
    id: json['id'] as int,
    codigo: json['codigo'] as String,
    estado: json['estado'] as String,
    fecha: fechaDelServidor(json['fecha'] as String),
    subtotal: double.parse(json['subtotal'].toString()),
    descuento: double.parse(json['descuento'].toString()),
    costoEnvio: double.parse(json['costo_envio'].toString()),
    total: double.parse(json['total'].toString()),
    detalle: (json['detalle'] as List).map((d) => VentaLinea.fromJson(d as Map<String, dynamic>)).toList(),
  );

  final int id;
  final String codigo;
  final String estado;
  final DateTime fecha;
  final double subtotal;
  final double descuento;
  final double costoEnvio;
  final double total;
  final List<VentaLinea> detalle;

  bool get esEnvioADomicilio => costoEnvio > 0;

  Venta conDetalle(List<VentaLinea> nuevoDetalle) => Venta(
    id: id,
    codigo: codigo,
    estado: estado,
    fecha: fecha,
    subtotal: subtotal,
    descuento: descuento,
    costoEnvio: costoEnvio,
    total: total,
    detalle: nuevoDetalle,
  );
}

const etiquetasEstadoVenta = {
  'pendiente_pago': 'Pendiente de pago',
  'pagada': 'Pagada',
  'entregada': 'Entregada',
  'anulada': 'Anulada',
};
