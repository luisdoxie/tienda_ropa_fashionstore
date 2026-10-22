import { DatePipe } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { switchMap } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { ProductoImagenLookupItem } from '../../../core/models/catalogo.models';
import { EstadoReserva, Reserva, ReservaDetalle } from '../../../core/models/reservas.models';
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

interface LineaReserva extends ReservaDetalle {
  productoNombre?: string;
  imagenPrincipal?: string | null;
  tallaCodigo?: string | null;
  colorNombre?: string | null;
}

@Component({
  selector: 'app-reserva-detalle',
  standalone: true,
  imports: [RouterLink, DatePipe],
  templateUrl: './reserva-detalle.component.html',
  styleUrl: './reserva-detalle.component.scss',
})
export class ReservaDetalleComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  protected readonly tienda = inject(TiendaActualService);
  private readonly reservasService = inject(ReservasClienteService);

  protected readonly reserva = signal<Reserva | null>(null);
  protected readonly lineas = signal<LineaReserva[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal(false);
  protected readonly cancelando = signal(false);

  protected readonly esCancelable = computed(() => {
    const estado = this.reserva()?.estado;
    return estado === 'pendiente' || estado === 'preparada';
  });

  ngOnInit(): void {
    const reservaId = Number(this.route.snapshot.paramMap.get('id'));
    this.reservasService
      .obtener(reservaId)
      .pipe(
        switchMap((reserva) => {
          this.reserva.set(reserva);
          const params = new HttpParams().set('variante_ids', reserva.detalle.map((d) => d.variante_id).join(','));
          return this.http.get<ProductoImagenLookupItem[]>(`${environment.apiUrl}/catalogo/variantes/detalle`, {
            params,
          });
        }),
      )
      .subscribe({
        next: (lookup) => {
          const porVariante = new Map(lookup.map((item) => [item.variante_id, item]));
          this.lineas.set(
            this.reserva()!.detalle.map((linea) => {
              const item = porVariante.get(linea.variante_id);
              return {
                ...linea,
                productoNombre: item?.producto_nombre,
                imagenPrincipal: item?.imagen_principal,
                tallaCodigo: item?.talla_codigo,
                colorNombre: item?.color_nombre,
              };
            }),
          );
          this.cargando.set(false);
        },
        error: () => {
          this.cargando.set(false);
          this.error.set(true);
        },
      });
  }

  etiquetaEstado(estado: EstadoReserva): string {
    return ETIQUETAS_ESTADO[estado];
  }

  cancelar(): void {
    const reserva = this.reserva();
    if (!reserva || this.cancelando()) return;

    this.cancelando.set(true);
    this.reservasService.cancelar(reserva.id).subscribe({
      next: () => this.router.navigate(this.tienda.ruta('mis-reservas')),
      error: () => this.cancelando.set(false),
    });
  }
}
