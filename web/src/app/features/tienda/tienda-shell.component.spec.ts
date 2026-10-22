import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { UsuarioYo } from '../../core/models/seguridad.models';
import { TiendaShellComponent } from './tienda-shell.component';
import { TiendaActualService } from './state/tienda-actual.service';

function usuario(empresaCodigo: string): UsuarioYo {
  return {
    id: 1,
    nombre: 'Ana',
    apellido: 'Pérez',
    email: 'ana@example.com',
    telefono: null,
    activo: true,
    roles: ['cliente'],
    permisos: [],
    empresa_id: 7,
    empresa_codigo: empresaCodigo,
  };
}

describe('TiendaShellComponent', () => {
  let http: HttpTestingController;

  function iniciarSesion(empresaCodigo: string): void {
    const auth = TestBed.inject(AuthService);
    auth.cargarUsuarioActual().subscribe();
    http.expectOne((peticion) => peticion.url.endsWith('/auth/yo')).flush(usuario(empresaCodigo));
  }

  function crear(): HTMLElement {
    const fixture = TestBed.createComponent(TiendaShellComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [TiendaShellComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
  });

  afterEach(() => localStorage.clear());

  it('muestra el nombre de la tienda como logo y apunta a su portada', () => {
    const el = crear();
    const logo = el.querySelector('a.tienda-logo') as HTMLAnchorElement;

    expect(logo.textContent?.trim()).toBe('Acme');
    expect(logo.getAttribute('href')).toBe('/t/acme');
    expect(el.querySelector('footer.tienda-pie')?.textContent).toContain('Con la tecnología de FashionStore');
  });

  it('con sesión de otra empresa muestra "Iniciar sesión"', () => {
    iniciarSesion('otra');
    const el = crear();
    const texto = el.textContent ?? '';

    expect(texto).toContain('Iniciar sesión');
    expect(texto).not.toContain('Mis compras');
    const login = Array.from(el.querySelectorAll('a')).find((a) => a.textContent?.includes('Iniciar sesión'));
    expect(login?.getAttribute('href')).toBe('/t/acme/login');
  });

  it('con sesión de la misma empresa muestra "Mis compras"', () => {
    iniciarSesion('acme');
    const el = crear();
    const texto = el.textContent ?? '';

    expect(texto).toContain('Mis compras');
    expect(texto).not.toContain('Iniciar sesión');
    const compras = Array.from(el.querySelectorAll('a')).find((a) => a.textContent?.includes('Mis compras'));
    expect(compras?.getAttribute('href')).toBe('/t/acme/mis-compras');
    // El efecto del carrito pide el carrito de esta tienda; no hace falta responderlo.
    http.match((peticion) => peticion.url.endsWith('/carrito'));
  });

  it('muestra el logo si hay logo_url http(s) y vuelve al nombre si falla', () => {
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: 'https://cdn.example.com/acme.png',
      color_acento: null,
    });
    const fixture = TestBed.createComponent(TiendaShellComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    const img = el.querySelector('a.tienda-logo img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('https://cdn.example.com/acme.png');
    expect(img.getAttribute('alt')).toBe('Acme');

    img.dispatchEvent(new Event('error'));
    fixture.detectChanges();

    expect(el.querySelector('a.tienda-logo img')).toBeNull();
    expect(el.querySelector('a.tienda-logo')?.textContent?.trim()).toBe('Acme');
  });
});
