class VarianteCatalogo {
  const VarianteCatalogo({
    required this.id,
    required this.tallaId,
    required this.colorId,
    required this.sku,
    required this.precioEfectivo,
    required this.cantidadDisponible,
  });

  factory VarianteCatalogo.fromJson(Map<String, dynamic> json) {
    return VarianteCatalogo(
      id: json['id'] as int,
      tallaId: json['talla_id'] as int,
      colorId: json['color_id'] as int,
      sku: json['sku'] as String,
      precioEfectivo: double.parse(json['precio_efectivo'].toString()),
      cantidadDisponible: json['cantidad_disponible'] as int?,
    );
  }

  final int id;
  final int tallaId;
  final int colorId;
  final String sku;
  final double precioEfectivo;
  // El backend la resuelve con inventario (CU-09) en
  // catalogo/casos_uso/cu06_consultar_buscar_catalogo.py::_disponibilidad_variante.
  final int? cantidadDisponible;
}

class ImagenProducto {
  const ImagenProducto({
    required this.id,
    required this.url,
    required this.colorId,
    required this.esPrincipal,
    required this.orden,
  });

  factory ImagenProducto.fromJson(Map<String, dynamic> json) {
    return ImagenProducto(
      id: json['id'] as int,
      url: json['url'] as String,
      colorId: json['color_id'] as int?,
      esPrincipal: json['es_principal'] as bool,
      orden: json['orden'] as int,
    );
  }

  final int id;
  final String url;
  final int? colorId;
  final bool esPrincipal;
  final int orden;
}

class CatalogoDetalle {
  const CatalogoDetalle({
    required this.id,
    required this.codigo,
    required this.nombre,
    required this.descripcion,
    required this.categoriaId,
    required this.materialId,
    required this.temporadaId,
    required this.coleccionId,
    required this.genero,
    required this.precioBase,
    required this.admiteProbador,
    required this.variantes,
    required this.imagenes,
  });

  factory CatalogoDetalle.fromJson(Map<String, dynamic> json) {
    return CatalogoDetalle(
      id: json['id'] as int,
      codigo: json['codigo'] as String,
      nombre: json['nombre'] as String,
      descripcion: json['descripcion'] as String?,
      categoriaId: json['categoria_id'] as int,
      materialId: json['material_id'] as int?,
      temporadaId: json['temporada_id'] as int?,
      coleccionId: json['coleccion_id'] as int?,
      genero: json['genero'] as String,
      precioBase: double.parse(json['precio_base'].toString()),
      admiteProbador: json['admite_probador'] as bool,
      variantes: (json['variantes'] as List)
          .map((v) => VarianteCatalogo.fromJson(v as Map<String, dynamic>))
          .toList(),
      imagenes: (json['imagenes'] as List)
          .map((i) => ImagenProducto.fromJson(i as Map<String, dynamic>))
          .toList(),
    );
  }

  final int id;
  final String codigo;
  final String nombre;
  final String? descripcion;
  final int categoriaId;
  final int? materialId;
  final int? temporadaId;
  final int? coleccionId;
  final String genero;
  final double precioBase;
  final bool admiteProbador;
  final List<VarianteCatalogo> variantes;
  final List<ImagenProducto> imagenes;
}
