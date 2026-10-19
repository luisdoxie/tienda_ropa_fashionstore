import '../../../core/utils/fecha_servidor.dart';

class Favorito {
  const Favorito({
    required this.varianteId,
    required this.productoId,
    required this.nombreProducto,
    required this.sku,
    required this.creadoEn,
  });

  factory Favorito.fromJson(Map<String, dynamic> json) {
    return Favorito(
      varianteId: json['variante_id'] as int,
      productoId: json['producto_id'] as int,
      nombreProducto: json['nombre_producto'] as String,
      sku: json['sku'] as String,
      creadoEn: fechaDelServidor(json['creado_en'] as String),
    );
  }

  final int varianteId;
  final int productoId;
  final String nombreProducto;
  final String sku;
  final DateTime creadoEn;
}
