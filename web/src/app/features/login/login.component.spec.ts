import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { environment } from '../../../environments/environment';
import { routes } from '../../app.routes';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';
import {
  CLAVE_ULTIMA_EMPRESA_PERSONAL,
  LoginComponent,
  MENSAJE_CUENTA_DE_CLIENTE,
  MENSAJE_LOGIN_PERSONAL,
  MENSAJE_SUSCRIPCION_INACTIVA,
} from './login.component';

const API = environment.apiUrl;

describe('LoginComponent', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness | undefined;

  beforeEach(() => {
    harness = undefined;
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [LoginComponent],
      providers: [
        provideRouter([
          { path: 'admin/login', data: { modo: 'personal' }, component: LoginComponent },
          { path: 't/:codigo/login', data: { modo: 'cliente' }, component: LoginComponent },
          { path: 'dashboard', children: [] },
          { path: 'plataforma/empresas', children: [] },
          { path: 'caja', children: [] },
        ]),
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    localStorage.clear();
    http.verify();
  });

  async function abrir(url: string): Promise<{ el: HTMLElement; comp: any }> {
    harness ??= await RouterTestingHarness.create();
    const comp = await harness.navigateByUrl(url, LoginComponent);
    harness!.detectChanges();
    return { el: harness.routeNativeElement as HTMLElement, comp };
  }

  function llenar(comp: any, valores: Record<string, string>): void {
    comp.formulario.patchValue(valores);
  }

  function responderSesion(roles: string[], empresaId: number | null): void {
    http.expectOne(`${API}/auth/login`).flush({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
    http.expectOne(`${API}/auth/yo`).flush({
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

  function botonPlataforma(el: HTMLElement): HTMLButtonElement {
    return el.querySelector('button.acceso-enlace') as HTMLButtonElement;
  }

  describe('login de una tienda (comprador)', () => {
    it('envía su código como empresa y muestra su nombre', async () => {
      TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
        codigo: 'acme',
        nombre: 'Acme',
        logo_url: null,
        color_acento: null,
      });
      const { el, comp } = await abrir('/t/acme/login');
      llenar(comp, { email: 'a@b.com', password: 'secreto123' });
      comp.enviar();

      const req = http.expectOne(`${API}/auth/login`);
      expect(req.request.body).toEqual({ empresa: 'acme', email: 'a@b.com', password: 'secreto123' });
      expect(el.querySelector('.acceso-eyebrow')?.textContent).toContain('Ingresas a Acme');
      expect(el.querySelector('#empresa')).toBeNull();
      const enlaces = Array.from(el.querySelectorAll('a.acceso-enlace')).map((a) => a.getAttribute('href'));
      expect(enlaces).toEqual(['/t/acme/recuperar', '/t/acme/registro']);
    });
  });

  describe('login del personal (/admin/login)', () => {
    it('pide la empresa arriba del correo y no tiene enlace de registro', async () => {
      const { el } = await abrir('/admin/login');

      expect(Array.from(el.querySelectorAll('input')).map((i) => i.id)).toEqual(['empresa', 'email', 'password']);
      const enlaces = Array.from(el.querySelectorAll('a.acceso-enlace')).map((a) => a.getAttribute('href'));
      expect(enlaces).toEqual(['/admin/recuperar']);
      expect(botonPlataforma(el).textContent).toContain('Soy administrador de la plataforma');
    });

    it('el ojo muestra y oculta la contraseña', async () => {
      const { el } = await abrir('/admin/login');
      const clave = () => el.querySelector<HTMLInputElement>('#password')!;
      const ojo = el.querySelector<HTMLButtonElement>('button.fs-campo__accion')!;
      expect(clave().type).toBe('password');
      expect(ojo.getAttribute('aria-label')).toBe('Mostrar contraseña');

      ojo.click();
      harness!.detectChanges();

      expect(clave().type).toBe('text');
      expect(ojo.getAttribute('aria-label')).toBe('Ocultar contraseña');
    });

    it('el texto del titular cambia entre empresa y administrador de la plataforma', async () => {
      const { el } = await abrir('/admin/login');
      expect(el.querySelector('.acceso-titular')?.textContent).toContain('Inicia sesión con tu empresa para continuar.');

      botonPlataforma(el).click();
      harness!.detectChanges();

      expect(el.querySelector('.acceso-titular')?.textContent).toContain(
        'Inicia sesión como administrador de la plataforma.',
      );
    });

    it('exige la empresa: sin ella no envía nada', async () => {
      const { comp } = await abrir('/admin/login');
      llenar(comp, { email: 'a@b.com', password: 'secreto123' });
      comp.enviar();

      http.expectNone(`${API}/auth/login`);
      expect(comp.formulario.controls.empresa.invalid).toBe(true);
    });

    it('una empresa de solo espacios no se envía (no se confunde con el superadministrador)', async () => {
      const { el, comp } = await abrir('/admin/login');
      llenar(comp, { empresa: '   ', email: 'a@b.com', password: 'secreto123' });
      comp.enviar();
      harness!.detectChanges();

      http.expectNone(`${API}/auth/login`);
      expect(comp.formulario.controls.empresa.invalid).toBe(true);
      const campo = el.querySelector('#empresa')!;
      expect(campo.getAttribute('aria-invalid')).toBe('true');
      expect(campo.getAttribute('aria-describedby')).toBe('error-empresa');
      expect(el.querySelector('#error-empresa')?.getAttribute('role')).toBe('alert');
    });

    it('correo y contraseña inválidos muestran su mensaje ligado al campo', async () => {
      const { el, comp } = await abrir('/admin/login');
      llenar(comp, { empresa: 'acme', email: 'no-es-correo', password: '' });
      comp.enviar();
      harness!.detectChanges();

      http.expectNone(`${API}/auth/login`);
      expect(el.querySelector('#email')?.getAttribute('aria-describedby')).toBe('error-email');
      expect(el.querySelector('#error-email')?.textContent).toContain('correo válido');
      expect(el.querySelector('#password')?.getAttribute('aria-describedby')).toBe('error-password');
      expect(el.querySelector('#error-password')?.textContent).toContain('Escribe tu contraseña.');
    });

    it('usa la pantalla oscura, con un solo h1 y el titular de la foto oculto a lectores', async () => {
      const { el } = await abrir('/admin/login');

      expect(el.querySelector('.acceso--personal.fs-zona-oscura')).not.toBeNull();
      expect(el.querySelectorAll('h1').length).toBe(1);
      expect(el.querySelector('.acceso-foto-titular')?.getAttribute('aria-hidden')).toBe('true');
      expect(el.querySelector('.acceso__foto h1, .acceso__foto h2')).toBeNull();
    });

    it('envía empresa, correo y clave', async () => {
      const { comp } = await abrir('/admin/login');
      llenar(comp, { empresa: ' Boutique Andina ', email: 'a@b.com', password: 'secreto123' });
      comp.enviar();

      const req = http.expectOne(`${API}/auth/login`);
      expect(req.request.body).toEqual({ empresa: 'Boutique Andina', email: 'a@b.com', password: 'secreto123' });
    });

    it('recuerda la última empresa tras entrar y la propone la próxima vez', async () => {
      const primera = await abrir('/admin/login');
      llenar(primera.comp, { empresa: 'Boutique Andina', email: 'a@b.com', password: 'secreto123' });
      primera.comp.enviar();
      responderSesion(['administrador'], 7);
      await harness!.fixture.whenStable();

      expect(localStorage.getItem(CLAVE_ULTIMA_EMPRESA_PERSONAL)).toBe('Boutique Andina');

      const segunda = await abrir('/admin/login');
      expect(segunda.comp.formulario.controls.empresa.value).toBe('Boutique Andina');
    });

    it('"Soy administrador de la plataforma" oculta Empresa y envía el login sin empresa', async () => {
      const { el, comp } = await abrir('/admin/login');
      botonPlataforma(el).click();
      harness!.detectChanges();

      expect(el.querySelector('#empresa')).toBeNull();
      expect(botonPlataforma(el).textContent).toContain('Volver a ingresar con una empresa');

      llenar(comp, { email: 'root@x.com', password: 'una-clave-larga-123' });
      comp.enviar();
      const req = http.expectOne(`${API}/auth/login`);
      expect('empresa' in req.request.body).toBe(false);
      expect(req.request.body).toEqual({ email: 'root@x.com', password: 'una-clave-larga-123' });
    });

    it('volver a "ingresar con una empresa" vuelve a exigirla', async () => {
      const { el, comp } = await abrir('/admin/login');
      botonPlataforma(el).click();
      botonPlataforma(el).click();
      harness!.detectChanges();

      expect(el.querySelector('#empresa')).not.toBeNull();
      llenar(comp, { email: 'a@b.com', password: 'secreto123' });
      comp.enviar();
      http.expectNone(`${API}/auth/login`);
    });

    it('un superadministrador entra a /plataforma/empresas', async () => {
      const { el, comp } = await abrir('/admin/login');
      botonPlataforma(el).click();
      llenar(comp, { email: 'root@x.com', password: 'una-clave-larga-123' });
      comp.enviar();
      responderSesion(['superadministrador'], null);
      await harness!.fixture.whenStable();

      expect(TestBed.inject(Router).url).toBe('/plataforma/empresas');
    });

    it('un administrador de empresa entra a /dashboard', async () => {
      const { comp } = await abrir('/admin/login');
      llenar(comp, { empresa: 'acme', email: 'a@b.com', password: 'secreto123' });
      comp.enviar();
      responderSesion(['administrador'], 7);
      await harness!.fixture.whenStable();

      expect(TestBed.inject(Router).url).toBe('/dashboard');
    });

    it('con returnTo vuelve a esa pantalla', async () => {
      const { comp } = await abrir('/admin/login?returnTo=%2Fcaja');
      llenar(comp, { empresa: 'acme', email: 'a@b.com', password: 'secreto123' });
      comp.enviar();
      responderSesion(['cajero'], 7);
      await harness!.fixture.whenStable();

      expect(TestBed.inject(Router).url).toBe('/caja');
    });

    it('una cuenta de cliente no entra: se cierra la sesión y se explica', async () => {
      const { comp } = await abrir('/admin/login');
      llenar(comp, { empresa: 'acme', email: 'c@b.com', password: 'secreto123' });
      comp.enviar();
      responderSesion(['cliente'], 7);
      await harness!.fixture.whenStable();

      expect(comp.errorLogin()).toBe(MENSAJE_CUENTA_DE_CLIENTE);
      expect(localStorage.getItem('fs_access_token')).toBeNull();
      expect(localStorage.getItem(CLAVE_ULTIMA_EMPRESA_PERSONAL)).toBeNull();
      expect(TestBed.inject(Router).url).toBe('/admin/login');
    });

    it('credenciales incorrectas: un solo mensaje que no revela qué falló', async () => {
      const { comp } = await abrir('/admin/login');
      llenar(comp, { empresa: 'no-existe', email: 'a@b.com', password: 'mala' });
      comp.enviar();
      http
        .expectOne(`${API}/auth/login`)
        .flush({ detail: 'Credenciales inválidas' }, { status: 401, statusText: 'Unauthorized' });

      expect(comp.errorLogin()).toBe(MENSAJE_LOGIN_PERSONAL);
      expect(MENSAJE_LOGIN_PERSONAL).toBe('Empresa, correo o contraseña incorrectos.');
    });

    it('el error se muestra en pantalla como alerta', async () => {
      const { el, comp } = await abrir('/admin/login');
      llenar(comp, { empresa: 'acme', email: 'a@b.com', password: 'mala' });
      comp.enviar();
      http.expectOne(`${API}/auth/login`).flush({ detail: 'x' }, { status: 401, statusText: 'Unauthorized' });
      harness!.detectChanges();

      expect(el.querySelector('[role="alert"]')?.textContent).toContain(MENSAJE_LOGIN_PERSONAL);
    });

    it('403 con suscripcion_no_activa muestra su mensaje', async () => {
      const { comp } = await abrir('/admin/login');
      llenar(comp, { empresa: 'acme', email: 'a@b.com', password: 'secreto123' });
      comp.enviar();
      http
        .expectOne(`${API}/auth/login`)
        .flush(
          { detail: 'suscripcion_no_activa', codigo: 'suscripcion_no_activa', mensaje: 'x', estado: 'vencida' },
          { status: 403, statusText: 'Forbidden' },
        );

      expect(comp.errorLogin()).toBe(MENSAJE_SUSCRIPCION_INACTIVA);
    });

    it('429 explica que son demasiados intentos', async () => {
      const { comp } = await abrir('/admin/login');
      llenar(comp, { empresa: 'acme', email: 'a@b.com', password: 'secreto123' });
      comp.enviar();
      http.expectOne(`${API}/auth/login`).flush({ detail: 'x' }, { status: 429, statusText: 'Too Many Requests' });

      expect(comp.errorLogin()).toContain('Demasiados intentos');
    });
  });

  describe('direcciones de antes', () => {
    it('/login redirige a /admin/login conservando el returnTo', async () => {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [provideRouter(routes), provideHttpClient(), provideHttpClientTesting()],
      });
      http = TestBed.inject(HttpTestingController);
      const arnes = await RouterTestingHarness.create();
      await arnes.navigateByUrl('/login?returnTo=%2Fcaja');

      expect(TestBed.inject(Router).url).toBe('/admin/login?returnTo=%2Fcaja');
    });
  });
});
