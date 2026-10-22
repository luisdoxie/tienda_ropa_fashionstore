import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
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
    expect((fixture.nativeElement as HTMLElement).querySelector('a.auth-enlace')?.getAttribute('href')).toBe('/t/acme/login');

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
});
