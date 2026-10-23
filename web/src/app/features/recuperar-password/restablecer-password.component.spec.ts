import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { environment } from '../../../environments/environment';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';
import { RestablecerPasswordComponent } from './restablecer-password.component';

const API = environment.apiUrl;

describe('RestablecerPasswordComponent', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [RestablecerPasswordComponent],
      providers: [
        provideRouter([
          { path: 'restablecer', component: RestablecerPasswordComponent },
          { path: 'admin/login', children: [] },
        ]),
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
    http.verify();
  });

  async function abrir(url: string) {
    const harness = await RouterTestingHarness.create();
    const comp = (await harness.navigateByUrl(url, RestablecerPasswordComponent)) as any;
    harness.detectChanges();
    return { harness, comp, el: harness.routeNativeElement as HTMLElement };
  }

  it('sin token muestra el estado "Enlace inválido" y ofrece pedir uno nuevo', async () => {
    const { el } = await abrir('/restablecer');

    expect(el.querySelector('h1')?.textContent).toContain('Enlace inválido');
    expect(el.textContent).toContain('Solicita uno nuevo');
    expect(el.querySelector('form')).toBeNull();
  });

  it('con token pide dos contraseñas y avisa si no coinciden', async () => {
    const { harness, comp, el } = await abrir('/restablecer?token=abc');

    expect(Array.from(el.querySelectorAll('input')).map((i) => i.id)).toEqual(['password', 'confirmarPassword']);
    comp.formulario.setValue({ password: 'secreto123', confirmarPassword: 'otra-cosa-1' });
    comp.formulario.controls.confirmarPassword.markAsTouched();
    comp.enviar();
    harness.detectChanges();

    http.expectNone(`${API}/auth/recuperar/confirmar`);
    expect(el.textContent).toContain('Las contraseñas no coinciden.');
  });

  it('el ojo del primer campo muestra y oculta las dos contraseñas', async () => {
    const { harness, el } = await abrir('/restablecer?token=abc');
    const tipos = () => Array.from(el.querySelectorAll('input')).map((i) => i.type);
    expect(tipos()).toEqual(['password', 'password']);

    el.querySelector<HTMLButtonElement>('button.fs-campo__accion')!.click();
    harness.detectChanges();

    expect(tipos()).toEqual(['text', 'text']);
  });

  it('al confirmar muestra "Contraseña actualizada" y lleva a ingresar', async () => {
    vi.useFakeTimers();
    const { harness, comp, el } = await abrir('/restablecer?token=abc');
    comp.formulario.setValue({ password: 'secreto123', confirmarPassword: 'secreto123' });
    comp.enviar();

    const req = http.expectOne(`${API}/auth/recuperar/confirmar`);
    expect(req.request.body).toEqual({ token: 'abc', password: 'secreto123' });
    req.flush({ detail: 'ok' });
    harness.detectChanges();

    expect(el.querySelector('h1')?.textContent).toContain('Contraseña actualizada');
    expect(el.textContent).toContain('Ya puedes ingresar con tu nueva contraseña.');
    expect(el.querySelector<HTMLAnchorElement>('a.fs-btn')?.getAttribute('href')).toBe('/admin/login');
    vi.runAllTimers();
  });

  it('un enlace vencido deja el mensaje en pantalla', async () => {
    const { harness, comp, el } = await abrir('/restablecer?token=abc');
    comp.formulario.setValue({ password: 'secreto123', confirmarPassword: 'secreto123' });
    comp.enviar();
    http.expectOne(`${API}/auth/recuperar/confirmar`).flush({ detail: 'x' }, { status: 400, statusText: 'Bad Request' });
    harness.detectChanges();

    expect(el.textContent).toContain('El enlace de recuperación venció o no es válido. Solicita uno nuevo.');
  });

  it('sin tienda (personal) usa la pantalla oscura con la foto de acceso', async () => {
    const conToken = await abrir('/restablecer?token=abc');
    expect(conToken.el.querySelector('.acceso--personal.fs-zona-oscura')).not.toBeNull();
    expect(conToken.el.querySelector('.acceso__foto-img')?.getAttribute('src')).toBe('/imagenes/acceso.png');
    expect(conToken.el.querySelector('button[type="submit"]')?.classList.contains('fs-btn--acento')).toBe(true);

  });

  it('sin tienda y sin token, el estado "Enlace inválido" también es oscuro', async () => {
    const { el } = await abrir('/restablecer');

    expect(el.querySelector('.acceso--personal')).not.toBeNull();
    expect(el.querySelector('a.fs-btn')?.classList.contains('fs-btn--acento')).toBe(true);
  });

  it('con tienda (cliente) usa la pantalla clara con la foto de portada', async () => {
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    const { el } = await abrir('/restablecer?token=abc');

    expect(el.querySelector('.acceso--personal')).toBeNull();
    expect(el.querySelector('header.acceso__cabecera')).not.toBeNull();
    expect(el.querySelector('.acceso__foto-img')?.getAttribute('src')).toBe('/imagenes/portada-tienda.png');
    expect(el.querySelector('button[type="submit"]')?.classList.contains('fs-btn--primario')).toBe(true);
  });

  it('los errores de contraseña quedan ligados a su campo con aria-invalid y aria-describedby', async () => {
    const { harness, comp, el } = await abrir('/restablecer?token=abc');
    comp.formulario.setValue({ password: 'corta', confirmarPassword: '' });
    comp.enviar();
    harness.detectChanges();

    const clave = el.querySelector('#password')!;
    expect(clave.getAttribute('aria-invalid')).toBe('true');
    expect(clave.getAttribute('aria-describedby')).toBe('error-password');
    expect(el.querySelector('#error-password')?.getAttribute('role')).toBe('alert');
    expect(el.querySelector('#error-password')?.textContent).toContain('al menos 8 caracteres');
    const confirmar = el.querySelector('#confirmarPassword')!;
    expect(confirmar.getAttribute('aria-describedby')).toBe('error-confirmar');
    expect(el.querySelector('#error-confirmar')?.textContent).toContain('Repite la contraseña.');
  });

  it('el aviso de contraseñas distintas está ligado al campo de confirmación', async () => {
    const { harness, comp, el } = await abrir('/restablecer?token=abc');
    comp.formulario.setValue({ password: 'secreto123', confirmarPassword: 'otra-cosa-1' });
    comp.formulario.controls.confirmarPassword.markAsTouched();
    harness.detectChanges();

    expect(el.querySelector('#confirmarPassword')?.getAttribute('aria-invalid')).toBe('true');
    expect(el.querySelector('#error-confirmar')?.textContent).toContain('Las contraseñas no coinciden.');
  });

  it('dentro de una tienda muestra su nombre y los enlaces quedan en ella', async () => {
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    const { el } = await abrir('/restablecer?token=abc');

    expect(el.querySelector('.acceso-eyebrow')?.textContent).toContain('Ingresas a Acme');
    expect(el.querySelector('a.acceso-enlace')?.getAttribute('href')).toBe('/t/acme/recuperar');
  });

  it('sin tienda, "pedir un enlace nuevo" lleva a la recuperación del personal (ruta que existe)', async () => {
    const { el } = await abrir('/restablecer?token=abc');

    expect(el.querySelector('a.acceso-enlace')?.getAttribute('href')).toBe('/admin/recuperar');
  });
});
