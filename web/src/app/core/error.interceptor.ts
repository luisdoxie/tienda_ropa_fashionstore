import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { MessageService } from 'primeng/api';
import { catchError, throwError } from 'rxjs';
import { codigoFuncional } from './errores-funcionales';
import { SIN_TOAST_ERROR } from './http-contexts';
import { mensajeFuncional } from './mensajes-error-funcional';
import { PlanService } from './plan.service';

// Rutas que ya manejan sus propios errores en la UI (p. ej. dashboard y
// caja muestran un aviso propio cuando el usuario no tiene registro de
// empleado) -- el toast global sería redundante.
const RUTAS_SIN_TOAST_ERROR = ['/empleados/yo'];

/** El mismo aviso del plan o la suscripción no se repite antes de este tiempo. */
export const ESPERA_AVISO_FUNCIONAL_MS = 10_000;

const ultimoAviso = new Map<string, number>();

/** Solo para las pruebas. */
export function reiniciarAvisosFuncionales(): void {
  ultimoAviso.clear();
}

function repetido(codigo: string): boolean {
  const ahora = Date.now();
  const antes = ultimoAviso.get(codigo);
  if (antes !== undefined && ahora - antes < ESPERA_AVISO_FUNCIONAL_MS) return true;
  ultimoAviso.set(codigo, ahora);
  return false;
}

function mensajeDe(error: HttpErrorResponse): string {
  const detalle = error.error?.detail;
  if (typeof detalle === 'string') {
    return detalle;
  }
  if (Array.isArray(detalle)) {
    // Errores de validación de Pydantic/FastAPI (422).
    return detalle.map((e: any) => e.msg ?? String(e)).join(' · ');
  }
  if (detalle !== null && typeof detalle === 'object' && typeof detalle.mensaje === 'string') {
    return detalle.mensaje;
  }
  if (typeof error.error?.mensaje === 'string') {
    return error.error.mensaje;
  }
  if (error.status === 0) {
    return 'No se pudo conectar con el servidor.';
  }
  return 'Ocurrió un error inesperado.';
}

/**
 * Muestra un toast con cualquier error HTTP que llegue hasta acá. El 401
 * que el authInterceptor logra recuperar reintentando con un token nuevo
 * nunca llega a este interceptor.
 *
 * Los errores del plan y la suscripción (`plan_no_incluye_funcionalidad`,
 * `suscripcion_no_activa`, `limite_plan_excedido`) se explican en lenguaje
 * claro, sin "Error 403", y no se repiten en 10 segundos.
 */
export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const messageService = inject(MessageService);
  const planService = inject(PlanService);

  return next(req).pipe(
    catchError((error: unknown) => {
      const esRutaSinToast =
        req.context.get(SIN_TOAST_ERROR) || RUTAS_SIN_TOAST_ERROR.some((ruta) => req.url.includes(ruta));
      if (error instanceof HttpErrorResponse && error.status !== 401) {
        const codigo = codigoFuncional(error);
        const funcional = mensajeFuncional(codigo, error.error, planService.nombrePlan());

        // El aviso persistente de suscripción aparece aunque la llamada no muestre toast.
        if (codigo === 'suscripcion_no_activa') {
          planService.marcarBloqueada(typeof error.error?.estado === 'string' ? error.error.estado : null);
        }

        if (!esRutaSinToast) {
          if (funcional !== null) {
            if (codigo !== null && !repetido(codigo)) {
              messageService.add({ severity: funcional.severidad, summary: funcional.resumen, detail: funcional.detalle });
            }
          } else {
            messageService.add({
              severity: 'error',
              summary: `Error ${error.status || ''}`.trim(),
              detail: mensajeDe(error),
            });
          }
        }
      }
      return throwError(() => error);
    }),
  );
};
