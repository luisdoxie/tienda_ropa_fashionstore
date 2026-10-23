import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../environments/environment';
import { CategoriasComponent } from './categorias.component';

const API = environment.apiUrl;

/** Patrón de las pantallas CRUD simples (canvas Crud), probado sobre Categorías. */
describe('CategoriasComponent (patrón CRUD)', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [CategoriasComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.match(() => true));

  function crear() {
    const fixture = TestBed.createComponent(CategoriasComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/categorias?pagina=1&tamanio=100`).flush([]);
    http
      .expectOne(`${API}/categorias?pagina=1&tamanio=20`)
      .flush([{ id: 1, nombre: 'Camisas', descripcion: 'Formales', categoria_padre_id: null, activo: true }]);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  const documento = () => document.body;

  it('dibuja el encabezado de la pantalla con rótulo, título y "Nueva categoría"', () => {
    const { el } = crear();

    expect(el.querySelector('.fs-eyebrow')?.textContent).toBe('Catálogo');
    expect(el.querySelector('h1')?.textContent).toBe('Categorías');
    expect(el.querySelector('[data-testid="tabla-nuevo"]')?.textContent).toContain('Nueva categoría');
    expect(el.querySelector('input[placeholder="Buscar categoría"]')).not.toBeNull();
    expect(el.querySelector('tbody tr td')?.textContent).toContain('Camisas');
  });

  it('el botón abre el diálogo "Nueva categoría" con pie Cancelar / Guardar', () => {
    const { fixture, el } = crear();

    (el.querySelector('[data-testid="tabla-nuevo"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(documento().querySelector('.p-dialog-title')?.textContent).toContain('Nueva categoría');
    const guardar = documento().querySelector('[data-testid="dialogo-guardar"]') as HTMLButtonElement;
    expect(guardar.getAttribute('form')).toBe('form-categoria');
    expect(guardar.type).toBe('submit');
    expect(documento().querySelector('[data-testid="dialogo-cancelar"]')?.textContent).toContain('Cancelar');
    expect(documento().querySelector('form#form-categoria')).not.toBeNull();
  });

  it('al editar el título cambia a "Editar categoría"', () => {
    const { fixture, el } = crear();

    (el.querySelector('tbody [aria-label="Editar"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(documento().querySelector('.p-dialog-title')?.textContent).toContain('Editar categoría');
  });

  it('guardar sin nombre no envía nada y muestra el error del campo', () => {
    const { fixture, el } = crear();
    (el.querySelector('[data-testid="tabla-nuevo"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    const formulario = documento().querySelector('form#form-categoria') as HTMLFormElement;
    formulario.dispatchEvent(new Event('submit'));
    fixture.detectChanges();

    http.expectNone(`${API}/categorias`);
    expect(formulario.querySelector('.fs-error-texto')?.textContent).toContain('Ingresa el nombre.');
  });

  it('guardar con datos válidos crea la categoría y recarga la tabla', () => {
    const { fixture, el } = crear();
    (el.querySelector('[data-testid="tabla-nuevo"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    const comp = fixture.componentInstance as unknown as { formulario: { patchValue(v: object): void } };
    comp.formulario.patchValue({ nombre: 'Pantalones' });
    (documento().querySelector('form#form-categoria') as HTMLFormElement).dispatchEvent(new Event('submit'));

    const peticion = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/categorias`);
    expect(peticion.request.body).toMatchObject({ nombre: 'Pantalones', categoria_padre_id: null });
    peticion.flush({});
  });
});
