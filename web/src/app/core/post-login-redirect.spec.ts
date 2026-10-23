import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { TiendaActualService } from '../features/tienda/state/tienda-actual.service';
import { AuthService } from './auth.service';
import { navegarDespuesDeLogin } from './post-login-redirect';

describe('navegarDespuesDeLogin', () => {
  let auth: AuthService;
  let router: Router;
  let http: HttpTestingController;
  let navegar: ReturnType<typeof vi.spyOn>;
  let navegarUrl: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()] });
    auth = TestBed.inject(AuthService);
    router = TestBed.inject(Router);
    http = TestBed.inject(HttpTestingController);
    navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    navegarUrl = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  function iniciarSesion(roles: string[], empresaId: number | null): void {
    auth.guardarTokens({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
    auth.cargarUsuarioActual().subscribe();
    http.expectOne((req) => req.url.endsWith('/auth/yo')).flush({
      id: 1,
      nombre: 'Ana',
      apellido: 'Paz',
      email: 'a@b.com',
      telefono: null,
      activo: true,
      roles,
      permisos: [],
      empresa_id: empresaId,
    });
  }

  it('el superadministrador va a /plataforma/empresas', () => {
    iniciarSesion(['superadministrador'], null);
    navegarDespuesDeLogin(router, auth, null);
    expect(navegarUrl).toHaveBeenCalledWith('/plataforma/empresas');
  });

  it('el superadministrador ignora un returnTo que no sea de /plataforma', () => {
    iniciarSesion(['superadministrador'], null);
    navegarDespuesDeLogin(router, auth, '/caja');
    expect(navegarUrl).toHaveBeenCalledWith('/plataforma/empresas');
  });

  it('el superadministrador vuelve a una pantalla de /plataforma', () => {
    iniciarSesion(['superadministrador'], null);
    navegarDespuesDeLogin(router, auth, '/plataforma/planes');
    expect(navegarUrl).toHaveBeenCalledWith('/plataforma/planes');
  });

  it('el personal va a returnTo si lo trae', () => {
    iniciarSesion(['cajero'], 7);
    navegarDespuesDeLogin(router, auth, '/caja');
    expect(navegarUrl).toHaveBeenCalledWith('/caja');
  });

  it('el personal sin returnTo va a /dashboard', () => {
    iniciarSesion(['administrador'], 7);
    navegarDespuesDeLogin(router, auth, null);
    expect(navegar).toHaveBeenCalledWith(['/dashboard']);
  });

  it('el cliente va a la portada de su tienda', () => {
    iniciarSesion(['cliente'], 7);
    const tienda = TestBed.inject(TiendaActualService);
    tienda.fijar('acme', 'lista', { codigo: 'acme', nombre: 'Acme', logo_url: null, color_acento: null });
    navegarDespuesDeLogin(router, auth, null, tienda);
    expect(navegar).toHaveBeenCalledWith(['/t', 'acme']);
  });
});
