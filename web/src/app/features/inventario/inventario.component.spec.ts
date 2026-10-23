import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { InventarioComponent } from './inventario.component';

const API = environment.apiUrl;

const fila = (producto: string, disponible: number, minimo: number, valor: number) => ({
  producto_id: 1,
  producto,
  variante_id: 1,
  sku: 'SKU-' + producto,
  talla: 'M',
  color: 'Celeste',
  sucursal_id: 1,
  sucursal: 'Central',
  cantidad_fisica: disponible + 1,
  cantidad_reservada: 1,
  cantidad_disponible: disponible,
  stock_minimo: minimo,
  costo_promedio: 10,
  valor_inventario: valor,
});

describe('InventarioComponent', () => {
  let http: HttpTestingController;

  // PrimeNG Tabs observa su tamaño con ResizeObserver, que jsdom no trae.
  beforeAll(() => {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    };
  });

  function abrir(permisos: string[], transferencias: unknown[] = []) {
    TestBed.configureTestingModule({
      imports: [InventarioComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        { provide: AuthService, useValue: { tienePermiso: (p: string) => permisos.includes(p) } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(InventarioComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/sucursales?pagina=1&tamanio=100`).flush([{ id: 1, nombre: 'Central' }]);
    if (permisos.includes('abastecimiento.gestionar')) {
      http.expectOne(`${API}/proveedores?pagina=1&tamanio=100`).flush([]);
      http.expectOne(`${API}/recepciones`).flush([]);
    }
    http
      .expectOne((r) => r.url === `${API}/inventario/consolidado`)
      .flush([fila('Camisa Oxford', 12, 5, 1680), fila('Polera básica', 3, 8, 232)]);
    http.expectOne((r) => r.url === `${API}/transferencias`).flush(transferencias);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  afterEach(() => http.match(() => true));

  it('muestra encabezado, pestañas subrayadas y la tabla consolidada con el valor del inventario', () => {
    const { el } = abrir(['inventario.gestionar']);

    expect(el.querySelector('.fs-eyebrow')?.textContent).toBe('Catálogo');
    expect(el.querySelector('h1')?.textContent).toBe('Inventario');
    const pestanias = Array.from(el.querySelectorAll('.p-tab')).map((t) => t.textContent?.trim());
    expect(pestanias).toEqual(['Consolidado', 'Kardex', 'Límites', 'Alertas', 'Valuación', 'Transferencias']);
    expect(el.querySelectorAll('p-tabpanel[value="consolidado"] tbody tr').length).toBe(2);
    expect(el.querySelector('.panel__total')?.textContent).toContain('Bs 1,912.00');
  });

  it('resalta la fila bajo mínimo con su chip y ofrece las acciones de 44 px', () => {
    const { el } = abrir(['inventario.gestionar']);

    const filas = el.querySelectorAll('p-tabpanel[value="consolidado"] tbody tr');
    expect(filas[0].classList).not.toContain('fila-alerta');
    expect(filas[1].classList).toContain('fila-alerta');
    expect(filas[1].querySelector('.fs-chip--advertencia')?.textContent).toBe('Bajo mínimo');
    expect(filas[1].querySelector('[aria-label="Ajustar stock"]')).not.toBeNull();
    expect(filas[1].querySelector('[aria-label="Ver kardex"]')).not.toBeNull();
  });

  it('"Solo bajo mínimo" y la búsqueda filtran las filas cargadas', () => {
    const { fixture, el } = abrir(['inventario.gestionar']);
    const comp = fixture.componentInstance as unknown as {
      soloBajoMinimo: { set(v: boolean): void };
      textoConsolidado: { set(v: string): void };
    };

    comp.soloBajoMinimo.set(true);
    fixture.detectChanges();
    expect(el.querySelectorAll('p-tabpanel[value="consolidado"] tbody tr').length).toBe(1);
    expect(el.querySelector('p-tabpanel[value="consolidado"] tbody')?.textContent).toContain('Polera básica');
    expect(el.querySelector('.panel__total')?.textContent).toContain('Bs 232.00');

    comp.soloBajoMinimo.set(false);
    comp.textoConsolidado.set('oxford');
    fixture.detectChanges();
    expect(el.querySelectorAll('p-tabpanel[value="consolidado"] tbody tr').length).toBe(1);
    expect(el.querySelector('p-tabpanel[value="consolidado"] tbody')?.textContent).toContain('Camisa Oxford');
  });

  it('sin permisos no hay botón de ajuste ni Recepción', () => {
    const { el } = abrir([]);

    expect(el.querySelector('[aria-label="Ajustar stock"]')).toBeNull();
    expect(el.textContent).not.toContain('Registrar recepción');
  });

  it('con permiso de abastecimiento aparece Recepción y el botón del encabezado', () => {
    const { el } = abrir(['abastecimiento.gestionar']);

    const pestanias = Array.from(el.querySelectorAll('.p-tab')).map((t) => t.textContent?.trim());
    expect(pestanias).toContain('Recepción');
    expect(el.querySelector('.fs-pagina-encabezado')?.textContent).toContain('Registrar recepción');
  });

  it('registrar una recepción envía el formulario y recarga recepciones y consolidado', () => {
    const { fixture } = abrir(['inventario.gestionar', 'abastecimiento.gestionar']);
    const comp = fixture.componentInstance as unknown as {
      formularioRecepcion: { patchValue(v: object): void };
      lineasRecepcion: { at(i: number): { patchValue(v: object): void } };
    };
    comp.formularioRecepcion.patchValue({ codigo: 'REC-9', proveedor_id: 2, sucursal_id: 1, observacion: 'Lote nuevo' });
    comp.lineasRecepcion.at(0).patchValue({ variante_id: 7, cantidad: 3, costo_unitario: 12.5 });

    const formulario = fixture.nativeElement.querySelector('.formulario-recepcion') as HTMLFormElement;
    formulario.dispatchEvent(new Event('submit'));

    const peticion = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/recepciones`);
    expect(peticion.request.body).toEqual({
      codigo: 'REC-9',
      proveedor_id: 2,
      sucursal_id: 1,
      observacion: 'Lote nuevo',
      detalle: [{ variante_id: 7, cantidad: 3, costo_unitario: 12.5 }],
    });
    peticion.flush({ codigo: 'REC-9' });
    http.expectOne((r) => r.method === 'GET' && r.url === `${API}/recepciones`).flush([]);
    http.expectOne((r) => r.url === `${API}/inventario/consolidado`).flush([]);
  });

  it('una recepción incompleta no se envía', () => {
    const { fixture } = abrir(['abastecimiento.gestionar']);

    (fixture.nativeElement.querySelector('.formulario-recepcion') as HTMLFormElement).dispatchEvent(new Event('submit'));

    http.expectNone((r) => r.method === 'POST' && r.url === `${API}/recepciones`);
  });

  it('una transferencia pendiente se envía desde su botón y la lista se recarga', () => {
    const { fixture, el } = abrir(
      ['inventario.gestionar'],
      [
        {
          id: 4,
          codigo: 'T-4',
          estado: 'pendiente',
          sucursal_origen_id: 1,
          sucursal_destino_id: 2,
          fecha_envio: null,
          fecha_recepcion: null,
        },
      ],
    );
    const fila = el.querySelector('p-tabpanel[value="transferencias"] tbody tr') as HTMLElement;
    expect(fila.querySelector('.fs-chip')?.textContent).toBe('Pendiente');

    (fila.querySelector('[aria-label="Enviar"]') as HTMLButtonElement).click();

    http.expectOne((r) => r.method === 'POST' && r.url === `${API}/transferencias/4/enviar`).flush({});
    http.expectOne((r) => r.method === 'GET' && r.url === `${API}/transferencias`).flush([
      {
        id: 4,
        codigo: 'T-4',
        estado: 'en_transito',
        sucursal_origen_id: 1,
        sucursal_destino_id: 2,
        fecha_envio: '2026-10-22T10:00:00',
        fecha_recepcion: null,
      },
    ]);
    http.expectOne((r) => r.url === `${API}/inventario/consolidado`).flush([]);
    fixture.detectChanges();

    const despues = el.querySelector('p-tabpanel[value="transferencias"] tbody tr') as HTMLElement;
    expect(despues.querySelector('.fs-chip--advertencia')?.textContent).toBe('En tránsito');
    expect(despues.querySelector('[aria-label="Recibir"]')).not.toBeNull();
    expect(despues.querySelector('[aria-label="Enviar"]')).toBeNull();
  });
});
