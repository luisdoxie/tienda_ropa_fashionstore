import { HttpErrorResponse } from '@angular/common/http';

const FORMATO_CODIGO = /^[a-z][a-z0-9_]*$/;

/**
 * El código funcional de un error del backend (`suscripcion_no_activa`,
 * `limite_plan_excedido`, ...) o null si el error no trae uno.
 *
 * El backend responde `{detail, codigo, mensaje, ...}` (`ErrorFuncional`); por
 * compatibilidad también se acepta el código dentro de `detail`, ya sea como
 * texto (`{"detail": "suscripcion_no_activa"}`) o como objeto
 * (`{"detail": {"codigo": "suscripcion_no_activa"}}`).
 */
export function codigoFuncional(error: unknown): string | null {
  if (!(error instanceof HttpErrorResponse)) return null;
  const cuerpo = error.error;
  if (cuerpo === null || typeof cuerpo !== 'object') return null;

  if (typeof cuerpo.codigo === 'string' && cuerpo.codigo) return cuerpo.codigo;

  const detalle = cuerpo.detail;
  if (typeof detalle === 'string' && FORMATO_CODIGO.test(detalle)) return detalle;
  if (detalle !== null && typeof detalle === 'object' && typeof detalle.codigo === 'string' && detalle.codigo) {
    return detalle.codigo;
  }
  return null;
}
