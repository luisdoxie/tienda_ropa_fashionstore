import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Una fila "etiqueta ... Bs 12.50" de un resumen de compra (subtotal, descuento, envío, total).
class FilaMonto extends StatelessWidget {
  const FilaMonto(this.etiqueta, this.monto, {this.negrita = false, this.color, super.key});

  final String etiqueta;
  final double monto;
  final bool negrita;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final estilo = TextStyle(
      fontWeight: negrita ? FontWeight.w700 : FontWeight.w400,
      fontSize: negrita ? 16 : 14,
      color: color ?? AppColors.texto,
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(etiqueta, style: estilo),
          Text('Bs ${monto.toStringAsFixed(2)}', style: estilo),
        ],
      ),
    );
  }
}
