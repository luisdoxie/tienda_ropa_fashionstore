import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/boton_cargando.dart';
import '../state/compras_providers.dart';

class DireccionFormScreen extends ConsumerStatefulWidget {
  const DireccionFormScreen({super.key});

  @override
  ConsumerState<DireccionFormScreen> createState() => _DireccionFormScreenState();
}

class _DireccionFormScreenState extends ConsumerState<DireccionFormScreen> {
  final _formKey = GlobalKey<FormState>();
  final _aliasController = TextEditingController();
  final _direccionController = TextEditingController();
  final _referenciaController = TextEditingController();
  int? _zonaEnvioId;
  bool _esPrincipal = false;
  bool _guardando = false;

  @override
  void dispose() {
    _aliasController.dispose();
    _direccionController.dispose();
    _referenciaController.dispose();
    super.dispose();
  }

  Future<void> _guardar() async {
    if (!_formKey.currentState!.validate() || _zonaEnvioId == null) {
      if (_zonaEnvioId == null) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Elegí una zona de envío')));
      }
      return;
    }
    setState(() => _guardando = true);
    try {
      final direccion = await ref
          .read(direccionesRepositoryProvider)
          .crear(
            zonaEnvioId: _zonaEnvioId,
            alias: _aliasController.text.trim().isEmpty ? null : _aliasController.text.trim(),
            direccion: _direccionController.text.trim(),
            referencia: _referenciaController.text.trim().isEmpty ? null : _referenciaController.text.trim(),
            esPrincipal: _esPrincipal,
          );
      if (!mounted) return;
      Navigator.of(context).pop(direccion);
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('No se pudo guardar la dirección. Probá de nuevo.')));
    } finally {
      if (mounted) setState(() => _guardando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final asyncZonas = ref.watch(zonasEnvioProvider);

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Nueva dirección')),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.md),
          children: [
            const Text('Zona de envío', style: TextStyle(color: AppColors.textoTenue, fontSize: 12)),
            const SizedBox(height: AppSpacing.xs),
            asyncZonas.when(
              loading: () => const LinearProgressIndicator(),
              error: (e, s) => const Text('No se pudieron cargar las zonas.', style: TextStyle(color: AppColors.error)),
              data: (zonas) => DropdownButtonFormField<int>(
                initialValue: _zonaEnvioId,
                items: [
                  for (final zona in zonas) DropdownMenuItem(value: zona.id, child: Text(zona.nombre)),
                ],
                onChanged: (id) => setState(() => _zonaEnvioId = id),
                hint: const Text('Elegí tu zona'),
              ),
            ),
            const SizedBox(height: AppSpacing.md),

            TextFormField(
              controller: _aliasController,
              decoration: const InputDecoration(labelText: 'Alias (opcional)', hintText: 'Casa, oficina...'),
            ),
            const SizedBox(height: AppSpacing.md),

            TextFormField(
              controller: _direccionController,
              decoration: const InputDecoration(labelText: 'Dirección'),
              validator: (valor) => (valor == null || valor.trim().isEmpty) ? 'Ingresá una dirección' : null,
            ),
            const SizedBox(height: AppSpacing.md),

            TextFormField(
              controller: _referenciaController,
              decoration: const InputDecoration(labelText: 'Referencia (opcional)'),
              maxLines: 2,
            ),
            const SizedBox(height: AppSpacing.sm),

            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              value: _esPrincipal,
              onChanged: (valor) => setState(() => _esPrincipal = valor ?? false),
              title: const Text('Usar como dirección principal'),
              controlAffinity: ListTileControlAffinity.leading,
            ),

            const SizedBox(height: AppSpacing.lg),
            ElevatedButton(
              onPressed: _guardando ? null : _guardar,
              child: _guardando ? const BotonCargando() : const Text('Guardar dirección'),
            ),
          ],
        ),
      ),
    );
  }
}
