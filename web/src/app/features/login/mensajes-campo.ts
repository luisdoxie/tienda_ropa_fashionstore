import { AbstractControl, ValidationErrors } from '@angular/forms';

/** Como `Validators.required`, pero un texto de solo espacios también cuenta como vacío. */
export function sinSoloEspacios(control: AbstractControl): ValidationErrors | null {
  return String(control.value ?? '').trim() === '' ? { required: true } : null;
}

/**
 * Mensaje de error de un campo, solo cuando ya se tocó (o se intentó enviar).
 * `mensajes` va por clave de error, en orden de prioridad.
 */
export function mensajeDeCampo(control: AbstractControl | null, mensajes: Record<string, string>): string | null {
  if (control === null || !control.invalid || !control.touched) return null;
  const clave = Object.keys(mensajes).find((c) => control.hasError(c));
  return clave === undefined ? null : mensajes[clave];
}
