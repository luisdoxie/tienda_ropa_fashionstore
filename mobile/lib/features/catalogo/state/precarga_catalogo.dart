import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/imagenes/cache_fotos.dart';
import '../../cliente_offline/config/cliente_offline_config.dart';
import '../models/catalogo_item.dart';
import 'catalogo_providers.dart';

/// Las primeras fotos del catálogo se bajan con cualquier red (datos móviles incluidos): así siempre hay algo que ver sin
/// conexión. El resto, solo con Wi‑Fi.
const fotosConCualquierRed = 30;

/// De cuántas prendas se guarda también el detalle (tallas, colores, descripción) y TODAS sus fotos, para abrirlas sin
/// conexión. Son las primeras del listado. Debe ser menor que [maxDetallesEnCache].
const detallesPrecargados = 60;

/// Cuántas fotos se bajan a la vez (no satura la red ni la batería).
const fotosSimultaneas = 3;

/// Tope de lo que una pasada descarga, en bytes (las que ya estaban guardadas no cuentan). Evita llenar el teléfono; lo que
/// quede pendiente se sigue en la próxima pasada.
const maxBytesPorPasada = 150 * 1024 * 1024;

/// Cuántos fallos seguidos pueden ocurrir antes de dejar la pasada (sin red de verdad o servidor de fotos caído).
const fallosSeguidosMax = 5;

const _prendasPorPagina = 50;

/// Lo que dejó una tarea: cuántas fotos se bajaron y cuántos bytes pesaron (las ya guardadas no cuentan).
typedef ResultadoDescarga = ({int fotos, int bytes});

/// Baja POR ADELANTADO lo del catálogo (con la misma calidad que entrega Cloudinary) para verlo sin conexión, aunque la
/// persona nunca se haya desplazado hasta ahí.
///
/// Fase 1: recorre el listado completo (lo que además deja las prendas guardadas en el teléfono, hasta [maxItemsEnCache])
/// y descarga la foto principal de cada una, en orden. Fase 2: de las primeras [maxDetalles] prendas guarda el detalle y
/// todas sus fotos. Se puede repetir sin riesgo: lo que ya está guardado no se vuelve a bajar. Nunca lanza errores: la
/// precarga es un extra.
class PrecargaCatalogo {
  PrecargaCatalogo({
    required this.listarPagina,
    required this.descargar,
    required this.hayConexion,
    required this.esWifi,
    this.detalle,
    this.maxPrendas = maxItemsEnCache,
    this.maxDetalles = detallesPrecargados,
    this.conCualquierRed = fotosConCualquierRed,
    this.simultaneas = fotosSimultaneas,
    this.maxBytes = maxBytesPorPasada,
    this.intervaloMinimo = const Duration(minutes: 10),
    DateTime Function()? ahora,
  }) : _ahora = ahora ?? DateTime.now;

  /// Una página del listado SIN filtros (pagina desde 1).
  final Future<List<CatalogoItem>> Function(int pagina, int tamanio) listarPagina;

  /// Baja la foto y devuelve los bytes que se descargaron (0 si ya estaba guardada).
  final Future<int> Function(String url) descargar;

  /// Pide el detalle de una prenda (lo que además lo deja guardado en el teléfono) y devuelve las URL de todas sus fotos.
  /// Sin esto no hay fase 2.
  final Future<List<String>> Function(int productoId)? detalle;

  final bool Function() hayConexion;
  final Future<bool> Function() esWifi;

  final int maxPrendas;
  final int maxDetalles;
  final int conCualquierRed;
  final int simultaneas;
  final int maxBytes;

  /// Una pasada que terminó completa no se repite antes de este tiempo (abrir y cerrar pantallas, o una red que parpadea,
  /// no deben volver a recorrer todo el catálogo).
  final Duration intervaloMinimo;
  final DateTime Function() _ahora;

  bool _enCurso = false;
  bool _cancelada = false;
  DateTime? _ultimaCompleta;

  bool get enCurso => _enCurso;

  /// Para la pasada en curso (la tienda cambió o se cerró la sesión).
  void cancelar() => _cancelada = true;

  /// Devuelve cuántas fotos se bajaron en esta pasada.
  Future<int> ejecutar() async {
    if (_enCurso) return 0;
    final ultima = _ultimaCompleta;
    if (ultima != null && _ahora().difference(ultima) < intervaloMinimo) return 0;
    _enCurso = true;
    _cancelada = false;
    var fotos = 0;
    try {
      final prendas = <({int id, String url})>[];
      final vistas = <String>{};
      var pagina = 1;
      while (prendas.length < maxPrendas && !_cancelada) {
        if (!hayConexion()) return fotos;
        final items = await listarPagina(pagina, _prendasPorPagina);
        for (final item in items) {
          final url = item.imagenPrincipal;
          if (url != null && prendas.length < maxPrendas && vistas.add(url)) prendas.add((id: item.id, url: url));
        }
        if (items.length < _prendasPorPagina) break;
        pagina++;
      }

      var bytes = 0;
      var fallosSeguidos = 0;

      /// Cortes graves (sin conexión, tope de bytes, fallos seguidos): paran TODA la pasada.
      var detener = false;

      /// Faltó Wi‑Fi para seguir: para solo la fase en curso (el detalle de las primeras prendas sí puede seguir con datos
      /// móviles) y deja la pasada como incompleta, para repetirla cuando haya Wi‑Fi.
      var faltoWifi = false;

      /// Reparte las tareas entre [simultaneas] trabajadores, en orden de posición.
      Future<void> correr(int total, Future<ResultadoDescarga> Function(int posicion) tarea) async {
        var siguiente = 0;
        var sinWifiEnEstaFase = false;
        Future<void> trabajador() async {
          while (!detener && !sinWifiEnEstaFase && !_cancelada) {
            final posicion = siguiente++;
            if (posicion >= total) return;
            if (!hayConexion()) {
              detener = true;
              return;
            }
            // Pasadas las primeras, solo con Wi‑Fi.
            if (posicion >= conCualquierRed && !await esWifi()) {
              sinWifiEnEstaFase = true;
              faltoWifi = true;
              return;
            }
            try {
              final resultado = await tarea(posicion);
              fallosSeguidos = 0;
              fotos += resultado.fotos;
              bytes += resultado.bytes;
              if (bytes >= maxBytes) detener = true;
            } catch (_) {
              fallosSeguidos++;
              if (fallosSeguidos >= fallosSeguidosMax) detener = true;
            }
          }
        }

        await Future.wait([for (var i = 0; i < simultaneas; i++) trabajador()]);
      }

      Future<ResultadoDescarga> bajar(String url) async {
        final nuevos = await descargar(url);
        return nuevos > 0 ? (fotos: 1, bytes: nuevos) : (fotos: 0, bytes: 0);
      }

      // Fase 1: la foto principal de cada prenda.
      await correr(prendas.length, (posicion) => bajar(prendas[posicion].url));

      // Fase 2: el detalle y todas las fotos de las primeras prendas.
      final pedirDetalle = detalle;
      if (pedirDetalle != null && !detener && !_cancelada) {
        final cuantas = prendas.length < maxDetalles ? prendas.length : maxDetalles;
        await correr(cuantas, (posicion) async {
          final urls = await pedirDetalle(prendas[posicion].id);
          var total = (fotos: 0, bytes: 0);
          for (final url in urls) {
            // La principal ya se bajó en la fase 1 y las repetidas de otras prendas, igual.
            if (url == prendas[posicion].url || !vistas.add(url)) continue;
            final resultado = await bajar(url);
            total = (fotos: total.fotos + resultado.fotos, bytes: total.bytes + resultado.bytes);
          }
          return total;
        });
      }
      // Solo cuenta como hecha si nada la detuvo (sin red, falta de Wi‑Fi, tope de bytes, fallos, cancelación).
      if (!detener && !faltoWifi && !_cancelada) _ultimaCompleta = _ahora();
    } catch (_) {
      // La precarga es un extra: cualquier problema simplemente la deja a medias.
    } finally {
      _enCurso = false;
    }
    return fotos;
  }
}

/// Baja una foto con la caché de la app. Devuelve los bytes descargados, o 0 si ya estaba guardada.
Future<int> _descargarConCacheFotos(String url) async {
  final cache = CacheFotos.instancia;
  final guardada = await cache.getFileFromCache(url);
  if (guardada != null && guardada.validTill.isAfter(DateTime.now())) return 0;
  final info = await cache.downloadFile(url);
  return info.file.length();
}

Future<bool> _hayWifi() async {
  try {
    final redes = await Connectivity().checkConnectivity();
    return redes.contains(ConnectivityResult.wifi) || redes.contains(ConnectivityResult.ethernet);
  } catch (_) {
    return false;
  }
}

/// Una por tienda (depende del repositorio, que depende de la tienda elegida).
final precargaCatalogoProvider = Provider<PrecargaCatalogo>((ref) {
  final repositorio = ref.watch(catalogoRepositoryProvider);
  final conectividad = ref.watch(conectividadServiceProvider);
  final precarga = PrecargaCatalogo(
    listarPagina: (pagina, tamanio) => repositorio.listar(pagina: pagina, tamanio: tamanio),
    descargar: _descargarConCacheFotos,
    detalle: (productoId) async => [for (final imagen in (await repositorio.detalle(productoId)).imagenes) imagen.url],
    hayConexion: () => conectividad.actual,
    esWifi: _hayWifi,
  );
  ref.onDispose(precarga.cancelar);
  return precarga;
});

/// Lanza la precarga sin esperarla. Usado cuando el catálogo carga con conexión y cuando vuelve la red.
///
/// Antes confirma con el servidor que de verdad hay conexión: la app arranca dando por hecho que la hay, y sin esta
/// comprobación una apertura sin red intentaría bajar fotos en vano.
void iniciarPrecargaDeFotos(Ref ref) {
  unawaited(() async {
    try {
      final conectado = await ref.read(conectividadServiceProvider).verificarAhora();
      if (conectado) await ref.read(precargaCatalogoProvider).ejecutar();
    } catch (_) {
      // Sin precarga la app funciona igual.
    }
  }());
}
