import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { environment } from '../../../environments/environment';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';
import { RegistroComponent } from './registro.component';

describe('RegistroComponent (tienda por empresa)', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [RegistroComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    localStorage.clear();
    http.verify();
  });

  function crear() {
    const fixture = TestBed.createComponent(RegistroComponent);
    fixture.detectChanges();
    const comp = fixture.componentInstance as unknown as {
      formulario: { setValue(v: Record<string, string>): void };
      enviar(): void;
      error(): string | null;
    };
    comp.formulario.setValue({
      nombre: 'Ana',
      apellido: 'Paz',
      email: 'ana@b.com',
      telefono: '',
      ciNit: '',
      password: 'secreto123',
    });
    return { fixture, comp };
  }

  it('registra en /public/{codigo}/registro y luego inicia sesión con la empresa de la tienda', () => {
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    const { fixture, comp } = crear();
    expect((fixture.nativeElement as HTMLElement).querySelector('a.acceso-enlace')?.getAttribute('href')).toBe('/t/acme/login');

    comp.enviar();
    const registro = http.expectOne(`${environment.apiUrl}/public/acme/registro`);
    expect(registro.request.body).toMatchObject({ nombre: 'Ana', email: 'ana@b.com', telefono: null, ci_nit: null });
    registro.flush({});

    const login = http.expectOne(`${environment.apiUrl}/auth/login`);
    expect(login.request.body).toEqual({ empresa: 'acme', email: 'ana@b.com', password: 'secreto123' });
  });

  it('sin tienda no llama a la API y muestra un mensaje', () => {
    const { comp } = crear();
    comp.enviar();
    http.expectNone(`${environment.apiUrl}/auth/login`);
    expect(comp.error()).toContain('tienda');
  });

  it('el ojo muestra y oculta la contraseña y avisa su estado con aria-pressed', () => {
    const { fixture } = crear();
    const el = fixture.nativeElement as HTMLElement;
    const clave = () => el.querySelector<HTMLInputElement>('#password')!;
    const ojo = el.querySelector<HTMLButtonElement>('button.fs-campo__accion')!;
    expect(clave().type).toBe('password');
    expect(ojo.getAttribute('aria-pressed')).toBe('false');
    expect(ojo.getAttribute('aria-label')).toBe('Mostrar contraseña');

    ojo.click();
    fixture.detectChanges();

    expect(clave().type).toBe('text');
    expect(ojo.getAttribute('aria-pressed')).toBe('true');
    expect(ojo.getAttribute('aria-label')).toBe('Ocultar contraseña');
  });

  it('la contraseña exige 8 caracteres y el error queda ligado al campo', () => {
    const { fixture, comp } = crear();
    const el = fixture.nativeElement as HTMLElement;
    const formulario = (comp as unknown as { formulario: { controls: Record<string, any>; markAllAsTouched(): void } })
      .formulario;
    formulario.controls['password'].setValue('corta12');
    expect(formulario.controls['password'].hasError('minlength')).toBe(true);
    formulario.controls['password'].setValue('larga-123');
    expect(formulario.controls['password'].valid).toBe(true);

    formulario.controls['password'].setValue('corta12');
    comp.enviar();
    fixture.detectChanges();

    http.expectNone(`${environment.apiUrl}/public/acme/registro`);
    const campo = el.querySelector<HTMLInputElement>('#password')!;
    expect(campo.getAttribute('aria-invalid')).toBe('true');
    expect(campo.getAttribute('aria-describedby')).toContain('error-password');
    const error = el.querySelector('#error-password');
    expect(error?.getAttribute('role')).toBe('alert');
    expect(error?.textContent).toContain('al menos 8 caracteres');
  });

  it('un nombre o un correo inválidos muestran su mensaje y no envían nada', () => {
    const { fixture, comp } = crear();
    const el = fixture.nativeElement as HTMLElement;
    const formulario = (comp as unknown as { formulario: { controls: Record<string, any> } }).formulario;
    formulario.controls['nombre'].setValue('');
    formulario.controls['email'].setValue('no-es-correo');
    comp.enviar();
    fixture.detectChanges();

    http.expectNone(`${environment.apiUrl}/public/acme/registro`);
    expect(el.querySelector('#error-nombre')?.textContent).toContain('Escribe tu nombre.');
    expect(el.querySelector('#error-email')?.textContent).toContain('correo válido');
    expect(el.querySelector('#nombre')?.getAttribute('aria-describedby')).toBe('error-nombre');
    expect(el.querySelector('#email')?.getAttribute('aria-invalid')).toBe('true');
  });

  it('el enlace de iniciar sesión conserva el returnTo', async () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [RegistroComponent],
      providers: [
        provideRouter([{ path: 'registro', component: RegistroComponent }]),
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/registro?returnTo=%2Fcaja', RegistroComponent);
    harness.detectChanges();

    const enlace = (harness.routeNativeElement as HTMLElement).querySelector('a.acceso-enlace');
    expect(enlace?.getAttribute('href')).toBe('/admin/login?returnTo=%2Fcaja');
  });
});
