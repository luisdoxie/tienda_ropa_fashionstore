/**
 * Dinero sin errores de coma flotante: se calcula con CENTAVOS enteros y se guarda y envía como texto decimal con dos
 * decimales ("149.00"), que es el contrato del servidor (E07). Un solo lugar para ajustar si el contrato cambia.
 */

/** "149.00" o 149 -> 14900. Devuelve NaN si no es un número válido. */
export function aCentavos(valor: string | number | null | undefined): number {
  if (valor === null || valor === undefined || valor === '') return Number.NaN;
  const numero = typeof valor === 'number' ? valor : Number(String(valor).trim().replace(',', '.'));
  return Number.isFinite(numero) ? Math.round(numero * 100) : Number.NaN;
}

/** 14900 -> "149.00". */
export function centavosATexto(centavos: number): string {
  const entero = Math.round(centavos);
  const signo = entero < 0 ? '-' : '';
  const absoluto = Math.abs(entero);
  return `${signo}${Math.floor(absoluto / 100)}.${String(absoluto % 100).padStart(2, '0')}`;
}

/** cantidad x (precio - descuento), todo en centavos. */
export function subtotalEnCentavos(cantidad: number, precio: string, descuento: string): number {
  return cantidad * (aCentavos(precio) - aCentavos(descuento));
}

/** Fecha-hora ISO con el desfase local ("2026-10-30T14:05:00-04:00"): lo que pide el servidor (con zona). */
export function fechaConDesfase(fecha: Date = new Date()): string {
  const pad = (n: number, largo = 2) => String(Math.abs(n)).padStart(largo, '0');
  const desfaseMin = -fecha.getTimezoneOffset();
  const signo = desfaseMin >= 0 ? '+' : '-';
  return (
    `${fecha.getFullYear()}-${pad(fecha.getMonth() + 1)}-${pad(fecha.getDate())}` +
    `T${pad(fecha.getHours())}:${pad(fecha.getMinutes())}:${pad(fecha.getSeconds())}` +
    `${signo}${pad(Math.floor(Math.abs(desfaseMin) / 60))}:${pad(Math.abs(desfaseMin) % 60)}`
  );
}
