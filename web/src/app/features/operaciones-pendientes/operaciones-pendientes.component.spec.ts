import 'fake-indexeddb/auto';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConectividadService, EstadoConexion } from '../../core/conectividad.service';
import type { EstadoCola } from '../../core/offline/cola-sincronizacion.service';
import { ColaSincronizacionService } from '../../core/offline/cola-sincronizacion.service';
import { BaseOffline } from '../../core/offline/db-offline';
import type { EstadoOperacion, OperacionOffline, PaqueteLocal, TipoOperacion } from '../../core/offline/offline.models';
import { RepositorioLocal } from '../../core/offline/repositorio-local';
import { SesionOfflineService } from '../../core/offline/sesion-offline.service';
import { OperacionesPendientesComponent } from './operaciones-pendientes.component';
import { TEXTO_MOTIVO, VISTA_ESTADO, formatoBs, htmlComprobante, motivoClaro, textoEstadoCola, textoIntento } from './textos-operacion';

let contador = 0;

function paquete(): PaqueteLocal {
  return {
    empresa: { id: 1, codigo: 'alfa', nombre: 'Alfa' },
    generadoEn: '2026-10-30T10:00:00Z',
    avisoDesactualizadoHoras: 12,
    sucursales: [
      { id: 10, codigo: 'SC-CENTRO', nombre: 'Centro', direccion: 'Calle 1', es_deposito: false, horarios: [] },
      { id: 12, codigo: 'SC-SUR', nombre: 'Sur', direccion: 'Calle 3', es_deposito: false, horarios: [] },
    ],
    categorias: [],
    tallas: [],
    colores: [],
    productos: [],
    stock: [],
    clientes: [],
    reglas: { metodos_pago_offline: ['efectivo'], max_operaciones_por_lote: 50, plazo_cambio_horas: 24, cambios_y_devoluciones: 'solo_en_linea', reservas_offline: 'permitidas' },
  };
}

function operacion(id: string, extra: Partial<OperacionOffline> = {}, tipo: TipoOperacion = 'venta_contado'): OperacionOffline {
  const esVenta = tipo === 'venta_contado';
  return {
    empresa_id: 1,
    usuario_id: 7,
    operacion_id: `${id}00000-0000-4000-8000-000000000000`,
    sucursal_id: 10,
    tipo,
    estado: 'registrada',
    fecha_operacion: '2026-10-28T10:00:00-04:00',
    creada_en: '2026-10-28T10:00:00-04:00',
    cliente_id: 1,
    cliente_nombre: 'María Pérez',
    lineas: [
      { variante_id: 1000, producto_nombre: 'Polera Estampada', sku: 'POL-M', talla: 'M', color: 'Negro', cantidad: 2, precio_unitario: '149.00', descuento_unitario: '14.90', subtotal: '268.20' },
    ],
    total: '268.20',
    pago: esVenta ? { metodo: 'efectivo', monto_recibido: '300.00', cambio: '31.80' } : null,
    reserva: esVenta ? null : { fecha_visita: '2026-11-02', hora_visita_desde: '10:00', hora_visita_hasta: '11:30', observacion: 'Viene con su hijo' },
    codigo_local: `OFF-${id.toUpperCase().slice(0, 6)}`,
    dispositivo: 'dispositivo-prueba',
    intentos: 0,
    ultimo_intento_en: null,
    proximo_intento_en: null,
    ultimo_error: null,
    bloqueada: false,
    motivo: null,
    mensaje: null,
    resultado: null,
    ...extra,
  };
}

describe('OperacionesPendientesComponent', () => {
  let db: BaseOffline;
  let repo: RepositorioLocal;
  let fixture: ComponentFixture<OperacionesPendientesComponent>;
  let el: HTMLElement;
  let comp: any;
  let fallaLaLectura: boolean;
  const conexion = signal<EstadoConexion>('en_linea');
  const cola = {
    estadoCola: signal<EstadoCola>('inactiva'),
    pendientes: signal(0),
    enConflicto: signal(0),
    rechazadas: signal(0),
    confirmadas: signal(0),
    proximoIntentoEn: signal<string | null>(null),
    motivoPausa: signal<string | null>(null),
    refrescarConteos: vi.fn(async () => undefined),
    notificarNuevaOperacion: vi.fn(),
    enviarAhora: vi.fn(async () => undefined),
  };

  /** Cinco operaciones mías (una de cada estado) y una de otro usuario. */
  async function sembrar(): Promise<void> {
    await repo.registrarOperacion(operacion('aaaaaa', { estado: 'registrada', fecha_operacion: '2026-10-28T10:00:00-04:00' }));
    await repo.registrarOperacion(
      operacion('bbbbbb', {
        estado: 'confirmada',
        fecha_operacion: '2026-10-29T09:00:00-04:00',
        cliente_nombre: 'Juan Rojas',
        total: '1234.50',
        intentos: 1,
        resultado: { estado: 'confirmada', recurso: { tipo: 'venta', id: 9, codigo: 'V-0012' } },
      }),
    );
    await repo.registrarOperacion(
      operacion(
        'cccccc',
        { estado: 'rechazada', fecha_operacion: '2026-10-30T08:00:00-04:00', sucursal_id: 12, intentos: 1, motivo: 'variante_inactiva', mensaje: 'texto técnico del servidor' },
        'reserva',
      ),
    );
    await repo.registrarOperacion(
      operacion('dddddd', {
        estado: 'en_conflicto',
        fecha_operacion: '2026-10-27T15:00:00-04:00',
        cliente_nombre: 'Álvaro Núñez',
        intentos: 2,
        motivo: 'stock_insuficiente',
        resultado: { estado: 'en_conflicto', motivo: 'stock_insuficiente', faltantes: [{ variante_id: 1000, solicitado: 2, disponible: 0 }] },
      }),
    );
    await repo.registrarOperacion(operacion('eeeeee', { estado: 'enviada', fecha_operacion: '2026-10-26T12:00:00-04:00', intentos: 1 }, 'reserva'));
    await new RepositorioLocal(db, { empresaId: 1, usuarioId: 8 }).registrarOperacion(
      operacion('ffffff', { usuario_id: 8, cliente_nombre: 'De Otro Usuario', fecha_operacion: '2026-10-30T12:00:00-04:00' }),
    );
  }

  async function crear(conOperaciones = true): Promise<void> {
    db = new BaseOffline(`prueba_pendientes_${++contador}_${Date.now()}`);
    repo = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
    fallaLaLectura = false;
    await repo.reemplazarReferencia(paquete());
    if (conOperaciones) await sembrar();
    conexion.set('en_linea');
    cola.estadoCola.set('inactiva');
    cola.pendientes.set(2);
    cola.enConflicto.set(1);
    cola.rechazadas.set(1);
    cola.confirmadas.set(1);
    cola.proximoIntentoEn.set(null);
    cola.motivoPausa.set(null);
    cola.enviarAhora.mockClear();
    TestBed.configureTestingModule({
      imports: [OperacionesPendientesComponent],
      providers: [
        { provide: ColaSincronizacionService, useValue: cola },
        { provide: ConectividadService, useValue: { estado: conexion } },
        {
          provide: SesionOfflineService,
          useValue: {
            alcance: () => ({ empresaId: 1, usuarioId: 7 }),
            repositorio: () => {
              if (fallaLaLectura) throw new Error('La base no se pudo abrir');
              return repo;
            },
          },
        },
      ],
    });
    fixture = TestBed.createComponent(OperacionesPendientesComponent);
    fixture.detectChanges();
    el = fixture.nativeElement as HTMLElement;
    comp = fixture.componentInstance;
  }

  async function esperar(condicion: () => void): Promise<void> {
    await vi.waitFor(() => {
      fixture.detectChanges();
      condicion();
    });
  }

  async function abrir(conOperaciones = true): Promise<void> {
    await crear(conOperaciones);
    await esperar(() => expect(comp.cargando()).toBe(false));
  }

  const filas = () => Array.from(el.querySelectorAll('tbody tr[data-operacion]'));
  const codigos = () => filas().map((f) => f.getAttribute('data-operacion'));
  const fila = (codigo: string) => el.querySelector(`tbody tr[data-operacion="${codigo}"]`) as HTMLElement;
  const resumen = (clave: string) => el.querySelector(`[data-resumen="${clave}"]`)?.textContent?.replace(/\s+/g, ' ').trim();
  const botonEnviar = () => el.querySelector('[data-accion="enviar-ahora"]') as HTMLButtonElement;
  const dialogo = () => document.body.querySelector('.p-dialog') as HTMLElement | null;

  afterEach(() => db.close());

  describe('resumen y estado de la cola', () => {
    it('cuenta pendientes, en conflicto, rechazadas y sincronizadas con los números de la cola', async () => {
      await abrir();
      cola.pendientes.set(3);
      cola.enConflicto.set(1);
      cola.rechazadas.set(1);
      cola.confirmadas.set(12);
      fixture.detectChanges();

      expect(resumen('pendientes')).toBe('3 pendientes');
      expect(resumen('en_conflicto')).toBe('1 en conflicto');
      expect(resumen('rechazadas')).toBe('1 rechazada');
      expect(resumen('confirmadas')).toBe('12 sincronizadas');
    });

    it('usa el singular y el plural correctos', async () => {
      await abrir();
      cola.pendientes.set(1);
      cola.rechazadas.set(2);
      cola.confirmadas.set(1);
      fixture.detectChanges();

      expect(resumen('pendientes')).toBe('1 pendiente');
      expect(resumen('rechazadas')).toBe('2 rechazadas');
      expect(resumen('confirmadas')).toBe('1 sincronizada');
    });

    it('dice en palabras en qué está la cola y por qué si hay un motivo de pausa', async () => {
      await abrir();
      const texto = () => el.querySelector('[data-estado-cola]')?.textContent?.replace(/\s+/g, ' ').trim();
      const casos: [EstadoCola, string][] = [
        ['sincronizando', 'Sincronizando…'],
        ['pausada_sesion', 'Pausada: inicia sesión'],
        ['detenida_por_fallos', 'Detenida: reintenta manualmente'],
        ['sin_conexion', 'Sin conexión'],
      ];
      for (const [estado, esperado] of casos) {
        cola.estadoCola.set(estado);
        fixture.detectChanges();
        expect(texto()).toContain(esperado);
      }

      cola.estadoCola.set('pausada_plan');
      cola.motivoPausa.set('La suscripción de la empresa no está activa.');
      fixture.detectChanges();
      expect(texto()).toContain('Pausada');
      expect(texto()).toContain('La suscripción de la empresa no está activa.');
    });

    it('muestra la cuenta atrás del reintento', async () => {
      await abrir();
      cola.estadoCola.set('esperando_reintento');
      cola.proximoIntentoEn.set(new Date(Date.now() + 40_000).toISOString());
      fixture.detectChanges();

      expect(el.querySelector('[data-estado-cola]')?.textContent).toMatch(/Reintento en (39|40|41) s/);
    });
  });

  describe('[Enviar ahora]', () => {
    it('llama a la cola, y vuelve a leer la lista', async () => {
      await abrir();
      expect(botonEnviar().disabled).toBe(false);

      botonEnviar().click();
      await esperar(() => expect(cola.enviarAhora).toHaveBeenCalledTimes(1));
    });

    it('sin red queda deshabilitado, lo explica y NO llama a la cola', async () => {
      await abrir();
      conexion.set('sin_conexion');
      fixture.detectChanges();

      expect(botonEnviar().disabled).toBe(true);
      expect(botonEnviar().getAttribute('title')).toContain('Conéctate a Internet');
      botonEnviar().click();
      expect(cola.enviarAhora).not.toHaveBeenCalled();
    });

    it('sin nada pendiente queda deshabilitado', async () => {
      await abrir();
      cola.pendientes.set(0);
      fixture.detectChanges();

      expect(botonEnviar().disabled).toBe(true);
      expect(botonEnviar().getAttribute('title')).toContain('No hay nada pendiente');
    });

    it('mientras la cola sincroniza dice "Enviando…" y no se puede pulsar otra vez', async () => {
      await abrir();
      cola.estadoCola.set('sincronizando');
      fixture.detectChanges();

      expect(botonEnviar().disabled).toBe(true);
      expect(botonEnviar().textContent).toContain('Enviando…');
    });
  });

  describe('la tabla', () => {
    it('lista SOLO mis operaciones, de la más nueva a la más vieja', async () => {
      await abrir();

      expect(codigos()).toEqual(['OFF-CCCCCC', 'OFF-BBBBBB', 'OFF-AAAAAA', 'OFF-DDDDDD', 'OFF-EEEEEE']);
      expect(el.textContent).not.toContain('De Otro Usuario');
      expect(el.querySelector('[data-conteo]')?.textContent).toContain('5 operaciones');
    });

    it('cada fila trae fecha dd/mm/aaaa HH:mm, tipo, cliente, total en Bs, intentos y el último resultado', async () => {
      await abrir();
      const celdas = Array.from(fila('OFF-BBBBBB').querySelectorAll('td')).map((c) => c.textContent?.replace(/\s+/g, ' ').trim());

      expect(celdas[0]).toMatch(/^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/);
      expect(celdas[1]).toBe('Venta');
      expect(celdas[2]).toBe('OFF-BBBBBB');
      expect(celdas[3]).toBe('Juan Rojas');
      expect(celdas[4]).toBe('Bs 1.234,50');
      expect(celdas[6]).toBe('1');
      expect(celdas[7]).toBe('Venta V-0012 en el servidor.');
      expect(fila('OFF-BBBBBB').querySelector('td.num.fs-num')).not.toBeNull();
      expect(fila('OFF-CCCCCC').querySelectorAll('td')[1].textContent).toContain('Reserva');
    });

    it('cada estado lleva texto, color (severidad) e ícono, no solo color', async () => {
      await abrir();
      const esperado: Record<string, [EstadoOperacion, string]> = {
        'OFF-AAAAAA': ['registrada', 'Pendiente de enviar'],
        'OFF-EEEEEE': ['enviada', 'Enviando…'],
        'OFF-BBBBBB': ['confirmada', 'Sincronizada'],
        'OFF-CCCCCC': ['rechazada', 'Rechazada'],
        'OFF-DDDDDD': ['en_conflicto', 'En conflicto: espera la revisión del encargado'],
      };
      const severidades = new Set<string>();
      for (const [codigo, [estado, texto]] of Object.entries(esperado)) {
        const etiqueta = fila(codigo).querySelector('p-tag') as HTMLElement;
        expect(etiqueta.textContent?.trim()).toBe(texto);
        expect(etiqueta.getAttribute('data-estado-operacion')).toBe(estado);
        expect(etiqueta.querySelector('fs-icono svg, fs-icono')).not.toBeNull();
        expect(`${etiqueta.className} ${etiqueta.firstElementChild?.className}`).toContain(`${VISTA_ESTADO[estado].severidad}`);
        severidades.add(VISTA_ESTADO[estado].severidad);
      }
      expect(severidades.size).toBe(5);
    });

    it('las rechazadas y en conflicto explican el motivo en lenguaje claro, sin códigos técnicos', async () => {
      await abrir();

      expect(fila('OFF-CCCCCC').textContent).toContain('Una de las prendas ya no está disponible: se dio de baja.');
      expect(fila('OFF-CCCCCC').textContent).not.toContain('variante_inactiva');
      expect(fila('OFF-CCCCCC').textContent).not.toContain('texto técnico del servidor');
      expect(fila('OFF-DDDDDD').textContent).toContain('No había stock suficiente');
      expect(fila('OFF-DDDDDD').textContent).not.toContain('stock_insuficiente');
    });

    it('NO ofrece ninguna acción de borrar, descartar ni quitar una operación', async () => {
      await abrir();
      const botones = Array.from(el.querySelectorAll('button, a'));
      const textos = botones.map((b) => `${b.textContent} ${b.getAttribute('aria-label') ?? ''} ${b.getAttribute('title') ?? ''}`.toLowerCase());

      expect(textos.some((t) => /borrar|eliminar|descartar|quitar|anular|cancelar operaci/.test(t))).toBe(false);
      expect(el.querySelector('fs-icono[nombre="basura"]')).toBeNull();
      // Lo único que hay en cada fila es mirar el detalle.
      expect(fila('OFF-AAAAAA').querySelectorAll('button').length).toBe(1);
      expect(fila('OFF-AAAAAA').querySelector('button')?.getAttribute('aria-label')).toBe('Ver detalle de OFF-AAAAAA');
    });
  });

  describe('filtros', () => {
    it('por estado', async () => {
      await abrir();
      comp.filtroEstado.set('rechazada');
      await esperar(() => expect(codigos()).toEqual(['OFF-CCCCCC']));
    });

    it('por tipo (venta o reserva)', async () => {
      await abrir();
      comp.filtroTipo.set('reserva');
      await esperar(() => expect(codigos()).toEqual(['OFF-CCCCCC', 'OFF-EEEEEE']));
      comp.filtroTipo.set('venta_contado');
      await esperar(() => expect(codigos()).toEqual(['OFF-BBBBBB', 'OFF-AAAAAA', 'OFF-DDDDDD']));
    });

    it('por sucursal', async () => {
      await abrir();
      comp.filtroSucursal.set(12);
      await esperar(() => expect(codigos()).toEqual(['OFF-CCCCCC']));
    });

    it('por rango de fechas, inclusivo en los dos extremos', async () => {
      await abrir();
      comp.filtroRango.set([new Date(2026, 9, 28), new Date(2026, 9, 29)]);
      await esperar(() => expect(codigos()).toEqual(['OFF-BBBBBB', 'OFF-AAAAAA']));

      // Con un solo extremo elegido se mira ese día.
      comp.filtroRango.set([new Date(2026, 9, 30), null]);
      await esperar(() => expect(codigos()).toEqual(['OFF-CCCCCC']));
    });

    it('por el código local o el cliente, sin importar mayúsculas ni tildes', async () => {
      await abrir();
      const buscar = async (texto: string) => {
        const campo = el.querySelector('.buscador input') as HTMLInputElement;
        campo.value = texto;
        campo.dispatchEvent(new Event('input', { bubbles: true }));
      };

      await buscar('alvaro nunez');
      await esperar(() => expect(codigos()).toEqual(['OFF-DDDDDD']));
      await buscar('off-bbb');
      await esperar(() => expect(codigos()).toEqual(['OFF-BBBBBB']));
    });

    it('varios filtros a la vez se combinan', async () => {
      await abrir();
      comp.filtroTipo.set('venta_contado');
      comp.filtroEstado.set('en_conflicto');
      await esperar(() => expect(codigos()).toEqual(['OFF-DDDDDD']));
      comp.filtroSucursal.set(12);
      await esperar(() => expect(codigos()).toEqual([]));
    });

    it('sin resultados lo dice y [Quitar los filtros] los restablece', async () => {
      await abrir();
      comp.filtroTexto.set('zzzz');
      await esperar(() => expect(el.querySelector('[data-estado="sin-resultados"]')).not.toBeNull());
      expect(el.querySelector('[data-estado="vacio"]')).toBeNull();

      (el.querySelector('[data-estado="sin-resultados"] button') as HTMLButtonElement).click();
      await esperar(() => expect(filas().length).toBe(5));
      expect(comp.hayFiltros()).toBe(false);
    });
  });

  describe('estados de la pantalla', () => {
    it('al abrir muestra "cargando" hasta leer la base', async () => {
      await crear();
      expect(el.querySelector('[data-estado="cargando"]')).not.toBeNull();
      await esperar(() => expect(el.querySelector('[data-estado="cargando"]')).toBeNull());
    });

    it('sin ninguna operación explica que todavía no hay nada', async () => {
      await abrir(false);

      expect(el.querySelector('[data-estado="vacio"]')?.textContent).toContain('Todavía no registraste ventas ni reservas');
      expect(el.querySelector('tbody')).toBeNull();
    });

    it('si no se puede leer la base lo dice y [Reintentar] vuelve a leer', async () => {
      await crear();
      fallaLaLectura = true;
      await esperar(() => expect(comp.cargando()).toBe(false));
      comp.filtroTexto.set('x');
      await esperar(() => expect(el.querySelector('[data-estado="error-lectura"]')).not.toBeNull());
      expect(el.querySelector('[data-estado="error-lectura"]')?.textContent).toContain('No pudimos leer las operaciones');

      fallaLaLectura = false;
      comp.filtroTexto.set('');
      (el.querySelector('[data-estado="error-lectura"] button') as HTMLButtonElement).click();
      await esperar(() => expect(filas().length).toBe(5));
    });

    it('se refresca solo cuando la cola cambia los conteos (aparece una operación nueva)', async () => {
      await abrir();
      expect(filas().length).toBe(5);

      await repo.registrarOperacion(operacion('999999', { fecha_operacion: '2026-10-30T11:00:00-04:00', cliente_nombre: 'Recién Llegada' }));
      cola.pendientes.update((n) => n + 1);
      await esperar(() => expect(filas().length).toBe(6));
      expect(codigos()[0]).toBe('OFF-999999');
    });
  });

  describe('detalle', () => {
    async function abrirDetalle(codigo: string): Promise<void> {
      (fila(codigo).querySelector('button') as HTMLButtonElement).click();
      await esperar(() => expect(dialogo()).not.toBeNull());
    }

    it('de una venta: líneas, total, cliente, fecha real, comprobante y el historial de intentos', async () => {
      await abrir();
      const operacionId = (await repo.misOperaciones({ texto: 'OFF-DDDDDD' }))[0].operacion_id;
      await repo.registrarIntento({ operacion_id: operacionId, fecha: '2026-10-27T15:01:00-04:00', http_status: null, motivo: null, respuesta: null });
      await repo.registrarIntento({ operacion_id: operacionId, fecha: '2026-10-27T15:05:00-04:00', http_status: 200, motivo: 'stock_insuficiente', respuesta: {} });
      await abrirDetalle('OFF-DDDDDD');
      await esperar(() => expect(dialogo()!.querySelectorAll('[data-detalle="intentos"] li').length).toBe(2));

      const texto = dialogo()!.textContent!.replace(/\s+/g, ' ');
      expect(texto).toContain('Venta OFF-DDDDDD');
      expect(texto).toContain('En conflicto: espera la revisión del encargado');
      expect(texto).toContain('Álvaro Núñez');
      expect(texto).toContain('Centro');
      expect(texto).toContain('Polera Estampada');
      expect(dialogo()!.querySelector('[data-detalle="total"]')?.textContent).toBe('Bs 268,20');
      expect(dialogo()!.querySelector('[data-detalle="motivo"]')?.textContent).toContain('Un encargado la revisará');
      expect(dialogo()!.querySelector('[data-detalle="faltantes"]')?.textContent).toContain('Pedías 2, había 0');
      expect(dialogo()!.querySelector('[data-detalle="faltantes"]')?.textContent).toContain('Polera Estampada (M · Negro)');
      expect(dialogo()!.querySelector('[data-detalle="comprobante"]')).not.toBeNull();
      expect(dialogo()!.textContent).toContain('Efectivo recibido Bs 300,00 · Cambio Bs 31,80');

      const intentos = Array.from(dialogo()!.querySelectorAll('[data-detalle="intentos"] li')).map((li) => li.textContent?.replace(/\s+/g, ' ').trim());
      expect(intentos[0]).toContain('Sin respuesta: no había conexión');
      expect(intentos[1]).toContain('No había stock suficiente');
      expect(intentos[0]).toMatch(/^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}/);
    });

    it('de una reserva: la visita y la observación, sin comprobante, y avisa si aún no hay intentos', async () => {
      await abrir();
      await abrirDetalle('OFF-EEEEEE');
      await esperar(() => expect(dialogo()!.querySelector('[data-detalle="sin-intentos"]')).not.toBeNull());

      const texto = dialogo()!.textContent!.replace(/\s+/g, ' ');
      expect(texto).toContain('Reserva OFF-EEEEEE');
      expect(texto).toContain('2026-11-02 · 10:00 - 11:30');
      expect(texto).toContain('Viene con su hijo');
      expect(texto).toContain('Valor referencial');
      expect(dialogo()!.querySelector('[data-detalle="comprobante"]')).toBeNull();
    });

    it('de una rechazada: el motivo en rojo y claro, y ningún botón de borrar', async () => {
      await abrir();
      await abrirDetalle('OFF-CCCCCC');

      const motivo = dialogo()!.querySelector('[data-detalle="motivo"]') as HTMLElement;
      expect(motivo.textContent).toContain('Una de las prendas ya no está disponible');
      expect(motivo.classList).toContain('fs-aviso--error');
      const botones = Array.from(dialogo()!.querySelectorAll('button')).map((b) => `${b.textContent} ${b.getAttribute('aria-label')}`.toLowerCase());
      expect(botones.some((t) => /borrar|eliminar|descartar|quitar/.test(t))).toBe(false);
    });

    it('imprimir el comprobante abre una ventana con el texto escapado', async () => {
      await abrir();
      const escrito: string[] = [];
      const ventana = { document: { write: (h: string) => escrito.push(h), close: vi.fn() }, focus: vi.fn(), print: vi.fn() };
      const abrirVentana = vi.spyOn(window, 'open').mockReturnValue(ventana as unknown as Window);
      await abrirDetalle('OFF-AAAAAA');

      const imprimir = Array.from(dialogo()!.querySelectorAll('button')).find((b) => b.textContent?.includes('Imprimir comprobante')) as HTMLButtonElement;
      imprimir.click();

      expect(abrirVentana).toHaveBeenCalledTimes(1);
      expect(ventana.print).toHaveBeenCalledTimes(1);
      expect(escrito.join('')).toContain('Venta registrada sin conexión: pendiente de enviar.');
      expect(escrito.join('')).toContain('OFF-AAAAAA');
      abrirVentana.mockRestore();
    });
  });
});

describe('textos de las operaciones', () => {
  const base = operacion('abcdef');

  it('cubre todos los motivos que el servidor puede devolver (backend/app/sincronizacion/politicas.py)', () => {
    const motivosDelServidor = [
      'suscripcion_no_activa', 'plan_sin_operacion_offline', 'sucursal_no_autorizada', 'sucursal_inexistente', 'usuario_no_es_empleado',
      'permiso_denegado', 'variante_inexistente', 'variante_inactiva', 'cliente_inexistente', 'payload_invalido', 'tipo_no_soportado',
      'total_inconsistente', 'total_invalido', 'metodo_pago_no_permitido', 'monto_insuficiente', 'fecha_futura', 'reserva_fuera_de_horario',
      'reserva_vencida', 'regla_de_negocio', 'stock_insuficiente', 'rechazada_por_encargado', 'operador_inactivo',
    ];
    for (const motivo of motivosDelServidor) {
      expect(TEXTO_MOTIVO[motivo], motivo).toBeTruthy();
      expect(TEXTO_MOTIVO[motivo]).not.toContain('_');
    }
  });

  it('un motivo desconocido usa el mensaje del servidor y, sin mensaje, un texto genérico', () => {
    expect(motivoClaro({ ...base, estado: 'rechazada', motivo: 'algo_nuevo', mensaje: 'Mensaje en español del servidor' })).toBe('Mensaje en español del servidor');
    expect(motivoClaro({ ...base, estado: 'rechazada', motivo: 'algo_nuevo', mensaje: null })).toBe('El servidor no aceptó la operación.');
  });

  it('una pendiente sin problemas no tiene motivo; una bloqueada o sin respuesta sí', () => {
    expect(motivoClaro(base)).toBeNull();
    expect(motivoClaro({ ...base, bloqueada: true })).toContain('error de formato');
    expect(motivoClaro({ ...base, ultimo_error: 'sin_respuesta' })).toContain('no respondió');
  });

  it('los textos de la cola y de los intentos no muestran códigos', () => {
    expect(textoEstadoCola('inactiva', 0, null)).toBe('Todo al día');
    expect(textoEstadoCola('inactiva', 2, null)).toBe('Listo para enviar');
    expect(textoEstadoCola('esperando_reintento', 1, 130)).toBe('Reintento en 3 min');
    expect(textoIntento({ empresa_id: 1, operacion_id: 'x', fecha: '', http_status: 401, motivo: null, respuesta: null })).toContain('sesión');
    expect(textoIntento({ empresa_id: 1, operacion_id: 'x', fecha: '', http_status: 503, motivo: null, respuesta: null })).toContain('servidor');
  });

  it('formatea el dinero como Bs 1.234,50', () => {
    expect(formatoBs('1234.5')).toBe('Bs 1.234,50');
    expect(formatoBs('0')).toBe('Bs 0,00');
    expect(formatoBs('1000000')).toBe('Bs 1.000.000,00');
    expect(formatoBs('abc')).toBe('—');
    expect(formatoBs(null)).toBe('—');
  });

  it('el comprobante escapa lo que viene de datos de la empresa', () => {
    const html = htmlComprobante({ ...base, cliente_nombre: '<script>alert(1)</script>', lineas: [{ ...base.lineas[0], producto_nombre: 'A & B "x"' }] }, 'Centro <b>', 'Alfa', '30/10/2026 10:00');

    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<b>');
    expect(html).toContain('&#60;script&#62;');
    expect(html).toContain('A &#38; B &#34;x&#34;');
    expect(html).toContain('Bs 268,20');
  });
});
