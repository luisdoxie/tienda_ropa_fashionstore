import { Router } from '@angular/router';
import { TiendaActualService } from '../features/tienda/state/tienda-actual.service';
import { AuthService } from './auth.service';
import { RUTA_INICIO_PERSONAL, RUTA_INICIO_SUPERADMIN } from './guards';

/**
 * A dónde mandar al usuario justo después de loguearse (login o registro +
 * login automático).
 *
 * - Superadministrador: a su panel (`/plataforma/empresas`), o a donde venía si
 *   era una pantalla de /plataforma.
 * - Si venía de un `authGuard` que lo frenó (`returnTo` en la query), vuelve ahí.
 * - Si no, un cliente va a la portada de su tienda (`/t/:codigo`; ['/'] si no
 *   hay tienda actual) y cualquier otro rol al back office -- ver `staffGuard`
 *   en `guards.ts`, que aplica la misma regla para bloquear el acceso directo
 *   por URL.
 */
export function navegarDespuesDeLogin(
  router: Router,
  authService: AuthService,
  returnTo: string | null,
  tienda?: TiendaActualService,
): void {
  if (authService.esSuperadmin()) {
    const aPlataforma = returnTo !== null && /^\/plataforma(?:[/?#]|$)/.test(returnTo);
    router.navigateByUrl(aPlataforma ? returnTo : RUTA_INICIO_SUPERADMIN);
    return;
  }
  if (returnTo) {
    router.navigateByUrl(returnTo);
    return;
  }
  if (authService.esSoloCliente()) {
    router.navigate(tienda ? tienda.ruta() : ['/']);
    return;
  }
  router.navigate([RUTA_INICIO_PERSONAL]);
}
