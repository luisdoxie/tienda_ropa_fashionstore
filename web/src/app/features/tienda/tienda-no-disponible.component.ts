import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';

export type MotivoTiendaNoDisponible = 'no_encontrada' | 'no_disponible';

/** Pantalla (no un toast) para una tienda que no existe o que no está operando. */
@Component({
  selector: 'app-tienda-no-disponible',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './tienda-no-disponible.component.html',
  styleUrl: './tienda-no-disponible.component.scss',
})
export class TiendaNoDisponibleComponent {
  readonly motivo = input<MotivoTiendaNoDisponible>('no_encontrada');
}
