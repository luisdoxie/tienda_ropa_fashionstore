import { AbstractControl, ValidationErrors } from '@angular/forms';

/** Hoy a medianoche LOCAL (las fechas del backend son 'YYYY-MM-DD', sin hora). */
export function hoyLocal(): Date {
  const ahora = new Date();
  return new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate());
}

export function sumarDias(fecha: Date, dias: number): Date {
  return new Date(fecha.getFullYear(), fecha.getMonth(), fecha.getDate() + dias);
}

/** Suma meses sin desbordar: 31 de enero + 1 mes = 28 (o 29) de febrero. */
export function sumarMeses(fecha: Date, meses: number): Date {
  const primero = new Date(fecha.getFullYear(), fecha.getMonth() + meses, 1);
  const ultimoDia = new Date(primero.getFullYear(), primero.getMonth() + 1, 0).getDate();
  return new Date(primero.getFullYear(), primero.getMonth(), Math.min(fecha.getDate(), ultimoDia));
}

/** Días de calendario entre hoy y `fecha` (negativo si ya pasó). */
export function diasHasta(fecha: Date, hoy: Date = hoyLocal()): number {
  const MS_DIA = 24 * 60 * 60 * 1000;
  const a = Date.UTC(fecha.getFullYear(), fecha.getMonth(), fecha.getDate());
  const b = Date.UTC(hoy.getFullYear(), hoy.getMonth(), hoy.getDate());
  return Math.round((a - b) / MS_DIA);
}

/** Aviso de formulario: la fecha tiene que ser posterior a hoy (el backend también lo exige). */
export function fechaPosteriorAHoy(control: AbstractControl): ValidationErrors | null {
  const valor = control.value;
  if (!(valor instanceof Date)) return null;
  return diasHasta(valor) > 0 ? null : { fechaPasada: true };
}
