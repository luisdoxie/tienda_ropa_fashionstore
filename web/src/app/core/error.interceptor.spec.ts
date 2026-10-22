import { HttpClient, HttpContext, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { errorInterceptor } from './error.interceptor';
import { SIN_TOAST_ERROR } from './http-contexts';

describe('errorInterceptor', () => {
  let http: HttpClient;
  let controller: HttpTestingController;
  let mensajes: MessageService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([errorInterceptor])), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
    mensajes = TestBed.inject(MessageService);
  });

  afterEach(() => controller.verify());

  it('sin el context muestra el toast en un 404', () => {
    const add = vi.spyOn(mensajes, 'add');
    let fallo: unknown = null;
    http.get('/api/x').subscribe({ error: (e) => (fallo = e) });
    controller.expectOne('/api/x').flush({ detail: 'No existe' }, { status: 404, statusText: 'Not Found' });
    expect(add).toHaveBeenCalledTimes(1);
    expect(add.mock.calls[0][0]).toMatchObject({ severity: 'error', detail: 'No existe' });
    expect(fallo).not.toBeNull();
  });

  it('con SIN_TOAST_ERROR no muestra el toast pero propaga el error', () => {
    const add = vi.spyOn(mensajes, 'add');
    let fallo: any = null;
    const context = new HttpContext().set(SIN_TOAST_ERROR, true);
    http.get('/api/x', { context }).subscribe({ error: (e) => (fallo = e) });
    controller.expectOne('/api/x').flush({ detail: 'No existe' }, { status: 404, statusText: 'Not Found' });
    expect(add).not.toHaveBeenCalled();
    expect(fallo?.status).toBe(404);
  });

  it('no muestra toast en un 401', () => {
    const add = vi.spyOn(mensajes, 'add');
    http.get('/api/x').subscribe({ error: () => undefined });
    controller.expectOne('/api/x').flush({}, { status: 401, statusText: 'Unauthorized' });
    expect(add).not.toHaveBeenCalled();
  });
});
