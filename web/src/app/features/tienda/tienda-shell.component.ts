import { Component, computed, effect, inject, signal } from '@angular/core';
import { NavigationStart, Router, RouterLink, RouterOutlet } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { CarritoService } from './data/carrito.service';
import { ReservaCarritoService } from './state/reserva-carrito.service';
import { TiendaActualService } from './state/tienda-actual.service';

@Component({
  selector: 'app-tienda-shell',
  standalone: true,
  imports: [RouterLink, RouterOutlet],
  templateUrl: './tienda-shell.component.html',
  styleUrl: './tienda-shell.component.scss',
})
export class TiendaShellComponent {
  protected readonly authService = inject(AuthService);
  protected readonly carritoService = inject(CarritoService);
  protected readonly reservaCarritoService = inject(ReservaCarritoService);
  protected readonly tienda = inject(TiendaActualService);

  // La sesión vale para UNA empresa: un usuario de otra tienda ve esta como visitante.
  protected readonly sesionDeEstaTienda = computed(
    () => this.authService.estaAutenticado() && this.authService.empresaCodigo() === this.tienda.codigo(),
  );

  // Si el logo de la empresa no carga, se muestra su nombre.
  protected readonly logoFallido = signal<string | null>(null);
  protected readonly logoUrl = computed(() => {
    const url = this.tienda.empresa()?.logo_url;
    return url && /^https?:\/\//i.test(url) && url !== this.logoFallido() ? url : null;
  });

  // Menú de "Iniciar sesión" / "Mis compras" etc. colapsado en celular: ver
  // tienda-shell.component.scss, se muestra en fila completa desde 760px y
  // no hace falta ni el botón ni este estado.
  protected readonly menuAbierto = signal(false);

  constructor() {
    effect(() => {
      if (this.sesionDeEstaTienda()) {
        this.carritoService.cargar().subscribe({ error: () => undefined });
      } else {
        this.carritoService.limpiar();
      }
    });

    // Sin esto, el menú se queda abierto al navegar (tocás "Mis compras" y
    // la próxima pantalla arranca con el menú tapando el contenido).
    const router = inject(Router);
    router.events.subscribe((evento) => {
      if (evento instanceof NavigationStart) this.menuAbierto.set(false);
    });
  }

  logoNoCargo(): void {
    this.logoFallido.set(this.tienda.empresa()?.logo_url ?? null);
  }

  alternarMenu(): void {
    this.menuAbierto.update((abierto) => !abierto);
  }

  cerrarSesion(): void {
    this.menuAbierto.set(false);
    this.authService.logout();
  }
}
