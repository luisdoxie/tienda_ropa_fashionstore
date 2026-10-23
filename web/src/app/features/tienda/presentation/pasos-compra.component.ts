import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { IconoComponent } from '../../../shared/icono/icono.component';

const PASOS = ['Entrega', 'Pago', 'Confirmación'] as const;

/**
 * Indicador de los 3 pasos de la compra (Entrega, Pago, Confirmación). `actual`
 * es el índice del paso vigente (0, 1 o 2): los anteriores se muestran hechos.
 * Con 3 no queda ninguno vigente: los tres están hechos (compra confirmada).
 */
@Component({
  selector: 'app-pasos-compra',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconoComponent],
  templateUrl: './pasos-compra.component.html',
  styleUrl: './pasos-compra.component.scss',
})
export class PasosCompraComponent {
  readonly actual = input.required<0 | 1 | 2 | 3>();
  protected readonly pasos = PASOS;
}
