import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../../environments/environment';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';
import { LoginComponent } from './login.component';

describe('LoginComponent (tienda por empresa)', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [LoginComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    localStorage.clear();
    http.verify();
  });

  function enviar(): HTMLElement {
    const fixture = TestBed.createComponent(LoginComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const comp = fixture.componentInstance as unknown as {
      formulario: { setValue(v: { email: string; password: string }): void };
      enviar(): void;
    };
    comp.formulario.setValue({ email: 'a@b.com', password: 'secreto123' });
    comp.enviar();
    return el;
  }

  it('dentro de una tienda envía su código como empresa y muestra su nombre', () => {
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    const el = enviar();
    const req = http.expectOne(`${environment.apiUrl}/auth/login`);
    expect(req.request.body).toEqual({ empresa: 'acme', email: 'a@b.com', password: 'secreto123' });
    expect(el.querySelector('.auth-marca')?.textContent).toContain('Ingresás a Acme');
    const enlaces = Array.from(el.querySelectorAll('a.auth-enlace')).map((a) => a.getAttribute('href'));
    expect(enlaces).toEqual(['/t/acme/recuperar', '/t/acme/registro']);
  });

  it('sin tienda (login del personal) no envía empresa y mantiene los enlaces de siempre', () => {
    const el = enviar();
    const req = http.expectOne(`${environment.apiUrl}/auth/login`);
    expect('empresa' in req.request.body).toBe(false);
    expect(el.querySelector('.auth-marca')?.textContent).toContain('FashionStore');
    const enlaces = Array.from(el.querySelectorAll('a.auth-enlace')).map((a) => a.getAttribute('href'));
    expect(enlaces).toEqual(['/recuperar', '/registro']);
  });
});
