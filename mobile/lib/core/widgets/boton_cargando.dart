import 'package:flutter/material.dart';

/// El indicador de progreso que reemplaza el texto de un botón mientras su acción está en curso.
class BotonCargando extends StatelessWidget {
  const BotonCargando({this.color = Colors.white, super.key});

  final Color color;

  @override
  Widget build(BuildContext context) {
    return SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: color));
  }
}
