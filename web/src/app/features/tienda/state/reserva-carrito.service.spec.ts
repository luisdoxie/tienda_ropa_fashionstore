import { TestBed } from '@angular/core/testing';
import { ItemReservaTemporal, ReservaCarritoService } from './reserva-carrito.service';

const item = (id: number): ItemReservaTemporal => ({
  varianteId: id,
  productoNombre: `Producto ${id}`,
  tallaCodigo: 'M',
  colorNombre: 'Negro',
  imagenPrincipal: null,
});

describe('ReservaCarritoService', () => {
  let servicio: ReservaCarritoService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    servicio = TestBed.inject(ReservaCarritoService);
  });

  it('sin tienda no agrega', () => {
    servicio.agregar(item(1));
    expect(servicio.lista()).toEqual([]);
    expect(servicio.cantidad()).toBe(0);
    expect(servicio.contiene(1)).toBe(false);
  });

  it('agregar, contiene, quitar y vaciar por tienda', () => {
    servicio.cambiarTienda('acme');
    servicio.agregar(item(1));
    servicio.agregar(item(2));
    expect(servicio.cantidad()).toBe(2);
    expect(servicio.contiene(1)).toBe(true);
    expect(servicio.contiene(3)).toBe(false);

    servicio.quitar(1);
    expect(servicio.lista().map((i) => i.varianteId)).toEqual([2]);
    expect(servicio.contiene(1)).toBe(false);

    servicio.vaciar();
    expect(servicio.cantidad()).toBe(0);
  });

  it('no duplica una variante ya agregada', () => {
    servicio.cambiarTienda('acme');
    servicio.agregar(item(1));
    servicio.agregar(item(1));
    expect(servicio.cantidad()).toBe(1);
  });

  it('cambiarTienda no mezcla ni pierde', () => {
    servicio.cambiarTienda('acme');
    servicio.agregar(item(1));

    servicio.cambiarTienda('otra');
    expect(servicio.lista()).toEqual([]);
    expect(servicio.contiene(1)).toBe(false);
    servicio.agregar(item(2));
    expect(servicio.lista().map((i) => i.varianteId)).toEqual([2]);

    servicio.cambiarTienda('acme');
    expect(servicio.lista().map((i) => i.varianteId)).toEqual([1]);

    servicio.cambiarTienda('otra');
    expect(servicio.lista().map((i) => i.varianteId)).toEqual([2]);
  });

  it('cambiarTienda(null) deja la lista vacía sin borrar lo guardado', () => {
    servicio.cambiarTienda('acme');
    servicio.agregar(item(1));
    servicio.cambiarTienda(null);
    expect(servicio.lista()).toEqual([]);
    servicio.cambiarTienda('acme');
    expect(servicio.cantidad()).toBe(1);
  });

  it('vaciar solo vacía la tienda actual', () => {
    servicio.cambiarTienda('acme');
    servicio.agregar(item(1));
    servicio.cambiarTienda('otra');
    servicio.agregar(item(2));

    servicio.vaciar();
    expect(servicio.cantidad()).toBe(0);

    servicio.cambiarTienda('acme');
    expect(servicio.lista().map((i) => i.varianteId)).toEqual([1]);
  });

  it('quitar solo afecta a la tienda actual', () => {
    servicio.cambiarTienda('acme');
    servicio.agregar(item(1));
    servicio.cambiarTienda('otra');
    servicio.agregar(item(1));
    servicio.quitar(1);
    expect(servicio.cantidad()).toBe(0);
    servicio.cambiarTienda('acme');
    expect(servicio.contiene(1)).toBe(true);
  });
});
