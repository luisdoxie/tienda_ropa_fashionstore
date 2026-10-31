import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { AnaliticaService } from './analitica.service';

const BASE = `${environment.apiUrl}/analitica`;

describe('AnaliticaService', () => {
  let servicio: AnaliticaService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    servicio = TestBed.inject(AnaliticaService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('estado, segmentos y panel son GET sin parámetros y sin el toast global', () => {
    servicio.estado().subscribe();
    servicio.segmentos().subscribe();
    servicio.panel().subscribe();
    for (const ruta of ['estado', 'segmentos', 'panel']) {
      const req = http.expectOne(`${BASE}/${ruta}`);
      expect(req.request.method).toBe('GET');
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush({});
    }
  });

  it('demanda manda las semanas y solo manda la categoría si se eligió una', () => {
    servicio.demanda(8).subscribe();
    const sin = http.expectOne((r) => r.url === `${BASE}/demanda`);
    expect(sin.request.params.keys()).toEqual(['semanas']);
    expect(sin.request.params.get('semanas')).toBe('8');
    sin.flush({});

    servicio.demanda(4, 12).subscribe();
    const con = http.expectOne((r) => r.url === `${BASE}/demanda`);
    expect(con.request.params.get('categoria_id')).toBe('12');
    con.flush({});
  });

  it('demanda usa 4 semanas por defecto', () => {
    servicio.demanda().subscribe();
    const req = http.expectOne((r) => r.url === `${BASE}/demanda`);
    expect(req.request.params.get('semanas')).toBe('4');
    req.flush({});
  });

  it('anomalias y reposicion usan sus parámetros y valores por defecto', () => {
    servicio.anomalias().subscribe();
    const a = http.expectOne((r) => r.url === `${BASE}/anomalias`);
    expect(a.request.params.get('dias')).toBe('90');
    a.flush({});

    servicio.reposicion(6).subscribe();
    const r = http.expectOne((x) => x.url === `${BASE}/reposicion`);
    expect(r.request.params.get('semanas')).toBe('6');
    r.flush({});
  });

  describe('entrenar', () => {
    it('sin tipos manda un cuerpo vacío (entrena los 3 modelos)', () => {
      servicio.entrenar().subscribe();
      const req = http.expectOne(`${BASE}/entrenar`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({});
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush({ resultados: [] });
    });

    it('con tipos manda solo esos', () => {
      servicio.entrenar(['demanda_semanal']).subscribe();
      const req = http.expectOne(`${BASE}/entrenar`);
      expect(req.request.body).toEqual({ tipos: ['demanda_semanal'] });
      req.flush({ resultados: [] });
    });
  });
});
