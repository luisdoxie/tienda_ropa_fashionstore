import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { ICONOS, NombreIcono } from './iconos';

/**
 * Ícono de trazo del sistema de diseño. Hereda el color del texto
 * (`currentColor`). Tamaños de la regla de íconos: etiquetas 20, botones y menú
 * 24, barra de la tienda 28, beneficios 36; nunca menos de 20.
 *
 * Es decorativo (`aria-hidden`): si el ícono es lo único del botón, el botón
 * lleva su `aria-label`.
 */
@Component({
  selector: 'fs-icono',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<svg
    [attr.width]="tam()"
    [attr.height]="tam()"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    [attr.stroke-width]="trazo()"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path [attr.d]="trazoSvg()" />
  </svg>`,
  styles: `
    :host {
      display: inline-flex;
      flex: none;
      line-height: 0;
    }
  `,
})
export class IconoComponent {
  readonly nombre = input.required<NombreIcono>();
  readonly tam = input(24);
  readonly trazo = input(1.75);

  protected readonly trazoSvg = computed(() => ICONOS[this.nombre()] ?? '');
}
