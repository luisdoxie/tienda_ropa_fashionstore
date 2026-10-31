import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { CopiaDescargada } from '../../../core/models/copias.models';
import { CopiasSeguridadService } from './copias-seguridad.service';

const BASE = `${environment.apiUrl}/copias-seguridad`;
const SHA = 'a'.repeat(63) + 'B';

describe('CopiasSeguridadService', () => {
  let servicio: CopiasSeguridadService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    servicio = TestBed.inject(CopiasSeguridadService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  describe('crear', () => {
    it('hace POST sin cuerpo, pide un blob con la respuesta completa y no muestra el toast global', () => {
      servicio.crear().subscribe();
      const req = http.expectOne(BASE);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toBeNull();
      expect(req.request.responseType).toBe('blob');
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush(new Blob(['zip']));
    });

    it('devuelve el blob con el nombre, el id y el checksum de las cabeceras', () => {
      let copia: CopiaDescargada | undefined;
      servicio.crear().subscribe((c) => (copia = c));
      http.expectOne(BASE).flush(new Blob(['zip']), {
        headers: {
          'Content-Disposition': 'attachment; filename="fashionstore-boutique-20261030-1405.zip"',
          'X-Copia-Id': '42',
          'X-Checksum-SHA256': SHA,
          'Content-Type': 'application/zip',
        },
      });
      expect(copia?.nombre).toBe('fashionstore-boutique-20261030-1405.zip');
      expect(copia?.copiaId).toBe(42);
      expect(copia?.checksum).toBe(SHA.toLowerCase());
      expect(copia?.blob.size).toBe(3);
    });

    it('sin cabeceras arma un nombre legible y deja el id y el checksum en null', () => {
      let copia: CopiaDescargada | undefined;
      servicio.crear().subscribe((c) => (copia = c));
      http.expectOne(BASE).flush(new Blob(['zip']));
      expect(copia?.nombre).toMatch(/^fashionstore-copia-\d{8}-\d{4}\.zip$/);
      expect(copia?.copiaId).toBeNull();
      expect(copia?.checksum).toBeNull();
    });

    it('descarta un checksum que no tiene forma de SHA-256 y un nombre con rutas', () => {
      let copia: CopiaDescargada | undefined;
      servicio.crear().subscribe((c) => (copia = c));
      http.expectOne(BASE).flush(new Blob(['zip']), {
        headers: {
          'Content-Disposition': 'attachment; filename="../../x.zip"',
          'X-Checksum-SHA256': '<script>',
          'X-Copia-Id': 'abc',
        },
      });
      expect(copia?.checksum).toBeNull();
      expect(copia?.copiaId).toBeNull();
      expect(copia?.nombre).not.toContain('/');
    });

    it('un error llega como Blob para que la pantalla lo lea', () => {
      let fallo: unknown;
      servicio.crear().subscribe({ error: (e) => (fallo = e) });
      http
        .expectOne(BASE)
        .flush(new Blob([JSON.stringify({ codigo: 'copia_en_curso' })]), { status: 409, statusText: 'Conflict' });
      expect(fallo).toBeDefined();
    });
  });

  describe('listar', () => {
    it('pide la página y el tamaño por query y sin el toast global', () => {
      servicio.listar(2, 10).subscribe();
      const req = http.expectOne((r) => r.url === BASE);
      expect(req.request.method).toBe('GET');
      expect(req.request.params.get('pagina')).toBe('2');
      expect(req.request.params.get('tamanio')).toBe('10');
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush({ total: 0, pagina: 2, tamanio: 10, items: [] });
    });

    it('por defecto pide la página 1 de 20', () => {
      servicio.listar().subscribe();
      const req = http.expectOne((r) => r.url === BASE);
      expect(req.request.params.get('pagina')).toBe('1');
      expect(req.request.params.get('tamanio')).toBe('20');
      req.flush({ total: 0, pagina: 1, tamanio: 20, items: [] });
    });
  });

  it('tablas pide GET /tablas sin el toast global', () => {
    servicio.tablas().subscribe();
    const req = http.expectOne(`${BASE}/tablas`);
    expect(req.request.method).toBe('GET');
    expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    req.flush({ incluidas: [], referencias: [], excluidas: [], columnas_excluidas: {} });
  });
});
