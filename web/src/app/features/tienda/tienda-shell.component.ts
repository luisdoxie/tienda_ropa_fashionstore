import { Component, DestroyRef, ElementRef, HostListener, computed, effect, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, NavigationStart, Router, RouterLink, RouterOutlet } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { IconoComponent } from '../../shared/icono/icono.component';
import { MarcaComponent } from '../../shared/marca/marca.component';
import { CarritoService } from './data/carrito.service';
import { irAColeccion } from './ir-a-coleccion';
import { ReservaCarritoService } from './state/reserva-carrito.service';
import { TiendaActualService } from './state/tienda-actual.service';

/** Por debajo de este ancho la cabecera pasa a menú desplegable (ver el .scss). */
const ANCHO_MOVIL = '(max-width: 960px)';

@Component({
  selector: 'app-tienda-shell',
  standalone: true,
  imports: [RouterLink, RouterOutlet, MarcaComponent, IconoComponent],
  templateUrl: './tienda-shell.component.html',
  styleUrl: './tienda-shell.component.scss',
})
export class TiendaShellComponent {
  protected readonly authService = inject(AuthService);
  protected readonly carritoService = inject(CarritoService);
  protected readonly reservaCarritoService = inject(ReservaCarritoService);
  protected readonly tienda = inject(TiendaActualService);
  private readonly router = inject(Router);

  // La sesión vale para UNA empresa: un usuario de otra tienda ve esta como visitante.
  protected readonly sesionDeEstaTienda = computed(
    () => this.authService.estaAutenticado() && this.authService.empresaCodigo() === this.tienda.codigo(),
  );

  protected readonly nombreTienda = computed(() => this.tienda.empresa()?.nombre ?? 'FashionStore');

  // Solo se pasa a la marca un logo http(s); si no carga, `fs-marca` cae al monograma.
  protected readonly logoUrl = computed(() => {
    const url = this.tienda.empresa()?.logo_url;
    return url && /^https?:\/\//i.test(url) ? url : null;
  });

  // Ruta actual sin query ni fragmento: decide qué cabecera se muestra.
  private readonly rutaActual = signal(this.sinParametros(this.router.url));
  private readonly base = computed(() => this.tienda.ruta().join('/'));

  /** La portada es el catálogo (la raíz de la tienda): cabecera oscura que continúa el hero. */
  protected readonly esPortada = computed(() => {
    const ruta = this.rutaActual().replace(/\/+$/, '');
    return ruta === this.base();
  });

  /** En los pasos de compra la cabecera se reduce a la marca y "Compra segura". */
  protected readonly esCheckout = computed(() => this.rutaActual().startsWith(`${this.base()}/checkout`));

  protected readonly enlacePortada = computed(() => this.base());

  // El monograma y el nombre de la marca no caben en 390 px: versión pequeña en celular.
  protected readonly esMovil = signal(this.coincideMovil());

  // Menú colapsado en celular (ver el .scss): en escritorio los enlaces van en la fila.
  protected readonly menuAbierto = signal(false);
  private readonly botonMenu = viewChild<ElementRef<HTMLButtonElement>>('botonMenu');

  constructor() {
    effect(() => {
      if (this.sesionDeEstaTienda()) {
        this.carritoService.cargar().subscribe({ error: () => undefined });
      } else {
        this.carritoService.limpiar();
      }
    });

    // Sin esto, el menú se queda abierto al navegar (tocas "Mi cuenta" y la
    // próxima pantalla arranca con el menú tapando el contenido).
    this.router.events.pipe(takeUntilDestroyed()).subscribe((evento) => {
      if (evento instanceof NavigationStart) this.menuAbierto.set(false);
      if (evento instanceof NavigationEnd) this.rutaActual.set(this.sinParametros(evento.urlAfterRedirects));
    });

    if (typeof matchMedia === 'function') {
      const consulta = matchMedia(ANCHO_MOVIL);
      const alCambiar = (e: MediaQueryListEvent) => this.esMovil.set(e.matches);
      consulta.addEventListener?.('change', alCambiar);
      inject(DestroyRef).onDestroy(() => consulta.removeEventListener?.('change', alCambiar));
    }
  }

  /** Escape cierra el menú de celular y devuelve el foco al botón que lo abrió. */
  @HostListener('document:keydown.escape')
  protected cerrarMenuConEscape(): void {
    if (!this.menuAbierto()) return;
    this.menuAbierto.set(false);
    this.botonMenu()?.nativeElement.focus();
  }

  alternarMenu(): void {
    this.menuAbierto.update((abierto) => !abierto);
  }

  cerrarSesion(): void {
    this.menuAbierto.set(false);
    this.authService.logout();
  }

  /** "Colección" y la lupa de la portada: bajan a la sección del catálogo (y enfocan el buscador). */
  irAColeccion(evento: Event, enfocarBuscador = false): void {
    this.menuAbierto.set(false);
    irAColeccion(evento, enfocarBuscador);
  }

  private sinParametros(url: string): string {
    return url.split(/[?#]/)[0];
  }

  private coincideMovil(): boolean {
    return typeof matchMedia === 'function' && matchMedia(ANCHO_MOVIL).matches;
  }
}
