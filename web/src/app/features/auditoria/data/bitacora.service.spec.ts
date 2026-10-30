import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { ConsultaBitacora, PaginaBitacora } from '../../../core/models/auditoria.models';
import { Usuario } from '../../../core/models/seguridad.models';
import { BitacoraService } from './bitacora.service';

const API = environment.apiUrl;
const VACIA: PaginaBitacora = { total: 0, pagina: 1, tamanio: 20, items: [] };
const RANGO: ConsultaBitacora = { desde: '2026-10-01', hasta: '2026-10-30' };

function usuario(id: number, roles: string[]): Usuario {
  return { id, nombre: `U${id}`, apellido: 'X', email: `u${id}@x.com`, telefono: null, activo: true, roles };
}

describe('BitacoraService', () => {
  let servicio: BitacoraService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    servicio = TestBed.inject(BitacoraService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  describe('listar (administrador de la empresa)', () => {
    it('pide GET /bitacora con el rango, la página y el tamaño por defecto, sin toast de error', () => {
      let recibida: PaginaBitacora | undefined;
      servicio.listar(RANGO).subscribe((p) => (recibida = p));

      const req = http.expectOne((r) => r.url === `${API}/bitacora`);
      expect(req.request.method).toBe('GET');
      expect(req.request.params.get('desde')).toBe('2026-10-01');
      expect(req.request.params.get('hasta')).toBe('2026-10-30');
      expect(req.request.params.get('pagina')).toBe('1');
      expect(req.request.params.get('tamanio')).toBe('20');
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush(VACIA);

      expect(recibida).toEqual(VACIA);
    });

    it('manda entidad, accion, usuario_id, pagina y tamanio cuando se piden', () => {
      servicio.listar({ ...RANGO, entidad: 'suscripcion', accion: 'cambiar_plan', usuario_id: 9, pagina: 3, tamanio: 50 }).subscribe();

      const req = http.expectOne((r) => r.url === `${API}/bitacora`);
      expect(req.request.params.get('entidad')).toBe('suscripcion');
      expect(req.request.params.get('accion')).toBe('cambiar_plan');
      expect(req.request.params.get('usuario_id')).toBe('9');
      expect(req.request.params.get('pagina')).toBe('3');
      expect(req.request.params.get('tamanio')).toBe('50');
      req.flush(VACIA);
    });

    it('no manda filtros vacíos (null, cadena vacía)', () => {
      servicio.listar({ ...RANGO, entidad: null, accion: '', usuario_id: null }).subscribe();

      const req = http.expectOne((r) => r.url === `${API}/bitacora`);
      expect(req.request.params.has('entidad')).toBe(false);
      expect(req.request.params.has('accion')).toBe(false);
      expect(req.request.params.has('usuario_id')).toBe(false);
      req.flush(VACIA);
    });

    it('NUNCA manda empresa_id ni sin_empresa al endpoint del administrador, aunque se los pasen', () => {
      const intruso = { ...RANGO, empresa_id: 99, sin_empresa: true } as ConsultaBitacora;
      servicio.listar(intruso).subscribe();

      const req = http.expectOne((r) => r.url === `${API}/bitacora`);
      expect(req.request.params.has('empresa_id')).toBe(false);
      expect(req.request.params.has('sin_empresa')).toBe(false);
      expect(req.request.url).not.toContain('empresa');
      req.flush(VACIA);
    });

    it('es de solo lectura: solo hace GET', () => {
      servicio.listar(RANGO).subscribe();
      const req = http.expectOne((r) => r.url === `${API}/bitacora`);
      expect(req.request.method).toBe('GET');
      expect(req.request.body).toBeNull();
      req.flush(VACIA);
    });
  });

  describe('listarPlataforma (superadministrador)', () => {
    it('pide GET /plataforma/bitacora con empresa_id', () => {
      servicio.listarPlataforma({ ...RANGO, empresa_id: 7, entidad: 'plan' }).subscribe();

      const req = http.expectOne((r) => r.url === `${API}/plataforma/bitacora`);
      expect(req.request.method).toBe('GET');
      expect(req.request.params.get('empresa_id')).toBe('7');
      expect(req.request.params.has('sin_empresa')).toBe(false);
      expect(req.request.params.get('entidad')).toBe('plan');
      expect(req.request.params.get('desde')).toBe('2026-10-01');
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush(VACIA);
    });

    it('con sin_empresa manda sin_empresa=true y ningún empresa_id', () => {
      servicio.listarPlataforma({ ...RANGO, sin_empresa: true }).subscribe();

      const req = http.expectOne((r) => r.url === `${API}/plataforma/bitacora`);
      expect(req.request.params.get('sin_empresa')).toBe('true');
      expect(req.request.params.has('empresa_id')).toBe(false);
      req.flush(VACIA);
    });

    it('sin empresa ni sin_empresa pide todas las empresas (no manda ninguno de los dos)', () => {
      servicio.listarPlataforma({ ...RANGO, empresa_id: null, sin_empresa: false }).subscribe();

      const req = http.expectOne((r) => r.url === `${API}/plataforma/bitacora`);
      expect(req.request.params.has('empresa_id')).toBe(false);
      expect(req.request.params.has('sin_empresa')).toBe(false);
      req.flush(VACIA);
    });
  });

  describe('listarPersonal (filtro de usuario)', () => {
    it('pide /usuarios y deja fuera a quienes solo son clientes', () => {
      let recibidos: Usuario[] = [];
      servicio.listarPersonal().subscribe((u) => (recibidos = u));

      const req = http.expectOne((r) => r.url === `${API}/usuarios`);
      expect(req.request.params.get('pagina')).toBe('1');
      expect(req.request.params.get('tamanio')).toBe('100');
      req.flush([usuario(1, ['administrador']), usuario(2, ['cliente']), usuario(3, ['cajero', 'cliente'])]);

      expect(recibidos.map((u) => u.id)).toEqual([1, 3]);
    });

    it('si la primera página viene llena pide la siguiente y junta ambas', () => {
      let recibidos: Usuario[] = [];
      servicio.listarPersonal().subscribe((u) => (recibidos = u));

      const llena = Array.from({ length: 100 }, (_, i) => usuario(i + 1, ['cajero']));
      http.expectOne((r) => r.url === `${API}/usuarios` && r.params.get('pagina') === '1').flush(llena);
      http.expectOne((r) => r.url === `${API}/usuarios` && r.params.get('pagina') === '2').flush([usuario(101, ['encargado'])]);

      expect(recibidos.length).toBe(101);
      expect(recibidos.at(-1)?.id).toBe(101);
    });

    it('con menos de 100 usuarios no pide más páginas', () => {
      servicio.listarPersonal().subscribe();
      http.expectOne((r) => r.url === `${API}/usuarios`).flush([usuario(1, ['administrador'])]);
      http.expectNone((r) => r.url === `${API}/usuarios`);
    });
  });
});
