import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, RouterStateSnapshot, convertToParamMap } from '@angular/router';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../core/http-contexts';
import { EmpresaPublica } from '../../core/models/empresa.models';
import { EstadoTienda, TiendaActualService } from './state/tienda-actual.service';
import { tiendaResolver } from './tienda.resolver';

const ACME: EmpresaPublica = { codigo: 'acme', nombre: 'Acme', logo_url: null, color_acento: '#2563eb' };
const URL_TIENDA = `${environment.apiUrl}/public/acme/tienda`;

describe('tiendaResolver', () => {
  let http: HttpTestingController;
  let servicio: TiendaActualService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    servicio = TestBed.inject(TiendaActualService);
  });

  afterEach(() => {
    localStorage.clear();
    http.verify();
  });

  function ejecutar(): { estado: EstadoTienda | null } {
    const ruta = { paramMap: convertToParamMap({ codigo: 'acme' }) } as unknown as ActivatedRouteSnapshot;
    const resultado: { estado: EstadoTienda | null } = { estado: null };
    const salida = TestBed.runInInjectionContext(() => tiendaResolver(ruta, {} as RouterStateSnapshot)) as Observable<EstadoTienda>;
    salida.subscribe((e) => (resultado.estado = e));
    return resultado;
  }

  it('200 -> "lista" y deja la marca en el servicio', () => {
    const r = ejecutar();
    http.expectOne(URL_TIENDA).flush(ACME);
    expect(r.estado).toBe('lista');
    expect(servicio.estado()).toBe('lista');
    expect(servicio.codigo()).toBe('acme');
    expect(servicio.empresa()).toEqual(ACME);
  });

  it('404 -> "no_encontrada"', () => {
    const r = ejecutar();
    http.expectOne(URL_TIENDA).flush({ detail: 'x' }, { status: 404, statusText: 'Not Found' });
    expect(r.estado).toBe('no_encontrada');
    expect(servicio.estado()).toBe('no_encontrada');
  });

  it('403 suscripcion_no_activa -> "no_disponible"', () => {
    const r = ejecutar();
    http
      .expectOne(URL_TIENDA)
      .flush({ codigo: 'suscripcion_no_activa', detail: 'x' }, { status: 403, statusText: 'Forbidden' });
    expect(r.estado).toBe('no_disponible');
    expect(servicio.estado()).toBe('no_disponible');
  });

  it('500 -> "error"', () => {
    const r = ejecutar();
    http.expectOne(URL_TIENDA).flush({ detail: 'x' }, { status: 500, statusText: 'Server Error' });
    expect(r.estado).toBe('error');
    expect(servicio.estado()).toBe('error');
  });

  it('la petición lleva el context SIN_TOAST_ERROR', () => {
    ejecutar();
    const req = http.expectOne(URL_TIENDA);
    expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    req.flush(ACME);
  });
});
