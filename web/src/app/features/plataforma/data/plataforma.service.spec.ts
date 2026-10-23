import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../../environments/environment';
import { EmpresaPlataforma } from '../../../core/models/plataforma.models';
import { PlataformaService } from './plataforma.service';

const BASE = `${environment.apiUrl}/plataforma`;

function empresa(id: number): EmpresaPlataforma {
  return {
    id,
    codigo: `e${id}`,
    nombre: `Empresa ${id}`,
    logo_url: null,
    color_acento: null,
    activo: true,
    plan_codigo: 'basico',
    suscripcion_estado: 'activa',
    fecha_inicio: '2026-10-01',
    fecha_vencimiento: '2026-11-01',
    administrador_email: null,
  };
}

describe('PlataformaService', () => {
  let servicio: PlataformaService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    servicio = TestBed.inject(PlataformaService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('lista planes con pagina y tamanio', () => {
    servicio.listarPlanes().subscribe();
    const req = http.expectOne((r) => r.url === `${BASE}/planes`);
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('pagina')).toBe('1');
    expect(req.request.params.get('tamanio')).toBe('100');
    req.flush([]);
  });

  it('actualiza un plan con PUT y solo los cambios', () => {
    servicio.actualizarPlan(3, { max_sucursales: 5, reportes_ia: true }).subscribe();
    const req = http.expectOne(`${BASE}/planes/3`);
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ max_sucursales: 5, reportes_ia: true });
    req.flush({});
  });

  it('lista empresas con q, activo, pagina y tamanio, y omite lo que no se filtra', () => {
    servicio.listarEmpresas({ q: ' moda ', activo: false, pagina: 2, tamanio: 20 }).subscribe();
    const req = http.expectOne((r) => r.url === `${BASE}/empresas`);
    expect(req.request.params.get('q')).toBe('moda');
    expect(req.request.params.get('activo')).toBe('false');
    expect(req.request.params.get('pagina')).toBe('2');
    expect(req.request.params.get('tamanio')).toBe('20');
    req.flush([]);

    servicio.listarEmpresas().subscribe();
    const sin = http.expectOne((r) => r.url === `${BASE}/empresas`);
    expect(sin.request.params.has('q')).toBe(false);
    expect(sin.request.params.has('activo')).toBe(false);
    expect(sin.request.params.get('pagina')).toBe('1');
    sin.flush([]);
  });

  it('junta todas las páginas de empresas', () => {
    let resultado: EmpresaPlataforma[] = [];
    servicio.listarTodasEmpresas().subscribe((r) => (resultado = r));

    const primera = http.expectOne((r) => r.url === `${BASE}/empresas` && r.params.get('pagina') === '1');
    expect(primera.request.params.get('tamanio')).toBe('100');
    primera.flush(Array.from({ length: 100 }, (_, i) => empresa(i + 1)));

    const segunda = http.expectOne((r) => r.url === `${BASE}/empresas` && r.params.get('pagina') === '2');
    segunda.flush([empresa(101)]);

    expect(resultado).toHaveLength(101);
  });

  it('pide el resumen, registra y actualiza una empresa', () => {
    servicio.resumenEmpresa(7).subscribe();
    const resumen = http.expectOne(`${BASE}/empresas/7/resumen`);
    expect(resumen.request.method).toBe('GET');
    resumen.flush({});

    const alta = {
      nombre: 'Moda',
      administrador: { nombre: 'Ana', apellido: 'Paz', email: 'a@b.com', password: 'secreto123' },
    };
    servicio.registrarEmpresa(alta).subscribe();
    const post = http.expectOne(`${BASE}/empresas`);
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual(alta);
    post.flush({});

    servicio.actualizarEmpresa(7, { activo: false }).subscribe();
    const put = http.expectOne(`${BASE}/empresas/7`);
    expect(put.request.method).toBe('PUT');
    expect(put.request.body).toEqual({ activo: false });
    put.flush({});
  });

  it('lista suscripciones con empresa_id y estado, y el historial de una empresa', () => {
    servicio.listarSuscripciones({ empresa_id: 4, estado: 'vencida', pagina: 1, tamanio: 20 }).subscribe();
    const req = http.expectOne((r) => r.url === `${BASE}/suscripciones`);
    expect(req.request.params.get('empresa_id')).toBe('4');
    expect(req.request.params.get('estado')).toBe('vencida');
    req.flush([]);

    servicio.historialDeEmpresa(4).subscribe();
    const historial = http.expectOne((r) => r.url === `${BASE}/suscripciones`);
    expect(historial.request.params.get('empresa_id')).toBe('4');
    expect(historial.request.params.has('estado')).toBe(false);
    expect(historial.request.params.get('tamanio')).toBe('100');
    historial.flush([]);
  });

  it('asigna plan, renueva y cambia el estado con los cuerpos del contrato', () => {
    servicio.asignarPlan({ empresa_id: 4, plan_codigo: 'profesional', fecha_inicio: '2026-10-22', fecha_vencimiento: '2026-11-21' }).subscribe();
    const post = http.expectOne(`${BASE}/suscripciones`);
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual({
      empresa_id: 4,
      plan_codigo: 'profesional',
      fecha_inicio: '2026-10-22',
      fecha_vencimiento: '2026-11-21',
    });
    post.flush({});

    servicio.renovar(9, '2027-01-31').subscribe();
    const renovar = http.expectOne(`${BASE}/suscripciones/9/renovar`);
    expect(renovar.request.method).toBe('PUT');
    expect(renovar.request.body).toEqual({ fecha_vencimiento: '2027-01-31' });
    renovar.flush({});

    servicio.cambiarEstado(9, 'suspendida').subscribe();
    const estado = http.expectOne(`${BASE}/suscripciones/9/estado`);
    expect(estado.request.method).toBe('PUT');
    expect(estado.request.body).toEqual({ estado: 'suspendida' });
    estado.flush({});
  });
});
