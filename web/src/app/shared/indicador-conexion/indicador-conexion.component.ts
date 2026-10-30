import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ConectividadService } from '../../core/conectividad.service';
import { IconoComponent } from '../icono/icono.component';

export type VarianteIndicadorConexion = 'pastilla' | 'franja';

/**
 * Estado de la conexión (PWA, E13).
 * - `pastilla` (barra del back office): en línea y sin pendientes es solo un punto verde, para no
 *   estorbar; sin conexión o con el servidor caído, un chip ámbar o rojo; con `pendientes` agrega
 *   "N por enviar".
 * - `franja` (tienda): barra de ancho completo que SOLO aparece sin conexión.
 * El contenedor `role="status"` existe siempre, para que el lector de pantalla anuncie los cambios.
 */
@Component({
  selector: 'app-indicador-conexion',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconoComponent, RouterLink],
  templateUrl: './indicador-conexion.component.html',
  styleUrl: './indicador-conexion.component.scss',
  host: { '[class.es-franja]': "variante() === 'franja'" },
})
export class IndicadorConexionComponent {
  private readonly conectividad = inject(ConectividadService);

  /** Operaciones guardadas en el equipo que aún no se enviaron al servidor. */
  readonly pendientes = input(0);
  /** Ruta a la que lleva el chip cuando hay pendientes (sin ella, el chip es solo texto). */
  readonly enlace = input<string | null>(null);
  readonly variante = input<VarianteIndicadorConexion>('pastilla');

  protected readonly estado = this.conectividad.estado;

  /** Texto del chip; `null` cuando solo corresponde el punto verde (en línea y sin pendientes). */
  protected readonly etiqueta = computed<string | null>(() => {
    const pendientes = this.pendientes() > 0 ? `${this.pendientes()} por enviar` : null;
    const base = this.estado() === 'sin_conexion' ? 'Sin conexión' : this.estado() === 'servidor_no_responde' ? 'Servidor no responde' : 'En línea';
    if (this.estado() === 'en_linea') return pendientes ? `${base} · ${pendientes}` : null;
    return pendientes ? `${base} · ${pendientes}` : base;
  });
}
