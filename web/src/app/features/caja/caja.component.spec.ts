import 'fake-indexeddb/auto';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Provider, WritableSignal, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { ConectividadService, EstadoConexion } from '../../core/conectividad.service';
import { ColaSincronizacionService } from '../../core/offline/cola-sincronizacion.service';
import { BaseOffline } from '../../core/offline/db-offline';
import { metaSucursalCaja } from '../../core/offline/offline.config';
import type { OperacionOffline, PaqueteLocal } from '../../core/offline/offline.models';
import { ErrorOperacionOffline, OperacionesOfflineService } from '../../core/offline/operaciones-offline.service';
import { RepositorioLocal } from '../../core/offline/repositorio-local';
import { SesionOfflineService } from '../../core/offline/sesion-offline.service';
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

  function configurar(roles: string[], empresaNombre: string | null = 'Boutique Andina', extra: Provider[] = []): void {
    TestBed.configureTestingModule({
      imports: [CajaComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        ...extra,
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

  describe('búsqueda sin conexión (E14)', () => {
    let db: BaseOffline;
    /** Cuántas veces se pidió el almacenamiento local: en línea debe seguir en 0. */
    let pedidosAlRepositorio: number;
    let fallaLaLectura: boolean;
    let nombreBase = 0;

    const paquete = (): PaqueteLocal => ({
      empresa: { id: 1, codigo: 'alfa', nombre: 'Alfa' },
      generadoEn: '2026-10-30T10:00:00Z',
      avisoDesactualizadoHoras: 12,
      sucursales: [{ id: 10, codigo: 'SC', nombre: 'Centro', direccion: 'Calle 1', es_deposito: false, horarios: [] }],
      categorias: [{ id: 1, nombre: 'Poleras', categoria_padre_id: null }],
      tallas: [
        { id: 1, codigo: 'M', orden: 2 },
        { id: 2, codigo: 'L', orden: 3 },
      ],
      colores: [{ id: 1, nombre: 'Negro', codigo_hex: '#000000' }],
      productos: [
        {
          id: 100,
          codigo: 'FS-10005',
          nombre: 'Polera Estampada',
          categoria_id: 1,
          genero: 'hombre',
          temporada_id: null,
          imagen_principal: null,
          variantes: [
            { id: 1000, talla_id: 1, color_id: 1, sku: 'POL-M', codigo_barras: '7770001', precio: '149.00', descuento_unitario: '0.00' },
            { id: 1001, talla_id: 2, color_id: 1, sku: 'POL-L', codigo_barras: null, precio: '149.50', descuento_unitario: '0.00' },
          ],
        },
      ],
      stock: [],
      clientes: [],
      reglas: {
        metodos_pago_offline: ['efectivo'],
        max_operaciones_por_lote: 50,
        plazo_cambio_horas: 24,
        cambios_y_devoluciones: 'solo_en_linea',
        reservas_offline: 'permitidas',
      },
    });

    beforeEach(async () => {
      db = new BaseOffline(`prueba_caja_offline_${++nombreBase}_${Date.now()}`);
      pedidosAlRepositorio = 0;
      fallaLaLectura = false;
      await new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 }).reemplazarReferencia(paquete());
    });

    afterEach(() => db.close());

    function configurarConEstado(estado: EstadoConexion): void {
      configurar(['cajero'], 'Boutique Andina', [
        { provide: ConectividadService, useValue: { estado: signal<EstadoConexion>(estado) } },
        {
          provide: SesionOfflineService,
          useValue: {
            repositorio: () => {
              pedidosAlRepositorio++;
              if (fallaLaLectura) throw new Error('La base no se pudo abrir');
              return new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
            },
          },
        },
      ]);
    }

    function escribirYBuscar(pantalla: ReturnType<typeof abrir>, texto: string): void {
      const entrada = pantalla.el.querySelector('#busqueda') as HTMLInputElement;
      entrada.value = texto;
      entrada.dispatchEvent(new Event('input'));
      entrada.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    }

    const hayBusquedaEnElServidor = () => http.match((r) => r.url === `${API}/catalogo/variantes/buscar`);

    it('sin conexión busca en los datos descargados y NO llama al servidor para buscar', async () => {
      configurarConEstado('sin_conexion');
      const pantalla = abrir(1);

      escribirYBuscar(pantalla, 'POLERA');
      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(pantalla.el.querySelectorAll('#lista-resultados li').length).toBe(2);
      });

      expect(hayBusquedaEnElServidor().length).toBe(0);
      const filas = Array.from(pantalla.el.querySelectorAll('#lista-resultados li')).map((li) => li.textContent);
      expect(filas[0]).toContain('Polera Estampada · M · Negro');
      expect(filas[0]).toContain('149.00');
      expect(filas[1]).toContain('Polera Estampada · L · Negro');
      expect(filas[1]).toContain('149.50');
      expect(pantalla.el.textContent).toContain('Sin conexión: buscaste en los datos descargados');
    });

    it('al elegir un resultado local la línea del carrito lleva el precio descargado', async () => {
      configurarConEstado('sin_conexion');
      const pantalla = abrir(1);
      escribirYBuscar(pantalla, 'polera');
      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(pantalla.el.querySelectorAll('#lista-resultados li').length).toBe(2);
      });

      (pantalla.el.querySelector('#resultado-1') as HTMLElement).click();
      pantalla.fixture.detectChanges();

      expect(pantalla.el.querySelector('.linea-nombre')?.textContent).toBe('Polera Estampada');
      expect(pantalla.el.querySelector('.linea-variante')?.textContent).toBe('L · Negro');
      expect(pantalla.el.querySelector('.total-panel__valor')?.textContent).toContain('Bs 149.50');
      // El aviso de "buscaste sin conexión" se va con la búsqueda.
      expect(pantalla.el.textContent).not.toContain('Sin conexión: buscaste en los datos descargados');
      expect(hayBusquedaEnElServidor().length).toBe(0);
    });

    it('un código de barras que identifica una sola variante la agrega directo', async () => {
      configurarConEstado('sin_conexion');
      const pantalla = abrir(1);

      escribirYBuscar(pantalla, '7770001');
      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(pantalla.el.querySelector('.linea-nombre')?.textContent).toBe('Polera Estampada');
      });

      expect(pantalla.el.querySelector('.linea-variante')?.textContent).toBe('M · Negro');
      expect(pantalla.el.querySelector('.total-panel__valor')?.textContent).toContain('Bs 149.00');
      expect(hayBusquedaEnElServidor().length).toBe(0);
    });

    it('lo que no está en los datos descargados avisa "sin resultados"', async () => {
      configurarConEstado('sin_conexion');
      const agregar = vi.spyOn(TestBed.inject(MessageService), 'add');
      const pantalla = abrir(1);

      escribirYBuscar(pantalla, 'sombrero');
      await vi.waitFor(() =>
        expect(agregar).toHaveBeenCalledWith({
          severity: 'warn',
          summary: 'Sin resultados',
          detail: 'sombrero (en los datos descargados)',
        }),
      );
      pantalla.fixture.detectChanges();
      expect(pantalla.el.querySelector('.linea-nombre')).toBeNull();
      expect(hayBusquedaEnElServidor().length).toBe(0);
    });

    it('con el servidor caído (hay red, pero no responde) también se busca en lo descargado', async () => {
      configurarConEstado('servidor_no_responde');
      const pantalla = abrir(1);

      escribirYBuscar(pantalla, '7770001');
      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(pantalla.el.querySelector('.linea-nombre')?.textContent).toBe('Polera Estampada');
      });
      expect(hayBusquedaEnElServidor().length).toBe(0);
    });

    it('en línea NO cambia nada: pregunta al servidor y no toca el almacenamiento local', () => {
      configurarConEstado('en_linea');
      const pantalla = abrir(1);

      escribirYBuscar(pantalla, 'camisa');
      http.expectOne((r) => r.url === `${API}/catalogo/variantes/buscar`).flush([VARIANTE]);
      pantalla.fixture.detectChanges();

      expect(pantalla.el.querySelector('.linea-nombre')?.textContent).toBe('Camisa Oxford');
      expect(pedidosAlRepositorio).toBe(0);
      expect(pantalla.el.textContent).not.toContain('Sin conexión: buscaste en los datos descargados');
    });

    it('en línea pero la petición falla sin respuesta (status 0) cae a los datos descargados', async () => {
      configurarConEstado('en_linea');
      const pantalla = abrir(1);

      escribirYBuscar(pantalla, '7770001');
      http.expectOne((r) => r.url === `${API}/catalogo/variantes/buscar`).error(new ProgressEvent('error'));

      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(pantalla.el.querySelector('.linea-nombre')?.textContent).toBe('Polera Estampada');
      });
    });

    it('en línea, un error del servidor distinto de "sin respuesta" NO usa los datos locales', () => {
      configurarConEstado('en_linea');
      const pantalla = abrir(1);

      escribirYBuscar(pantalla, 'camisa');
      http
        .expectOne((r) => r.url === `${API}/catalogo/variantes/buscar`)
        .flush({ detail: 'Error' }, { status: 500, statusText: 'Server Error' });
      pantalla.fixture.detectChanges();

      expect(pedidosAlRepositorio).toBe(0);
      expect(pantalla.el.querySelector('.linea-nombre')).toBeNull();
    });

    it('si los datos locales no se pueden leer avisa con claridad y la búsqueda no queda cargando', async () => {
      configurarConEstado('sin_conexion');
      fallaLaLectura = true;
      const agregar = vi.spyOn(TestBed.inject(MessageService), 'add');
      const pantalla = abrir(1);

      escribirYBuscar(pantalla, 'polera');
      await vi.waitFor(() =>
        expect(agregar).toHaveBeenCalledWith(
          expect.objectContaining({ severity: 'error', summary: 'No pudimos buscar sin conexión' }),
        ),
      );
      expect((pantalla.fixture.componentInstance as unknown as { buscando: () => boolean }).buscando()).toBe(false);
    });
  });

  describe('venta sin conexión (E14b)', () => {
    const ALCANCE = { empresaId: 1, usuarioId: 7 };
    const SUCURSAL = 10;

    let db: BaseOffline;
    let nombreBase = 0;
    let estado: WritableSignal<EstadoConexion>;
    let pedidosAlRepositorio: number;
    const cola = { notificarNuevaOperacion: vi.fn(), refrescarConteos: vi.fn() };

    /** Polera M (149,00, stock 5), Polera L (149,50, stock 0) y Camisa (100,00 con 10,00 de descuento, stock 10). */
    const paquete = (): PaqueteLocal => ({
      empresa: { id: 1, codigo: 'alfa', nombre: 'Alfa' },
      generadoEn: '2026-10-30T10:00:00Z',
      avisoDesactualizadoHoras: 12,
      sucursales: [{ id: SUCURSAL, codigo: 'SC', nombre: 'Centro', direccion: 'Calle 1', es_deposito: false, horarios: [] }],
      categorias: [{ id: 1, nombre: 'Poleras', categoria_padre_id: null }],
      tallas: [
        { id: 1, codigo: 'M', orden: 2 },
        { id: 2, codigo: 'L', orden: 3 },
        { id: 3, codigo: 'S', orden: 1 },
      ],
      colores: [{ id: 1, nombre: 'Negro', codigo_hex: '#000000' }],
      productos: [
        {
          id: 100,
          codigo: 'FS-10005',
          nombre: 'Polera Estampada',
          categoria_id: 1,
          genero: 'hombre',
          temporada_id: null,
          imagen_principal: null,
          variantes: [
            { id: 1000, talla_id: 1, color_id: 1, sku: 'POL-M', codigo_barras: '7770001', precio: '149.00', descuento_unitario: '0.00' },
            { id: 1001, talla_id: 2, color_id: 1, sku: 'POL-L', codigo_barras: null, precio: '149.50', descuento_unitario: '0.00' },
          ],
        },
        {
          id: 101,
          codigo: 'FS-10006',
          nombre: 'Camisa Lisa',
          categoria_id: 1,
          genero: 'hombre',
          temporada_id: null,
          imagen_principal: null,
          variantes: [
            { id: 1002, talla_id: 3, color_id: 1, sku: 'CAM-S', codigo_barras: '7770003', precio: '100.00', descuento_unitario: '10.00' },
          ],
        },
      ],
      stock: [
        {
          sucursalId: SUCURSAL,
          generadoEn: '2026-10-30T10:00:00Z',
          items: [
            { variante_id: 1000, cantidad_disponible: 5, actualizado_en: '2026-10-30T10:00:00Z' },
            { variante_id: 1001, cantidad_disponible: 0, actualizado_en: '2026-10-30T10:00:00Z' },
            { variante_id: 1002, cantidad_disponible: 10, actualizado_en: '2026-10-30T10:00:00Z' },
          ],
        },
      ],
      clientes: [],
      reglas: {
        metodos_pago_offline: ['efectivo'],
        max_operaciones_por_lote: 50,
        plazo_cambio_horas: 24,
        cambios_y_devoluciones: 'solo_en_linea',
        reservas_offline: 'permitidas',
      },
    });

    beforeEach(async () => {
      db = new BaseOffline(`prueba_caja_venta_offline_${++nombreBase}_${Date.now()}`);
      pedidosAlRepositorio = 0;
      cola.notificarNuevaOperacion.mockReset();
      cola.refrescarConteos.mockReset().mockResolvedValue(undefined);
      await new RepositorioLocal(db, ALCANCE).reemplazarReferencia(paquete());
    });

    afterEach(() => db.close());

    function configurarVenta(inicial: EstadoConexion): void {
      estado = signal<EstadoConexion>(inicial);
      configurar(['cajero'], 'Boutique Andina', [
        { provide: ConectividadService, useValue: { estado } },
        { provide: ColaSincronizacionService, useValue: cola },
        {
          provide: SesionOfflineService,
          useValue: {
            repositorio: () => {
              pedidosAlRepositorio++;
              return new RepositorioLocal(db, ALCANCE);
            },
            alcance: () => ALCANCE,
            dispositivoId: () => 'equipo-de-prueba',
            guardarSucursalDeCaja: (id: number) =>
              new RepositorioLocal(db, ALCANCE).guardarMeta(metaSucursalCaja(ALCANCE.usuarioId), id),
            sucursalDeCajaGuardada: async () =>
              (await new RepositorioLocal(db, ALCANCE).leerMeta<number>(metaSucursalCaja(ALCANCE.usuarioId))) ?? null,
          },
        },
      ]);
    }

    const guardadas = (): Promise<OperacionOffline[]> => new RepositorioLocal(db, ALCANCE).misOperaciones();
    const hayLlamadasDeVenta = () =>
      http.match((r) => r.url.includes('/ventas') || r.url.includes('/pagos')).length > 0;
    const botonDe = (texto: string) =>
      Array.from(document.body.querySelectorAll('button')).find((b) => b.textContent?.includes(texto)) as
        | HTMLButtonElement
        | undefined;

    /** Busca (en lo descargado) y espera a que el carrito tenga `lineas` renglones. */
    async function agregar(pantalla: Pantalla, texto: string, lineas: number): Promise<void> {
      const entrada = pantalla.el.querySelector('#busqueda') as HTMLInputElement;
      entrada.value = texto;
      entrada.dispatchEvent(new Event('input'));
      entrada.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(pantalla.el.querySelectorAll('.linea-nombre').length).toBe(lineas);
      });
    }

    async function abrirCobro(pantalla: Pantalla): Promise<void> {
      (pantalla.el.querySelector('.btn-cobrar') as HTMLButtonElement).click();
      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(pantalla.el.querySelector('#monto-recibido')).not.toBeNull();
      });
    }

    function escribirMonto(pantalla: Pantalla, monto: string): void {
      const campo = pantalla.el.querySelector('#monto-recibido') as HTMLInputElement;
      campo.value = monto;
      campo.dispatchEvent(new Event('input'));
      pantalla.fixture.detectChanges();
    }

    const confirmar = (pantalla: Pantalla) => (pantalla.el.querySelector('.btn-cobrar') as HTMLButtonElement).click();

    const comprobante = () => document.body.querySelector('#area-imprimible') as HTMLElement | null;
    const textoTotal = (pantalla: Pantalla) => pantalla.el.querySelector('.total-panel__valor')?.textContent ?? '';

    it('sin conexión muestra la franja de ayuda y el cobro solo permite efectivo', async () => {
      configurarVenta('sin_conexion');
      const pantalla = abrir(SUCURSAL);
      expect(pantalla.el.querySelector('.franja-offline')?.textContent).toContain(
        'Estás sin conexión. Las ventas se guardan en este equipo y se envían solas al volver Internet.',
      );
      await agregar(pantalla, '7770001', 1);
      await abrirCobro(pantalla);

      const metodos = Array.from(pantalla.el.querySelectorAll('.metodo')) as HTMLButtonElement[];
      expect(metodos.map((b) => b.textContent?.trim())).toEqual(['Efectivo', 'QR', 'Tarjeta', 'Transferencia']);
      expect(metodos.map((b) => b.disabled)).toEqual([false, true, true, true]);
      expect(metodos[1].getAttribute('title')).toBe('Requiere conexión');
      expect(metodos[0].getAttribute('title')).toBeNull();
      expect(pantalla.el.textContent).toContain('Sin conexión solo se cobra en efectivo');

      // Ni con el clic ni con las flechas se puede cambiar de método.
      metodos[2].click();
      metodos[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
      pantalla.fixture.detectChanges();
      expect(pantalla.el.querySelector('.metodo--activo')?.textContent).toContain('Efectivo');
      expect(pantalla.el.querySelector('#monto-recibido')).not.toBeNull();
      expect(hayLlamadasDeVenta()).toBe(false);
    });

    it('confirmar guarda la venta en este equipo, NO usa la red y muestra el comprobante local con OFF-', async () => {
      configurarVenta('sin_conexion');
      const pantalla = abrir(SUCURSAL);
      await agregar(pantalla, '7770001', 1);
      await abrirCobro(pantalla);
      expect(pantalla.el.querySelector('.btn-cobrar')?.textContent).toContain('Confirmar pago (F9)');
      expect(await guardadas()).toHaveLength(0);

      escribirMonto(pantalla, '200');
      expect(pantalla.el.querySelector('.cambio__valor')?.textContent).toContain('Bs 51.00');
      confirmar(pantalla);
      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(comprobante()).not.toBeNull();
      });

      const operaciones = await guardadas();
      expect(operaciones).toHaveLength(1);
      const [operacion] = operaciones;
      expect(operacion).toMatchObject({
        tipo: 'venta_contado',
        estado: 'registrada',
        sucursal_id: SUCURSAL,
        total: '149.00',
        pago: { metodo: 'efectivo', monto_recibido: '200.00', cambio: '51.00' },
      });
      expect(operacion.lineas).toEqual([
        expect.objectContaining({ variante_id: 1000, cantidad: 1, precio_unitario: '149.00', subtotal: '149.00' }),
      ]);

      const texto = comprobante()!.textContent ?? '';
      expect(comprobante()!.querySelector('h2')?.textContent).toBe('Boutique Andina');
      expect(texto).toContain('Venta registrada sin conexión — pendiente de enviar');
      expect(texto).toContain(`Venta OFF-${operacion.operacion_id.slice(0, 6).toUpperCase()}`);
      expect(operacion.codigo_local).toMatch(/^OFF-[0-9A-F]{6}$/);
      expect(texto).toContain('Polera Estampada · M · Negro x1');
      expect(texto).toContain('Total: 149.00');
      expect(texto).toContain('Recibido: 200.00');
      expect(texto).toContain('Cambio: 51.00');
      expect(texto).toMatch(/\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}/);

      // Carrito vacío, la cola de envío avisada y la red sin tocar.
      expect(pantalla.el.querySelector('.linea-nombre')).toBeNull();
      expect(cola.notificarNuevaOperacion).toHaveBeenCalledTimes(1);
      expect(cola.refrescarConteos).toHaveBeenCalledTimes(1);
      expect(hayLlamadasDeVenta()).toBe(false);

      // "Nueva venta" deja la caja lista para otra.
      botonDe('Nueva venta')!.click();
      pantalla.fixture.detectChanges();
      expect(pantalla.el.querySelector('.btn-cobrar')?.textContent).toContain('Cobrar (F9)');
      expect(pantalla.el.querySelector('.total-panel__valor')?.textContent).toContain('Bs 0.00');
    });

    it('el total mostrado antes de cobrar es el que se guarda, descuento incluido', async () => {
      configurarVenta('sin_conexion');
      const pantalla = abrir(SUCURSAL);
      await agregar(pantalla, '7770003', 1);
      (pantalla.el.querySelector('[aria-label="Aumentar cantidad"]') as HTMLButtonElement).click();
      pantalla.fixture.detectChanges();
      // 2 x (100,00 - 10,00) = 180,00 en el panel, antes de cobrar.
      expect(textoTotal(pantalla)).toContain('Bs 180.00');
      await agregar(pantalla, '7770001', 2);
      expect(textoTotal(pantalla)).toContain('Bs 329.00');

      await abrirCobro(pantalla);
      expect(textoTotal(pantalla)).toContain('Bs 329.00');
      const resumen = pantalla.el.querySelector('.resumen-venta')?.textContent ?? '';
      expect(resumen).toContain('Bs 349.00');
      expect(resumen).toContain('Bs 20.00');

      escribirMonto(pantalla, '400');
      confirmar(pantalla);
      await vi.waitFor(() => expect(comprobante()).not.toBeNull());

      const [operacion] = await guardadas();
      expect(operacion.total).toBe('329.00');
      expect(operacion.lineas.find((l) => l.variante_id === 1002)).toMatchObject({
        cantidad: 2,
        precio_unitario: '100.00',
        descuento_unitario: '10.00',
        subtotal: '180.00',
      });
      const texto = comprobante()!.textContent ?? '';
      expect(texto).toContain('Subtotal: 349.00');
      expect(texto).toContain('Descuento: 20.00');
      expect(texto).toContain('Total: 329.00');
      expect(texto).toContain('Cambio: 71.00');
    });

    it('un efectivo que no cubre el total no se guarda', async () => {
      configurarVenta('sin_conexion');
      const pantalla = abrir(SUCURSAL);
      await agregar(pantalla, '7770001', 1);
      await abrirCobro(pantalla);

      escribirMonto(pantalla, '100');
      confirmar(pantalla);
      await new Promise((r) => setTimeout(r, 30));

      expect(await guardadas()).toHaveLength(0);
      expect(comprobante()).toBeNull();
    });

    describe('reabrir Caja sin conexión (la página se recarga sin red)', () => {
      const abrirSinRed = async (): Promise<Pantalla> => {
        const fixture = TestBed.createComponent(CajaComponent);
        fixture.detectChanges();
        http.expectOne(`${API}/empleados/yo`).error(new ProgressEvent('error'));
        return { fixture, el: fixture.nativeElement as HTMLElement };
      };
      /** Espera a que Caja termine de resolver la sucursal (la lectura local es asíncrona). */
      const terminoDeCargar = (pantalla: Pantalla) =>
        vi.waitFor(() => {
          pantalla.fixture.detectChanges();
          expect(pantalla.el.textContent).not.toContain('Cargando');
        });

      it('con conexión recuerda en qué sucursal cobra la persona', async () => {
        configurarVenta('en_linea');
        abrir(SUCURSAL);

        await vi.waitFor(async () =>
          expect(await new RepositorioLocal(db, ALCANCE).leerMeta(metaSucursalCaja(ALCANCE.usuarioId))).toBe(SUCURSAL),
        );
      });

      it('sin red abre con la sucursal recordada y se puede buscar y vender con lo descargado', async () => {
        await new RepositorioLocal(db, ALCANCE).guardarMeta(metaSucursalCaja(ALCANCE.usuarioId), SUCURSAL);
        configurarVenta('sin_conexion');

        const pantalla = await abrirSinRed();
        await terminoDeCargar(pantalla);

        expect(pantalla.el.textContent).not.toContain('no puedes operar');
        expect(pantalla.el.querySelector('#busqueda')).not.toBeNull();
        await agregar(pantalla, 'camisa', 1);
        expect(hayLlamadasDeVenta()).toBe(false);
      });

      it('sin red y sin sucursal recordada muestra el aviso de siempre (no inventa una sucursal)', async () => {
        configurarVenta('sin_conexion');

        const pantalla = await abrirSinRed();
        await terminoDeCargar(pantalla);

        expect(pantalla.el.querySelector('#busqueda')).toBeNull();
        expect(pantalla.el.textContent).toMatch(/no (eres|tienes)|no puedes/i);
      });

      it('un fallo del servidor distinto de "sin respuesta" NO usa la sucursal recordada', async () => {
        await new RepositorioLocal(db, ALCANCE).guardarMeta(metaSucursalCaja(ALCANCE.usuarioId), SUCURSAL);
        configurarVenta('en_linea');
        const fixture = TestBed.createComponent(CajaComponent);
        fixture.detectChanges();

        http.expectOne(`${API}/empleados/yo`).flush({ detail: 'error' }, { status: 500, statusText: 'Error' });
        fixture.detectChanges();

        expect((fixture.nativeElement as HTMLElement).querySelector('#busqueda')).toBeNull();
      });
    });

    describe('stock local insuficiente', () => {
      async function hastaElAviso(pantalla: Pantalla): Promise<void> {
        await agregar(pantalla, 'POL-L', 1);
        await abrirCobro(pantalla);
        escribirMonto(pantalla, '200');
        confirmar(pantalla);
        await vi.waitFor(() => {
          pantalla.fixture.detectChanges();
          expect(document.body.querySelector('.aviso-sin-stock')).not.toBeNull();
        });
      }

      it('abre la confirmación con las prendas faltantes y NO guarda hasta aceptar', async () => {
        configurarVenta('sin_conexion');
        const pantalla = abrir(SUCURSAL);
        await hastaElAviso(pantalla);

        expect(document.body.querySelector('.aviso-sin-stock')?.textContent).toContain(
          'Según tu información local no hay stock suficiente. La operación se registrará y puede quedar en conflicto.',
        );
        const fila = document.body.querySelector('.faltantes li')?.textContent ?? '';
        expect(fila).toContain('Polera Estampada · L · Negro');
        expect(fila).toContain('Pides 1');
        expect(fila).toContain('hay 0');
        expect(botonDe('Cancelar')).toBeDefined();
        expect(botonDe('Registrar de todos modos')).toBeDefined();

        expect(await guardadas()).toHaveLength(0);
        expect(comprobante()).toBeNull();
        expect(cola.notificarNuevaOperacion).not.toHaveBeenCalled();
      });

      it('aceptar guarda UNA sola operación, con el mismo identificador', async () => {
        configurarVenta('sin_conexion');
        const registrar = vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarVenta');
        const pantalla = abrir(SUCURSAL);
        await hastaElAviso(pantalla);

        botonDe('Registrar de todos modos')!.click();
        await vi.waitFor(() => {
          pantalla.fixture.detectChanges();
          expect(comprobante()).not.toBeNull();
        });
        await new Promise((r) => setTimeout(r, 30));

        const operaciones = await guardadas();
        expect(operaciones).toHaveLength(1);
        expect(operaciones[0].lineas[0]).toMatchObject({ variante_id: 1001, cantidad: 1 });
        expect(registrar).toHaveBeenCalledTimes(2);
        const [primera, segunda] = registrar.mock.calls.map((llamada) => llamada[0]);
        expect(primera.aceptarSinStock).toBeFalsy();
        expect(segunda.aceptarSinStock).toBe(true);
        expect(segunda.operacionId).toBeTruthy();
        expect(segunda.operacionId).toBe(primera.operacionId);
        expect(operaciones[0].operacion_id).toBe(primera.operacionId);
        expect(cola.notificarNuevaOperacion).toHaveBeenCalledTimes(1);
        expect(comprobante()?.textContent).toContain('Venta registrada sin conexión — pendiente de enviar');
      });

      it('cancelar no guarda nada y el cobro sigue abierto', async () => {
        configurarVenta('sin_conexion');
        const pantalla = abrir(SUCURSAL);
        await hastaElAviso(pantalla);

        botonDe('Cancelar')!.click();
        await new Promise((r) => setTimeout(r, 30));
        pantalla.fixture.detectChanges();

        expect(
          (pantalla.fixture.componentInstance as unknown as { sinStockVisible(): boolean }).sinStockVisible(),
        ).toBe(false);
        expect(await guardadas()).toHaveLength(0);
        expect(comprobante()).toBeNull();
        expect(cola.notificarNuevaOperacion).not.toHaveBeenCalled();
        expect(pantalla.el.querySelector('.linea-nombre')?.textContent).toBe('Polera Estampada');
        expect(pantalla.el.querySelector('.btn-cobrar')?.textContent).toContain('Confirmar pago (F9)');

        // Si vuelve a confirmar, el aviso aparece otra vez: nunca se guardó "de paso".
        confirmar(pantalla);
        await vi.waitFor(() => expect(document.body.querySelector('.aviso-sin-stock')).not.toBeNull());
        expect(await guardadas()).toHaveLength(0);
      });
    });

    it('un doble clic en confirmar no duplica la venta', async () => {
      configurarVenta('sin_conexion');
      const registrar = vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarVenta');
      const pantalla = abrir(SUCURSAL);
      await agregar(pantalla, '7770001', 1);
      await abrirCobro(pantalla);
      escribirMonto(pantalla, '200');

      confirmar(pantalla);
      confirmar(pantalla);
      await vi.waitFor(() => expect(comprobante()).not.toBeNull());
      await new Promise((r) => setTimeout(r, 30));

      expect(await guardadas()).toHaveLength(1);
      expect(registrar).toHaveBeenCalledTimes(1);
      expect(cola.notificarNuevaOperacion).toHaveBeenCalledTimes(1);
    });

    it('si la venta no se puede guardar muestra el mensaje y conserva el carrito', async () => {
      configurarVenta('sin_conexion');
      const pantalla = abrir(SUCURSAL);
      const toast = vi.spyOn(TestBed.inject(MessageService), 'add');
      await agregar(pantalla, '7770001', 1);
      await abrirCobro(pantalla);
      // La prenda desaparece de los datos descargados entre abrir el cobro y confirmar.
      await db.variantes.clear();
      escribirMonto(pantalla, '200');
      confirmar(pantalla);

      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(pantalla.el.querySelector('[data-estado="error-offline"]')).not.toBeNull();
      });
      expect(pantalla.el.querySelector('[data-estado="error-offline"]')?.textContent).toContain(
        'Una de las prendas no está en los datos descargados en este equipo.',
      );
      expect(pantalla.el.querySelector('[data-estado="error-offline"]')?.getAttribute('role')).toBe('alert');
      expect(pantalla.el.querySelector('.linea-nombre')?.textContent).toBe('Polera Estampada');
      expect(await guardadas()).toHaveLength(0);
      expect(comprobante()).toBeNull();
      expect(cola.notificarNuevaOperacion).not.toHaveBeenCalled();
      // El botón vuelve a quedar disponible para reintentar.
      expect((pantalla.el.querySelector('.btn-cobrar') as HTMLButtonElement).disabled).toBe(false);
      expect(toast).not.toHaveBeenCalledWith(expect.objectContaining({ severity: 'error' }));
    });

    it('un error del servicio con mensaje propio se muestra tal cual y un error inesperado también avisa', async () => {
      configurarVenta('sin_conexion');
      const registrar = vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarVenta');
      registrar.mockRejectedValueOnce(
        new ErrorOperacionOffline('No hay espacio en este equipo. La operación NO se registró: libera espacio e inténtalo de nuevo.'),
      );
      registrar.mockRejectedValueOnce(new Error('falla interna'));
      const pantalla = abrir(SUCURSAL);
      await agregar(pantalla, '7770001', 1);
      await abrirCobro(pantalla);
      escribirMonto(pantalla, '200');

      confirmar(pantalla);
      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(pantalla.el.querySelector('[data-estado="error-offline"]')?.textContent).toContain('No hay espacio en este equipo');
      });
      expect(pantalla.el.querySelector('.linea-nombre')).not.toBeNull();

      confirmar(pantalla);
      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(pantalla.el.querySelector('[data-estado="error-offline"]')?.textContent).toContain(
          'No se pudo registrar la venta en este equipo. NO se guardó',
        );
      });
      expect(await guardadas()).toHaveLength(0);
      expect(comprobante()).toBeNull();
    });

    it('si una prenda del carrito no está en los datos descargados no abre el cobro y lo dice', async () => {
      configurarVenta('sin_conexion');
      const pantalla = abrir(SUCURSAL);
      await agregar(pantalla, '7770001', 1);
      await db.variantes.clear();

      (pantalla.el.querySelector('.btn-cobrar') as HTMLButtonElement).click();
      await vi.waitFor(() => {
        pantalla.fixture.detectChanges();
        expect(pantalla.el.querySelector('[data-estado="error-offline"]')).not.toBeNull();
      });

      expect(pantalla.el.querySelector('[data-estado="error-offline"]')?.textContent).toContain(
        'no está en los datos descargados en este equipo',
      );
      expect(pantalla.el.querySelector('#monto-recibido')).toBeNull();
      expect(pantalla.el.querySelector('.btn-cobrar')?.textContent).toContain('Cobrar (F9)');
      expect(pantalla.el.querySelector('.linea-nombre')).not.toBeNull();
    });

    it('"Volver al carrito" cierra el cobro sin guardar nada', async () => {
      configurarVenta('sin_conexion');
      const pantalla = abrir(SUCURSAL);
      await agregar(pantalla, '7770001', 1);
      await abrirCobro(pantalla);

      (Array.from(pantalla.el.querySelectorAll('button')).find((b) => b.textContent?.includes('Volver al carrito')) as HTMLButtonElement).click();
      pantalla.fixture.detectChanges();

      expect(pantalla.el.querySelector('#monto-recibido')).toBeNull();
      expect(pantalla.el.querySelector('.btn-cobrar')?.textContent).toContain('Cobrar (F9)');
      expect(pantalla.el.querySelector('.linea-nombre')).not.toBeNull();
      expect(await guardadas()).toHaveLength(0);
    });

    it('sin conexión quedan deshabilitados reserva atendida, historial y devolución, y vuelven al reconectar', async () => {
      configurarVenta('en_linea');
      const pantalla = abrir(SUCURSAL);
      const { fixture, el } = pantalla;
      const botonReserva = () => el.querySelector('.btn-reserva') as HTMLButtonElement;
      const botonHistorial = () => el.querySelector('.btn-historial') as HTMLButtonElement;
      const campoReserva = () => el.querySelector('#reserva') as HTMLInputElement;

      // En línea: todo habilitado y sin franja.
      campoReserva().value = 'R-1';
      campoReserva().dispatchEvent(new Event('input'));
      fixture.detectChanges();
      expect(el.querySelector('.franja-offline')).toBeNull();
      expect(botonReserva().disabled).toBe(false);
      expect(botonHistorial().disabled).toBe(false);
      expect(campoReserva().disabled).toBe(false);

      // Historial abierto en línea; luego se pierde la conexión.
      botonHistorial().click();
      http.expectOne(`${API}/ventas/sucursal/${SUCURSAL}`).flush([{ ...VENTA, estado: 'pagada', fecha: fechaDeHoy() }]);
      fixture.detectChanges();
      const devolucion = () => botonDe('Devolución') as HTMLButtonElement;
      expect(devolucion().disabled).toBe(false);

      estado.set('sin_conexion');
      fixture.detectChanges();
      expect(el.querySelector('.franja-offline')).not.toBeNull();
      expect(botonReserva().disabled).toBe(true);
      expect(botonReserva().getAttribute('title')).toBe('Requiere conexión');
      // ngModel aplica `disabled` en un microtask.
      await vi.waitFor(() => expect(campoReserva().disabled).toBe(true));
      expect(campoReserva().getAttribute('title')).toBe('Requiere conexión');
      expect(botonHistorial().disabled).toBe(true);
      expect(botonHistorial().getAttribute('title')).toBe('Requiere conexión');
      expect(devolucion().disabled).toBe(true);
      expect(devolucion().getAttribute('title')).toBe('Requiere conexión');

      // Aunque se fuerce el método (atajo, Enter), no sale ninguna petición.
      (fixture.componentInstance as unknown as { cargarReserva(): void }).cargarReserva();
      (fixture.componentInstance as unknown as { abrirHistorial(): void }).abrirHistorial();
      expect(http.match(() => true)).toHaveLength(0);

      // Vuelve la conexión: todo regresa sin recargar.
      estado.set('en_linea');
      fixture.detectChanges();
      expect(el.querySelector('.franja-offline')).toBeNull();
      expect(botonReserva().disabled).toBe(false);
      expect(botonHistorial().disabled).toBe(false);
      expect(devolucion().disabled).toBe(false);
      await vi.waitFor(() => expect(campoReserva().disabled).toBe(false));
    });

    it('al volver la conexión con el carrito armado, Cobrar sigue el flujo en línea de siempre', async () => {
      configurarVenta('sin_conexion');
      const pantalla = abrir(SUCURSAL);
      await agregar(pantalla, '7770001', 1);

      estado.set('en_linea');
      pantalla.fixture.detectChanges();
      (pantalla.el.querySelector('.btn-cobrar') as HTMLButtonElement).click();

      const venta = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/ventas/presencial`);
      expect(venta.request.body).toEqual({ sucursal_id: SUCURSAL, detalle: [{ variante_id: 1000, cantidad: 1 }] });
      venta.flush(VENTA);
      pantalla.fixture.detectChanges();
      expect(pantalla.el.querySelector('.total-panel__valor')?.textContent).toContain('Bs 180.00');
      expect((Array.from(pantalla.el.querySelectorAll('.metodo')) as HTMLButtonElement[]).map((b) => b.disabled)).toEqual([
        false, false, false, false,
      ]);
      expect(pantalla.el.textContent).not.toContain('Sin conexión solo se cobra en efectivo');
      expect(await guardadas()).toHaveLength(0);
    });

    it('en línea NO cambia nada: vende por la API y no toca el almacenamiento local', () => {
      configurarVenta('en_linea');
      const registrar = vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarVenta');
      const pantalla = abrir(1);
      const { fixture, el } = pantalla;
      buscarYAgregar(pantalla);
      cobrar(pantalla);

      expect(el.querySelector('.total-panel__valor')?.textContent).toContain('Bs 180.00');
      expect((Array.from(el.querySelectorAll('.metodo')) as HTMLButtonElement[]).map((b) => b.disabled)).toEqual([
        false, false, false, false,
      ]);
      expect(el.textContent).not.toContain('Sin conexión solo se cobra en efectivo');

      const monto = el.querySelector('#monto-recibido') as HTMLInputElement;
      monto.value = '200';
      monto.dispatchEvent(new Event('input'));
      confirmar(pantalla);
      const pago = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/pagos/caja`);
      expect(pago.request.body).toEqual({ venta_id: 55, metodo_pago: 'efectivo', monto_recibido: 200 });
      pago.flush({ pago: { metodo_pago: 'efectivo' }, cambio: 20 });
      fixture.detectChanges();

      const texto = comprobante()!.textContent ?? '';
      expect(texto).toContain('Venta V-0055');
      expect(texto).toContain('Cambio: 20.00');
      expect(texto).not.toContain('sin conexión');
      expect(texto).not.toContain('OFF-');
      expect(registrar).not.toHaveBeenCalled();
      expect(pedidosAlRepositorio).toBe(0);
      expect(cola.notificarNuevaOperacion).not.toHaveBeenCalled();
      expect(cola.refrescarConteos).not.toHaveBeenCalled();
    });
  });
});
