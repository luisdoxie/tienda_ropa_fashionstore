import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconoComponent } from '../../shared/icono/icono.component';
import { PanelEstadoTiendaComponent } from './panel-estado-tienda.component';

export type MotivoTiendaNoDisponible = 'no_encontrada' | 'no_disponible';

/** Pantalla (no un toast) para una tienda que no existe o que no está operando. */
@Component({
  selector: 'app-tienda-no-disponible',
  standalone: true,
  imports: [RouterLink, IconoComponent, PanelEstadoTiendaComponent],
  templateUrl: './tienda-no-disponible.component.html',
})
export class TiendaNoDisponibleComponent {
  readonly motivo = input<MotivoTiendaNoDisponible>('no_encontrada');
}
