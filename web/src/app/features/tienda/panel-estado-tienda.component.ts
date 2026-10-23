import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { IconoComponent } from '../../shared/icono/icono.component';
import { NombreIcono } from '../../shared/icono/iconos';
import { MarcaComponent } from '../../shared/marca/marca.component';

/**
 * Pantalla completa de estado de la tienda (no disponible, no encontrada,
 * error de carga): cabecera oscura con la marca de la plataforma, un panel
 * oscuro con ícono, título y texto, y el pie claro. La acción (enlace o botón)
 * entra por contenido proyectado.
 */
@Component({
  selector: 'app-panel-estado-tienda',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconoComponent, MarcaComponent],
  templateUrl: './panel-estado-tienda.component.html',
  styleUrl: './panel-estado-tienda.component.scss',
})
export class PanelEstadoTiendaComponent {
  readonly icono = input.required<NombreIcono>();
  readonly titulo = input.required<string>();
  readonly texto = input.required<string>();
}
