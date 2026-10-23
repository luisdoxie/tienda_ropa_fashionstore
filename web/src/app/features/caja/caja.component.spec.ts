import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { CajaComponent } from './caja.component';

const API = environment.apiUrl;

const VARIANTE = {
  variante_id: 7,
  producto_id: 3,
  producto_nombre: 'Camisa Oxford',
  producto_codigo: 'CAM-001',
  talla_codigo: 'M',
  color_nombre: 'Celeste',
  sku: 'CAM-001-M-CEL',
  codigo_barras: '7790001',
  precio_efectivo: 100,
};

const VENTA = {
  id: 55,
  codigo: 'V-0055',
  canal: 'presencial',
  cliente_id: null,
  sucursal_id: 1,
  cajero_id: 1,
  reserva_id: null,
  estado: 'pendiente_pago',
  fecha: '2026-10-22T10:00:00',
  subtotal: 200,
  descuento: 20,
  costo_envio: 0,
  total: 180,
  detalle: [
    {
      id: 9,
      variante_id: 7,
      cantidad: 2,
      precio_unitario: 100,
      descuento_unitario: 10,
      costo_unitario: null,
      subtotal: 180,
    },
  ],
};

function fechaDeHoy(): string {
  const hoy = new Date();
  const mes = String(hoy.getMonth() + 1).padStart(2, '0');
  const dia = String(hoy.getDate()).padStart(2, '0');
  return `${hoy.getFullYear()}-${mes}-${dia}T09:30:00`;
}

describe('CajaComponent', () => {
  let http: HttpTestingController;

  function configurar(roles: string[], empresaNombre: string | null = 'Boutique Andina'): void {
    TestBed.configureTestingModule({
      imports: [CajaComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        {
          provide: AuthService,
          useValue: {
            roles: signal(roles),
            tienePermiso: () => true,
            usuario: signal({ empresa_nombre: empresaNombre }),
          },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  }

  afterEach(() => http.match(() => true));

  function abrir(sucursalId: number | null) {
    const fixture = TestBed.createComponent(CajaComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, sucursal_id: sucursalId });
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  type Pantalla = ReturnType<typeof abrir>;

  function buscarYAgregar(pantalla: Pantalla): void {
    const entrada = pantalla.el.querySelector('#busqueda') as HTMLInputElement;
    entrada.value = 'camisa';
    entrada.dispatchEvent(new Event('input'));
    entrada.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    http.expectOne((r) => r.url === `${API}/catalogo/variantes/buscar`).flush([VARIANTE]);
    pantalla.fixture.detectChanges();
  }

  function cobrar(pantalla: Pantalla): void {
    (pantalla.el.querySelector('.btn-cobrar') as HTMLButtonElement).click();
    http.expectOne((r) => r.method === 'POST' && r.url === `${API}/ventas/presencial`).flush(VENTA);
    pantalla.fixture.detectChanges();
  }

  it('muestra el encabezado con los atajos y la búsqueda grande', () => {
    configurar(['cajero']);
    const { el } = abrir(1);

    expect(el.querySelector('.fs-eyebrow')?.textContent).toBe('Venta presencial');
    expect(el.querySelector('h1')?.textContent).toBe('Caja');
    const atajos = el.querySelector('.atajos')?.textContent ?? '';
    for (const tecla of ['Enter', 'F2', 'F9', 'Esc']) {
      expect(atajos).toContain(tecla);
    }
    expect(el.querySelector('.busqueda-grande #busqueda')).not.toBeNull();
    expect(el.querySelector('.btn-cobrar')?.textContent).toContain('Cobrar (F9)');
    expect(el.querySelector('.btn-cobrar')?.hasAttribute('disabled')).toBe(true);
  });

  it('un administrador sin sucursal ve el resumen de hoy y no puede cobrar', () => {
    configurar(['administrador']);
    const fixture = TestBed.createComponent(CajaComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, sucursal_id: null });
    http.expectOne((r) => r.url === `${API}/reportes/ventas`).flush({
      resumen: {},
      top_productos: [],
      por_canal: [],
      por_sucursal: [{ sucursal_id: 1, sucursal: 'Central', transacciones: 4, total_ventas: 1250 }],
      detalle: [],
    });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    expect(el.textContent).toContain('Como administrador no tienes una sucursal propia');
    expect(el.querySelector('tbody')?.textContent).toContain('Central');
    expect(el.querySelector('.btn-cobrar')).toBeNull();
  });

  it('sin sucursal asignada avisa en tuteo', () => {
    configurar(['cajero']);
    const { el } = abrir(null);

    expect(el.querySelector('.fs-aviso')?.textContent).toContain('No tienes una sucursal asignada');
  });

  it('agrega un producto al carrito y los botones de 44 px cambian la cantidad', () => {
    configurar(['cajero']);
    const pantalla = abrir(1);
    const { fixture, el } = pantalla;
    buscarYAgregar(pantalla);

    expect(el.querySelector('.linea-nombre')?.textContent).toBe('Camisa Oxford');
    expect(el.querySelector('.linea-variante')?.textContent).toBe('M · Celeste');
    expect(el.querySelector('.total-panel__valor')?.textContent).toContain('Bs 100.00');

    (el.querySelector('[aria-label="Aumentar cantidad"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect((el.querySelector('input.cantidad__valor') as HTMLInputElement).value).toBe('2');
    expect(el.querySelector('.total-panel__valor')?.textContent).toContain('Bs 200.00');

    (el.querySelector('[aria-label="Disminuir cantidad"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect((el.querySelector('input.cantidad__valor') as HTMLInputElement).value).toBe('1');
    expect((el.querySelector('[aria-label="Disminuir cantidad"]') as HTMLButtonElement).disabled).toBe(true);

    (el.querySelector('[aria-label="Quitar producto"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelector('.linea-nombre')).toBeNull();
    expect(el.textContent).toContain('Sin productos todavía. Escanea o busca uno arriba.');
  });

  it('la cantidad se puede escribir: pasar a 20 unidades no exige 19 clics', () => {
    configurar(['cajero']);
    const pantalla = abrir(1);
    const { fixture, el } = pantalla;
    buscarYAgregar(pantalla);

    const campo = () => el.querySelector('input.cantidad__valor') as HTMLInputElement;
    campo().value = '20';
    campo().dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(campo().value).toBe('20');
    expect(el.querySelector('.total-panel__valor')?.textContent).toContain('Bs 2,000.00');

    // Vacío: vuelve a la cantidad anterior.
    campo().value = '';
    campo().dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(campo().value).toBe('20');

    // Decimales: se truncan.
    campo().value = '3.9';
    campo().dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(campo().value).toBe('3');

    // Cero: quita la línea (como antes del rediseño).
    campo().value = '0';
    campo().dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(el.querySelector('input.cantidad__valor')).toBeNull();
  });

  it('Cobrar crea la venta y muestra métodos de pago, monto recibido y cambio', () => {
    configurar(['cajero']);
    const pantalla = abrir(1);
    const { fixture, el } = pantalla;
    buscarYAgregar(pantalla);

    (el.querySelector('.btn-cobrar') as HTMLButtonElement).click();
    const venta = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/ventas/presencial`);
    expect(venta.request.body).toEqual({ sucursal_id: 1, detalle: [{ variante_id: 7, cantidad: 1 }] });
    venta.flush(VENTA);
    fixture.detectChanges();

    expect(el.querySelector('.total-panel__valor')?.textContent).toContain('Bs 180.00');
    expect(el.querySelector('.resumen-venta')?.textContent).toContain('Bs 20.00');
    const metodos = Array.from(el.querySelectorAll('.metodo')).map((b) => b.textContent?.trim());
    expect(metodos).toEqual(['Efectivo', 'QR', 'Tarjeta', 'Transferencia']);
    expect(el.querySelector('.metodo--activo')?.textContent).toContain('Efectivo');
    expect(el.querySelector('.btn-cobrar')?.textContent).toContain('Confirmar pago (F9)');

    const monto = el.querySelector('#monto-recibido') as HTMLInputElement;
    monto.value = '200';
    monto.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(el.querySelector('.cambio__valor')?.textContent).toContain('Bs 20.00');

    (el.querySelectorAll('.metodo')[2] as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelector('.metodo--activo')?.textContent).toContain('Tarjeta');
    expect(el.querySelector('#monto-recibido')).toBeNull();
  });

  it('F9 dispara el cobro como atajo de teclado', () => {
    configurar(['cajero']);
    const pantalla = abrir(1);
    buscarYAgregar(pantalla);

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'F9' }));

    http.expectOne((r) => r.method === 'POST' && r.url === `${API}/ventas/presencial`);
  });

  it('confirmar el pago envía el monto y abre el comprobante con la empresa y el nombre de la prenda', () => {
    configurar(['cajero']);
    const pantalla = abrir(1);
    const { fixture, el } = pantalla;
    buscarYAgregar(pantalla);
    cobrar(pantalla);

    const monto = el.querySelector('#monto-recibido') as HTMLInputElement;
    monto.value = '200';
    monto.dispatchEvent(new Event('input'));
    (el.querySelector('.btn-cobrar') as HTMLButtonElement).click();

    const pago = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/pagos/caja`);
    expect(pago.request.body).toEqual({ venta_id: 55, metodo_pago: 'efectivo', monto_recibido: 200 });
    pago.flush({ pago: { metodo_pago: 'efectivo' }, cambio: 20 });
    fixture.detectChanges();

    const comprobante = document.body.querySelector('#area-imprimible') as HTMLElement;
    expect(comprobante.querySelector('h2')?.textContent).toBe('Boutique Andina');
    expect(comprobante.textContent).toContain('Camisa Oxford · M · Celeste x2');
    expect(comprobante.textContent).toContain('Cambio: 20.00');
    expect(comprobante.textContent).not.toContain('FashionStore');

    const nueva = Array.from(document.body.querySelectorAll('.comprobante-acciones button')).find((b) =>
      b.textContent?.includes('Nueva venta'),
    ) as HTMLButtonElement;
    nueva.click();
    fixture.detectChanges();
    expect(el.querySelector('.linea-nombre')).toBeNull();
    expect(el.querySelector('.btn-cobrar')?.textContent).toContain('Cobrar (F9)');
  });

  it('un efectivo que no cubre el total no se envía', () => {
    configurar(['cajero']);
    const pantalla = abrir(1);
    const { el } = pantalla;
    buscarYAgregar(pantalla);
    cobrar(pantalla);

    const monto = el.querySelector('#monto-recibido') as HTMLInputElement;
    monto.value = '50';
    monto.dispatchEvent(new Event('input'));
    (el.querySelector('.btn-cobrar') as HTMLButtonElement).click();

    http.expectNone(`${API}/pagos/caja`);
  });

  it('sin nombre de empresa en la sesión el comprobante usa un título neutro y "Variante id"', () => {
    configurar(['cajero'], null);
    const { fixture } = abrir(1);
    const comp = fixture.componentInstance as unknown as {
      ventaConfirmada: { set(v: unknown): void };
      comprobanteVisible: { set(v: boolean): void };
    };
    comp.ventaConfirmada.set(VENTA);
    comp.comprobanteVisible.set(true);
    fixture.detectChanges();

    const comprobante = document.body.querySelector('#area-imprimible') as HTMLElement;
    expect(comprobante.querySelector('h2')?.textContent).toBe('Comprobante de venta');
    expect(comprobante.textContent).toContain('Variante 7 x2');
  });

  it('el historial de hoy permite registrar una devolución', () => {
    configurar(['cajero']);
    const { fixture, el } = abrir(1);

    Array.from(el.querySelectorAll('button'))
      .find((b) => b.textContent?.includes('Historial de hoy'))!
      .click();
    http.expectOne(`${API}/ventas/sucursal/1`).flush([
      { ...VENTA, estado: 'pagada', fecha: fechaDeHoy() },
      { ...VENTA, id: 56, codigo: 'V-0056', estado: 'anulada', fecha: fechaDeHoy() },
    ]);
    fixture.detectChanges();

    const filas = document.body.querySelectorAll('.p-dialog tbody tr');
    expect(filas.length).toBe(2);
    // Orden: la venta más reciente primero (id mayor); solo la pagada ofrece devolución.
    expect(filas[0].textContent).toContain('V-0056');
    expect(filas[0].textContent).not.toContain('Devolución');
    expect(filas[1].textContent).toContain('Devolución');

    const abrirDevolucion = Array.from(filas[1].querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Devolución'),
    ) as HTMLButtonElement;
    abrirDevolucion.click();
    fixture.detectChanges();

    const cantidad = document.body.querySelector('input.input-cantidad') as HTMLInputElement;
    cantidad.value = '1';
    cantidad.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    const confirmar = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Confirmar devolución'),
    ) as HTMLButtonElement;
    confirmar.click();

    const devolucion = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/devoluciones`);
    expect(devolucion.request.body).toEqual({ venta_id: 55, detalle: [{ venta_detalle_id: 9, cantidad: 1 }] });
  });

  it('F2 lleva el foco al código de reserva y Esc limpia la búsqueda', () => {
    configurar(['cajero']);
    const { fixture, el } = abrir(1);

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'F2' }));
    expect(document.activeElement?.id).toBe('reserva');

    const entrada = el.querySelector('#busqueda') as HTMLInputElement;
    entrada.value = 'polera';
    entrada.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    entrada.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();
    expect((fixture.componentInstance as unknown as { textoBusqueda(): string }).textoBusqueda()).toBe('');
  });

  it('con varios resultados la búsqueda anuncia la opción activa y las flechas la mueven', () => {
    configurar(['cajero']);
    const { fixture, el } = abrir(1);
    const entrada = el.querySelector('#busqueda') as HTMLInputElement;
    entrada.value = 'camisa';
    entrada.dispatchEvent(new Event('input'));
    entrada.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    http
      .expectOne((r) => r.url === `${API}/catalogo/variantes/buscar`)
      .flush([VARIANTE, { ...VARIANTE, variante_id: 8, talla_codigo: 'L' }]);
    fixture.detectChanges();

    expect(entrada.getAttribute('aria-activedescendant')).toBe('resultado-0');
    expect(el.querySelector('#resultado-0')?.getAttribute('aria-selected')).toBe('true');
    entrada.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    fixture.detectChanges();
    expect(entrada.getAttribute('aria-activedescendant')).toBe('resultado-1');
  });

  it('los métodos de pago se recorren con las flechas del teclado', () => {
    configurar(['cajero']);
    const pantalla = abrir(1);
    const { fixture, el } = pantalla;
    buscarYAgregar(pantalla);
    cobrar(pantalla);

    const metodos = () => Array.from(el.querySelectorAll('.metodo')) as HTMLButtonElement[];
    expect(metodos()[0].getAttribute('tabindex')).toBe('0');
    expect(metodos()[1].getAttribute('tabindex')).toBe('-1');
    metodos()[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    fixture.detectChanges();
    expect(metodos()[1].getAttribute('aria-checked')).toBe('true');
    expect(document.activeElement).toBe(metodos()[1]);
    metodos()[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    fixture.detectChanges();
    expect(metodos()[0].getAttribute('aria-checked')).toBe('true');
  });
});
