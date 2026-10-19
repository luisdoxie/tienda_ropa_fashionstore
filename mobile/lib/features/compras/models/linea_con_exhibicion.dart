/// Una línea del carrito o del comprobante: el backend solo conoce `variante_id`, así que nombre, foto, talla y color
/// se resuelven aparte (ver `aplicarExhibicion` en compras_providers.dart) y se vuelcan en una copia de la línea.
abstract interface class LineaConExhibicion<L> {
  int get varianteId;

  L conExhibicion({
    required String? productoNombre,
    required String? imagenPrincipal,
    required String? tallaCodigo,
    required String? colorNombre,
  });
}
