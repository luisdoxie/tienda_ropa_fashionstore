import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/fecha_servidor.dart';
import '../models/reserva.dart';
import '../state/reservas_providers.dart';

final _reservaDetalleProvider = FutureProvider.autoDispose.family<Reserva, int>(
  (ref, reservaId) => ref.watch(reservasRepositoryProvider).obtener(reservaId),
);

class ReservaDetalleScreen extends ConsumerStatefulWidget {
  const ReservaDetalleScreen({required this.reservaId, super.key});

  final int reservaId;

  @override
  ConsumerState<ReservaDetalleScreen> createState() => _ReservaDetalleScreenState();
}

class _ReservaDetalleScreenState extends ConsumerState<ReservaDetalleScreen> {
  bool _cancelando = false;

  Future<void> _cancelar() async {
    setState(() => _cancelando = true);
    try {
      await ref.read(reservasRepositoryProvider).cancelar(widget.reservaId);
      ref.invalidate(_reservaDetalleProvider(widget.reservaId));
      await ref.read(misReservasControllerProvider.notifier).cargar();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Reserva cancelada')));
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('No se pudo cancelar la reserva.')));
    } finally {
      if (mounted) setState(() => _cancelando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final asyncReserva = ref.watch(_reservaDetalleProvider(widget.reservaId));

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Detalle de reserva')),
      body: asyncReserva.when(
        loading: () => const Center(child: CircularProgressIndicator(color: AppColors.acento)),
        error: (error, stack) => const Center(child: Text('No se pudo cargar la reserva.')),
        data: (reserva) => ListView(
          padding: const EdgeInsets.all(AppSpacing.md),
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(reserva.codigo, style: Theme.of(context).textTheme.headlineMedium),
                Chip(label: Text(etiquetasEstadoReserva[reserva.estado] ?? reserva.estado)),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              '${reserva.fechaVisita} · ${reserva.horaVisitaDesde.substring(0, 5)} - ${reserva.horaVisitaHasta.substring(0, 5)}',
              style: const TextStyle(color: AppColors.textoTenue),
            ),
            if (reserva.observacion != null) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(reserva.observacion!),
            ],
            const SizedBox(height: AppSpacing.lg),

            const Text('Prendas', style: TextStyle(color: AppColors.textoTenue, fontSize: 12)),
            const SizedBox(height: AppSpacing.xs),
            for (final linea in reserva.detalle)
              Card(
                margin: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: ListTile(
                  title: Text('Variante #${linea.varianteId}'),
                  subtitle: Text('Cantidad: ${linea.cantidad}'),
                  trailing: linea.seleccionada == null
                      ? null
                      : Icon(
                          linea.seleccionada! ? Icons.check_circle : Icons.cancel,
                          color: linea.seleccionada! ? AppColors.exito : AppColors.error,
                        ),
                ),
              ),

            const SizedBox(height: AppSpacing.lg),
            const Text('Historial', style: TextStyle(color: AppColors.textoTenue, fontSize: 12)),
            const SizedBox(height: AppSpacing.xs),
            for (final item in reserva.historial)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      etiquetasEstadoReserva[item.estado] ?? item.estado,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                    Text(
                      formatearFechaHora(item.creadoEn),
                      style: const TextStyle(color: AppColors.textoTenue, fontSize: 12),
                    ),
                    if (item.comentario != null) Text(item.comentario!),
                  ],
                ),
              ),

            if (reserva.esCancelable) ...[
              const SizedBox(height: AppSpacing.lg),
              OutlinedButton(
                onPressed: _cancelando ? null : _cancelar,
                style: OutlinedButton.styleFrom(foregroundColor: AppColors.error),
                child: _cancelando ? const Text('Cancelando...') : const Text('Cancelar reserva'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
