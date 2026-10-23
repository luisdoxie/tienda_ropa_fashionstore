import { DatePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DatePickerModule } from 'primeng/datepicker';
import { DialogModule } from 'primeng/dialog';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TooltipModule } from 'primeng/tooltip';
import { environment } from '../../../environments/environment';
import { EstadoReserva, Reserva, SeleccionActualizar } from '../../core/models/reservas.models';
import { Sucursal } from '../../core/models/organizacion.models';
import { IconoComponent } from '../../shared/icono/icono.component';

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
