import { Router } from '@angular/router';
import { TiendaActualService } from '../features/tienda/state/tienda-actual.service';
import { AuthService } from './auth.service';

/**
 * A dónde mandar al usuario justo después de loguearse (login o registro +
 * login automático). Si venía de un `authGuard` que lo frenó (`returnTo` en
 * la query), vuelve ahí. Si no, un cliente va a la portada de su tienda
 * (`/t/:codigo`; ['/'] si no hay tienda actual) y cualquier otro rol al back
 * office -- ver `staffGuard` en `guards.ts`, que aplica la misma regla para
 * bloquear el acceso directo por URL.
 */
export function navegarDespuesDeLogin(
  router: Router,
  authService: AuthService,
  returnTo: string | null,
  tienda?: TiendaActualService,
): void {
  if (returnTo) {
    router.navigateByUrl(returnTo);
    return;
  }
  const roles = authService.roles();
  const esSoloCliente = roles.length > 0 && roles.every((rol) => rol === 'cliente');
  if (esSoloCliente) {
    router.navigate(tienda ? tienda.ruta() : ['/']);
    return;
  }
  router.navigate(['/dashboard']);
}
