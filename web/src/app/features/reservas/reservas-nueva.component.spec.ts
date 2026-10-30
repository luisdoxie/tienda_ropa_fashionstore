import 'fake-indexeddb/auto';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { ConectividadService, EstadoConexion } from '../../core/conectividad.service';
import { ColaSincronizacionService } from '../../core/offline/cola-sincronizacion.service';
import { BaseOffline } from '../../core/offline/db-offline';
import type { OperacionOffline, PaqueteLocal } from '../../core/offline/offline.models';
import { ErrorOperacionOffline, OperacionesOfflineService } from '../../core/offline/operaciones-offline.service';
import { RepositorioLocal } from '../../core/offline/repositorio-local';
import { SesionOfflineService } from '../../core/offline/sesion-offline.service';
import { PlanService } from '../../core/plan.service';
import { ReservasComponent } from './reservas.component';

const API = environment.apiUrl;
let contador = 0;
const GENERADO = '2026-10-30T10:00:00Z';

function paquete(): PaqueteLocal {
  return {
    empresa: { id: 1, codigo: 'alfa', nombre: 'Alfa' },
    generadoEn: GENERADO,
    avisoDesactualizadoHoras: 12,
    sucursales: [
      { id: 10, codigo: 'SC-CENTRO', nombre: 'Centro', direccion: 'Calle 1', es_deposito: false, horarios: [] },
      { id: 12, codigo: 'SC-SUR', nombre: 'Sur', direccion: 'Calle 3', es_deposito: false, horarios: [] },
      { id: 11, codigo: 'SC-DEP', nombre: 'Depósito', direccion: 'Calle 2', es_deposito: true, horarios: [] },
    ],
    categorias: [{ id: 1, nombre: 'Poleras', categoria_padre_id: null }],
    tallas: [{ id: 1, codigo: 'M', orden: 1 }],
    colores: [{ id: 1, nombre: 'Negro', codigo_hex: '#000000' }],
    productos: [
      {
        id: 100,
        codigo: 'FS-1',
        nombre: 'Polera Estampada',
        categoria_id: 1,
        genero: 'hombre',
        temporada_id: null,
        imagen_principal: null,
        variantes: [
          { id: 1000, talla_id: 1, color_id: 1, sku: 'POL-M', codigo_barras: null, precio: '149.00', descuento_unitario: '0.00' },
          { id: 1001, talla_id: 1, color_id: 1, sku: 'POL-L', codigo_barras: null, precio: '99.90', descuento_unitario: '0.00' },
        ],
      },
    ],
    stock: [
      {
        sucursalId: 10,
        generadoEn: GENERADO,
        items: [
          { variante_id: 1000, cantidad_disponible: 5, actualizado_en: GENERADO },
          { variante_id: 1001, cantidad_disponible: 0, actualizado_en: GENERADO },
        ],
      },
    ],
    clientes: [
      { id: 1, nombre: 'María', apellido: 'Pérez', ci_nit: '123' },
      { id: 2, nombre: 'Juan', apellido: 'Rojas', ci_nit: '456' },
    ],
    reglas: { metodos_pago_offline: ['efectivo'], max_operaciones_por_lote: 50, plazo_cambio_horas: 24, cambios_y_devoluciones: 'solo_en_linea', reservas_offline: 'permitidas' },
  };
}

function enDias(dias: number): Date {
  const fecha = new Date();
  fecha.setDate(fecha.getDate() + dias);
  return fecha;
}

function iso(fecha: Date): string {
  const dos = (n: number) => String(n).padStart(2, '0');
  return `${fecha.getFullYear()}-${dos(fecha.getMonth() + 1)}-${dos(fecha.getDate())}`;
}

describe('ReservasComponent: nueva reserva', () => {
  let db: BaseOffline;
  let repo: RepositorioLocal;
  let http: HttpTestingController;
  let fixture: ComponentFixture<ReservasComponent>;
  let el: HTMLElement;
  let comp: any;
  let mensajes: ReturnType<typeof vi.spyOn>;
  const conexion = signal<EstadoConexion>('en_linea');
  const cola = {
    estadoCola: signal('inactiva'),
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

  async function crear(conDatos = true): Promise<void> {
    db = new BaseOffline(`prueba_reservas_nueva_${++contador}_${Date.now()}`);
    repo = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
    if (conDatos) await repo.reemplazarReferencia(paquete());
    conexion.set('en_linea');
    cola.refrescarConteos.mockClear();
    cola.notificarNuevaOperacion.mockClear();
    TestBed.configureTestingModule({
      imports: [ReservasComponent],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        { provide: ColaSincronizacionService, useValue: cola },
        { provide: ConectividadService, useValue: { estado: conexion } },
        {
          provide: SesionOfflineService,
          useValue: {
            alcance: () => ({ empresaId: 1, usuarioId: 7 }),
            repositorio: () => repo,
            dispositivoId: () => 'dispositivo-prueba',
          },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    mensajes = vi.spyOn(TestBed.inject(MessageService), 'add');
    fixture = TestBed.createComponent(ReservasComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/sucursales?pagina=1&tamanio=100`).flush([{ id: 10, nombre: 'Centro' }]);
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

  async function abrirDialogo(): Promise<void> {
    (el.querySelector('.nueva-reserva') as HTMLButtonElement).click();
    await esperar(() => expect(comp.cargandoNueva()).toBe(false));
  }

  const dialogo = () => document.body.querySelector('.p-dialog') as HTMLElement;
  const textoDialogos = () => Array.from(document.body.querySelectorAll('.p-dialog')).map((d) => d.textContent ?? '').join(' ');
  const botonDe = (texto: string) =>
    Array.from(document.body.querySelectorAll('.p-dialog button')).find((b) => b.textContent?.includes(texto)) as HTMLButtonElement | undefined;

  function escribir(selector: string, valor: string): void {
    const campo = document.body.querySelector(selector) as HTMLInputElement;
    campo.value = valor;
    campo.dispatchEvent(new Event('input', { bubbles: true }));
  }

  /** Cliente, prenda, fecha y franja ya elegidos; solo falta Guardar. */
  async function llenar(varianteBuscada = 'POL-M'): Promise<void> {
    escribir('#nr-cliente', 'maría');
    await esperar(() => expect(document.body.querySelector('.resultados .resultado')).not.toBeNull());
    (document.body.querySelector('.resultados .resultado') as HTMLButtonElement).click();
    escribir('#nr-prenda', varianteBuscada);
    await esperar(() => expect(document.body.querySelector('[aria-label="Prendas encontradas"] .resultado')).not.toBeNull());
    (document.body.querySelector('[aria-label="Prendas encontradas"] .resultado') as HTMLButtonElement).click();
    comp.fechaNueva.set(enDias(2));
    escribir('#nr-desde', '10:00');
    escribir('#nr-hasta', '11:30');
    escribir('#nr-observacion', 'Viene con su hijo');
    fixture.detectChanges();
  }

  afterEach(() => {
    http.match(() => true);
    db.close();
  });

  describe('el botón', () => {
    it('va AL FINAL de la fila de filtros y no mueve nada de lo que ya estaba', async () => {
      await crear();
      const filtros = el.querySelector('.filtros') as HTMLElement;
      const hijos = Array.from(filtros.children).map((h) => h.tagName.toLowerCase());

      expect(hijos).toEqual(['p-select', 'p-datepicker', 'p-select', 'button', 'span', 'button']);
      expect(filtros.lastElementChild?.textContent?.trim()).toBe('Nueva reserva');
      expect(filtros.children[3].getAttribute('aria-label')).toBe('Actualizar');
    });

    it('con un plan que no incluye operar sin conexión sale deshabilitado y lo explica', async () => {
      await crear();
      TestBed.inject(PlanService).suscripcion.set({
        plan_codigo: 'basico',
        plan_nombre: 'Básico',
        estado: 'activa',
        fecha_inicio: '2026-01-01',
        fecha_vencimiento: '2099-01-01',
        max_sucursales: 2,
        sucursales_activas: 1,
        funcionalidades: [],
      });
      fixture.detectChanges();

      const boton = el.querySelector('.nueva-reserva') as HTMLButtonElement;
      expect(boton.disabled).toBe(true);
      expect(boton.getAttribute('title')).toContain('plan no incluye');
    });
  });

  describe('sin datos descargados', () => {
    it('explica "Descarga los datos primero", enlaza a /catalogo-local y no ofrece el formulario', async () => {
      await crear(false);
      await abrirDialogo();

      const aviso = document.body.querySelector('[data-estado="sin-datos"]') as HTMLElement;
      expect(aviso.textContent).toContain('Descarga los datos primero');
      expect(aviso.querySelector('a')?.getAttribute('href')).toBe('/catalogo-local');
      expect(botonDe('Guardar reserva')).toBeUndefined();
    });
  });

  describe('el formulario', () => {
    it('ofrece las sucursales descargadas SIN el depósito y deja elegir al cliente y la prenda de lo local', async () => {
      await crear();
      await abrirDialogo();

      expect((comp.sucursalesLocales() as { nombre: string }[]).map((s) => s.nombre)).toEqual(['Centro', 'Sur']);
      // Con más de una sucursal y ninguna elegida en la pantalla, no se adivina.
      expect(comp.sucursalNueva()).toBeNull();

      escribir('#nr-cliente', 'rojas');
      await esperar(() => expect(document.body.querySelectorAll('.resultados .resultado').length).toBe(1));
      expect(document.body.querySelector('.resultados .resultado')?.textContent).toContain('Juan Rojas');
      (document.body.querySelector('.resultados .resultado') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(document.body.querySelector('.cliente-elegido')?.textContent).toContain('Juan Rojas');

      (document.body.querySelector('[aria-label="Cambiar de cliente"]') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(document.body.querySelector('#nr-cliente')).not.toBeNull();
    });

    it('usa la sucursal elegida en la pantalla si es una de las descargadas', async () => {
      await crear();
      comp.filtroSucursal.set(12);
      await abrirDialogo();

      expect(comp.sucursalNueva()).toBe(12);
    });

    it('agregar dos veces la misma prenda suma una unidad; quitar la saca de la lista', async () => {
      await crear();
      await abrirDialogo();
      for (let i = 0; i < 2; i++) {
        escribir('#nr-prenda', 'POL-M');
        await esperar(() => expect(document.body.querySelector('[aria-label="Prendas encontradas"] .resultado')).not.toBeNull());
        (document.body.querySelector('[aria-label="Prendas encontradas"] .resultado') as HTMLButtonElement).click();
        fixture.detectChanges();
      }

      const lineas = document.body.querySelectorAll('[aria-label="Prendas de la reserva"] li');
      expect(lineas.length).toBe(1);
      expect(comp.lineasNuevas().map((l: { varianteId: number; cantidad: number }) => [l.varianteId, l.cantidad])).toEqual([[1000, 2]]);
      // El campo lo escribe ngModel de forma asíncrona.
      await esperar(() => expect((lineas[0].querySelector('input[type="number"]') as HTMLInputElement).value).toBe('2'));

      (document.body.querySelector('[aria-label="Quitar Polera Estampada"]') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(document.body.querySelector('[aria-label="Prendas de la reserva"]')).toBeNull();
    });
  });

  describe('validaciones', () => {
    it('Guardar vacío dice qué falta y NO guarda nada', async () => {
      await crear();
      await abrirDialogo();
      const registrar = vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarReserva');

      botonDe('Guardar reserva')!.click();
      fixture.detectChanges();

      const texto = textoDialogos();
      expect(texto).toContain('Elige el cliente de la reserva.');
      expect(texto).toContain('Elige la sucursal.');
      expect(texto).toContain('Elige la fecha de la visita.');
      expect(texto).toContain('Indica la hora de inicio y la de fin de la visita.');
      expect(texto).toContain('Agrega al menos una prenda.');
      expect(registrar).not.toHaveBeenCalled();
      expect(await repo.misOperaciones()).toEqual([]);
    });

    it('una fecha pasada y una franja al revés se rechazan con su mensaje', async () => {
      await crear();
      comp.filtroSucursal.set(10);
      await abrirDialogo();
      await llenar();
      const registrar = vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarReserva');

      comp.fechaNueva.set(new Date(2020, 0, 1));
      escribir('#nr-desde', '12:00');
      escribir('#nr-hasta', '11:00');
      fixture.detectChanges();
      botonDe('Guardar reserva')!.click();
      fixture.detectChanges();

      expect(textoDialogos()).toContain('no puede ser anterior a hoy');
      expect(textoDialogos()).toContain('La hora de inicio debe ser anterior a la hora de fin.');
      expect(registrar).not.toHaveBeenCalled();
      expect(await repo.misOperaciones()).toEqual([]);
    });

    it('una cantidad vacía o cero no pasa', async () => {
      await crear();
      comp.filtroSucursal.set(10);
      await abrirDialogo();
      await llenar();
      const registrar = vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarReserva');

      comp.cambiarCantidad(1000, 0);
      fixture.detectChanges();
      botonDe('Guardar reserva')!.click();
      fixture.detectChanges();

      expect(textoDialogos()).toContain('Las cantidades deben ser números enteros mayores que cero.');
      expect(registrar).not.toHaveBeenCalled();
    });
  });

  describe('guardar', () => {
    it('escribe UNA operación tipo reserva con el horario, avisa a la cola y cierra el diálogo (sin red)', async () => {
      await crear();
      conexion.set('sin_conexion');
      comp.filtroSucursal.set(10);
      await abrirDialogo();
      await llenar();

      botonDe('Guardar reserva')!.click();
      await esperar(() => expect(comp.nuevaVisible()).toBe(false));

      const operaciones = await repo.misOperaciones();
      expect(operaciones.length).toBe(1);
      const operacion = operaciones[0] as OperacionOffline;
      expect(operacion).toMatchObject({
        tipo: 'reserva',
        estado: 'registrada',
        sucursal_id: 10,
        cliente_id: 1,
        cliente_nombre: 'María Pérez',
        total: '149.00',
      });
      expect(operacion.reserva).toEqual({
        fecha_visita: iso(enDias(2)),
        hora_visita_desde: '10:00',
        hora_visita_hasta: '11:30',
        observacion: 'Viene con su hijo',
      });
      expect(operacion.lineas.map((l) => [l.variante_id, l.cantidad])).toEqual([[1000, 1]]);

      expect(cola.notificarNuevaOperacion).toHaveBeenCalledTimes(1);
      expect(cola.refrescarConteos).toHaveBeenCalledTimes(1);
      expect(mensajes).toHaveBeenCalledWith({
        severity: 'success',
        summary: `Reserva registrada (${operacion.codigo_local}).`,
        detail: 'Se enviará sola cuando haya conexión.',
      });
      expect(operacion.codigo_local).toMatch(/^OFF-[0-9A-F]{6}$/);
    });

    it('con red avisa que "se está enviando" y la guarda por el mismo camino', async () => {
      await crear();
      comp.filtroSucursal.set(10);
      await abrirDialogo();
      await llenar();

      botonDe('Guardar reserva')!.click();
      await esperar(() => expect(comp.nuevaVisible()).toBe(false));

      expect((await repo.misOperaciones()).length).toBe(1);
      expect(mensajes).toHaveBeenCalledWith({ severity: 'success', summary: 'Reserva registrada.', detail: 'Se está enviando.' });
      http.expectNone((r) => r.url.includes('/reservas') && r.method === 'POST');
    });

    it('el doble clic NO duplica: el botón se deshabilita al primer clic y solo se registra una vez', async () => {
      await crear();
      comp.filtroSucursal.set(10);
      await abrirDialogo();
      await llenar();
      const original = TestBed.inject(OperacionesOfflineService).registrarReserva.bind(TestBed.inject(OperacionesOfflineService));
      let liberar: () => void = () => undefined;
      const detenida = new Promise<void>((r) => (liberar = r));
      const registrar = vi
        .spyOn(TestBed.inject(OperacionesOfflineService), 'registrarReserva')
        .mockImplementation(async (entrada) => {
          await detenida;
          return original(entrada);
        });

      const guardar = botonDe('Guardar reserva')!;
      guardar.click();
      guardar.click();
      fixture.detectChanges();

      expect(registrar).toHaveBeenCalledTimes(1);
      expect(botonDe('Guardando')?.disabled).toBe(true);

      liberar();
      await esperar(() => expect(comp.nuevaVisible()).toBe(false));
      expect((await repo.misOperaciones()).length).toBe(1);
      expect(cola.notificarNuevaOperacion).toHaveBeenCalledTimes(1);
    });

    it('un error del registro se muestra DENTRO del diálogo, que sigue abierto y listo para reintentar', async () => {
      await crear();
      comp.filtroSucursal.set(10);
      await abrirDialogo();
      await llenar();
      vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarReserva').mockRejectedValue(
        new ErrorOperacionOffline('No hay espacio en este equipo. La operación NO se registró: libera espacio e inténtalo de nuevo.'),
      );

      botonDe('Guardar reserva')!.click();
      await esperar(() => expect(document.body.querySelector('[data-estado="error-guardar"]')).not.toBeNull());

      expect(document.body.querySelector('[data-estado="error-guardar"]')?.textContent).toContain('No hay espacio en este equipo');
      expect(comp.nuevaVisible()).toBe(true);
      expect(botonDe('Guardar reserva')?.disabled).toBe(false);
      expect(cola.notificarNuevaOperacion).not.toHaveBeenCalled();
      expect(mensajes).not.toHaveBeenCalled();
    });

    it('un fallo inesperado también se explica sin cerrar nada', async () => {
      await crear();
      comp.filtroSucursal.set(10);
      await abrirDialogo();
      await llenar();
      vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarReserva').mockRejectedValue(new Error('boom'));

      botonDe('Guardar reserva')!.click();
      await esperar(() => expect(document.body.querySelector('[data-estado="error-guardar"]')).not.toBeNull());

      expect(document.body.querySelector('[data-estado="error-guardar"]')?.textContent).toContain('No pudimos registrar la reserva');
      expect(comp.nuevaVisible()).toBe(true);
    });

    it('si la cola falla DESPUÉS de guardar, la reserva igual queda registrada y se avisa bien', async () => {
      await crear();
      comp.filtroSucursal.set(10);
      await abrirDialogo();
      await llenar();
      cola.notificarNuevaOperacion.mockImplementationOnce(() => {
        throw new Error('cola caída');
      });

      botonDe('Guardar reserva')!.click();
      await esperar(() => expect(comp.nuevaVisible()).toBe(false));

      expect((await repo.misOperaciones()).length).toBe(1);
      expect(mensajes).toHaveBeenCalledTimes(1);
    });
  });

  describe('stock local insuficiente', () => {
    it('pide confirmación con las prendas faltantes y NO guarda hasta aceptar', async () => {
      await crear();
      comp.filtroSucursal.set(10);
      await abrirDialogo();
      await llenar('POL-L'); // la variante L tiene 0 en la sucursal Centro
      const registrar = vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarReserva');

      botonDe('Guardar reserva')!.click();
      await esperar(() => expect(document.body.querySelector('[data-estado="stock-insuficiente"]')).not.toBeNull());

      expect(textoDialogos()).toContain(
        'Según tu información local no hay stock suficiente. La operación se registrará y puede quedar en conflicto.',
      );
      expect(document.body.querySelector('.faltantes')?.textContent).toContain('Polera Estampada (M · Negro)');
      expect(document.body.querySelector('.faltantes')?.textContent).toContain('Pides 1, hay 0');
      expect(botonDe('Cancelar')).toBeDefined();
      expect(botonDe('Registrar de todos modos')).toBeDefined();
      expect(await repo.misOperaciones()).toEqual([]);
      expect(cola.notificarNuevaOperacion).not.toHaveBeenCalled();
      expect(registrar).toHaveBeenCalledTimes(1);
    });

    it('[Cancelar] cierra el aviso, no guarda y deja el formulario como estaba', async () => {
      await crear();
      comp.filtroSucursal.set(10);
      await abrirDialogo();
      await llenar('POL-L');
      botonDe('Guardar reserva')!.click();
      await esperar(() => expect(comp.faltantes()).not.toBeNull());

      const cancelar = Array.from(document.body.querySelectorAll('.p-dialog button')).filter((b) => b.textContent?.trim() === 'Cancelar');
      (cancelar[cancelar.length - 1] as HTMLButtonElement).click();
      await esperar(() => expect(comp.faltantes()).toBeNull());

      expect(await repo.misOperaciones()).toEqual([]);
      expect(comp.nuevaVisible()).toBe(true);
      expect(comp.lineasNuevas().length).toBe(1);
      expect(comp.clienteElegido()).not.toBeNull();
    });

    it('[Registrar de todos modos] guarda con el MISMO identificador y marca que ya se avisó', async () => {
      await crear();
      comp.filtroSucursal.set(10);
      await abrirDialogo();
      await llenar('POL-L');
      const registrar = vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarReserva');
      botonDe('Guardar reserva')!.click();
      await esperar(() => expect(comp.faltantes()).not.toBeNull());

      botonDe('Registrar de todos modos')!.click();
      await esperar(() => expect(comp.nuevaVisible()).toBe(false));

      expect(registrar).toHaveBeenCalledTimes(2);
      const [primera, segunda] = registrar.mock.calls.map((c) => c[0]);
      expect(primera.aceptarSinStock).toBe(false);
      expect(segunda.aceptarSinStock).toBe(true);
      expect(segunda.operacionId).toBe(primera.operacionId);
      expect(primera.operacionId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);

      const operaciones = await repo.misOperaciones();
      expect(operaciones.length).toBe(1);
      expect(operaciones[0].operacion_id).toBe(primera.operacionId);
      expect(cola.notificarNuevaOperacion).toHaveBeenCalledTimes(1);
    });

    it('al abrir el diálogo de nuevo se genera otro identificador (una reserva por apertura)', async () => {
      await crear();
      comp.filtroSucursal.set(10);
      const registrar = vi.spyOn(TestBed.inject(OperacionesOfflineService), 'registrarReserva');
      await abrirDialogo();
      await llenar();
      botonDe('Guardar reserva')!.click();
      await esperar(() => expect(comp.nuevaVisible()).toBe(false));

      await abrirDialogo();
      await llenar();
      botonDe('Guardar reserva')!.click();
      await esperar(() => expect(registrar).toHaveBeenCalledTimes(2));
      await esperar(() => expect(comp.nuevaVisible()).toBe(false));

      expect(registrar.mock.calls[0][0].operacionId).not.toBe(registrar.mock.calls[1][0].operacionId);
      expect((await repo.misOperaciones()).length).toBe(2);
    });
  });
});
