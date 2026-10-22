import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../environments/environment';
import { authInterceptor } from './auth.interceptor';

describe('authInterceptor', () => {
  let http: HttpClient;
  let controller: HttpTestingController;

  beforeEach(() => {
    localStorage.setItem('fs_access_token', 'token-de-prueba');
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    controller.verify();
    localStorage.clear();
  });

  it('no manda Authorization a las rutas públicas de una tienda', () => {
    http.get(`${environment.apiUrl}/public/acme/catalogo`).subscribe();
    const req = controller.expectOne(`${environment.apiUrl}/public/acme/catalogo`);
    expect(req.request.headers.has('Authorization')).toBe(false);
    req.flush([]);
  });

  it('manda Authorization a una ruta privada', () => {
    http.get(`${environment.apiUrl}/carrito`).subscribe();
    const req = controller.expectOne(`${environment.apiUrl}/carrito`);
    expect(req.request.headers.get('Authorization')).toBe('Bearer token-de-prueba');
    req.flush({});
  });
});
