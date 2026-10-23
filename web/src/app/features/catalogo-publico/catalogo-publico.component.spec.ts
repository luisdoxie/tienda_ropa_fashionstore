import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { CatalogoItem } from '../../core/models/catalogo.models';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';
import { CatalogoPublicoComponent } from './catalogo-publico.component';

const BASE = `${environment.apiUrl}/public/acme`;

function item(id: number, probador: boolean, imagen: string | null = null): CatalogoItem {
  return {
    id,
    codigo: `P-${id}`,
    nombre: `Prenda ${id}`,
    categoria_id: 1,
    genero: 'hombre',
    precio_base: 289,
    admite_probador: probador,
    imagen_principal: imagen,
  };
}

describe('CatalogoPublicoComponent', () => {
  let controller: HttpTestingController;

  function crear(): { fixture: ReturnType<typeof TestBed.createComponent<CatalogoPublicoComponent>>; el: HTMLElement } {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    controller = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(CatalogoPublicoComponent);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  function responderReferencias(): void {
    for (const lista of ['categorias', 'tallas', 'colores', 'materiales', 'temporadas']) {
      controller.expectOne((r) => r.url.startsWith(`${BASE}/${lista}?`)).flush([]);
    }
  }

  function responderCatalogo(productos: CatalogoItem[]): void {
    controller.expectOne((r) => r.url.startsWith(`${BASE}/catalogo?`) && !r.url.includes('/buscar')).flush(productos);
  }

  afterEach(() => localStorage.clear());

  it('carga catálogo y referencias desde /public/<codigo>/...', () => {
    crear();

    responderCatalogo([]);
    responderReferencias();
    controller.verify();
  });

  it('muestra la portada: titular, foto, probador en la app y los 4 beneficios, sin el marquee viejo', () => {
    const { el } = crear();
    responderCatalogo([]);
    responderReferencias();

    expect(el.querySelector('.portada')?.classList).toContain('fs-zona-oscura');
    expect(el.querySelector('h1')?.textContent).toContain('Tu estilo');
    expect(el.querySelector('h1 em')?.textContent).toContain('en tus manos');
    expect(el.querySelector('.hero__foto img')?.getAttribute('src')).toBe('/imagenes/portada-tienda.png');
    expect(el.querySelector('.hero__probador')?.textContent).toContain('con IA en la app');
    expect(el.querySelectorAll('.beneficio').length).toBe(4);
    expect(el.querySelector('.marquee')).toBeNull();
    expect(el.querySelector('.hero-pasos')).toBeNull();
    // Textos en tuteo, sin voseo.
    expect(el.textContent).toContain('pruébatela');
    expect(el.textContent).not.toMatch(
      /Vestite|probate|Elegí|Subí|Mirá|Buscá|Probá|Tenés|Podés|Querés|Decidí|Iniciá|Revisá|Intentá|Ingresá|Seleccioná|Quitá|Escribí/,
    );
  });

  it('dibuja la cuadrícula con precio en Bs y la etiqueta "Probador IA" solo donde corresponde', () => {
    const { fixture, el } = crear();
    responderCatalogo([item(1, true), item(2, false, 'https://cdn.example.com/p2.jpg')]);
    responderReferencias();
    fixture.detectChanges();

    const tarjetas = el.querySelectorAll('a.tarjeta');
    expect(tarjetas.length).toBe(2);
    expect(tarjetas[0].getAttribute('href')).toBe('/t/acme/producto/1');
    expect(tarjetas[0].textContent).toContain('Bs 289.00');
    expect(tarjetas[0].querySelector('.tarjeta__probador')?.textContent).toContain('Probador IA');
    expect(tarjetas[1].querySelector('.tarjeta__probador')).toBeNull();
    expect(tarjetas[1].querySelector('img')?.getAttribute('src')).toBe('https://cdn.example.com/p2.jpg');
    expect(el.textContent).toContain('2 prendas a la vista');
    expect(el.textContent).toContain('Estás viendo todo el catálogo.');
  });

  it('con una página completa ofrece "Ver más prendas" y pide la siguiente', () => {
    const { fixture, el } = crear();
    responderCatalogo(Array.from({ length: 20 }, (_, i) => item(i + 1, false)));
    responderReferencias();
    fixture.detectChanges();

    const boton = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Ver más prendas'));
    expect(boton).toBeDefined();

    boton!.click();
    controller
      .expectOne((r) => r.url.startsWith(`${BASE}/catalogo?`) && r.url.includes('pagina=2'))
      .flush([item(21, false)]);
    fixture.detectChanges();

    expect(el.querySelectorAll('a.tarjeta').length).toBe(21);
  });

  it('con error muestra el aviso y "Reintentar" vuelve a pedir el catálogo', () => {
    const { fixture, el } = crear();
    controller
      .expectOne((r) => r.url.startsWith(`${BASE}/catalogo?`))
      .flush('boom', { status: 500, statusText: 'Server Error' });
    responderReferencias();
    fixture.detectChanges();

    expect(el.querySelector('.estado-error')?.textContent).toContain('No se pudo cargar el catálogo.');
    const reintentar = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Reintentar'));
    reintentar!.click();
    responderCatalogo([]);
    fixture.detectChanges();

    expect(el.querySelector('.estado-error')).toBeNull();
    expect(el.textContent).toContain('No encontramos productos con ese filtro.');
  });

  it('las categorías filtran: "Todo" más una por categoría', () => {
    const { fixture, el } = crear();
    responderCatalogo([]);
    controller
      .expectOne((r) => r.url.startsWith(`${BASE}/categorias?`))
      .flush([
        { id: 5, nombre: 'Camisas' },
        { id: 6, nombre: 'Poleras' },
      ]);
    for (const lista of ['tallas', 'colores', 'materiales', 'temporadas']) {
      controller.expectOne((r) => r.url.startsWith(`${BASE}/${lista}?`)).flush([]);
    }
    fixture.detectChanges();

    const botones = Array.from(el.querySelectorAll<HTMLButtonElement>('.categoria'));
    expect(botones.map((b) => b.textContent?.trim())).toEqual(['Todo', 'Camisas', 'Poleras']);
    expect(botones[0].classList).toContain('categoria--activa');

    botones[1].click();
    controller.expectOne((r) => r.url.startsWith(`${BASE}/catalogo/buscar?`) && r.url.includes('categoria_id=5')).flush([]);
    fixture.detectChanges();

    expect(el.querySelectorAll<HTMLButtonElement>('.categoria')[1].classList).toContain('categoria--activa');
  });

  it('el botón Filtros abre el panel y el contador cuenta los filtros puestos', () => {
    const { fixture, el } = crear();
    responderCatalogo([]);
    controller
      .expectOne((r) => r.url.startsWith(`${BASE}/tallas?`))
      .flush([{ id: 3, codigo: 'M', descripcion: null, orden: 1 }]);
    for (const lista of ['categorias', 'colores', 'materiales', 'temporadas']) {
      controller.expectOne((r) => r.url.startsWith(`${BASE}/${lista}?`)).flush([]);
    }
    fixture.detectChanges();

    expect(el.querySelector('.panel-filtros')).toBeNull();
    (el.querySelector('.boton-filtros') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelector('.panel-filtros')).not.toBeNull();

    const talla = el.querySelector('.panel-filtros select') as HTMLSelectElement;
    talla.value = '3';
    talla.dispatchEvent(new Event('change'));
    controller.expectOne((r) => r.url.startsWith(`${BASE}/catalogo/buscar?`) && r.url.includes('talla_id=3')).flush([]);
    fixture.detectChanges();

    expect(el.querySelector('.globo-filtros')?.textContent?.trim()).toBe('1');
  });
});
