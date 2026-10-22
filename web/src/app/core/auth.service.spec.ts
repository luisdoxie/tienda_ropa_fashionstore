import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { environment } from '../../environments/environment';
import { TiendaActualService } from '../features/tienda/state/tienda-actual.service';
import { AuthService } from './auth.service';

const API = environment.apiUrl;

describe('AuthService (tienda por empresa)', () => {
  let auth: AuthService;
  let tienda: TiendaActualService;
  let http: HttpTestingController;
  let router: Router;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    auth = TestBed.inject(AuthService);
    tienda = TestBed.inject(TiendaActualService);
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    http.verify();
  });

  function fijarAcme(): void {
    tienda.fijar('acme', 'lista', { codigo: 'acme', nombre: 'Acme', logo_url: null, color_acento: null });
  }

  describe('login', () => {
    it('manda la empresa en el cuerpo cuando viene', () => {
      auth.login('a@b.com', 'secreto123', 'acme').subscribe();
      const req = http.expectOne(`${API}/auth/login`);
      expect(req.request.body).toEqual({ empresa: 'acme', email: 'a@b.com', password: 'secreto123' });
      req.flush({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
    });

    it('sin tercer parámetro NO manda el campo empresa', () => {
      auth.login('a@b.com', 'secreto123').subscribe();
      const req = http.expectOne(`${API}/auth/login`);
      expect(req.request.body).toEqual({ email: 'a@b.com', password: 'secreto123' });
      expect('empresa' in req.request.body).toBe(false);
      req.flush({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
    });

    it('con empresa vacía o null tampoco manda el campo', () => {
      auth.login('a@b.com', 'x', '').subscribe();
      auth.login('a@b.com', 'x', null).subscribe();
      const reqs = http.match(`${API}/auth/login`);
      expect(reqs).toHaveLength(2);
      for (const req of reqs) {
        expect('empresa' in req.request.body).toBe(false);
        req.flush({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
      }
    });
  });

  it('registrar usa /public/{codigo}/registro', () => {
    const datos = { nombre: 'Ana', apellido: 'Paz', email: 'ana@b.com', telefono: null, ci_nit: null, password: 'secreto123' };
    auth.registrar(datos, 'acme').subscribe();
    const req = http.expectOne(`${API}/public/acme/registro`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(datos);
    req.flush({});
  });

  describe('solicitarRecuperacion', () => {
    it('manda la empresa cuando viene', () => {
      auth.solicitarRecuperacion('a@b.com', 'acme').subscribe();
      const req = http.expectOne(`${API}/auth/recuperar`);
      expect(req.request.body).toEqual({ email: 'a@b.com', empresa: 'acme' });
      req.flush({ detail: 'ok' });
    });

    it('sin empresa manda solo el email', () => {
      auth.solicitarRecuperacion('a@b.com').subscribe();
      const req = http.expectOne(`${API}/auth/recuperar`);
      expect(req.request.body).toEqual({ email: 'a@b.com' });
      req.flush({ detail: 'ok' });
    });
  });

  it('confirmarRecuperacion manda solo token y password (sin empresa)', () => {
    auth.confirmarRecuperacion('tok', 'nueva1234').subscribe();
    const req = http.expectOne(`${API}/auth/recuperar/confirmar`);
    expect(req.request.body).toEqual({ token: 'tok', password: 'nueva1234' });
    req.flush({ detail: 'ok' });
  });

  describe('logout', () => {
    it('dentro de una tienda navega a /t/acme/login', () => {
      fijarAcme();
      const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);
      auth.logout();
      expect(navegar).toHaveBeenCalledWith(['/t', 'acme', 'login']);
    });

    it('sin tienda navega a /login', () => {
      const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);
      auth.logout();
      expect(navegar).toHaveBeenCalledWith(['/login']);
    });

    it('limpia los tokens guardados', () => {
      localStorage.setItem('fs_access_token', 'a');
      localStorage.setItem('fs_refresh_token', 'r');
      vi.spyOn(router, 'navigate').mockResolvedValue(true);
      auth.logout();
      expect(localStorage.getItem('fs_access_token')).toBeNull();
      expect(localStorage.getItem('fs_refresh_token')).toBeNull();
    });
  });
});
