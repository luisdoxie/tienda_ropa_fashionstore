import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { SincronizacionAdminService } from './sincronizacion-admin.service';

const BASE = `${environment.apiUrl}/sincronizacion`;
const ID = '3f1c2a9e-7b1d-4c55-9a0e-2d6f5b8a1c01';

describe('SincronizacionAdminService', () => {
  let servicio: SincronizacionAdminService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    servicio = TestBed.inject(SincronizacionAdminService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  describe('listar', () => {
    it('sin filtros pide la página 1 de 20 y no manda ningún filtro', () => {
      servicio.listar().subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/operaciones`);
      expect(req.request.method).toBe('GET');
      expect(req.request.params.keys().sort()).toEqual(['pagina', 'tamanio']);
      expect(req.request.params.get('pagina')).toBe('1');
      expect(req.request.params.get('tamanio')).toBe('20');
      req.flush({ total: 0, pagina: 1, tamanio: 20, items: [] });
    });

    it('arma todos los filtros con los nombres del servidor', () => {
      servicio
        .listar({
          pagina: 3,
          tamanio: 50,
          estado: 'en_conflicto',
          tipo: 'venta_contado',
          sucursal_id: 4,
          usuario_id: 9,
          desde: '2026-10-01',
          hasta: '2026-10-31',
        })
        .subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/operaciones`);
      const p = req.request.params;
      expect(p.get('pagina')).toBe('3');
      expect(p.get('tamanio')).toBe('50');
      expect(p.get('estado')).toBe('en_conflicto');
      expect(p.get('tipo')).toBe('venta_contado');
      expect(p.get('sucursal_id')).toBe('4');
      expect(p.get('usuario_id')).toBe('9');
      expect(p.get('desde')).toBe('2026-10-01');
      expect(p.get('hasta')).toBe('2026-10-31');
      req.flush({ total: 0, pagina: 3, tamanio: 50, items: [] });
    });

    it('un filtro nulo o vacío no se envía', () => {
      servicio.listar({ estado: null, tipo: null, sucursal_id: null, usuario_id: null, desde: null, hasta: '' }).subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/operaciones`);
      expect(req.request.params.keys().sort()).toEqual(['pagina', 'tamanio']);
      req.flush({ total: 0, pagina: 1, tamanio: 20, items: [] });
    });

    it('lo normal deja el aviso de error al manejo global y lo silencioso lo apaga', () => {
      servicio.listar().subscribe();
      const normal = http.expectOne((r) => r.url === `${BASE}/operaciones`);
      expect(normal.request.context.get(SIN_TOAST_ERROR)).toBe(false);
      normal.flush({ total: 0, pagina: 1, tamanio: 20, items: [] });

      servicio.listar({}, true).subscribe();
      const mudo = http.expectOne((r) => r.url === `${BASE}/operaciones`);
      expect(mudo.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      mudo.flush({ total: 0, pagina: 1, tamanio: 20, items: [] });
    });
  });

  it('contarConflictos pide una sola fila en conflicto y devuelve el total', () => {
    let total = -1;
    servicio.contarConflictos().subscribe((n) => (total = n));
    const req = http.expectOne((r) => r.url === `${BASE}/operaciones`);
    expect(req.request.params.get('estado')).toBe('en_conflicto');
    expect(req.request.params.get('tamanio')).toBe('1');
    expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    req.flush({ total: 7, pagina: 1, tamanio: 1, items: [] });
    expect(total).toBe(7);
  });

  it('obtener pide el detalle por el UUID de la operación', () => {
    servicio.obtener(ID).subscribe();
    const req = http.expectOne(`${BASE}/operaciones/${ID}`);
    expect(req.request.method).toBe('GET');
    req.flush({});
  });

  describe('resolver', () => {
    it('forzar envía exactamente {accion, motivo} a /resolver', () => {
      servicio.resolver(ID, { accion: 'forzar', motivo: 'La prenda ya salió de la tienda' }).subscribe();
      const req = http.expectOne(`${BASE}/operaciones/${ID}/resolver`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ accion: 'forzar', motivo: 'La prenda ya salió de la tienda' });
      req.flush({});
    });

    it('rechazar envía exactamente {accion, motivo}', () => {
      servicio.resolver(ID, { accion: 'rechazar', motivo: 'Se devolvió el efectivo' }).subscribe();
      const req = http.expectOne(`${BASE}/operaciones/${ID}/resolver`);
      expect(req.request.body).toEqual({ accion: 'rechazar', motivo: 'Se devolvió el efectivo' });
      req.flush({});
    });

    it('sus errores los explica la pantalla: no pasan por el toast global', () => {
      servicio.resolver(ID, { accion: 'rechazar', motivo: 'x' }).subscribe({ error: () => undefined });
      const req = http.expectOne(`${BASE}/operaciones/${ID}/resolver`);
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush({ detail: 'ya resuelta' }, { status: 409, statusText: 'Conflict' });
    });

    it('propaga el 409 al que llamó', () => {
      let estado = 0;
      servicio.resolver(ID, { accion: 'forzar', motivo: 'motivo largo ok' }).subscribe({ error: (e) => (estado = e.status) });
      http.expectOne(`${BASE}/operaciones/${ID}/resolver`).flush({ detail: 'x' }, { status: 409, statusText: 'Conflict' });
      expect(estado).toBe(409);
    });
  });

  it('no existe ninguna forma de borrar una operación', () => {
    const metodos = Object.getOwnPropertyNames(Object.getPrototypeOf(servicio));
    expect(metodos.filter((m) => /borr|elimin|delete|remove/i.test(m))).toEqual([]);
  });

  describe('apoyo', () => {
    it('sucursales y usuarios piden hasta 100 y no abren toast si fallan', () => {
      servicio.sucursales().subscribe();
      const sucursales = http.expectOne((r) => r.url === `${environment.apiUrl}/sucursales`);
      expect(sucursales.request.params.get('tamanio')).toBe('100');
      expect(sucursales.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      sucursales.flush([]);

      servicio.usuarios().subscribe();
      const usuarios = http.expectOne((r) => r.url === `${environment.apiUrl}/usuarios`);
      expect(usuarios.request.params.get('tamanio')).toBe('100');
      expect(usuarios.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      usuarios.flush([]);
    });

    it('detallesDeVariantes junta los ids sin repetir; sin ids no llama al servidor', () => {
      let vacio: unknown[] | null = null;
      servicio.detallesDeVariantes([]).subscribe((r) => (vacio = r));
      expect(vacio).toEqual([]);
      http.expectNone(() => true);

      servicio.detallesDeVariantes([5, 7, 5]).subscribe();
      const req = http.expectOne((r) => r.url === `${environment.apiUrl}/catalogo/variantes/detalle`);
      expect(req.request.params.get('variante_ids')).toBe('5,7');
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush([]);
    });
  });
});
