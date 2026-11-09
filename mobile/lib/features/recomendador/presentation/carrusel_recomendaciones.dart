import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/foto_prenda.dart';
import '../models/recomendacion_item.dart';

/// Carrusel de recomendaciones (P6.2), reusado en el home y en el detalle
/// de una prenda -- cambia el provider que observa y el título.
///
/// No es un flujo crítico como la búsqueda: si está cargando, falla, o
/// viene vacío (no debería pasar nunca del lado del backend, pero por las
/// dudas), se oculta la sección entera en vez de mostrar un hueco vacío o
/// un spinner que distraiga del resto de la pantalla.
class CarruselRecomendaciones extends ConsumerWidget {
  const CarruselRecomendaciones({required this.provider, required this.titulo, super.key});

  final ProviderListenable<AsyncValue<List<RecomendacionItem>>> provider;
  final String titulo;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncRecomendaciones = ref.watch(provider);
    return asyncRecomendaciones.maybeWhen(
      data: (items) => items.isEmpty ? const SizedBox.shrink() : _Carrusel(titulo: titulo, items: items),
      orElse: () => const SizedBox.shrink(),
    );
  }
}

class _Carrusel extends StatelessWidget {
  const _Carrusel({required this.titulo, required this.items});

  final String titulo;
  final List<RecomendacionItem> items;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
            child: Text(titulo, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
          ),
          const SizedBox(height: AppSpacing.sm),
          SizedBox(
            height: 230,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
              itemCount: items.length,
              separatorBuilder: (context, index) => const SizedBox(width: AppSpacing.sm),
              itemBuilder: (context, index) => _TarjetaRecomendacion(item: items[index]),
            ),
          ),
        ],
      ),
    );
  }
}

class _TarjetaRecomendacion extends StatelessWidget {
  const _TarjetaRecomendacion({required this.item});

  final RecomendacionItem item;

  @override
  Widget build(BuildContext context) {
    final producto = item.producto;
    return GestureDetector(
      onTap: () => context.push('/producto/${producto.id}'),
      child: SizedBox(
        width: 140,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.base),
              child: SizedBox(
                height: 140,
                width: 140,
                child: producto.imagenPrincipal != null
                    ? FotoPrenda(url: producto.imagenPrincipal!, ancho: 140, alto: 140)
                    : Container(
                        color: AppColors.fondoAlterno,
                        child: const Icon(Icons.checkroom, color: AppColors.textoTenue),
                      ),
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(producto.nombre, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13)),
            Text(
              'Bs ${producto.precioBase.toStringAsFixed(2)}',
              style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13, color: AppColors.acento),
            ),
            Text(
              item.motivo,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11, color: AppColors.textoTenue),
            ),
          ],
        ),
      ),
    );
  }
}
