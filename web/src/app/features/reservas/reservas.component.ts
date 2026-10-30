import { DatePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DatePickerModule } from 'primeng/datepicker';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TooltipModule } from 'primeng/tooltip';
import { RouterLink } from '@angular/router';
import { environment } from '../../../environments/environment';
import { ConectividadService } from '../../core/conectividad.service';
import { EstadoReserva, Reserva, SeleccionActualizar } from '../../core/models/reservas.models';
import { Sucursal } from '../../core/models/organizacion.models';
import { CatalogoLocalService, VarianteBusquedaLocal } from '../../core/offline/catalogo-local.service';
import { ColaSincronizacionService } from '../../core/offline/cola-sincronizacion.service';
import type { FaltanteLocal, FilaCliente, FilaSucursal } from '../../core/offline/offline.models';
import {
  ErrorOperacionOffline,
  OperacionesOfflineService,
  StockLocalInsuficienteError,
} from '../../core/offline/operaciones-offline.service';
import { PlanService } from '../../core/plan.service';
import { IconoComponent } from '../../shared/icono/icono.component';

/** Una prenda de la reserva nueva (cantidad `null` = el campo quedó vacío). */
export interface LineaReservaNueva {
  varianteId: number;
  producto: string;
  detalle: string;
  cantidad: number | null;
}

/** Los problemas del formulario de "Nueva reserva"; solo sale lo que está mal. */
export interface ErroresReservaNueva {
  cliente?: string;
  sucursal?: string;
  fecha?: string;
  horario?: string;
  prendas?: string;
}

/** Cuántas prendas se muestran como máximo al buscar. */
const MAX_RESULTADOS = 8;
const MAX_OBSERVACION = 300;

const ETIQUETAS_ESTADO: Record<EstadoReserva, string> = {
  pendiente: 'Pendiente',
  preparada: 'Preparada',
  en_prueba: 'En prueba',
  completada: 'Completada',
  cancelada: 'Cancelada',
  expirada: 'Expirada',
};

const CLASE_ESTADO: Record<EstadoReserva, string> = {
  pendiente: '',
  preparada: 'fs-chip--advertencia',
  en_prueba: 'fs-chip--advertencia',
  completada: 'fs-chip--exito',
  cancelada: 'fs-chip--error',
  expirada: '',
};

const OPCIONES_ESTADO: { label: string; value: EstadoReserva | null }[] = [
  { label: 'Todos los estados', value: null },
  { label: 'Pendiente', value: 'pendiente' },
  { label: 'Preparada', value: 'preparada' },
  { label: 'En prueba', value: 'en_prueba' },
  { label: 'Completada', value: 'completada' },
  { label: 'Cancelada', value: 'cancelada' },
  { label: 'Expirada', value: 'expirada' },
];

const OPCIONES_COMPRA = [
  { label: 'Comprada', value: true },
  { label: 'No comprada', value: false },
];

@Component({
  selector: 'app-reservas',
  standalone: true,
  imports: [
    DatePipe,
    FormsModule,
    ButtonModule,
    CheckboxModule,
    DatePickerModule,
    DialogModule,
    InputTextModule,
    RouterLink,
    SelectButtonModule,
    SelectModule,
    TableModule,
    TooltipModule,
    IconoComponent,
  ],
  templateUrl: './reservas.component.html',
  styleUrl: './reservas.component.scss',
})
export class ReservasComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly messageService = inject(MessageService);
  private readonly catalogoLocal = inject(CatalogoLocalService);
  private readonly operaciones = inject(OperacionesOfflineService);
  private readonly cola = inject(ColaSincronizacionService);
  private readonly conectividad = inject(ConectividadService);
  private readonly plan = inject(PlanService);

  protected readonly opcionesEstado = OPCIONES_ESTADO;
  protected readonly opcionesCompra = OPCIONES_COMPRA;

  protected etiquetaEstado(estado: EstadoReserva): string {
    return ETIQUETAS_ESTADO[estado];
  }

  protected claseEstado(estado: EstadoReserva): string {
    return CLASE_ESTADO[estado];
  }

  protected readonly sucursales = signal<Sucursal[]>([]);
  protected readonly filtroSucursal = signal<number | null>(null);
  protected readonly filtroFecha = signal<Date | null>(null);
  protected readonly filtroEstado = signal<EstadoReserva | null>(null);

  protected readonly reservasSucursal = signal<Reserva[]>([]);
  protected readonly cargando = signal(false);

  protected readonly filasFiltradas = computed(() => {
    const fecha = this.filtroFecha();
    const estado = this.filtroEstado();
    return this.reservasSucursal().filter((reserva) => {
      if (estado !== null && reserva.estado !== estado) return false;
      if (fecha !== null && reserva.fecha_visita !== this.aFechaIso(fecha)) return false;
      return true;
    });
  });

  // ---- Detalle -------------------------------------------------------------

  protected readonly dialogoDetalleVisible = signal(false);
  protected readonly reservaActual = signal<Reserva | null>(null);
  protected readonly checklistPreparacion = signal<Record<number, boolean>>({});
  protected readonly seleccionLineas = signal<Record<number, boolean | null>>({});
  protected readonly guardando = signal(false);

  protected readonly todoPreparadoMarcado = computed(() => {
    const checklist = this.checklistPreparacion();
    return Object.values(checklist).length > 0 && Object.values(checklist).every((marcado) => marcado);
  });

  protected readonly todaLaSeleccionDecidida = computed(() => {
    const seleccion = this.seleccionLineas();
    const valores = Object.values(seleccion);
    return valores.length > 0 && valores.every((v) => v !== null);
  });

  // ---- Nueva reserva (E14b): siempre por OperacionesOfflineService, en línea y sin conexión ----------------------

  protected readonly maxObservacion = MAX_OBSERVACION;
  protected readonly hoy = new Date();
  protected readonly nuevaVisible = signal(false);
  /** Leyendo lo descargado en este equipo al abrir el diálogo. */
  protected readonly cargandoNueva = signal(false);
  /** Todavía no se descargaron los datos (no hay sucursales locales): se pide descargarlos primero. */
  protected readonly sinDatos = signal(false);
  protected readonly errorLecturaNueva = signal(false);
  protected readonly sucursalesLocales = signal<FilaSucursal[]>([]);

  protected readonly sucursalNueva = signal<number | null>(null);
  protected readonly fechaNueva = signal<Date | null>(null);
  protected readonly horaDesde = signal('');
  protected readonly horaHasta = signal('');
  protected readonly observacion = signal('');

  protected readonly textoCliente = signal('');
  protected readonly resultadosCliente = signal<FilaCliente[]>([]);
  protected readonly clienteElegido = signal<{ id: number; nombre: string } | null>(null);

  protected readonly textoPrenda = signal('');
  protected readonly resultadosPrenda = signal<VarianteBusquedaLocal[]>([]);
  protected readonly lineasNuevas = signal<LineaReservaNueva[]>([]);

  /** Se pone en verdadero al primer clic y no vuelve a falso hasta terminar: el doble clic no duplica. */
  protected readonly guardandoNueva = signal(false);
  protected readonly intentoGuardar = signal(false);
  /** Mensaje de un error al guardar (se muestra dentro del diálogo, que sigue abierto). */
  protected readonly errorNueva = signal<string | null>(null);
  /** Prendas que no alcanzan según lo descargado: abre la confirmación [Cancelar] / [Registrar de todos modos]. */
  protected readonly faltantes = signal<FaltanteLocal[] | null>(null);

  /** Se genera UNA vez al abrir el diálogo: todos los reintentos de esta reserva usan el mismo. */
  private operacionIdNueva = '';
  private busquedaCliente = 0;
  private busquedaPrenda = 0;

  /** Sin la funcionalidad en el plan la reserva se rechazaría al enviarla: no se ofrece. */
  protected readonly planPermiteReservar = computed(() => this.plan.incluye('operacion_offline'));

  protected readonly erroresNueva = computed<ErroresReservaNueva>(() => {
    const errores: ErroresReservaNueva = {};
    if (this.clienteElegido() === null) errores.cliente = 'Elige el cliente de la reserva.';
    if (this.sucursalNueva() === null) errores.sucursal = 'Elige la sucursal.';

    const fecha = this.fechaNueva();
    if (fecha === null) errores.fecha = 'Elige la fecha de la visita.';
    else if (this.aFechaIso(fecha) < this.aFechaIso(new Date())) errores.fecha = 'La fecha de la visita no puede ser anterior a hoy.';

    const desde = this.horaDesde();
    const hasta = this.horaHasta();
    if (!desde || !hasta) errores.horario = 'Indica la hora de inicio y la de fin de la visita.';
    else if (desde >= hasta) errores.horario = 'La hora de inicio debe ser anterior a la hora de fin.';

    const lineas = this.lineasNuevas();
    if (lineas.length === 0) errores.prendas = 'Agrega al menos una prenda.';
    else if (lineas.some((l) => l.cantidad === null || !Number.isInteger(l.cantidad) || l.cantidad < 1)) {
      errores.prendas = 'Las cantidades deben ser números enteros mayores que cero.';
    }
    return errores;
  });

  protected async abrirNueva(): Promise<void> {
    this.operacionIdNueva = this.operaciones.nuevoOperacionId();
    this.clienteElegido.set(null);
    this.textoCliente.set('');
    this.resultadosCliente.set([]);
    this.textoPrenda.set('');
    this.resultadosPrenda.set([]);
    this.lineasNuevas.set([]);
    this.fechaNueva.set(null);
    this.horaDesde.set('');
    this.horaHasta.set('');
    this.observacion.set('');
    this.errorNueva.set(null);
    this.faltantes.set(null);
    this.intentoGuardar.set(false);
    this.guardandoNueva.set(false);
    this.sinDatos.set(false);
    this.errorLecturaNueva.set(false);
    this.sucursalNueva.set(null);
    this.cargandoNueva.set(true);
    this.nuevaVisible.set(true);
    try {
      const sucursales = (await this.catalogoLocal.sucursales()).filter((s) => !s.es_deposito);
      this.sucursalesLocales.set(sucursales);
      this.sinDatos.set(sucursales.length === 0);
      const elegida = this.filtroSucursal();
      if (elegida !== null && sucursales.some((s) => s.id === elegida)) this.sucursalNueva.set(elegida);
      else if (sucursales.length === 1) this.sucursalNueva.set(sucursales[0].id);
    } catch {
      this.errorLecturaNueva.set(true);
    } finally {
      this.cargandoNueva.set(false);
    }
  }

  protected cerrarNueva(): void {
    this.nuevaVisible.set(false);
    this.faltantes.set(null);
  }

  protected async buscarCliente(texto: string): Promise<void> {
    this.textoCliente.set(texto);
    const secuencia = ++this.busquedaCliente;
    if (!texto.trim()) {
      this.resultadosCliente.set([]);
      return;
    }
    try {
      const clientes = await this.catalogoLocal.clientes(texto);
      if (secuencia === this.busquedaCliente) this.resultadosCliente.set(clientes);
    } catch {
      if (secuencia === this.busquedaCliente) this.resultadosCliente.set([]);
    }
  }

  protected elegirCliente(cliente: FilaCliente): void {
    this.clienteElegido.set({ id: cliente.id, nombre: `${cliente.nombre} ${cliente.apellido}`.trim() });
    this.textoCliente.set('');
    this.resultadosCliente.set([]);
  }

  protected quitarCliente(): void {
    this.clienteElegido.set(null);
  }

  protected async buscarPrenda(texto: string): Promise<void> {
    this.textoPrenda.set(texto);
    const secuencia = ++this.busquedaPrenda;
    if (!texto.trim()) {
      this.resultadosPrenda.set([]);
      return;
    }
    try {
      const variantes = await this.catalogoLocal.buscarVariantes(texto);
      if (secuencia === this.busquedaPrenda) this.resultadosPrenda.set(variantes.slice(0, MAX_RESULTADOS));
    } catch {
      if (secuencia === this.busquedaPrenda) this.resultadosPrenda.set([]);
    }
  }

  /** Agrega la prenda; si ya estaba, suma una unidad. */
  protected agregarPrenda(variante: VarianteBusquedaLocal): void {
    this.lineasNuevas.update((lineas) => {
      const existente = lineas.find((l) => l.varianteId === variante.variante_id);
      if (existente) {
        return lineas.map((l) => (l === existente ? { ...l, cantidad: (l.cantidad ?? 0) + 1 } : l));
      }
      const detalle = [variante.talla_codigo, variante.color_nombre].filter(Boolean).join(' · ');
      return [...lineas, { varianteId: variante.variante_id, producto: variante.producto_nombre, detalle, cantidad: 1 }];
    });
    this.textoPrenda.set('');
    this.resultadosPrenda.set([]);
  }

  protected cambiarCantidad(varianteId: number, cantidad: number | null): void {
    this.lineasNuevas.update((lineas) => lineas.map((l) => (l.varianteId === varianteId ? { ...l, cantidad } : l)));
  }

  protected quitarPrenda(varianteId: number): void {
    this.lineasNuevas.update((lineas) => lineas.filter((l) => l.varianteId !== varianteId));
  }

  protected tieneErrores(): boolean {
    return Object.keys(this.erroresNueva()).length > 0;
  }

  protected nombreFaltante(faltante: FaltanteLocal): string {
    const detalle = [faltante.talla, faltante.color].filter(Boolean).join(' · ');
    return detalle ? `${faltante.producto_nombre} (${detalle})` : faltante.producto_nombre;
  }

  /** [Guardar]. Con `aceptarSinStock` el usuario ya vio el aviso de stock y decidió seguir (se reusa el mismo `operacionId`). */
  protected async guardarNueva(aceptarSinStock = false): Promise<void> {
    if (this.guardandoNueva()) return;
    this.intentoGuardar.set(true);
    if (this.tieneErrores()) return;
    const cliente = this.clienteElegido()!;
    this.guardandoNueva.set(true);
    this.errorNueva.set(null);
    this.faltantes.set(null);
    try {
      const operacion = await this.operaciones.registrarReserva({
        sucursalId: this.sucursalNueva()!,
        lineas: this.lineasNuevas().map((l) => ({ varianteId: l.varianteId, cantidad: l.cantidad as number })),
        clienteId: cliente.id,
        clienteNombre: cliente.nombre,
        fechaVisita: this.aFechaIso(this.fechaNueva()!),
        horaDesde: this.horaDesde(),
        horaHasta: this.horaHasta(),
        observacion: this.observacion(),
        operacionId: this.operacionIdNueva,
        aceptarSinStock,
      });
      this.nuevaVisible.set(false);
      await this.avisarALaCola();
      const hayRed = this.conectividad.estado() === 'en_linea';
      this.messageService.add(
        hayRed
          ? { severity: 'success', summary: 'Reserva registrada.', detail: 'Se está enviando.' }
          : {
              severity: 'success',
              summary: `Reserva registrada (${operacion.codigo_local}).`,
              detail: 'Se enviará sola cuando haya conexión.',
            },
      );
    } catch (error) {
      if (error instanceof StockLocalInsuficienteError) this.faltantes.set(error.faltantes);
      else if (error instanceof ErrorOperacionOffline) this.errorNueva.set(error.message);
      else this.errorNueva.set('No pudimos registrar la reserva. Inténtalo de nuevo.');
    } finally {
      this.guardandoNueva.set(false);
    }
  }

  /** Ya está guardada: si la cola falla, la reserva sigue registrada y se enviará en el próximo ciclo. */
  private async avisarALaCola(): Promise<void> {
    try {
      this.cola.notificarNuevaOperacion();
      await this.cola.refrescarConteos();
    } catch {
      // Nada que deshacer: la operación ya está en este equipo.
    }
  }

  ngOnInit(): void {
    this.http
      .get<Sucursal[]>(`${environment.apiUrl}/sucursales?pagina=1&tamanio=100`)
      .subscribe((sucursales) => this.sucursales.set(sucursales));
  }

  private aFechaIso(fecha: Date): string {
    const y = fecha.getFullYear();
    const m = String(fecha.getMonth() + 1).padStart(2, '0');
    const d = String(fecha.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  buscarReservas(): void {
    const sucursalId = this.filtroSucursal();
    if (sucursalId === null) return;
    this.cargando.set(true);
    this.http.get<Reserva[]>(`${environment.apiUrl}/reservas/sucursal/${sucursalId}`).subscribe({
      next: (reservas) => {
        this.reservasSucursal.set(reservas);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  abrirDetalle(reserva: Reserva): void {
    this.reservaActual.set(reserva);
    this.checklistPreparacion.set(Object.fromEntries(reserva.detalle.map((linea) => [linea.variante_id, false])));
    this.seleccionLineas.set(Object.fromEntries(reserva.detalle.map((linea) => [linea.variante_id, null])));
    this.dialogoDetalleVisible.set(true);
  }

  marcarPreparada(varianteId: number, marcado: boolean): void {
    this.checklistPreparacion.update((actual) => ({ ...actual, [varianteId]: marcado }));
  }

  elegirCompra(varianteId: number, comprada: boolean): void {
    this.seleccionLineas.update((actual) => ({ ...actual, [varianteId]: comprada }));
  }

  private actualizarReservaEnLista(actualizada: Reserva): void {
    this.reservaActual.set(actualizada);
    this.reservasSucursal.update((filas) => filas.map((f) => (f.id === actualizada.id ? actualizada : f)));
  }

  confirmarPreparacion(): void {
    const reserva = this.reservaActual();
    if (!reserva || !this.todoPreparadoMarcado()) return;
    this.guardando.set(true);
    this.http.put<Reserva>(`${environment.apiUrl}/reservas/${reserva.id}/preparar`, {}).subscribe({
      next: (actualizada) => {
        this.guardando.set(false);
        this.actualizarReservaEnLista(actualizada);
        this.messageService.add({ severity: 'success', summary: 'Reserva preparada' });
      },
      error: () => this.guardando.set(false),
    });
  }

  confirmarLlegada(): void {
    const reserva = this.reservaActual();
    if (!reserva) return;
    this.guardando.set(true);
    this.http.put<Reserva>(`${environment.apiUrl}/reservas/${reserva.id}/confirmar-llegada`, {}).subscribe({
      next: (actualizada) => {
        this.guardando.set(false);
        this.actualizarReservaEnLista(actualizada);
        this.messageService.add({ severity: 'success', summary: 'Llegada confirmada' });
      },
      error: () => this.guardando.set(false),
    });
  }

  confirmarSeleccion(): void {
    const reserva = this.reservaActual();
    if (!reserva || !this.todaLaSeleccionDecidida()) return;
    const seleccion = this.seleccionLineas();
    const payload: SeleccionActualizar = {
      lineas: Object.entries(seleccion).map(([varianteId, comprada]) => ({
        variante_id: Number(varianteId),
        seleccionada: comprada as boolean,
      })),
    };
    this.guardando.set(true);
    this.http.put<Reserva>(`${environment.apiUrl}/reservas/${reserva.id}/seleccion`, payload).subscribe({
      next: (actualizada) => {
        this.guardando.set(false);
        this.actualizarReservaEnLista(actualizada);
        this.messageService.add({ severity: 'success', summary: 'Selección registrada' });
      },
      error: () => this.guardando.set(false),
    });
  }
}
