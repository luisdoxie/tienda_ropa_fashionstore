import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../environments/environment';
import { ProductosComponent } from './productos.component';

const API = environment.apiUrl;

const PRODUCTO = {
  id: 3,
  codigo: 'CAM-001',
  nombre: 'Camisa Oxford',
  descripcion: null,
  categoria_id: 1,
  material_id: null,
  temporada_id: null,
  coleccion_id: null,
  genero: 'hombre',
  precio_base: 289,
  admite_probador: true,
  activo: true,
};

describe('ProductosComponent', () => {
  let http: HttpTestingController;

  function abrir() {
    TestBed.configureTestingModule({
      imports: [ProductosComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(ProductosComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/categorias?pagina=1&tamanio=100`).flush([{ id: 1, nombre: 'Camisas' }]);
    http.expectOne(`${API}/materiales?pagina=1&tamanio=100`).flush([]);
    http.expectOne(`${API}/temporadas?pagina=1&tamanio=100`).flush([]);
    http.expectOne(`${API}/colecciones?pagina=1&tamanio=100`).flush([]);
    http
      .expectOne(`${API}/tallas?pagina=1&tamanio=100`)
      .flush([
        { id: 1, codigo: 'S', descripcion: null, orden: 1 },
        { id: 2, codigo: 'M', descripcion: null, orden: 2 },
      ]);
    http
      .expectOne(`${API}/colores?pagina=1&tamanio=100`)
      .flush([
        { id: 1, nombre: 'Celeste', codigo_hex: '#b9cad6' },
        { id: 2, nombre: 'Arena', codigo_hex: null },
      ]);
    http.expectOne((r) => r.method === 'GET' && r.url.startsWith(`${API}/productos?`)).flush([PRODUCTO]);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  afterEach(() => http.match(() => true));

  const documento = () => document.body;

  it('dibuja el encabezado de la pantalla y la lista de productos', () => {
    const { el } = abrir();

    expect(el.querySelector('.fs-eyebrow')?.textContent).toBe('Catálogo');
    expect(el.querySelector('h1')?.textContent).toBe('Productos');
    expect(el.querySelector('tbody')?.textContent).toContain('Camisa Oxford');
  });

  it('el diálogo de producto nuevo tiene secciones, interruptor del probador y tallas/colores como chips', () => {
    const { fixture } = abrir();
    (fixture.componentInstance as unknown as { abrirCrear(): void }).abrirCrear();
    fixture.detectChanges();

    const dialogo = documento();
    const titulos = Array.from(dialogo.querySelectorAll('.seccion__titulo')).map((t) => t.textContent?.trim());
    expect(titulos).toEqual(['Datos del producto', 'Tallas y colores']);
    expect(dialogo.querySelector('.probador__texto')?.textContent).toContain('Admite probador virtual');
    expect(dialogo.querySelector('p-toggleswitch#admite_probador, p-toggleswitch')).not.toBeNull();
    const tallas = Array.from(dialogo.querySelectorAll('[aria-labelledby="etiqueta-tallas"] .fs-pill')).map((t) =>
      t.textContent?.trim(),
    );
    expect(tallas).toEqual(['S', 'M']);
    expect(dialogo.querySelectorAll('[aria-labelledby="etiqueta-colores"] .pill-color').length).toBe(2);
    expect(dialogo.textContent).toContain('Se crea una variante por cada combinación de talla y color elegidas.');
  });

  it('tocar un chip de talla lo selecciona y vuelve a tocarlo lo quita', () => {
    const { fixture } = abrir();
    const comp = fixture.componentInstance as unknown as {
      abrirCrear(): void;
      formulario: { controls: { tallas_ids: { value: number[] } } };
    };
    comp.abrirCrear();
    fixture.detectChanges();

    const chip = () =>
      documento().querySelector('[aria-labelledby="etiqueta-tallas"] .fs-pill') as HTMLButtonElement;
    chip().click();
    fixture.detectChanges();
    expect(comp.formulario.controls.tallas_ids.value).toEqual([1]);
    expect(chip().getAttribute('aria-pressed')).toBe('true');
    expect(chip().classList).toContain('activa');

    chip().click();
    fixture.detectChanges();
    expect(comp.formulario.controls.tallas_ids.value).toEqual([]);
    expect(chip().getAttribute('aria-pressed')).toBe('false');
  });

  it('guardar sin datos no envía nada y muestra los errores de los campos', () => {
    const { fixture } = abrir();
    (fixture.componentInstance as unknown as { abrirCrear(): void }).abrirCrear();
    fixture.detectChanges();

    const botones = Array.from(documento().querySelectorAll('.producto__form button[type="submit"]'));
    (botones[0] as HTMLButtonElement).click();
    fixture.detectChanges();

    http.expectNone((r) => r.method === 'POST' && r.url === `${API}/productos`);
    const errores = Array.from(documento().querySelectorAll('.fs-error-texto')).map((e) => e.textContent?.trim());
    expect(errores).toContain('Ingresa el código.');
    expect(errores).toContain('Ingresa el nombre.');
    expect(errores).toContain('Elige al menos una talla y un color.');
  });

  /** Abre el producto en edición y responde las variantes y las imágenes. */
  function editar(fixture: ReturnType<typeof abrir>['fixture']): void {
    (fixture.componentInstance as unknown as { abrirEditar(p: unknown): void }).abrirEditar(PRODUCTO);
    http
      .expectOne(`${API}/productos/3/variantes`)
      .flush([{ id: 11, producto_id: 3, talla_id: 1, color_id: 1, sku: 'S-CEL', codigo_barras: null, precio: null, precio_efectivo: 289, activo: true }]);
    http.expectOne(`${API}/catalogo/3`).flush({ imagenes: [{ id: 5, producto_id: 3, color_id: null, public_id: 'x', url: 'x.png', orden: 1, es_principal: false }] });
    fixture.detectChanges();
  }

  it('al editar muestra variantes con interruptor accesible, imágenes con acciones y sin tallas/colores', () => {
    const { fixture } = abrir();
    editar(fixture);

    const dialogo = documento();
    const titulos = Array.from(dialogo.querySelectorAll('.seccion__titulo')).map((t) => t.textContent?.trim());
    expect(titulos).toEqual(['Datos del producto', 'Variantes', 'Imágenes']);
    expect(dialogo.querySelector('#titulo-tallas')).toBeNull();
    expect(dialogo.querySelector('p-toggleswitch[ariaLabel], .tabla-variantes p-toggleswitch')).not.toBeNull();
    expect(dialogo.textContent).toContain('Elegir imagen');
    expect(dialogo.querySelector('[aria-label="Marcar como principal"]')).not.toBeNull();
    expect(dialogo.querySelector('[aria-label="Eliminar imagen"]')).not.toBeNull();
  });

  it('"Agregar tallas/colores" abre su diálogo y envía los ids elegidos', () => {
    const { fixture } = abrir();
    editar(fixture);

    const agregar = Array.from(documento().querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Agregar tallas/colores'),
    ) as HTMLButtonElement;
    agregar.click();
    fixture.detectChanges();
    expect(documento().textContent).toContain('Agregar tallas y colores');

    const grupoTallas = documento().querySelector('[aria-labelledby="etiqueta-tallas-nuevas"]')!;
    const grupoColores = documento().querySelector('[aria-labelledby="etiqueta-colores-nuevos"]')!;
    (grupoTallas.querySelectorAll('.fs-pill')[1] as HTMLButtonElement).click();
    (grupoColores.querySelectorAll('.fs-pill')[0] as HTMLButtonElement).click();
    fixture.detectChanges();

    const enviar = Array.from(documento().querySelectorAll('button[type="submit"]')).find((b) =>
      b.textContent?.includes('Agregar variantes'),
    ) as HTMLButtonElement;
    enviar.click();

    const peticion = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/productos/3/variantes`);
    expect(peticion.request.body).toEqual({ tallas_ids: [2], colores_ids: [1] });
    peticion.flush([]);
    http.expectOne(`${API}/productos/3/variantes`).flush([]);
  });

  it('el diálogo de variantes avisa si no se elige ninguna talla ni color', () => {
    const { fixture } = abrir();
    editar(fixture);
    (Array.from(documento().querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Agregar tallas/colores'),
    ) as HTMLButtonElement).click();
    fixture.detectChanges();

    (Array.from(documento().querySelectorAll('button[type="submit"]')).find((b) =>
      b.textContent?.includes('Agregar variantes'),
    ) as HTMLButtonElement).click();
    fixture.detectChanges();

    http.expectNone((r) => r.method === 'POST' && r.url === `${API}/productos/3/variantes`);
    expect(documento().textContent).toContain('Elige al menos una talla y un color.');
  });

  it('eliminar una imagen pide confirmación antes de borrarla', () => {
    const { fixture } = abrir();
    editar(fixture);

    (documento().querySelector('[aria-label="Eliminar imagen"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    http.expectNone((r) => r.method === 'DELETE');
    expect(documento().textContent).toContain('¿Eliminar esta imagen del producto?');

    (Array.from(documento().querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Sí, eliminar'),
    ) as HTMLButtonElement).click();
    http.expectOne((r) => r.method === 'DELETE' && r.url === `${API}/imagenes/5`).flush({});
    http.expectOne(`${API}/catalogo/3`).flush({ imagenes: [] });
  });
});
