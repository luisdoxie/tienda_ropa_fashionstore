import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../../environments/environment';
import { CarritoService } from './carrito.service';

const API = environment.apiUrl;
const PROMOCION = `${API}/carrito/aplicar-promocion`;

describe('CarritoService (resumen)', () => {
  let http: HttpTestingController;
  let servicio: CarritoService;

  function cargarUnaLinea(): void {
    servicio.cargar().subscribe();
    http.expectOne(`${API}/carrito`).flush({
      id: 1,
      cliente_id: 1,
      sucursal_id: null,
      actualizado_en: '2026-10-22T10:00:00',
      subtotal: 100,
      detalle: [{ id: 1, variante_id: 10, cantidad: 1, precio_unitario: 100, subtotal: 100, disponible: true }],
    });
    http.expectOne((r) => r.url === `${API}/catalogo/variantes/detalle`).flush([]);
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    servicio = TestBed.inject(CarritoService);
  });

  it('con el carrito vacío no pide nada y deja el resumen en null', () => {
    servicio.refrescarResumen();

    http.expectNone(PROMOCION);
    expect(servicio.resumen()).toBeNull();
    expect(servicio.calculandoResumen()).toBe(false);
  });

  it('con líneas pide el resumen, marca "calculando" y lo guarda', () => {
    cargarUnaLinea();

    servicio.refrescarResumen();
    expect(servicio.calculandoResumen()).toBe(true);
    http.expectOne(PROMOCION).flush({ lineas: [], subtotal: 100, descuento: 10, total: 90 });

    expect(servicio.calculandoResumen()).toBe(false);
    expect(servicio.resumen()?.total).toBe(90);
  });

  it('si la petición falla el resumen queda en null', () => {
    cargarUnaLinea();

    servicio.refrescarResumen();
    http.expectOne(PROMOCION).flush('x', { status: 500, statusText: 'Error' });

    expect(servicio.resumen()).toBeNull();
    expect(servicio.calculandoResumen()).toBe(false);
  });

  it('limpiar() descarta el resumen', () => {
    cargarUnaLinea();
    servicio.refrescarResumen();
    http.expectOne(PROMOCION).flush({ lineas: [], subtotal: 100, descuento: 0, total: 100 });

    servicio.limpiar();

    expect(servicio.resumen()).toBeNull();
    expect(servicio.lineas()).toEqual([]);
  });
});
