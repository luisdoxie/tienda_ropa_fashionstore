import 'dart:async';
import 'dart:io';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gal/gal.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../../core/network/mensaje_error.dart';
import '../../../core/theme/app_theme.dart';
import '../../tracking/models/evento.dart';
import '../../tracking/state/tracking_service.dart';
import '../state/probador_providers.dart';

/// Pantalla del probador: foto del cliente (cámara o galería) + prenda
/// elegida -> imagen generada por IA en el backend.
class ProbadorScreen extends StatelessWidget {
  const ProbadorScreen({this.varianteInicial, super.key});

  /// La prenda (variante) que el cliente eligió en el detalle o en el carrito: el probador abre con ella puesta.
  /// Sin ella (ícono del catálogo) abre con la primera de la lista.
  final int? varianteInicial;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(backgroundColor: Colors.black, foregroundColor: Colors.white, title: const Text('Probador')),
      // SafeArea: desde que el edge-to-edge es obligatorio (Android 15+),
      // la barra de navegación del sistema se dibuja ENCIMA del contenido
      // en vez de reservarle espacio -- sin esto, cualquier control pegado
      // al borde inferior (guardar/compartir del resultado) queda tapado
      // detrás de la barra y parece que no existe.
      body: SafeArea(child: _PruebaGenerativa(varianteInicial: varianteInicial)),
    );
  }
}

enum _EstadoGeneracion { ninguna, enviando, enProceso, completado, fallido }

/// Prueba generativa (P4.6): foto (cámara o galería) -> POST /probador/generar
/// -> polling a GET /probador/generar/{id} cada 2s -> resultado a pantalla
/// completa. Nunca cuelga la app: cualquier falla de red, tanto al subir
/// como durante el polling, termina en un estado de error explícito con
/// un mensaje y la opción de reintentar (desconectar internet a propósito
/// tiene que degradar con elegancia, no colgarse).
class _PruebaGenerativa extends ConsumerStatefulWidget {
  const _PruebaGenerativa({this.varianteInicial});

  final int? varianteInicial;

  @override
  ConsumerState<_PruebaGenerativa> createState() => _PruebaGenerativaState();
}

class _PruebaGenerativaState extends ConsumerState<_PruebaGenerativa> {
  static const _intervaloPolling = Duration(seconds: 2);

  bool _consentimiento = false;
  PrendaProbador? _prenda;
  Uint8List? _fotoBytes;

  var _estado = _EstadoGeneracion.ninguna;
  int? _generacionId;
  String? _urlResultado;
  String? _mensajeError;

  Timer? _timerPolling;
  int _intentosFallidosSeguidos = 0;
  DateTime? _inicioPolling;

  bool get _puedeCapturar => _consentimiento && _prenda != null;
  bool get _puedeGenerar => _puedeCapturar && _fotoBytes != null && _estado == _EstadoGeneracion.ninguna;

  @override
  void initState() {
    super.initState();
    // Con una prenda inicial (elegida en el detalle o el carrito) el probador empieza con ella, una
    // sola vez. Sin ella sigue como siempre: el cliente elige la prenda en el selector.
    final inicial = widget.varianteInicial;
    if (inicial != null) {
      ref.listenManual(prendasParaProbadorProvider(inicial), (previous, next) {
        next.whenData((prendas) {
          if (mounted && _prenda == null && prendas.isNotEmpty) setState(() => _prenda = prendas.first);
        });
      }, fireImmediately: true);
    }
  }

  @override
  void dispose() {
    _timerPolling?.cancel();
    super.dispose();
  }

  Future<void> _elegirFoto(ImageSource origen) async {
    try {
      final xfile = await ImagePicker().pickImage(source: origen, imageQuality: 85, maxWidth: 1600);
      if (xfile == null) return;
      final bytes = await xfile.readAsBytes();
      if (!mounted) return;
      setState(() {
        _fotoBytes = bytes;
        _estado = _EstadoGeneracion.ninguna;
        _urlResultado = null;
        _mensajeError = null;
      });
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No se pudo obtener la foto.')));
    }
  }

  Future<void> _generar() async {
    final prenda = _prenda;
    final foto = _fotoBytes;
    if (prenda == null || foto == null) return;

    setState(() {
      _estado = _EstadoGeneracion.enviando;
      _mensajeError = null;
    });

    try {
      final repo = ref.read(probadorRepositoryProvider);
      final resultado = await repo.iniciarGeneracion(
        varianteId: prenda.varianteId,
        fotoBytes: foto,
        nombreArchivo: 'foto.jpg',
      );
      if (!mounted) return;

      if (resultado.completado) {
        _terminarConExito(resultado.urlResultado);
        return;
      }
      if (resultado.fallido) {
        _terminarConError(resultado.mensajeError ?? 'No se pudo generar la imagen.');
        return;
      }

      setState(() => _estado = _EstadoGeneracion.enProceso);
      _generacionId = resultado.id;
      _intentosFallidosSeguidos = 0;
      _inicioPolling = DateTime.now();
      _programarPolling();
    } catch (e) {
      if (!mounted) return;
      _terminarConError(_mensajeParaError(e));
    }
  }

  void _programarPolling() {
    _timerPolling?.cancel();
    _timerPolling = Timer(_intervaloPolling, _consultarEstado);
  }

  Future<void> _consultarEstado() async {
    final id = _generacionId;
    final inicio = _inicioPolling;
    if (id == null || inicio == null || !mounted) return;

    final transcurrido = DateTime.now().difference(inicio);
    if (debeAbandonarPolling(intentosFallidosSeguidos: _intentosFallidosSeguidos, transcurridoDesdeElInicio: transcurrido)) {
      _terminarConError(
        _intentosFallidosSeguidos > 0
            ? 'Se perdió la conexión. Revisá tu internet e intentá de nuevo.'
            : 'La generación está tardando demasiado. Probá de nuevo más tarde.',
      );
      return;
    }

    try {
      final repo = ref.read(probadorRepositoryProvider);
      final resultado = await repo.consultarGeneracion(id);
      if (!mounted) return;
      _intentosFallidosSeguidos = 0;

      if (resultado.completado) {
        _terminarConExito(resultado.urlResultado);
        return;
      }
      if (resultado.fallido) {
        _terminarConError(resultado.mensajeError ?? 'No se pudo generar la imagen.');
        return;
      }
      _programarPolling();
    } catch (_) {
      // Se reintenta unas cuantas veces (podría ser un corte de red
      // momentáneo): recién después de varios intentos seguidos fallidos,
      // el próximo _consultarEstado la abandona por debeAbandonarPolling.
      // Nunca se queda esperando para siempre (ver debeAbandonarPolling).
      _intentosFallidosSeguidos++;
      if (!mounted) return;
      _programarPolling();
    }
  }

  void _terminarConExito(String? url) {
    final prenda = _prenda;
    setState(() {
      _estado = _EstadoGeneracion.completado;
      _urlResultado = url;
    });
    if (prenda != null) {
      ref.read(trackingServiceProvider).track(tipo: TipoEvento.probador, varianteId: prenda.varianteId);
    }
  }

  void _terminarConError(String mensaje) {
    setState(() {
      _estado = _EstadoGeneracion.fallido;
      _mensajeError = mensaje;
    });
  }

  String _mensajeParaError(Object e) {
    return mensajeDeError(
      e,
      esSinConexion(e)
          ? 'Sin conexión a internet. Revisá tu conexión e intentá de nuevo.'
          : 'No se pudo generar la imagen. Probá de nuevo más tarde.',
    );
  }

  void _reiniciar() {
    _timerPolling?.cancel();
    setState(() {
      _estado = _EstadoGeneracion.ninguna;
      _fotoBytes = null;
      _urlResultado = null;
      _mensajeError = null;
      _generacionId = null;
    });
  }

  Future<void> _guardar() async {
    final url = _urlResultado;
    if (url == null) return;
    try {
      final bytes = await ref.read(probadorRepositoryProvider).descargarBytes(url);
      final tienePermiso = await Gal.requestAccess();
      if (!tienePermiso) {
        if (!mounted) return;
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('Sin permiso para guardar en la galería.')));
        return;
      }
      await Gal.putImageBytes(bytes);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Imagen guardada en la galería.')));
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No se pudo guardar la imagen.')));
    }
  }

  Future<void> _compartir() async {
    final url = _urlResultado;
    if (url == null) return;
    try {
      final bytes = await ref.read(probadorRepositoryProvider).descargarBytes(url);
      final dir = await getTemporaryDirectory();
      final archivo = File('${dir.path}/probador_resultado.png');
      await archivo.writeAsBytes(bytes);
      await SharePlus.instance.share(
        ShareParams(files: [XFile(archivo.path)], text: 'Así me queda esta prenda en FashionStore'),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No se pudo compartir la imagen.')));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_estado == _EstadoGeneracion.completado && _urlResultado != null) {
      return _vistaResultado();
    }
    if (_estado == _EstadoGeneracion.fallido) {
      return _vistaError();
    }
    if (_estado == _EstadoGeneracion.enviando || _estado == _EstadoGeneracion.enProceso) {
      return _vistaProgreso();
    }

    final asyncPrendas = ref.watch(prendasParaProbadorProvider(widget.varianteInicial));
    return asyncPrendas.when(
      data: (prendas) => _vistaPreparacion(prendas),
      loading: () => const Center(child: CircularProgressIndicator(color: Colors.white)),
      error: (error, stack) =>
          const Center(child: Text('No se pudo cargar el catálogo.', style: TextStyle(color: Colors.white))),
    );
  }

  Widget _vistaPreparacion(List<PrendaProbador> prendas) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CheckboxListTile(
            value: _consentimiento,
            onChanged: (valor) => setState(() => _consentimiento = valor ?? false),
            controlAffinity: ListTileControlAffinity.leading,
            contentPadding: EdgeInsets.zero,
            activeColor: AppColors.exito,
            checkColor: Colors.white,
            title: const Text('Acepto enviar mi foto', style: TextStyle(color: Colors.white)),
            subtitle: const Text(
              'Tu foto se envía a un servicio externo de generación de imágenes (Vertex AI) '
              'solo para crear el resultado. No se guarda en ningún lado: ni la app ni el '
              'servidor la almacenan.',
              style: TextStyle(color: Colors.white70, fontSize: 12),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          if (prendas.isEmpty)
            const Text('Todavía no hay prendas listas para probar.', style: TextStyle(color: Colors.white70))
          else ...[
            const Text('Elegí una prenda', style: TextStyle(color: Colors.white70, fontSize: 12)),
            const SizedBox(height: AppSpacing.xs),
            _selectorPrendas(prendas),
          ],
          const SizedBox(height: AppSpacing.lg),
          if (_fotoBytes != null) ...[
            ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.base),
              child: Image.memory(_fotoBytes!, height: 240, width: double.infinity, fit: BoxFit.cover),
            ),
            const SizedBox(height: AppSpacing.md),
          ],
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.white,
                    side: const BorderSide(color: Colors.white54),
                  ),
                  onPressed: _puedeCapturar ? () => _elegirFoto(ImageSource.camera) : null,
                  icon: const Icon(Icons.camera_alt_outlined),
                  label: const Text('Sacar foto'),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.white,
                    side: const BorderSide(color: Colors.white54),
                  ),
                  onPressed: _puedeCapturar ? () => _elegirFoto(ImageSource.gallery) : null,
                  icon: const Icon(Icons.photo_library_outlined),
                  label: const Text('Galería'),
                ),
              ),
            ],
          ),
          if (!_puedeCapturar) ...[
            const SizedBox(height: AppSpacing.xs),
            const Text(
              'Aceptá el envío de tu foto y elegí una prenda para poder sacar o elegir una foto.',
              style: TextStyle(color: Colors.white38, fontSize: 12),
            ),
          ],
          if (_fotoBytes != null) ...[
            const SizedBox(height: AppSpacing.md),
            ElevatedButton(onPressed: _puedeGenerar ? _generar : null, child: const Text('Generar')),
          ],
        ],
      ),
    );
  }

  Widget _selectorPrendas(List<PrendaProbador> prendas) {
    return SizedBox(
      height: 72,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: prendas.length,
        separatorBuilder: (context, index) => const SizedBox(width: AppSpacing.sm),
        itemBuilder: (context, index) {
          final prenda = prendas[index];
          final seleccionada = prenda.varianteId == _prenda?.varianteId;
          return GestureDetector(
            onTap: () => setState(() => _prenda = prenda),
            child: Container(
              width: 64,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(AppRadius.base),
                border: Border.all(color: seleccionada ? AppColors.exito : Colors.white54, width: seleccionada ? 3 : 1),
              ),
              clipBehavior: Clip.antiAlias,
              child: CachedNetworkImage(
                imageUrl: prenda.assets.overlay.url,
                fit: BoxFit.cover,
                placeholder: (context, url) => Container(color: Colors.white24),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _vistaProgreso() {
    final texto = _estado == _EstadoGeneracion.enviando
        ? 'Enviando tu foto...'
        : 'Generando la imagen... puede tardar unos segundos.';
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(color: Colors.white),
            const SizedBox(height: AppSpacing.md),
            Text(texto, style: const TextStyle(color: Colors.white), textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }

  Widget _vistaError() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, color: Colors.white54, size: 48),
            const SizedBox(height: AppSpacing.md),
            Text(
              _mensajeError ?? 'No se pudo generar la imagen.',
              style: const TextStyle(color: Colors.white),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.md),
            ElevatedButton(onPressed: _reiniciar, child: const Text('Intentar de nuevo')),
          ],
        ),
      ),
    );
  }

  Widget _vistaResultado() {
    return Stack(
      fit: StackFit.expand,
      children: [
        ColoredBox(
          color: Colors.black,
          child: CachedNetworkImage(
            imageUrl: _urlResultado!,
            fit: BoxFit.contain,
            placeholder: (context, url) => const Center(child: CircularProgressIndicator(color: Colors.white)),
            errorWidget: (context, url, error) =>
                const Center(child: Icon(Icons.broken_image_outlined, color: Colors.white54, size: 48)),
          ),
        ),
        Positioned(
          top: AppSpacing.sm,
          left: AppSpacing.sm,
          child: IconButton(
            icon: const Icon(Icons.close, color: Colors.white),
            tooltip: 'Sacar otra foto',
            onPressed: _reiniciar,
          ),
        ),
        Positioned(
          left: 0,
          right: 0,
          bottom: AppSpacing.xl,
          // Positioned con left/right pero sin top deja la altura sin
          // acotar (0..infinito); un SizedBox con altura fija le da al
          // Row -- y a los ElevatedButton adentro -- una restricción
          // concreta en vez de eso (si no, tira BoxConstraints(unconstrained)).
          child: SizedBox(
            height: 48,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _botonResultado(icon: Icons.download_outlined, label: 'Guardar', onPressed: _guardar),
                const SizedBox(width: AppSpacing.lg),
                _botonResultado(icon: Icons.share_outlined, label: 'Compartir', onPressed: _compartir),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _botonResultado({required IconData icon, required String label, required VoidCallback onPressed}) {
    return ElevatedButton.icon(
      // El tema global (app_theme.dart) fija minimumSize en Size.fromHeight(52)
      // -- ancho infinito -- pensado para botones de una sola columna. Acá
      // van dos uno al lado del otro dentro de un Row sin Expanded, así que
      // ese ancho infinito hay que pisarlo o tira BoxConstraints inválido.
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.acento,
        foregroundColor: Colors.white,
        minimumSize: Size.zero,
      ),
      onPressed: onPressed,
      icon: Icon(icon),
      label: Text(label),
    );
  }
}

/// Cuándo el polling de una generación tiene que dejar de reintentar y
/// terminar en un error explícito, en vez de seguir esperando para
/// siempre: ya sea porque se acumularon demasiados intentos fallidos
/// seguidos (probable corte de red) o porque pasó demasiado tiempo desde
/// que arrancó, tenga o no errores (el servicio externo se colgó).
/// Desconectar internet a propósito no puede colgar la app.
bool debeAbandonarPolling({
  required int intentosFallidosSeguidos,
  required Duration transcurridoDesdeElInicio,
  int maxIntentosFallidosSeguidos = 5,
  Duration timeoutTotal = const Duration(seconds: 90),
}) {
  if (transcurridoDesdeElInicio > timeoutTotal) return true;
  return intentosFallidosSeguidos >= maxIntentosFallidosSeguidos;
}
