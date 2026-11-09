import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../conectividad/conectividad_service.dart';
import '../conectividad/reconexiones.dart';
import '../imagenes/cache_fotos.dart';
import '../theme/app_theme.dart';

/// La foto de una prenda, con la caché duradera de la app ([CacheFotos]).
///
/// - Sin conexión muestra la foto guardada; si esa foto nunca se bajó, un ícono de "sin conexión" (y no la percha, que
///   significa "esta prenda no tiene foto").
/// - Al volver la conexión reintenta sola las fotos que habían fallado.
/// - [decodificarCompleta] en falso (las tarjetas) decodifica la imagen al ancho que se ve en pantalla: el archivo guardado
///   es el original, así que solo se ahorra memoria. En el detalle se deja completa.
class FotoPrenda extends ConsumerWidget {
  const FotoPrenda({
    required this.url,
    this.fit = BoxFit.cover,
    this.ancho,
    this.alto,
    this.decodificarCompleta = false,
    this.tamanoIcono = 24,
    super.key,
  });

  final String url;
  final BoxFit fit;
  final double? ancho;
  final double? alto;
  final bool decodificarCompleta;
  final double tamanoIcono;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Cambia al volver la conexión: una foto que falló se vuelve a pedir en vez de quedarse con el error.
    final reconexiones = ref.watch(reconexionesProvider);
    final enLinea = ref.watch(enLineaProvider).valueOrNull ?? true;
    final pixeles = MediaQuery.devicePixelRatioOf(context);

    Widget vacio(IconData icono) => Container(
      width: ancho,
      height: alto,
      color: AppColors.fondoAlterno,
      alignment: Alignment.center,
      child: Icon(icono, size: tamanoIcono, color: AppColors.textoTenue),
    );

    return LayoutBuilder(
      builder: (context, restricciones) {
        final anchoVisible = ancho ?? (restricciones.hasBoundedWidth ? restricciones.maxWidth : null);
        final memCacheWidth = decodificarCompleta || anchoVisible == null || !anchoVisible.isFinite
            ? null
            : (anchoVisible * pixeles).ceil();
        return CachedNetworkImage(
          key: ValueKey('$url#$reconexiones'),
          imageUrl: url,
          cacheManager: CacheFotos.instancia,
          width: ancho ?? double.infinity,
          height: alto,
          fit: fit,
          memCacheWidth: memCacheWidth,
          fadeInDuration: const Duration(milliseconds: 150),
          placeholder: (context, _) => Container(color: AppColors.fondoAlterno),
          errorWidget: (context, _, error) => vacio(enLinea ? Icons.checkroom : Icons.cloud_off_outlined),
        );
      },
    );
  }
}
