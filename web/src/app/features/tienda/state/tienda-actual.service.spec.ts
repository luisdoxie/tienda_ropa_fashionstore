import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { EmpresaPublica } from '../../../core/models/empresa.models';
import { CarritoService } from '../data/carrito.service';
import { CheckoutService } from './checkout.service';
import { ReservaCarritoService } from './reserva-carrito.service';
import { CLAVE_ULTIMA_TIENDA, EstadoTienda, TiendaActualService } from './tienda-actual.service';

const ACME: EmpresaPublica = { codigo: 'acme', nombre: 'Acme', logo_url: null, color_acento: '#2563eb' };

const ITEM = (id: number) => ({
  varianteId: id,
  productoNombre: `P${id}`,
  tallaCodigo: 'M',
  colorNombre: 'Rojo',
  imagenPrincipal: null,
});

describe('TiendaActualService', () => {
  let servicio: TiendaActualService;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    servicio = TestBed.inject(TiendaActualService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    http.verify();
  });

  describe('rutas', () => {
    it('ruta() arma [/t, codigo, ...segmentos]', () => {
      servicio.fijar('acme', 'lista', ACME);
      expect(servicio.ruta('carrito')).toEqual(['/t', 'acme', 'carrito']);
      expect(servicio.ruta()).toEqual(['/t', 'acme']);
    });

    it('ruta() sin tienda devuelve ["/"]', () => {
      expect(servicio.ruta()).toEqual(['/']);
      expect(servicio.ruta('carrito')).toEqual(['/']);
    });

    it('urlPublica arma la URL de la API y no duplica barras', () => {
      servicio.fijar('acme', 'lista', ACME);
      expect(servicio.urlPublica('catalogo')).toBe(`${environment.apiUrl}/public/acme/catalogo`);
      expect(servicio.urlPublica('/catalogo')).toBe(`${environment.apiUrl}/public/acme/catalogo`);
      expect(servicio.urlPublica('//catalogo/1')).toBe(`${environment.apiUrl}/public/acme/catalogo/1`);
    });
  });

  describe('cambio de tienda', () => {
    it('cambiar de código limpia carrito, reinicia checkout y cambia la reserva temporal', () => {
      const carrito = TestBed.inject(CarritoService);
      const checkout = TestBed.inject(CheckoutService);
      const reserva = TestBed.inject(ReservaCarritoService);
      const limpiar = vi.spyOn(carrito, 'limpiar');
      const reiniciar = vi.spyOn(checkout, 'reiniciar');
      const cambiar = vi.spyOn(reserva, 'cambiarTienda');

      servicio.fijar('acme', 'lista', ACME);
      expect(limpiar).toHaveBeenCalledTimes(1);
      expect(reiniciar).toHaveBeenCalledTimes(1);
      expect(cambiar).toHaveBeenLastCalledWith('acme');

      servicio.fijar('otra', 'lista', { ...ACME, codigo: 'otra' });
      expect(limpiar).toHaveBeenCalledTimes(2);
      expect(reiniciar).toHaveBeenCalledTimes(2);
      expect(cambiar).toHaveBeenLastCalledWith('otra');
    });

    it('fijar el mismo código no limpia nada', () => {
      const carrito = TestBed.inject(CarritoService);
      const checkout = TestBed.inject(CheckoutService);
      servicio.fijar('acme', 'cargando');
      const limpiar = vi.spyOn(carrito, 'limpiar');
      const reiniciar = vi.spyOn(checkout, 'reiniciar');

      servicio.fijar('acme', 'lista', ACME);

      expect(limpiar).not.toHaveBeenCalled();
      expect(reiniciar).not.toHaveBeenCalled();
    });

    it('la reserva temporal de acme no aparece en otra tienda y vuelve al regresar', () => {
      const reserva = TestBed.inject(ReservaCarritoService);
      servicio.fijar('acme', 'lista', ACME);
      reserva.agregar(ITEM(1));
      expect(reserva.cantidad()).toBe(1);

      servicio.fijar('otra', 'lista', { ...ACME, codigo: 'otra' });
      expect(reserva.cantidad()).toBe(0);

      servicio.fijar('acme', 'lista', ACME);
      expect(reserva.lista().map((i) => i.varianteId)).toEqual([1]);
    });

    it('salir() limpia el estado pero conserva la última tienda', () => {
      servicio.fijar('acme', 'lista', ACME);
      servicio.salir();
      expect(servicio.estado()).toBe('sin_tienda');
      expect(servicio.codigo()).toBeNull();
      expect(servicio.empresa()).toBeNull();
      expect(servicio.ultimaTienda()).toBe('acme');
    });
  });

  describe('última tienda', () => {
    it('solo se guarda cuando el estado es "lista"', () => {
      for (const estado of ['cargando', 'no_encontrada', 'no_disponible', 'error'] as EstadoTienda[]) {
        servicio.fijar('acme', estado);
        expect(localStorage.getItem(CLAVE_ULTIMA_TIENDA), estado).toBeNull();
      }
      expect(CLAVE_ULTIMA_TIENDA).toBe('fs_ultima_tienda');
      servicio.fijar('acme', 'lista', ACME);
      expect(localStorage.getItem('fs_ultima_tienda')).toBe('acme');
      expect(servicio.ultimaTienda()).toBe('acme');
    });

    it('ultimaTienda() es null si no hay nada guardado', () => {
      expect(servicio.ultimaTienda()).toBeNull();
    });

    it('no falla si localStorage lanza', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('bloqueado');
      });
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('bloqueado');
      });
      expect(() => servicio.fijar('acme', 'lista', ACME)).not.toThrow();
      expect(servicio.estado()).toBe('lista');
      expect(servicio.ultimaTienda()).toBeNull();
    });
  });

  describe('cargar', () => {
    function cargarYResponder(
      respuesta: { body: object; status: number; statusText: string },
    ): { estado: EstadoTienda | null } {
      const resultado: { estado: EstadoTienda | null } = { estado: null };
      servicio.cargar('acme').subscribe((e) => (resultado.estado = e));
      const req = http.expectOne(`${environment.apiUrl}/public/acme/tienda`);
      req.flush(respuesta.body, { status: respuesta.status, statusText: respuesta.statusText });
      return resultado;
    }

    it('mientras carga queda en "cargando" y la petición es GET sin toast', () => {
      servicio.cargar('acme').subscribe();
      expect(servicio.estado()).toBe('cargando');
      expect(servicio.codigo()).toBe('acme');
      const req = http.expectOne(`${environment.apiUrl}/public/acme/tienda`);
      expect(req.request.method).toBe('GET');
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush(ACME);
    });

    it('200 -> "lista" con la marca', () => {
      const r = cargarYResponder({ body: ACME, status: 200, statusText: 'OK' });
      expect(r.estado).toBe('lista');
      expect(servicio.estado()).toBe('lista');
      expect(servicio.empresa()).toEqual(ACME);
      expect(servicio.ultimaTienda()).toBe('acme');
    });

    it('200 con disponible:false -> "no_disponible"', () => {
      const r = cargarYResponder({ body: { ...ACME, disponible: false }, status: 200, statusText: 'OK' });
      expect(r.estado).toBe('no_disponible');
      expect(servicio.estado()).toBe('no_disponible');
      expect(localStorage.getItem(CLAVE_ULTIMA_TIENDA)).toBeNull();
    });

    it('200 con disponible:true -> "lista"', () => {
      const r = cargarYResponder({ body: { ...ACME, disponible: true }, status: 200, statusText: 'OK' });
      expect(r.estado).toBe('lista');
    });

    it('404 -> "no_encontrada"', () => {
      const r = cargarYResponder({ body: { detail: 'No encontrada' }, status: 404, statusText: 'Not Found' });
      expect(r.estado).toBe('no_encontrada');
      expect(servicio.estado()).toBe('no_encontrada');
      expect(servicio.empresa()).toBeNull();
    });

    it('403 con {codigo:"suscripcion_no_activa"} -> "no_disponible"', () => {
      const r = cargarYResponder({ body: { codigo: 'suscripcion_no_activa' }, status: 403, statusText: 'Forbidden' });
      expect(r.estado).toBe('no_disponible');
    });

    it('403 con detail string -> "no_disponible"', () => {
      const r = cargarYResponder({ body: { detail: 'suscripcion_no_activa' }, status: 403, statusText: 'Forbidden' });
      expect(r.estado).toBe('no_disponible');
    });

    it('403 con detail objeto -> "no_disponible"', () => {
      const r = cargarYResponder({
        body: { detail: { codigo: 'suscripcion_no_activa' } },
        status: 403,
        statusText: 'Forbidden',
      });
      expect(r.estado).toBe('no_disponible');
    });

    it('403 con otro código -> "error"', () => {
      const r = cargarYResponder({ body: { codigo: 'otra_cosa' }, status: 403, statusText: 'Forbidden' });
      expect(r.estado).toBe('error');
    });

    it('500 -> "error"', () => {
      const r = cargarYResponder({ body: { detail: 'boom' }, status: 500, statusText: 'Server Error' });
      expect(r.estado).toBe('error');
      expect(servicio.estado()).toBe('error');
    });

    it('error de red (status 0) -> "error"', () => {
      const resultado: { estado: EstadoTienda | null } = { estado: null };
      servicio.cargar('acme').subscribe((e) => (resultado.estado = e));
      http.expectOne(`${environment.apiUrl}/public/acme/tienda`).error(new ProgressEvent('error'));
      expect(resultado.estado).toBe('error');
    });

    it('codifica el código en la URL', () => {
      servicio.cargar('a b').subscribe();
      const req = http.expectOne(`${environment.apiUrl}/public/a%20b/tienda`);
      req.flush(ACME);
    });
  });
});
