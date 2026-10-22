import { HttpContextToken } from '@angular/common/http';

/**
 * Marca una petición cuyo error ya se muestra en la propia pantalla (p. ej.
 * "No encontramos esta tienda"): el `errorInterceptor` no abre el toast rojo.
 * Uso: `http.get(url, { context: new HttpContext().set(SIN_TOAST_ERROR, true) })`.
 */
export const SIN_TOAST_ERROR = new HttpContextToken<boolean>(() => false);
