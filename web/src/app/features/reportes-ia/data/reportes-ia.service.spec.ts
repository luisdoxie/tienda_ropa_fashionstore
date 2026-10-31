import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { SolicitudResuelta } from '../../../core/models/reportes-ia.models';
import { ReportesIaService, nombreDeContentDisposition } from './reportes-ia.service';

const BASE = `${environment.apiUrl}/reportes-ia`;

const resuelta: SolicitudResuelta = {
  tipo_reporte: 'ventas_por_sucursal',
  periodo: { desde: '2026-09-01', hasta: '2026-09-30', etiqueta: 'septiembre de 2026' },
  sucursales: [],
  categorias: [],
  productos: [],
  canal: null,
  agrupacion: null,
  orden: null,
  limite: null,
  horizonte_semanas: null,
};

describe('ReportesIaService', () => {
  let servicio: ReportesIaService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    servicio = TestBed.inject(ReportesIaService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('catalogo pide GET /catalogo sin el toast global', () => {
    servicio.catalogo().subscribe();
    const req = http.expectOne(`${BASE}/catalogo`);
    expect(req.request.method).toBe('GET');
    expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    req.flush([]);
  });

  it('ejecutar con texto manda solo el texto y su origen', () => {
    servicio.ejecutar({ texto: 'ventas de septiembre', origen: 'voz' }).subscribe();
    const req = http.expectOne(`${BASE}/ejecutar`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ texto: 'ventas de septiembre', origen: 'voz' });
    expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    req.flush({ estado: 'ok' });
  });

  it('ejecutar con una solicitud ya armada no manda texto', () => {
    servicio.ejecutar({ solicitud: { tipo_reporte: 'ventas_por_sucursal' } }).subscribe();
    const req = http.expectOne(`${BASE}/ejecutar`);
    expect(req.request.body).toEqual({ solicitud: { tipo_reporte: 'ventas_por_sucursal' } });
    req.flush({ estado: 'ok' });
  });

  describe('exportar', () => {
    it('pide un blob y toma el nombre de Content-Disposition', () => {
      let archivo: { blob: Blob; nombre: string } | undefined;
      servicio.exportar({ formato: 'xlsx', resuelta }).subscribe((a) => (archivo = a));
      const req = http.expectOne(`${BASE}/exportar`);
      expect(req.request.method).toBe('POST');
      expect(req.request.responseType).toBe('blob');
      expect(req.request.body).toEqual({ formato: 'xlsx', resuelta });
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush(new Blob(['x']), {
        headers: { 'Content-Disposition': 'attachment; filename="reporte-ventas_por_sucursal-fashionstore-20261020-1405.xlsx"' },
      });
      expect(archivo?.nombre).toBe('reporte-ventas_por_sucursal-fashionstore-20261020-1405.xlsx');
      expect(archivo?.blob.size).toBe(1);
    });

    it('sin Content-Disposition arma un nombre legible con el tipo y la extensión', () => {
      let nombre = '';
      servicio.exportar({ formato: 'pdf', resuelta }).subscribe((a) => (nombre = a.nombre));
      http.expectOne(`${BASE}/exportar`).flush(new Blob(['x']));
      expect(nombre).toMatch(/^reporte-ventas_por_sucursal-\d{8}\.pdf$/);
    });

    it('un error 422 llega como Blob para que la pantalla lo lea', () => {
      let fallo: unknown;
      servicio.exportar({ formato: 'pdf', resuelta }).subscribe({ error: (e) => (fallo = e) });
      http
        .expectOne(`${BASE}/exportar`)
        .flush(new Blob([JSON.stringify({ codigo: 'reporte_no_exportable' })]), { status: 422, statusText: 'Unprocessable' });
      expect(fallo).toBeDefined();
    });
  });
});

describe('nombreDeContentDisposition', () => {
  it('lee filename simple y filename*', () => {
    expect(nombreDeContentDisposition('attachment; filename="a b.xlsx"')).toBe('a_b.xlsx');
    expect(nombreDeContentDisposition("attachment; filename*=UTF-8''reporte%20ventas.pdf")).toBe('reporte_ventas.pdf');
  });

  it('no deja pasar rutas ni caracteres raros', () => {
    expect(nombreDeContentDisposition('attachment; filename="../../etc/passwd"')).toBe('_.._etc_passwd');
    expect(nombreDeContentDisposition('attachment; filename="<x>.pdf"')).toBe('_x_.pdf');
  });

  it('devuelve null si no hay nombre', () => {
    expect(nombreDeContentDisposition(null)).toBeNull();
    expect(nombreDeContentDisposition('attachment')).toBeNull();
  });
});
