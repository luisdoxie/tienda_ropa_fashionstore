import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ConectividadService } from '../../core/conectividad.service';
import { destinoInternoSeguro } from '../../core/navegacion-sin-conexion';
import { IconoComponent } from '../../shared/icono/icono.component';
import { PanelEstadoTiendaComponent } from '../tienda/panel-estado-tienda.component';

/**
 * Pantalla "Sin conexión" (PWA, E13): a donde lleva el enrutador cuando una pantalla no se pudo
 * cargar sin red. "Reintentar" prueba el servidor y, si responde, vuelve a la pantalla que se
 * quería abrir (`returnTo`, solo rutas internas).
 */
@Component({
  selector: 'app-sin-conexion',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, IconoComponent, PanelEstadoTiendaComponent],
  templateUrl: './sin-conexion.component.html',
  styleUrl: './sin-conexion.component.scss',
})
export class SinConexionComponent {
  private readonly conectividad = inject(ConectividadService);
  private readonly router = inject(Router);
  private readonly ruta = inject(ActivatedRoute);

  protected readonly comprobando = signal(false);
  /** Resultado del último intento (se anuncia con `aria-live`). */
  protected readonly aviso = signal<string | null>(null);

  async reintentar(): Promise<void> {
    if (this.comprobando()) return;
    this.comprobando.set(true);
    this.aviso.set(null);
    const hayRed = await this.conectividad.verificarServidor();
    this.comprobando.set(false);

    if (hayRed) {
      await this.router.navigateByUrl(destinoInternoSeguro(this.ruta.snapshot.queryParamMap.get('returnTo')));
    } else {
      this.aviso.set('Todavía no hay conexión. Revisa tu Internet y vuelve a intentarlo.');
    }
  }
}
