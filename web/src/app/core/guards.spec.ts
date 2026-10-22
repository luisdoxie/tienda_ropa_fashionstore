import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, CanActivateFn, Router, RouterStateSnapshot, UrlTree, provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { CLAVE_ULTIMA_TIENDA, TiendaActualService } from '../features/tienda/state/tienda-actual.service';
import { AuthService } from './auth.service';
import { UsuarioYo } from './models/seguridad.models';
import { authGuard, staffGuard, tiendaSesionGuard } from './guards';

function usuario(roles: string[], empresaCodigo: string | null): UsuarioYo {
  return {
    id: 1,
    nombre: 'Ana',
    apellido: 'Pérez',
    email: 'ana@example.com',
    telefono: null,
    activo: true,
    roles,
    permisos: [],
    empresa_id: empresaCodigo === null ? null : 7,
    empresa_codigo: empresaCodigo,
  };
}

describe('guards', () => {
  let auth: AuthService;
  let http: HttpTestingController;
  let router: Router;
  let mensajes: MessageService;

  const ruta = {} as ActivatedRouteSnapshot;
  const estado = (url: string) => ({ url }) as RouterStateSnapshot;
  const ejecutar = (guard: CanActivateFn, url: string) =>
    TestBed.runInInjectionContext(() => guard(ruta, estado(url)));

  function iniciarSesion(datos: UsuarioYo): void {
    auth.guardarTokens({ access_token: 'acceso', refresh_token: 'refresco' } as never);
    auth.cargarUsuarioActual().subscribe();
    http.expectOne((peticion) => peticion.url.endsWith('/auth/yo')).flush(datos);
  }

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    auth = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    mensajes = TestBed.inject(MessageService);
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
  });

  afterEach(() => localStorage.clear());

  describe('tiendaSesionGuard', () => {
    it('cierra la sesión de otra empresa y redirige al login de la tienda', () => {
      iniciarSesion(usuario(['cliente'], 'otra'));
      const agregar = vi.spyOn(mensajes, 'add');

      const resultado = ejecutar(tiendaSesionGuard, '/t/acme/carrito');

      expect(resultado).toBeInstanceOf(UrlTree);
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/t/acme/login?returnTo=%2Ft%2Facme%2Fcarrito');
      expect(auth.estaAutenticado()).toBe(false);
      expect(auth.getAccessToken()).toBeNull();
      expect(agregar).toHaveBeenCalledWith(
        expect.objectContaining({
          severity: 'info',
          summary: 'Sesión cerrada',
          detail: 'Cerramos tu sesión porque entraste a otra tienda. Ingresá con tu cuenta de Acme.',
        }),
      );
    });

    it('cierra la sesión de un superadministrador (sin empresa)', () => {
      iniciarSesion(usuario(['superadministrador'], null));

      const resultado = ejecutar(tiendaSesionGuard, '/t/acme/mis-compras');

      expect(router.serializeUrl(resultado as UrlTree)).toBe('/t/acme/login?returnTo=%2Ft%2Facme%2Fmis-compras');
      expect(auth.estaAutenticado()).toBe(false);
    });

    it('deja pasar a quien tiene sesión de la misma empresa', () => {
      iniciarSesion(usuario(['cliente'], 'acme'));

      expect(ejecutar(tiendaSesionGuard, '/t/acme/carrito')).toBe(true);
      expect(auth.estaAutenticado()).toBe(true);
    });
  });

  describe('authGuard', () => {
    it('sin sesión en una tienda va al login de esa tienda', () => {
      const resultado = ejecutar(authGuard, '/t/acme/carrito?x=1');

      expect(router.serializeUrl(resultado as UrlTree)).toBe(
        '/t/acme/login?returnTo=%2Ft%2Facme%2Fcarrito%3Fx%3D1',
      );
    });

    it('sin sesión fuera de una tienda va a /login', () => {
      const resultado = ejecutar(authGuard, '/dashboard');

      expect(router.serializeUrl(resultado as UrlTree)).toBe('/login?returnTo=%2Fdashboard');
    });

    it('con sesión devuelve true', () => {
      iniciarSesion(usuario(['cliente'], 'acme'));

      expect(ejecutar(authGuard, '/t/acme/carrito')).toBe(true);
    });
  });

  describe('staffGuard', () => {
    it('manda al cliente a la última tienda', () => {
      localStorage.setItem(CLAVE_ULTIMA_TIENDA, 'acme');
      iniciarSesion(usuario(['cliente'], 'acme'));

      const resultado = ejecutar(staffGuard, '/dashboard');

      expect(router.serializeUrl(resultado as UrlTree)).toBe('/t/acme');
    });

    it('manda al cliente a / si no hay última tienda', () => {
      iniciarSesion(usuario(['cliente'], 'acme'));
      localStorage.removeItem(CLAVE_ULTIMA_TIENDA);

      const resultado = ejecutar(staffGuard, '/dashboard');

      expect(router.serializeUrl(resultado as UrlTree)).toBe('/');
    });

    it('deja pasar al staff', () => {
      iniciarSesion(usuario(['administrador'], 'acme'));

      expect(ejecutar(staffGuard, '/dashboard')).toBe(true);
    });
  });
});
