import { ChangeDetectionStrategy, Component, ViewEncapsulation, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { esUrlHttp } from '../../core/seo.service';
import { IconoComponent } from '../../shared/icono/icono.component';
import { MarcaComponent } from '../../shared/marca/marca.component';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';

/**
 * Estructura de las pantallas de acceso (login, registro, recuperar y
 * restablecer contraseña): un panel con fotografía y un panel con el
 * formulario.
 *  - `personal`: acceso del personal, sobre carbón, sin cabecera.
 *  - `cliente`: con la cabecera clara de la tienda (o de la plataforma si no
 *    hay tienda) y el pie "Con la tecnología de FashionStore".
 *
 * Lo que va sobre la foto se proyecta con el atributo `panelImagen`; el resto
 * es el formulario. Usa ViewEncapsulation.None porque sus clases `.acceso-*`
 * (titular, campos, enlaces, error) las comparten los formularios proyectados.
 */
@Component({
  selector: 'app-acceso-pantalla',
  standalone: true,
  imports: [RouterLink, IconoComponent, MarcaComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  templateUrl: './acceso-pantalla.component.html',
  styleUrl: './acceso-pantalla.component.scss',
})
export class AccesoPantallaComponent {
  readonly modo = input<'personal' | 'cliente'>('cliente');
  /** `acceso.png` (login y recuperación) o `portada-tienda.png` (registro y restablecer). */
  readonly foto = input<'acceso' | 'portada'>('acceso');
  readonly altFoto = input('');

  private readonly tienda = inject(TiendaActualService);

  protected readonly esPersonal = computed(() => this.modo() === 'personal');
  protected readonly srcFoto = computed(() =>
    this.foto() === 'portada' ? '/imagenes/portada-tienda.png' : '/imagenes/acceso.png',
  );
  protected readonly nombreMarca = computed(() => this.tienda.empresa()?.nombre ?? 'FashionStore');
  protected readonly logoMarca = computed(() => {
    const logo = this.tienda.empresa()?.logo_url;
    return esUrlHttp(logo) ? logo.trim() : null;
  });
  /** Con tienda, la marca y "Volver a la tienda" llevan a su catálogo; sin ella, a la plataforma. */
  protected readonly rutaInicio = computed(() => this.tienda.ruta());
  protected readonly textoVolver = computed(() => (this.tienda.codigo() ? 'Volver a la tienda' : 'Ir al inicio'));
}
