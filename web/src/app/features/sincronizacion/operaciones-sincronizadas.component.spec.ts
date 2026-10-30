import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { OperacionSync, OperacionSyncDetalle, OperacionSyncPagina } from '../../core/models/sincronizacion.models';
import {
  OperacionesSincronizadasComponent,
  TAMANIO_PAGINA,
  horasDeRetraso,
  vistaEstadoSync,
} from './operaciones-sincronizadas.component';

const API = environment.apiUrl;
const OPS = `${API}/sincronizacion/operaciones`;
const VARIANTES = `${API}/catalogo/variantes/detalle`;

const ID_A = '11111111-1111-4111-8111-111111111111';
const ID_B = '22222222-2222-4222-8222-222222222222';
const ID_C = '33333333-3333-4333-8333-333333333333';
const ID_D = '44444444-4444-4444-8444-444444444444';

const COMPLETO = ['sincronizacion.supervisar', 'sincronizacion.resolver', 'usuarios.gestionar'];

function op(id: string, extra: Partial<OperacionSync> = {}): OperacionSync {
  return {
    operacion_id: id,
    tipo: 'venta_contado',
    estado: 'confirmada',
    motivo: null,
    mensaje: null,
    sucursal_id: 1,
    usuario_id: 7,
    fecha_operacion: '2026-10-29T14:00:00Z',
    recibida_en: '2026-10-29T14:05:00Z',
    procesada_en: '2026-10-29T14:05:01Z',
    intentos: 1,
    dispositivo: 'PWA Chrome',
    recurso: { tipo: 'venta', id: 1, codigo: 'V-0001', total: '120.00', fecha_expiracion: null },
    cambio: '0.00',
    avisos: [],
    faltantes: [],
    resolucion: null,
    ...extra,
  };
}

function detalle(id: string, extra: Partial<OperacionSyncDetalle> = {}): OperacionSyncDetalle {
  return {
    ...op(id),
    payload: {
      cliente_id: 5,
      lineas: [
        { variante_id: 11, cantidad: 3, precio_unitario: '120.00', descuento_unitario: '0.00' },
        { variante_id: 12, cantidad: 1, precio_unitario: '50.00', descuento_unitario: '10.00' },
      ],
      total: '400.00',
      pago: { metodo: 'efectivo', monto_recibido: '500.00' },
    },
    ...extra,
  };
}

/** Una venta en conflicto de stock con todo lo que el detalle puede mostrar. */
function conflicto(id: string, extra: Partial<OperacionSyncDetalle> = {}): OperacionSyncDetalle {
  return detalle(id, {
    estado: 'en_conflicto',
    motivo: 'stock_insuficiente',
    recurso: null,
    cambio: null,
    intentos: 3,
    faltantes: [{ variante_id: 11, solicitado: 3, disponible: 1 }],
    avisos: [{ codigo: 'precio_distinto', variante_id: 12, precio_operacion: '120.00', precio_actual: '130.00' }],
    ...extra,
  });
}

function reservaEnConflicto(id: string): OperacionSyncDetalle {
  return conflicto(id, {
    tipo: 'reserva',
    payload: {
      cliente_id: 9,
      fecha_visita: '2026-11-02',
      hora_visita_desde: '10:00',
      hora_visita_hasta: '11:00',
      observacion: 'Viene con su hermana',
      lineas: [{ variante_id: 11, cantidad: 2 }],
    },
    faltantes: [{ variante_id: 11, solicitado: 2, disponible: 0 }],
    avisos: [],
  });
}

function pagina(items: OperacionSync[], total = items.length, numero = 1): OperacionSyncPagina {
  return { total, pagina: numero, tamanio: TAMANIO_PAGINA, items };
}

const PRENDAS = [
  { variante_id: 11, producto_id: 1, producto_nombre: 'Polera Estampada', imagen_principal: null, talla_codigo: 'M', color_nombre: 'Negro' },
  { variante_id: 12, producto_id: 2, producto_nombre: 'Camisa Lino', imagen_principal: null, talla_codigo: 'L', color_nombre: 'Blanco' },
];

describe('horasDeRetraso', () => {
  it('es nulo hasta 1 hora (inclusive) y cuenta las horas redondeadas desde ahí', () => {
    expect(horasDeRetraso('2026-10-29T14:30:00Z', '2026-10-29T14:00:00Z')).toBeNull();
    expect(horasDeRetraso('2026-10-29T15:00:00Z', '2026-10-29T14:00:00Z')).toBeNull();
    expect(horasDeRetraso('2026-10-29T15:00:01Z', '2026-10-29T14:00:00Z')).toBe(1);
    expect(horasDeRetraso('2026-10-29T17:10:00Z', '2026-10-29T14:00:00Z')).toBe(3);
    expect(horasDeRetraso('2026-10-30T14:00:00Z', '2026-10-29T14:00:00Z')).toBe(24);
  });

  it('una fecha ilegible no inventa un retraso', () => {
    expect(horasDeRetraso('no es una fecha', '2026-10-29T14:00:00Z')).toBeNull();
  });
});

describe('vistaEstadoSync', () => {
  it('cada estado tiene texto, ícono y color propios; registrada y enviada son grises', () => {
    expect(vistaEstadoSync('confirmada')).toMatchObject({ texto: 'Confirmada', severidad: 'success', icono: 'check' });
    expect(vistaEstadoSync('rechazada')).toMatchObject({ texto: 'Rechazada', severidad: 'danger', icono: 'cerrar' });
    expect(vistaEstadoSync('en_conflicto')).toMatchObject({ texto: 'En conflicto', severidad: 'warn', icono: 'advertencia' });
    expect(vistaEstadoSync('registrada').severidad).toBe('secondary');
    expect(vistaEstadoSync('enviada').severidad).toBe('info');
    expect(vistaEstadoSync('otra_cosa')).toMatchObject({ texto: 'otra_cosa', severidad: 'secondary' });
  });
});

describe('OperacionesSincronizadasComponent', () => {
  let fixture: ComponentFixture<OperacionesSincronizadasComponent>;
  let http: HttpTestingController;
  let avisos: ReturnType<typeof vi.spyOn>;
  let comp: any;
  let el: HTMLElement;

  interface Inicio {
    permisos?: string[];
    items?: OperacionSync[];
    total?: number;
    conflictos?: number;
    sinResponder?: boolean;
  }

  const lista = () =>
    http.expectOne((r) => r.url === OPS && r.params.get('tamanio') === String(TAMANIO_PAGINA) && r.method === 'GET');
  const cuenta = () => http.expectOne((r) => r.url === OPS && r.params.get('tamanio') === '1');
  const sucursalesReq = () => http.expectOne((r) => r.url === `${API}/sucursales`);

  function iniciar(opciones: Inicio = {}): void {
    const permisos = opciones.permisos ?? COMPLETO;
    TestBed.configureTestingModule({
      imports: [OperacionesSincronizadasComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        { provide: AuthService, useValue: { tienePermiso: (codigo: string) => permisos.includes(codigo) } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    avisos = vi.spyOn(TestBed.inject(MessageService), 'add');
    fixture = TestBed.createComponent(OperacionesSincronizadasComponent);
    el = fixture.nativeElement as HTMLElement;
    comp = fixture.componentInstance;
    fixture.detectChanges();
    if (opciones.sinResponder) return;

    const items = opciones.items ?? [];
    lista().flush(pagina(items, opciones.total ?? items.length));
    cuenta().flush(pagina([], opciones.conflictos ?? 0));
    sucursalesReq().flush([
      { id: 1, nombre: 'Sucursal Centro' },
      { id: 2, nombre: 'Sucursal Norte' },
    ]);
    if (permisos.includes('usuarios.gestionar')) {
      http.expectOne((r) => r.url === `${API}/usuarios`).flush([
        { id: 7, nombre: 'Carla', apellido: 'Rojas', email: 'c@x.com', telefono: null, activo: true, roles: [] },
        { id: 8, nombre: 'Diego', apellido: 'Mamani', email: 'd@x.com', telefono: null, activo: true, roles: [] },
      ]);
    }
    fixture.detectChanges();
  }

  const filas = () => Array.from(el.querySelectorAll('tbody tr[data-operacion]')) as HTMLElement[];
  const fila = (id: string) => el.querySelector(`tbody tr[data-operacion="${id}"]`) as HTMLElement;
  const celdas = (id: string) =>
    Array.from(fila(id).querySelectorAll('td')).map((c) => c.textContent?.replace(/\s+/g, ' ').trim() ?? '');
  const dlg = (clase: string) => document.body.querySelector(`.${clase}`) as HTMLElement | null;
  const texto = (nodo: Element | null | undefined) => nodo?.textContent?.replace(/\s+/g, ' ').trim() ?? '';

  /** Abre el detalle de una fila y responde a las dos llamadas que dispara (detalle y nombres de prendas). */
  function abrirDetalle(d: OperacionSyncDetalle, prendas = PRENDAS): void {
    (fila(d.operacion_id).querySelector('[data-accion="detalle"]') as HTMLButtonElement).click();
    http.expectOne(`${OPS}/${d.operacion_id}`).flush(d);
    const pedido = http.match((r) => r.url === VARIANTES);
    expect(pedido.length).toBe(1);
    pedido[0].flush(prendas);
    fixture.detectChanges();
  }

  function escribir(selector: string, valor: string): void {
    const campo = dlg(selector.split(' ')[0])!.querySelector(selector.split(' ')[1]) as HTMLTextAreaElement;
    campo.value = valor;
    campo.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  const botonForzar = () => dlg('dlg-forzar')!.querySelector('[data-accion="confirmar-forzar"]') as HTMLButtonElement;
  const botonRechazar = () => dlg('dlg-rechazar')!.querySelector('[data-accion="confirmar-rechazar"]') as HTMLButtonElement;

  afterEach(() => {
    try {
      http.verify();
    } finally {
      fixture.destroy();
      document.body.querySelectorAll('.p-dialog-mask, .p-dialog').forEach((n) => n.remove());
      TestBed.resetTestingModule();
    }
  });

  describe('lista', () => {
    it('al entrar pide la página 1 de 20 sin filtros, y el conteo de conflictos', () => {
      iniciar({ sinResponder: true });
      const pedida = lista();
      expect(pedida.request.params.keys().sort()).toEqual(['pagina', 'tamanio']);
      expect(pedida.request.params.get('pagina')).toBe('1');
      const conteo = cuenta();
      expect(conteo.request.params.get('estado')).toBe('en_conflicto');
      pedida.flush(pagina([]));
      conteo.flush(pagina([]));
      sucursalesReq().flush([]);
      http.expectOne((r) => r.url === `${API}/usuarios`).flush([]);
    });

    it('muestra cada operación con sus datos: tipo, sucursal, usuario, total, estado e intentos', () => {
      iniciar({
        items: [
          op(ID_A, { intentos: 2 }),
          op(ID_B, { tipo: 'reserva', estado: 'rechazada', motivo: 'reserva_vencida', recurso: null, sucursal_id: 2, usuario_id: 8 }),
        ],
      });

      expect(filas().length).toBe(2);
      const a = celdas(ID_A);
      expect(a[0]).toMatch(/^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}/); // Recibida
      expect(a[1]).toMatch(/^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/); // Fecha real
      expect(a[2]).toBe('Venta de contado');
      expect(a[3]).toBe('Sucursal Centro');
      expect(a[4]).toBe('Carla Rojas');
      expect(a[5]).toBe('Bs 120,00');
      expect(a[6]).toBe('Confirmada');
      expect(a[7]).toBe('2');

      const b = celdas(ID_B);
      expect(b[2]).toBe('Reserva');
      expect(b[3]).toBe('Sucursal Norte');
      expect(b[4]).toBe('Diego Mamani');
      expect(b[5]).toBe('—');
      expect(b[6]).toBe('Rechazada');
      expect(texto(el.querySelector('[data-conteo]'))).toBe('2 operaciones');
    });

    it('si no se pueden leer los nombres de sucursal o usuario, muestra "Sucursal n.º 4" y "Usuario n.º 7" sin romperse', () => {
      iniciar({ sinResponder: true });
      lista().flush(pagina([op(ID_A, { sucursal_id: 4 })]));
      cuenta().flush(pagina([]));
      sucursalesReq().flush({ detail: 'x' }, { status: 403, statusText: 'Forbidden' });
      http.expectOne((r) => r.url === `${API}/usuarios`).flush({ detail: 'x' }, { status: 403, statusText: 'Forbidden' });
      fixture.detectChanges();

      expect(celdas(ID_A)[3]).toBe('Sucursal n.º 4');
      expect(celdas(ID_A)[4]).toBe('Usuario n.º 7');
    });

    it('cada estado se ve con TEXTO, ícono y color: confirmada verde, rechazada roja, en conflicto ámbar', () => {
      iniciar({
        items: [op(ID_A), op(ID_B, { estado: 'rechazada', recurso: null }), op(ID_C, { estado: 'en_conflicto', recurso: null })],
      });

      const esperados: [string, string, string, string][] = [
        [ID_A, 'confirmada', 'Confirmada', 'success'],
        [ID_B, 'rechazada', 'Rechazada', 'danger'],
        [ID_C, 'en_conflicto', 'En conflicto', 'warn'],
      ];
      for (const [id, estado, etiqueta, severidad] of esperados) {
        const tag = fila(id).querySelector('p-tag') as HTMLElement;
        expect(tag.getAttribute('data-estado-operacion')).toBe(estado);
        expect(texto(tag)).toBe(etiqueta);
        expect(tag.querySelector('fs-icono')).not.toBeNull();
        expect(tag.className).toContain(`p-tag-${severidad}`);
      }
    });

    it('marca "llegó con N h de retraso" solo cuando recibida - fecha real supera 1 hora', () => {
      iniciar({
        items: [
          op(ID_A, { fecha_operacion: '2026-10-29T10:00:00Z', recibida_en: '2026-10-29T13:10:00Z' }), // 3 h 10 min
          op(ID_B, { fecha_operacion: '2026-10-29T10:00:00Z', recibida_en: '2026-10-29T10:40:00Z' }), // 40 min
          op(ID_C, { fecha_operacion: '2026-10-29T10:00:00Z', recibida_en: '2026-10-29T11:00:00Z' }), // 1 h exacta
        ],
      });

      expect(texto(fila(ID_A).querySelector('[data-retraso]'))).toBe('llegó con 3 h de retraso');
      expect(fila(ID_A).querySelector('[data-retraso] fs-icono')).not.toBeNull();
      expect(fila(ID_B).querySelector('[data-retraso]')).toBeNull();
      expect(fila(ID_C).querySelector('[data-retraso]')).toBeNull();
    });
  });

  describe('estados de la pantalla', () => {
    it('cargando: mientras espera la respuesta lo dice', () => {
      iniciar({ sinResponder: true });
      fixture.detectChanges();

      expect(el.querySelector('[data-estado="cargando"]')).not.toBeNull();
      lista().flush(pagina([]));
      cuenta().flush(pagina([]));
      sucursalesReq().flush([]);
      http.expectOne((r) => r.url === `${API}/usuarios`).flush([]);
      fixture.detectChanges();
      expect(el.querySelector('[data-estado="cargando"]')).toBeNull();
    });

    it('vacío: "Todavía no hay operaciones sincronizadas."', () => {
      iniciar({ items: [] });

      expect(texto(el.querySelector('[data-estado="vacio"]'))).toContain('Todavía no hay operaciones sincronizadas.');
      expect(el.querySelector('[data-estado="error"]')).toBeNull();
      expect(filas().length).toBe(0);
    });

    it('con filtros y sin resultados no dice "todavía no hay": ofrece quitar los filtros', () => {
      iniciar({ items: [op(ID_A)] });
      comp.cambiarEstado('rechazada');
      lista().flush(pagina([]));
      fixture.detectChanges();

      expect(el.querySelector('[data-estado="vacio"]')).toBeNull();
      expect(texto(el.querySelector('[data-estado="sin-resultados"]'))).toContain('No encontramos operaciones con esos filtros.');

      (el.querySelector('[data-estado="sin-resultados"] button') as HTMLButtonElement).click();
      const sinFiltros = lista();
      expect(sinFiltros.request.params.has('estado')).toBe(false);
      sinFiltros.flush(pagina([op(ID_A)]));
      fixture.detectChanges();
      expect(filas().length).toBe(1);
    });

    it('error: muestra el aviso con [Reintentar], que vuelve a pedir y recupera la tabla', () => {
      iniciar({ sinResponder: true });
      lista().flush({ detail: 'falló' }, { status: 500, statusText: 'Server Error' });
      cuenta().flush(pagina([]));
      sucursalesReq().flush([]);
      http.expectOne((r) => r.url === `${API}/usuarios`).flush([]);
      fixture.detectChanges();

      expect(texto(el.querySelector('[data-estado="error"]'))).toContain('No pudimos cargar las operaciones sincronizadas.');
      expect(el.querySelector('[data-estado="vacio"]')).toBeNull();
      expect(el.querySelector('table')).toBeNull();

      (el.querySelector('[data-accion="reintentar"]') as HTMLButtonElement).click();
      lista().flush(pagina([op(ID_A)]));
      fixture.detectChanges();

      expect(el.querySelector('[data-estado="error"]')).toBeNull();
      expect(filas().length).toBe(1);
    });
  });

  describe('paginación del servidor', () => {
    it('con más de 20 operaciones muestra el paginador y pide la página que se elige', () => {
      iniciar({ items: Array.from({ length: 20 }, (_, i) => op(`a000000${i}-0000-4000-8000-000000000000`)), total: 45 });

      expect(texto(el.querySelector('[data-conteo]'))).toBe('45 operaciones');
      const siguiente = el.querySelector('.p-paginator-next') as HTMLButtonElement;
      expect(siguiente).not.toBeNull();
      siguiente.click();

      const pedida = lista();
      expect(pedida.request.params.get('pagina')).toBe('2');
      pedida.flush(pagina([op(ID_B)], 45, 2));
      fixture.detectChanges();
      expect(filas().length).toBe(1);
    });

    it('con 20 o menos no hay paginador', () => {
      iniciar({ items: [op(ID_A)] });
      expect(el.querySelector('.p-paginator')).toBeNull();
    });
  });

  describe('filtros', () => {
    function pedida(): TestRequest {
      return lista();
    }

    it('cada filtro cambia la consulta con el nombre que usa el servidor', () => {
      iniciar({ items: [op(ID_A)] });

      comp.cambiarEstado('en_conflicto');
      let p = pedida();
      expect(p.request.params.get('estado')).toBe('en_conflicto');
      p.flush(pagina([]));

      comp.cambiarTipo('reserva');
      p = pedida();
      expect(p.request.params.get('estado')).toBe('en_conflicto');
      expect(p.request.params.get('tipo')).toBe('reserva');
      p.flush(pagina([]));

      comp.cambiarSucursal(2);
      p = pedida();
      expect(p.request.params.get('sucursal_id')).toBe('2');
      p.flush(pagina([]));

      comp.cambiarUsuario(8);
      p = pedida();
      expect(p.request.params.get('usuario_id')).toBe('8');
      expect(p.request.params.get('tipo')).toBe('reserva');
      p.flush(pagina([]));
    });

    it('quitar un filtro (null) deja de enviarlo', () => {
      iniciar({ items: [] });
      comp.cambiarEstado('rechazada');
      pedida().flush(pagina([]));
      comp.cambiarEstado(null);
      const p = pedida();
      expect(p.request.params.has('estado')).toBe(false);
      p.flush(pagina([]));
    });

    it('el rango de fechas manda desde y hasta (inclusivos, AAAA-MM-DD) solo cuando están los dos días', () => {
      iniciar({ items: [] });

      comp.cambiarRango([new Date(2026, 9, 1), null]); // falta el segundo día: no consulta
      http.expectNone((r) => r.url === OPS);

      comp.cambiarRango([new Date(2026, 9, 1), new Date(2026, 9, 31)]);
      const p = pedida();
      expect(p.request.params.get('desde')).toBe('2026-10-01');
      expect(p.request.params.get('hasta')).toBe('2026-10-31');
      p.flush(pagina([]));

      comp.cambiarRango(null);
      const sin = pedida();
      expect(sin.request.params.has('desde')).toBe(false);
      expect(sin.request.params.has('hasta')).toBe(false);
      sin.flush(pagina([]));
    });

    it('cambiar un filtro vuelve a la página 1', () => {
      iniciar({ items: [op(ID_A)], total: 60 });
      comp.alPaginar({ first: 40, rows: TAMANIO_PAGINA });
      const segunda = pedida();
      expect(segunda.request.params.get('pagina')).toBe('3');
      segunda.flush(pagina([], 60, 3));

      comp.cambiarTipo('venta_contado');
      const p = pedida();
      expect(p.request.params.get('pagina')).toBe('1');
      p.flush(pagina([], 60));
    });

    it('el filtro por usuario solo se ofrece si se pueden listar los usuarios (usuarios.gestionar)', () => {
      iniciar({ items: [op(ID_A)] });
      expect(el.querySelector('p-select[ariaLabel="Usuario"], p-select[arialabel="Usuario"]')).not.toBeNull();
      expect(el.querySelectorAll('.filtros p-select').length).toBe(4);
    });

    it('sin usuarios.gestionar no se piden los usuarios ni aparece el filtro, y la lista sigue funcionando', () => {
      iniciar({ permisos: ['sincronizacion.supervisar'], items: [op(ID_A)] });

      http.expectNone((r) => r.url === `${API}/usuarios`);
      expect(el.querySelectorAll('.filtros p-select').length).toBe(3);
      expect(celdas(ID_A)[4]).toBe('Usuario n.º 7');
    });
  });

  describe('acceso rápido a los conflictos', () => {
    it('con conflictos pendientes muestra "N conflictos por resolver" y al pulsarlo filtra por en_conflicto', () => {
      iniciar({ items: [op(ID_A)], conflictos: 3 });

      const acceso = el.querySelector('[data-accion="ver-conflictos"]') as HTMLButtonElement;
      expect(texto(acceso)).toContain('3 conflictos por resolver');
      acceso.click();

      const p = lista();
      expect(p.request.params.get('estado')).toBe('en_conflicto');
      p.flush(pagina([op(ID_C, { estado: 'en_conflicto', recurso: null })]));
      fixture.detectChanges();

      expect(filas().length).toBe(1);
      // Ya está filtrando por conflictos: el acceso rápido sobra.
      expect(el.querySelector('[data-accion="ver-conflictos"]')).toBeNull();
    });

    it('en singular dice "1 conflicto por resolver"', () => {
      iniciar({ items: [op(ID_A)], conflictos: 1 });
      expect(texto(el.querySelector('[data-accion="ver-conflictos"]'))).toContain('1 conflicto por resolver');
    });

    it('sin conflictos no aparece', () => {
      iniciar({ items: [op(ID_A)], conflictos: 0 });
      expect(el.querySelector('[data-accion="ver-conflictos"]')).toBeNull();
    });
  });

  describe('detalle', () => {
    it('muestra las prendas con su nombre, talla y color, el total, el cliente, el pago, el dispositivo y los intentos', () => {
      iniciar({ items: [op(ID_A)] });
      abrirDetalle(detalle(ID_A, { intentos: 2, cambio: '100.00' }));

      const d = dlg('dlg-detalle')!;
      const lineas = d.querySelector('[data-detalle="lineas"]')!;
      expect(texto(lineas)).toContain('Polera Estampada');
      expect(texto(lineas)).toContain('M · Negro');
      expect(texto(lineas)).toContain('Camisa Lino');
      expect(texto(lineas)).toContain('L · Blanco');
      // Subtotales: 3 x 120 = 360 y 1 x (50 - 10) = 40.
      expect(texto(lineas)).toContain('Bs 360,00');
      expect(texto(lineas)).toContain('Bs 40,00');
      expect(texto(d.querySelector('[data-detalle="total"]'))).toBe('Bs 400,00');
      expect(texto(d.querySelector('[data-detalle="cliente"]'))).toBe('Cliente n.º 5');
      expect(texto(d.querySelector('[data-detalle="pago"]'))).toBe('Efectivo · recibido Bs 500,00 · cambio Bs 100,00');
      expect(texto(d.querySelector('[data-detalle="dispositivo"]'))).toBe('PWA Chrome');
      expect(texto(d.querySelector('[data-detalle="intentos"]'))).toBe('2');
      expect(texto(d.querySelector('[data-detalle="recurso"]'))).toBe('V-0001');
      expect(d.querySelector('[data-detalle="motivo"]')).toBeNull();
      // Una confirmada no ofrece ninguna acción.
      expect(d.querySelector('[data-detalle="acciones"]')).toBeNull();
    });

    it('pide el nombre de las prendas de una sola vez, sin repetir ids', () => {
      iniciar({ items: [op(ID_C)] });
      (fila(ID_C).querySelector('[data-accion="detalle"]') as HTMLButtonElement).click();
      http.expectOne(`${OPS}/${ID_C}`).flush(conflicto(ID_C));

      const pedido = http.expectOne((r) => r.url === VARIANTES);
      expect(pedido.request.params.get('variante_ids')).toBe('11,12');
      pedido.flush([]);
      fixture.detectChanges();

      // Si no se pudieron resolver los nombres, no se rompe: muestra el número de variante.
      expect(texto(dlg('dlg-detalle')!.querySelector('[data-detalle="lineas"]'))).toContain('Variante n.º 11');
    });

    it('en un conflicto de stock muestra por prenda "pedidas 3 / disponibles 1" y la diferencia de precio', () => {
      iniciar({ items: [op(ID_C, { estado: 'en_conflicto', recurso: null })] });
      abrirDetalle(conflicto(ID_C));

      const d = dlg('dlg-detalle')!;
      expect(texto(d.querySelector('[data-detalle="faltantes"]'))).toContain('Polera Estampada (M · Negro)');
      expect(texto(d.querySelector('[data-detalle="faltantes"]'))).toContain('pedidas 3 / disponibles 1');
      expect(texto(d.querySelector('[data-detalle="avisos"]'))).toContain('Camisa Lino (L · Blanco)');
      expect(texto(d.querySelector('[data-detalle="avisos"]'))).toContain(
        'El cliente pagó Bs 120,00; el precio actual es Bs 130,00',
      );
      expect(texto(d.querySelector('[data-detalle="motivo"]'))).toContain('No había stock suficiente');
      expect(d.querySelector('[data-detalle="intentos"]')?.textContent?.trim()).toBe('3');
      expect(d.querySelector('[data-detalle-estado="en_conflicto"]')).not.toBeNull();
    });

    it('una operación rechazada explica el motivo en lenguaje claro, sin el código técnico', () => {
      iniciar({ items: [op(ID_B, { estado: 'rechazada', recurso: null })] });
      abrirDetalle(detalle(ID_B, { estado: 'rechazada', motivo: 'reserva_fuera_de_horario', recurso: null }));

      const motivo = texto(dlg('dlg-detalle')!.querySelector('[data-detalle="motivo"]'));
      expect(motivo).toBe('La visita quedó fuera del horario de la sucursal.');
      expect(motivo).not.toContain('reserva_fuera_de_horario');
    });

    it('una resolución previa muestra quién, cuándo, el motivo y los ajustes de inventario', () => {
      iniciar({ items: [op(ID_A)] });
      abrirDetalle(
        detalle(ID_A, {
          resolucion: {
            accion: 'forzar',
            por_usuario_id: 8,
            en: '2026-10-29T18:00:00Z',
            motivo: 'La prenda ya salió con el cliente',
            ajustes: [{ variante_id: 11, cantidad: 2, movimiento_id: 55 }],
          },
        }),
      );

      const r = dlg('dlg-detalle')!.querySelector('[data-detalle="resolucion"]')!;
      expect(texto(r)).toContain('Forzada');
      expect(texto(r)).toContain('Por Diego Mamani el');
      expect(texto(r.querySelector('[data-detalle="resolucion-motivo"]'))).toBe('Motivo: La prenda ya salió con el cliente');
      expect(texto(r.querySelector('[data-detalle="ajustes"]'))).toContain('Polera Estampada (M · Negro)');
      expect(texto(r.querySelector('[data-detalle="ajustes"]'))).toContain('+2 al inventario (movimiento n.º 55)');
    });

    it('una reserva muestra la visita y no tiene columnas de precio', () => {
      iniciar({ items: [op(ID_D, { tipo: 'reserva', estado: 'en_conflicto', recurso: null })] });
      abrirDetalle(reservaEnConflicto(ID_D));

      const d = dlg('dlg-detalle')!;
      expect(texto(d.querySelector('[data-detalle="visita"]'))).toBe('2026-11-02 · 10:00 - 11:00');
      expect(texto(d.querySelector('[data-detalle="lineas"]'))).not.toContain('Precio');
      expect(d.querySelector('[data-detalle="total"]')).toBeNull();
    });

    it('si el detalle ya no existe (404) cierra el diálogo y vuelve a leer la lista', () => {
      iniciar({ items: [op(ID_A)] });
      (fila(ID_A).querySelector('[data-accion="detalle"]') as HTMLButtonElement).click();
      http.expectOne(`${OPS}/${ID_A}`).flush({ detail: 'Operación no encontrada' }, { status: 404, statusText: 'Not Found' });
      lista().flush(pagina([]));
      fixture.detectChanges();

      expect(comp.detalleVisible()).toBe(false);
      expect(filas().length).toBe(0);
    });
  });

  describe('quién ve las acciones', () => {
    it('sin sincronizacion.resolver no aparece [Forzar] ni [Rechazar], aunque esté en conflicto', () => {
      iniciar({ permisos: ['sincronizacion.supervisar'], items: [op(ID_C, { estado: 'en_conflicto', recurso: null })] });
      abrirDetalle(conflicto(ID_C));

      const d = dlg('dlg-detalle')!;
      expect(d.querySelector('[data-accion="forzar"]')).toBeNull();
      expect(d.querySelector('[data-accion="rechazar"]')).toBeNull();
      expect(d.querySelector('[data-detalle="acciones"]')).toBeNull();
      // Pero sí ve el conflicto completo.
      expect(d.querySelector('[data-detalle="faltantes"]')).not.toBeNull();
    });

    it.each([
      ['confirmada', detalle(ID_A)],
      ['rechazada', detalle(ID_A, { estado: 'rechazada', motivo: 'rechazada_por_encargado', recurso: null })],
    ])('con permiso pero en estado %s tampoco hay acciones', (_estado, d) => {
      iniciar({ items: [op(ID_A)] });
      abrirDetalle(d);

      expect(dlg('dlg-detalle')!.querySelector('[data-accion="forzar"]')).toBeNull();
      expect(dlg('dlg-detalle')!.querySelector('[data-accion="rechazar"]')).toBeNull();
    });

    it('una venta en conflicto con permiso ofrece [Forzar] y [Rechazar]', () => {
      iniciar({ items: [op(ID_C, { estado: 'en_conflicto', recurso: null })] });
      abrirDetalle(conflicto(ID_C));

      const d = dlg('dlg-detalle')!;
      expect(texto(d.querySelector('[data-accion="forzar"]'))).toBe('Forzar');
      expect(texto(d.querySelector('[data-accion="rechazar"]'))).toBe('Rechazar');
    });

    it('una reserva en conflicto solo se puede rechazar: no se ofrece [Forzar]', () => {
      iniciar({ items: [op(ID_D, { tipo: 'reserva', estado: 'en_conflicto', recurso: null })] });
      abrirDetalle(reservaEnConflicto(ID_D));

      const d = dlg('dlg-detalle')!;
      expect(d.querySelector('[data-accion="forzar"]')).toBeNull();
      expect(d.querySelector('[data-accion="rechazar"]')).not.toBeNull();
      expect(texto(d.querySelector('[data-detalle="solo-rechazar"]'))).toContain('solo se puede rechazar');

      // Aunque alguien lo intente por código, el diálogo de forzar no se abre para una reserva.
      comp.abrirAccion('forzar');
      expect(comp.accionPendiente()).toBeNull();
    });

    it('sin permiso, abrir la acción por código tampoco hace nada', () => {
      iniciar({ permisos: ['sincronizacion.supervisar'], items: [op(ID_C, { estado: 'en_conflicto', recurso: null })] });
      abrirDetalle(conflicto(ID_C));

      comp.abrirAccion('rechazar');
      expect(comp.accionPendiente()).toBeNull();
    });
  });

  describe('forzar', () => {
    function abrirForzar(): void {
      iniciar({ items: [op(ID_C, { estado: 'en_conflicto', recurso: null })], conflictos: 1 });
      abrirDetalle(conflicto(ID_C));
      (dlg('dlg-detalle')!.querySelector('[data-accion="forzar"]') as HTMLButtonElement).click();
      fixture.detectChanges();
    }

    const casilla = () => dlg('dlg-forzar')!.querySelector('#sync-entiendo') as HTMLInputElement;

    it('explica qué significa y muestra lo que se sumará al inventario (el faltante exacto)', () => {
      abrirForzar();

      const d = dlg('dlg-forzar')!;
      expect(texto(d.querySelector('[data-forzar="explicacion"]'))).toContain('ya salió de la tienda');
      expect(texto(d.querySelector('[data-forzar="explicacion"]'))).toContain('el stock no quedará en negativo');
      // pedidas 3, disponibles 1 -> se ajustan 2.
      const ajustes = texto(d.querySelector('[data-forzar="ajustes"]'));
      expect(ajustes).toContain('Polera Estampada (M · Negro)');
      expect(ajustes).toContain('+2 al inventario');
      expect(d.querySelectorAll('[data-forzar="ajustes"] li').length).toBe(1);
    });

    it('el botón está deshabilitado sin motivo, con motivo corto (menos de 10) o sin marcar la casilla', () => {
      abrirForzar();
      expect(botonForzar().disabled).toBe(true);

      escribir('dlg-forzar textarea', 'corto');
      casilla().click();
      fixture.detectChanges();
      expect(botonForzar().disabled).toBe(true);
      expect(dlg('dlg-forzar')!.querySelector('[data-forzar="error-motivo"]')).not.toBeNull();

      // 10 caracteres reales, pero sin la casilla: sigue deshabilitado.
      casilla().click();
      escribir('dlg-forzar textarea', 'Ya salió ok');
      fixture.detectChanges();
      expect(casilla().checked).toBe(false);
      expect(botonForzar().disabled).toBe(true);
    });

    it('los espacios de relleno no cuentan para los 10 caracteres', () => {
      abrirForzar();
      casilla().click();
      escribir('dlg-forzar textarea', '   abc       ');

      expect(botonForzar().disabled).toBe(true);
    });

    it('con motivo de 9 caracteres no se habilita y con 10 sí', () => {
      abrirForzar();
      casilla().click();
      escribir('dlg-forzar textarea', '123456789');
      expect(botonForzar().disabled).toBe(true);
      escribir('dlg-forzar textarea', '1234567890');
      expect(botonForzar().disabled).toBe(false);
    });

    it('confirmar envía {accion: forzar, motivo} y deja la fila, el detalle y el aviso al día', () => {
      abrirForzar();
      casilla().click();
      escribir('dlg-forzar textarea', '  La prenda ya salió con el cliente  ');
      botonForzar().click();

      const post = http.expectOne(`${OPS}/${ID_C}/resolver`);
      expect(post.request.method).toBe('POST');
      expect(post.request.body).toEqual({ accion: 'forzar', motivo: 'La prenda ya salió con el cliente' });

      post.flush(
        detalle(ID_C, {
          estado: 'confirmada',
          motivo: null,
          intentos: 3,
          recurso: { tipo: 'venta', id: 9, codigo: 'V-0099', total: '400.00', fecha_expiracion: null },
          faltantes: [],
          resolucion: {
            accion: 'forzar',
            por_usuario_id: 8,
            en: '2026-10-30T10:00:00Z',
            motivo: 'La prenda ya salió con el cliente',
            ajustes: [{ variante_id: 11, cantidad: 2, movimiento_id: 77 }],
          },
        }),
      );
      // Al resolver se vuelve a contar lo que queda por decidir (y los nombres del ajuste).
      cuenta().flush(pagina([], 0));
      const nombres = http.match((r) => r.url === VARIANTES);
      nombres.forEach((n) => n.flush(PRENDAS));
      fixture.detectChanges();

      expect(comp.accionPendiente()).toBeNull();
      expect(celdas(ID_C)[6]).toBe('Confirmada');
      expect(celdas(ID_C)[5]).toBe('Bs 400,00');
      expect(el.querySelector('[data-accion="ver-conflictos"]')).toBeNull();
      const d = dlg('dlg-detalle')!;
      expect(d.querySelector('[data-detalle-estado="confirmada"]')).not.toBeNull();
      expect(d.querySelector('[data-accion="forzar"]')).toBeNull();
      expect(texto(d.querySelector('[data-detalle="ajustes"]'))).toContain('+2 al inventario (movimiento n.º 77)');
      expect(avisos).toHaveBeenCalledWith(
        expect.objectContaining({ severity: 'success', summary: 'Venta confirmada', detail: expect.stringContaining('V-0099') }),
      );
    });

    it('un doble clic no manda dos resoluciones: el botón se deshabilita al primer clic', () => {
      abrirForzar();
      casilla().click();
      escribir('dlg-forzar textarea', 'Motivo suficientemente largo');

      botonForzar().click();
      // Sin respuesta todavía: el segundo clic llega con el envío en curso.
      expect(comp.enviando()).toBe(true);
      comp.confirmarAccion();
      fixture.detectChanges();
      expect(botonForzar().disabled).toBe(true);
      botonForzar().click();

      const posts = http.match(`${OPS}/${ID_C}/resolver`);
      expect(posts.length).toBe(1);
      posts[0].flush(detalle(ID_C, { estado: 'confirmada' }));
      cuenta().flush(pagina([], 0));
      http.match((r) => r.url === VARIANTES).forEach((n) => n.flush([]));
    });

    it('[Volver] cierra sin enviar nada', () => {
      abrirForzar();
      (dlg('dlg-forzar')!.querySelector('[data-accion="cancelar-accion"]') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(comp.accionPendiente()).toBeNull();
      http.expectNone(`${OPS}/${ID_C}/resolver`);
      expect(celdas(ID_C)[6]).toBe('En conflicto');
    });
  });

  describe('rechazar', () => {
    function abrirRechazar(): void {
      iniciar({ items: [op(ID_C, { estado: 'en_conflicto', recurso: null })], conflictos: 1 });
      abrirDetalle(conflicto(ID_C));
      (dlg('dlg-detalle')!.querySelector('[data-accion="rechazar"]') as HTMLButtonElement).click();
      fixture.detectChanges();
    }

    it('explica que no toca el inventario y exige un motivo (los espacios no cuentan)', () => {
      abrirRechazar();

      const d = dlg('dlg-rechazar')!;
      expect(texto(d.querySelector('[data-rechazar="explicacion"]'))).toContain('sin tocar el inventario');
      expect(botonRechazar().disabled).toBe(true);

      escribir('dlg-rechazar textarea', '     ');
      expect(botonRechazar().disabled).toBe(true);

      escribir('dlg-rechazar textarea', 'Sin stock');
      expect(botonRechazar().disabled).toBe(false);
    });

    it('no pide la casilla del ajuste de inventario (eso es solo de forzar)', () => {
      abrirRechazar();
      expect(dlg('dlg-rechazar')!.querySelector('input[type="checkbox"]')).toBeNull();
    });

    it('confirmar envía {accion: rechazar, motivo} y deja la fila como rechazada', () => {
      abrirRechazar();
      escribir('dlg-rechazar textarea', 'Se devolvió el efectivo al cliente');
      botonRechazar().click();

      const post = http.expectOne(`${OPS}/${ID_C}/resolver`);
      expect(post.request.body).toEqual({ accion: 'rechazar', motivo: 'Se devolvió el efectivo al cliente' });
      post.flush(
        detalle(ID_C, {
          estado: 'rechazada',
          motivo: 'rechazada_por_encargado',
          mensaje: 'Se devolvió el efectivo al cliente',
          recurso: null,
          resolucion: { accion: 'rechazar', por_usuario_id: 8, en: '2026-10-30T10:00:00Z', motivo: 'Se devolvió el efectivo al cliente', ajustes: [] },
        }),
      );
      cuenta().flush(pagina([], 0));
      http.match((r) => r.url === VARIANTES).forEach((n) => n.flush(PRENDAS));
      fixture.detectChanges();

      expect(celdas(ID_C)[6]).toBe('Rechazada');
      expect(comp.accionPendiente()).toBeNull();
      expect(texto(dlg('dlg-detalle')!.querySelector('[data-detalle="resolucion"]'))).toContain('Rechazada');
      expect(avisos).toHaveBeenCalledWith(expect.objectContaining({ severity: 'success', summary: 'Operación rechazada' }));
    });

    it('un doble clic no manda dos rechazos', () => {
      abrirRechazar();
      escribir('dlg-rechazar textarea', 'Motivo');
      botonRechazar().click();
      comp.confirmarAccion();
      botonRechazar().click();

      const posts = http.match(`${OPS}/${ID_C}/resolver`);
      expect(posts.length).toBe(1);
      posts[0].flush(detalle(ID_C, { estado: 'rechazada' }));
      cuenta().flush(pagina([], 0));
      http.match((r) => r.url === VARIANTES).forEach((n) => n.flush([]));
    });
  });

  describe('cuando el servidor no deja resolver', () => {
    function intentarRechazar(): TestRequest {
      iniciar({ items: [op(ID_C, { estado: 'en_conflicto', recurso: null })], conflictos: 1 });
      abrirDetalle(conflicto(ID_C));
      (dlg('dlg-detalle')!.querySelector('[data-accion="rechazar"]') as HTMLButtonElement).click();
      fixture.detectChanges();
      escribir('dlg-rechazar textarea', 'No hay cómo cubrirla');
      botonRechazar().click();
      return http.expectOne(`${OPS}/${ID_C}/resolver`);
    }

    it('409: explica con el mensaje del servidor, refresca la fila y muestra cómo quedó', () => {
      const post = intentarRechazar();
      const mensaje = 'La operación ya fue confirmada por un encargado y no se puede resolver de otra forma';
      post.flush({ detail: mensaje }, { status: 409, statusText: 'Conflict' });

      expect(avisos).toHaveBeenCalledWith(
        expect.objectContaining({ severity: 'warn', summary: 'No se pudo resolver', detail: mensaje }),
      );
      expect(comp.accionPendiente()).toBeNull();

      // Vuelve a leer la operación y lo que queda por decidir.
      http
        .expectOne(`${OPS}/${ID_C}`)
        .flush(
          detalle(ID_C, {
            estado: 'confirmada',
            motivo: null,
            recurso: { tipo: 'venta', id: 3, codigo: 'V-0003', total: '400.00', fecha_expiracion: null },
            resolucion: { accion: 'forzar', por_usuario_id: 8, en: '2026-10-30T09:00:00Z', motivo: 'Ya salió', ajustes: [] },
          }),
        );
      cuenta().flush(pagina([], 0));
      http.match((r) => r.url === VARIANTES).forEach((n) => n.flush(PRENDAS));
      fixture.detectChanges();

      expect(celdas(ID_C)[6]).toBe('Confirmada');
      expect(dlg('dlg-detalle')!.querySelector('[data-detalle-estado="confirmada"]')).not.toBeNull();
      expect(dlg('dlg-detalle')!.querySelector('[data-accion="rechazar"]')).toBeNull();
      expect(texto(dlg('dlg-detalle')!.querySelector('[data-detalle="resolucion"]'))).toContain('Forzada');
    });

    it('404: avisa que ya no está disponible, cierra el detalle y actualiza la lista', () => {
      const post = intentarRechazar();
      post.flush({ detail: 'Operación no encontrada' }, { status: 404, statusText: 'Not Found' });

      expect(avisos).toHaveBeenCalledWith(
        expect.objectContaining({ severity: 'warn', summary: 'Operación no disponible', detail: expect.stringContaining('ya no está disponible') }),
      );
      lista().flush(pagina([]));
      cuenta().flush(pagina([], 0));
      fixture.detectChanges();

      expect(comp.detalleVisible()).toBe(false);
      expect(comp.accionPendiente()).toBeNull();
      expect(filas().length).toBe(0);
    });

    it('un error del servidor (500) deja el diálogo abierto para reintentar y libera el botón', () => {
      const post = intentarRechazar();
      post.flush({ detail: 'Error interno' }, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(avisos).toHaveBeenCalledWith(expect.objectContaining({ severity: 'error', summary: 'No se pudo resolver', detail: 'Error interno' }));
      expect(comp.accionPendiente()).toBe('rechazar');
      expect(comp.enviando()).toBe(false);
      expect(botonRechazar().disabled).toBe(false);
      expect(celdas(ID_C)[6]).toBe('En conflicto');

      // Reintenta y esta vez sí funciona.
      botonRechazar().click();
      http.expectOne(`${OPS}/${ID_C}/resolver`).flush(detalle(ID_C, { estado: 'rechazada' }));
      cuenta().flush(pagina([], 0));
      http.match((r) => r.url === VARIANTES).forEach((n) => n.flush([]));
    });
  });

  describe('solo lectura y resolución: nada se borra', () => {
    it('no hay botones ni íconos de borrar en la tabla ni en el detalle, y nunca se envía un DELETE', () => {
      iniciar({ items: [op(ID_C, { estado: 'en_conflicto', recurso: null })], conflictos: 1 });
      abrirDetalle(conflicto(ID_C));
      (dlg('dlg-detalle')!.querySelector('[data-accion="forzar"]') as HTMLButtonElement).click();
      fixture.detectChanges();

      const todo = [el, document.body];
      for (const raiz of todo) {
        expect(raiz.querySelector('fs-icono[nombre="basura"]')).toBeNull();
        const botones = Array.from(raiz.querySelectorAll('button, a'));
        const sospechosos = botones.filter((b) =>
          /borrar|eliminar|quitar operaci|descartar|delete/i.test(`${b.textContent} ${b.getAttribute('aria-label') ?? ''}`),
        );
        expect(sospechosos.map((b) => b.textContent?.trim())).toEqual([]);
      }
      // "Quitar los filtros" sí existe cuando hay filtros, pero no borra operaciones: ahí no hay filtros.
      expect(http.match((r) => r.method === 'DELETE').length).toBe(0);
      expect(typeof comp.borrar).toBe('undefined');
      expect(typeof comp.eliminar).toBe('undefined');
    });
  });
});
