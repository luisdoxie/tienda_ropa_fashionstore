import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { MessageService } from 'primeng/api';
import { catchError, throwError } from 'rxjs';
import { SIN_TOAST_ERROR } from './http-contexts';

// Rutas que ya manejan sus propios errores en la UI (p. ej. dashboard y
// caja muestran un aviso propio cuando el usuario no tiene registro de
// empleado) -- el toast global sería redundante.
const RUTAS_SIN_TOAST_ERROR = ['/empleados/yo'];

function mensajeDe(error: HttpErrorResponse): string {
  const detalle = error.error?.detail;
  if (typeof detalle === 'string') {
    return detalle;
  }
  if (Array.isArray(detalle)) {
    // Errores de validación de Pydantic/FastAPI (422).
    return detalle.map((e: any) => e.msg ?? String(e)).join(' · ');
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
 */
export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const messageService = inject(MessageService);

  return next(req).pipe(
    catchError((error: unknown) => {
      const esRutaSinToast =
        req.context.get(SIN_TOAST_ERROR) || RUTAS_SIN_TOAST_ERROR.some((ruta) => req.url.includes(ruta));
      if (error instanceof HttpErrorResponse && error.status !== 401 && !esRutaSinToast) {
        messageService.add({
          severity: 'error',
          summary: `Error ${error.status || ''}`.trim(),
          detail: mensajeDe(error),
        });
      }
      return throwError(() => error);
    }),
  );
};
