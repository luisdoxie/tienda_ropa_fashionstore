import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Tarjeta "Resumen" de los pasos de compra: subtotal, descuento, envío y
 * total. La acción del paso (continuar, pagar) entra por contenido proyectado.
 * Sin importes (`subtotal` o `total` nulos) muestra "Calculando…" mientras
 * `cargando` y, si no, que no se pudo calcular.
 */
@Component({
  selector: 'app-resumen-compra',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DecimalPipe],
  templateUrl: './resumen-compra.component.html',
  styleUrl: './resumen-compra.component.scss',
})
export class ResumenCompraComponent {
  readonly subtotal = input<number | null>(null);
  readonly descuento = input(0);
  /** Costo de envío; nulo cuando el paso todavía no lo conoce (no se muestra la fila). */
  readonly envio = input<number | null>(null);
  readonly total = input<number | null>(null);
  readonly cargando = input(false);
}
