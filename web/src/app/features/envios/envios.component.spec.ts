import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { EnviosComponent } from './envios.component';

const API = environment.apiUrl;

const envio = (id: number, estado: string) => ({
  id,
  venta_id: 100 + id,
  estado,
  repartidor: null,
  costo: 15,
  fecha_entrega: null,
});

describe('EnviosComponent', () => {
  let http: HttpTestingController;

  function abrir() {
    TestBed.configureTestingModule({
      imports: [EnviosComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(EnviosComponent);
    fixture.detectChanges();
    http
      .expectOne((r) => r.url === `${API}/envios`)
      .flush([envio(1, 'programado'), envio(2, 'en_ruta'), envio(3, 'entregado'), envio(4, 'fallido')]);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  afterEach(() => http.match(() => true));

  it('dibuja el encabezado y un chip de estado por envío', () => {
    const { el } = abrir();

    expect(el.querySelector('.fs-eyebrow')?.textContent).toBe('Comercial');
    expect(el.querySelector('h1')?.textContent).toBe('Envíos');
    const chips = Array.from(el.querySelectorAll('tbody .fs-chip')).map((c) => c.textContent?.trim());
    expect(chips).toEqual(['Programado', 'En ruta', 'Entregado', 'Fallido']);
    expect(el.querySelector('tbody .fs-chip--exito')?.textContent).toBe('Entregado');
    expect(el.querySelector('tbody .fs-chip--error')?.textContent).toBe('Fallido');
  });

  it('ofrece solo las acciones que corresponden a cada estado', () => {
    const { el } = abrir();
    const filas = el.querySelectorAll('tbody tr');
    const acciones = (i: number) =>
      Array.from(filas[i].querySelectorAll('.acciones button')).map((b) => b.textContent?.trim());

    expect(acciones(0)).toEqual(['Enviar', 'Falló']);
    expect(acciones(1)).toEqual(['Entregado', 'Falló']);
    expect(acciones(2)).toEqual([]);
    expect(acciones(3)).toEqual([]);
  });

  it('la paginación deshabilita los botones cuando no hay más páginas', () => {
    const { el } = abrir();

    expect((el.querySelector('[aria-label="Página anterior"]') as HTMLButtonElement).disabled).toBe(true);
    expect((el.querySelector('[aria-label="Página siguiente"]') as HTMLButtonElement).disabled).toBe(true);
    expect(el.querySelector('.panel__pie')?.textContent).toContain('Página 1');
  });
});
