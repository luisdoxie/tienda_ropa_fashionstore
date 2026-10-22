import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { MessageService } from 'primeng/api';
import { CarritoService } from '../features/tienda/data/carrito.service';
import { TiendaActualService } from '../features/tienda/state/tienda-actual.service';
import { AuthService } from './auth.service';

/** Código de tienda al comienzo de una URL del comprador: /t/:codigo/... */
const PATRON_TIENDA = /^\/t\/([^/?#]+)/;

export const authGuard: CanActivateFn = (_route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.estaAutenticado()) {
    return true;
  }
  const coincidencia = PATRON_TIENDA.exec(state.url);
  if (coincidencia) {
    return router.createUrlTree(['/t', decodeURIComponent(coincidencia[1]), 'login'], {
      queryParams: { returnTo: state.url },
    });
  }
  return router.createUrlTree(['/login'], { queryParams: { returnTo: state.url } });
};

/**
 * Va después de `authGuard` en las rutas privadas de /t/:codigo. La sesión es
 * de UNA empresa: si el comprador entra a otra tienda (o es superadministrador,
 * sin empresa), se cierra la sesión y se lo manda a ingresar en esta tienda.
 * Mirar el catálogo es público y nunca pasa por acá.
 */
export const tiendaSesionGuard: CanActivateFn = (_route, state) => {
  const authService = inject(AuthService);
  const tienda = inject(TiendaActualService);
  const router = inject(Router);

  const codigo = tienda.codigo();
  if (codigo === null) {
    return true;
  }
  if (!authService.estaAutenticado() || authService.empresaCodigo() === codigo) {
    return true;
  }

  authService.limpiarSesion();
  inject(CarritoService).limpiar();
  const nombre = tienda.empresa()?.nombre ?? codigo;
  inject(MessageService).add({
    severity: 'info',
    summary: 'Sesión cerrada',
    detail: `Cerramos tu sesión porque entraste a otra tienda. Ingresá con tu cuenta de ${nombre}.`,
  });
  return router.createUrlTree(['/t', codigo, 'login'], { queryParams: { returnTo: state.url } });
};

/** Guarda de ruta por permiso (p. ej. "roles.gestionar"). */
export function permisoGuard(permiso: string): CanActivateFn {
  return () => {
    const authService = inject(AuthService);
    const router = inject(Router);

    if (!authService.estaAutenticado()) {
      return router.parseUrl('/login');
    }
    if (!authService.tienePermiso(permiso)) {
      return router.parseUrl('/dashboard');
    }
    return true;
  };
}

/**
 * Protege la raíz del back office: un cliente autenticado (rol único
 * "cliente") nunca debe ver ninguna pantalla de administración, ni
 * escribiendo la URL a mano. Reemplaza a `authGuard` en esa ruta.
 */
export const staffGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.estaAutenticado()) {
    return router.parseUrl('/login');
  }
  const roles = authService.roles();
  // Sin ningún rol de staff (incluye roles.length === 0, un usuario
  // logueado cuya asignación de roles quedó desincronizada) no hay nada
  // que autorice el back office -- antes, roles.length === 0 caía al
  // `return true` final y dejaba entrar a cualquiera sin permisos reales.
  const esStaff = roles.some((rol) => rol !== 'cliente');
  if (!esStaff) {
    const ultima = inject(TiendaActualService).ultimaTienda();
    return router.createUrlTree(ultima ? ['/t', ultima] : ['/']);
  }
  return true;
};
