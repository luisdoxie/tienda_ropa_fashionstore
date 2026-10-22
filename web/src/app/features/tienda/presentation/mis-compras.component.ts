import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EstadoVenta, Venta } from '../../../core/models/ventas.models';
import { PedidosService } from '../data/pedidos.service';
import { TiendaActualService } from '../state/tienda-actual.service';

const ETIQUETAS_ESTADO: Record<EstadoVenta, string> = {
  pendiente_pago: 'Pendiente de pago',
  pagada: 'Pagada',
  entregada: 'Entregada',
  anulada: 'Anulada',
};

@Component({
  selector: 'app-mis-compras',
  standalone: true,
  imports: [RouterLink, DatePipe, DecimalPipe],
  templateUrl: './mis-compras.component.html',
  styleUrl: './mis-compras.component.scss',
})
export class MisComprasComponent implements OnInit {
  private readonly pedidosService = inject(PedidosService);
  protected readonly tienda = inject(TiendaActualService);

  protected readonly compras = signal<Venta[]>([]);
  protected readonly cargando = signal(true);

  ngOnInit(): void {
    this.pedidosService.listarMisCompras().subscribe({
      next: (compras) => {
        this.compras.set(compras);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  etiquetaEstado(estado: EstadoVenta): string {
    return ETIQUETAS_ESTADO[estado];
  }
}
