/// El backend guarda las fechas en UTC y las manda sin zona ("2026-09-20T16:52:29"): sin la 'Z', Dart las tomaría como
/// hora local y quedarían corridas (en Bolivia, 4 horas). Devuelve la fecha ya en hora local.
DateTime fechaDelServidor(String valor) {
  final tieneZona = valor.endsWith('Z') || RegExp(r'[+-]\d{2}:?\d{2}$').hasMatch(valor);
  return DateTime.parse(tieneZona ? valor : '${valor}Z').toLocal();
}

/// "dd/MM/yyyy HH:mm" de una fecha ya en hora local (la que devuelve [fechaDelServidor]).
String formatearFechaHora(DateTime f) {
  String dos(int n) => n.toString().padLeft(2, '0');
  return '${dos(f.day)}/${dos(f.month)}/${f.year} ${dos(f.hour)}:${dos(f.minute)}';
}
