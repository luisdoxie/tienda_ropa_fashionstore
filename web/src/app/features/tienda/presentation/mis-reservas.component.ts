import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EstadoReserva, Reserva } from '../../../core/models/reservas.models';
import { ReservasClienteService } from '../data/reservas.service';
import { TiendaActualService } from '../state/tienda-actual.service';

const ETIQUETAS_ESTADO: Record<EstadoReserva, string> = {
  pendiente: 'Pendiente',
  preparada: 'Preparada',
  en_prueba: 'En prueba',
  completada: 'Completada',
  cancelada: 'Cancelada',
  expirada: 'Expirada',
};

@Component({
  selector: 'app-mis-reservas',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './mis-reservas.component.html',
  styleUrl: './mis-reservas.component.scss',
})
export class MisReservasComponent implements OnInit {
  private readonly reservasService = inject(ReservasClienteService);
  protected readonly tienda = inject(TiendaActualService);

  protected readonly reservas = signal<Reserva[]>([]);
  protected readonly cargando = signal(true);

  ngOnInit(): void {
    this.reservasService.listarMisReservas().subscribe({
      next: (reservas) => {
        this.reservas.set(reservas);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  etiquetaEstado(estado: EstadoReserva): string {
    return ETIQUETAS_ESTADO[estado];
  }
}
