import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { TiendaActualService } from '../state/tienda-actual.service';
import { ProductoDetalleComponent } from './producto-detalle.component';

const BASE = `${environment.apiUrl}/public/acme`;

function detalle(admiteProbador: boolean) {
  return {
    id: 9,
    codigo: 'P-9',
    nombre: 'Camisa Oxford',
    descripcion: 'Camisa de algodón.',
    categoria_id: 1,
    genero: 'hombre',
    precio_base: 289,
    admite_probador: admiteProbador,
    variantes: [{ id: 100, talla_id: 1, color_id: 1, sku: 'S1', precio_efectivo: 289, cantidad_disponible: 3 }],
    imagenes: [
      { id: 1, producto_id: 9, color_id: null, public_id: 'a', url: 'https://cdn.example.com/a.jpg', orden: 0, es_principal: true },
      { id: 2, producto_id: 9, color_id: null, public_id: 'b', url: 'https://cdn.example.com/b.jpg', orden: 1, es_principal: false },
    ],
  };
}

describe('ProductoDetalleComponent', () => {
  function montar(admiteProbador: boolean) {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: '9' }) } } },
      ],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    const http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(ProductoDetalleComponent);
    fixture.detectChanges();
    http.expectOne(`${BASE}/catalogo/9`).flush(detalle(admiteProbador));
    http.expectOne((r) => r.url === `${BASE}/tallas`).flush([{ id: 1, codigo: 'M', descripcion: null, orden: 1 }]);
    http
      .expectOne((r) => r.url === `${BASE}/colores`)
      .flush([
        { id: 1, nombre: 'Celeste', codigo_hex: '#b9cad6' },
        { id: 2, nombre: 'Sin hex', codigo_hex: null },
      ]);
    http.expectOne((r) => r.url === `${BASE}/sucursales`).flush([]);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement, http };
  }

  afterEach(() => localStorage.clear());

  it('muestra nombre, precio en Bs, migas y descripción', () => {
    const { el } = montar(true);

    expect(el.querySelector('h1')?.textContent).toContain('Camisa Oxford');
    expect(el.querySelector('.precio')?.textContent).toContain('Bs 289.00');
    expect(el.querySelector('.migas a')?.getAttribute('href')).toBe('/t/acme');
    expect(el.querySelector('.migas__actual')?.textContent).toContain('Camisa Oxford');
    expect(el.textContent).toContain('Camisa de algodón.');
  });

  it('el color elegido se marca, se nombra junto al título y las muestras tienen etiqueta', () => {
    const { fixture, el } = montar(true);
    expect(el.querySelector('.selector__valor')).toBeNull();

    // Con solo el color elegido todavía no hay variante: no se pide disponibilidad.
    (el.querySelector('button[aria-label="Color Celeste"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    const muestra = el.querySelector('button[aria-label="Color Celeste"]') as HTMLButtonElement;
    expect(muestra.getAttribute('aria-pressed')).toBe('true');
    expect(muestra.classList).toContain('activa');
    expect(el.querySelector('.selector__valor')?.textContent).toContain('Celeste');
  });

  it('muestra el aviso "Pruébalo en la app" solo si la prenda admite probador', () => {
    expect(montar(true).el.querySelector('.aviso-app')?.textContent).toContain('Pruébalo en la app.');

    TestBed.resetTestingModule();
    expect(montar(false).el.querySelector('.aviso-app')).toBeNull();
  });

  it('las miniaturas marcan aria-current solo en la foto activa', () => {
    const { fixture, el } = montar(true);
    const miniaturas = () => Array.from(el.querySelectorAll<HTMLButtonElement>('.miniatura'));

    expect(miniaturas().map((m) => m.getAttribute('aria-current'))).toEqual(['true', null]);

    miniaturas()[1].click();
    fixture.detectChanges();
    expect(miniaturas().map((m) => m.getAttribute('aria-current'))).toEqual([null, 'true']);
    expect(el.querySelector('.galeria-principal img')?.getAttribute('src')).toBe('https://cdn.example.com/b.jpg');
  });

  it('sin sesión invita a iniciar sesión una vez elegida la variante', () => {
    const { fixture, el, http } = montar(true);

    (el.querySelector('button[aria-label="Color Celeste"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    (Array.from(el.querySelectorAll('.tallas button'))[0] as HTMLButtonElement).click();
    http.expectOne((r) => r.url.endsWith('/inventario/disponibilidad')).flush([]);
    fixture.detectChanges();

    expect(el.querySelector('.acciones a')?.textContent).toContain('Inicia sesión para comprar');
  });
});
