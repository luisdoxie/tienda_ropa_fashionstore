import 'dart:io' as io;

import 'package:file/file.dart' hide FileSystem;
import 'package:file/local.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:path_provider/path_provider.dart';

/// Dónde se guardan las fotos de las prendas para verlas sin conexión. Es la carpeta de DATOS de la app, no la de
/// "caché" del sistema: Android no la vacía cuando le falta espacio y el botón "Borrar caché" de Ajustes tampoco la toca.
/// Los archivos son los mismos que entrega Cloudinary, sin reducir ni recomprimir: no se pierde calidad.
class ArchivosDuraderos implements FileSystem {
  ArchivosDuraderos(this._nombreCarpeta, {Future<io.Directory> Function()? base})
    : _base = base ?? getApplicationSupportDirectory;

  final String _nombreCarpeta;
  final Future<io.Directory> Function() _base;
  Future<Directory>? _carpeta;

  Future<Directory> _crear() async {
    final raiz = await _base();
    final carpeta = const LocalFileSystem().directory('${raiz.path}${io.Platform.pathSeparator}$_nombreCarpeta');
    await carpeta.create(recursive: true);
    return carpeta;
  }

  @override
  Future<File> createFile(String name) async {
    var carpeta = await (_carpeta ??= _crear());
    // Si la carpeta desapareció (se borraron los datos a mano), se vuelve a crear en vez de fallar.
    if (!await carpeta.exists()) {
      _carpeta = _crear();
      carpeta = await _carpeta!;
    }
    return carpeta.childFile(name);
  }
}

/// Nombre de la carpeta y de la base de metadatos de la caché de fotos.
const claveCacheFotos = 'fashionstore_fotos';

/// Cuántas fotos se recuerdan como máximo (se descartan las menos usadas) y por cuánto tiempo sin renovarse.
const maxFotosEnCache = 1500;
const vigenciaFotosEnCache = Duration(days: 90);

/// La caché de fotos de TODA la app (catálogo, carrusel, detalle, carrito, compras): lo que se baja en una pantalla se ve
/// en las demás, con o sin conexión. Se crea la primera vez que se usa, no al arrancar.
class CacheFotos extends CacheManager {
  CacheFotos._()
    : super(
        Config(
          claveCacheFotos,
          stalePeriod: vigenciaFotosEnCache,
          maxNrOfCacheObjects: maxFotosEnCache,
          fileSystem: ArchivosDuraderos(claveCacheFotos),
        ),
      );

  static final CacheFotos instancia = CacheFotos._();
}
