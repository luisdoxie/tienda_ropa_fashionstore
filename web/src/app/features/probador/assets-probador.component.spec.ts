import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../environments/environment';
import { AssetsProbadorComponent } from './assets-probador.component';

const API = environment.apiUrl;

const PENDIENTE = { id: 1, tipo: 'overlay_2d', estado: 'pendiente', url: 'a.png', ancho_px: 600, alto_px: 800 };
const VALIDADO = { id: 2, tipo: 'thumb', estado: 'validado', url: 'b.png', ancho_px: 512, alto_px: 512 };

type Comp = {
  varianteId: { set(v: number | null): void };
  cargarAssets(): void;
  archivoNuevo: File | null;
};

describe('AssetsProbadorComponent', () => {
  let http: HttpTestingController;

  function abrir() {
    TestBed.configureTestingModule({
      imports: [AssetsProbadorComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(AssetsProbadorComponent);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement, comp: fixture.componentInstance as unknown as Comp };
  }

  const boton = (el: HTMLElement, texto: string) =>
    Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes(texto)) as HTMLButtonElement;

  function cargarAssets(pantalla: ReturnType<typeof abrir>, assets: unknown[]): void {
    pantalla.comp.varianteId.set(7);
    pantalla.comp.cargarAssets();
    http.expectOne((r) => r.url === `${API}/probador/assets` && r.params.get('variante_id') === '7').flush(assets);
    pantalla.fixture.detectChanges();
  }

  afterEach(() => http.match(() => true));

  it('"Cargar assets" y "Subir" se habilitan solo con una variante', () => {
    const { fixture, el, comp } = abrir();

    expect(boton(el, 'Cargar assets').disabled).toBe(true);
    expect(boton(el, 'Subir').disabled).toBe(true);

    comp.varianteId.set(7);
    fixture.detectChanges();
    expect(boton(el, 'Cargar assets').disabled).toBe(false);
  });

  it('cargar assets de una variante los lista con su estado y muestra el detalle del elegido', () => {
    const pantalla = abrir();
    const { fixture, el } = pantalla;
    cargarAssets(pantalla, [PENDIENTE, VALIDADO]);

    const chips = el.querySelectorAll('.asset-chip');
    expect(chips.length).toBe(2);
    expect(chips[0].querySelector('.fs-chip--advertencia')?.textContent).toBe('pendiente');
    expect(chips[1].querySelector('.fs-chip--exito')?.textContent).toBe('validado');

    (chips[1] as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelector('.datos')?.textContent).toContain('512 × 512 px');
    expect(boton(el, 'Validar').disabled).toBe(true);

    (chips[0] as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelector('.datos')?.textContent).toContain('600 × 800 px');
    expect(boton(el, 'Validar').disabled).toBe(false);
  });

  it('validar un asset pendiente lo marca como validado y recarga la lista', () => {
    const pantalla = abrir();
    const { fixture, el } = pantalla;
    cargarAssets(pantalla, [PENDIENTE]);
    (el.querySelector('.asset-chip') as HTMLButtonElement).click();
    fixture.detectChanges();

    boton(el, 'Validar').click();
    http
      .expectOne((r) => r.method === 'PUT' && r.url === `${API}/probador/assets/1/validar`)
      .flush({ ...PENDIENTE, estado: 'validado' });
    http.expectOne((r) => r.method === 'GET' && r.url === `${API}/probador/assets`).flush([{ ...PENDIENTE, estado: 'validado' }]);
    fixture.detectChanges();

    expect(el.querySelector('.datos .fs-chip--exito')?.textContent).toBe('validado');
    expect(boton(el, 'Validar').disabled).toBe(true);
  });

  it('subir un PNG envía el tipo, la variante y el archivo, y selecciona el asset creado', () => {
    const pantalla = abrir();
    const { fixture, el, comp } = pantalla;
    comp.varianteId.set(7);
    const archivo = new File(['png'], 'camisa.png', { type: 'image/png' });
    const entrada = el.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(entrada, 'files', { value: [archivo] });
    entrada.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(el.querySelector('.subir')?.textContent).toContain('camisa.png');

    boton(el, 'Subir').click();
    const peticion = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/probador/assets`);
    const cuerpo = peticion.request.body as FormData;
    expect(cuerpo.get('variante_id')).toBe('7');
    expect(cuerpo.get('tipo')).toBe('overlay_2d');
    expect((cuerpo.get('archivo') as File).name).toBe('camisa.png');
    peticion.flush(PENDIENTE);
    http.expectOne((r) => r.method === 'GET' && r.url === `${API}/probador/assets`).flush([PENDIENTE]);
    fixture.detectChanges();

    expect(el.querySelector('.datos')?.textContent).toContain('600 × 800 px');
  });
});
