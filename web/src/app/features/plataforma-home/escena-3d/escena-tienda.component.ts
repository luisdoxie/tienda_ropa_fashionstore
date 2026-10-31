import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  InjectionToken,
  NgZone,
  afterNextRender,
  effect,
  inject,
  input,
  output,
  viewChild,
} from '@angular/core';
import type { MarcaDemo, PlanEscena, TiendaEscena } from './contrato';
// Solo el tipo: el motor y three se cargan a demanda (fragmento aparte) con `import()`.
import type { EscenaTienda } from './escena-tienda';

/** Carga el motor (y three) a demanda. Es un token para que las pruebas lo sustituyan sin tocar el motor. */
export type CargadorEscena = () => Promise<typeof import('./escena-tienda')>;

export const CARGAR_ESCENA = new InjectionToken<CargadorEscena>('CARGAR_ESCENA', {
  providedIn: 'root',
  factory: () => () => import('./escena-tienda'),
});

/**
 * La escena 3D de la portada pública. El lienzo ocupa toda la pantalla detrás del contenido; el motor
 * (three.js) se descarga solo cuando hace falta y corre fuera de la zona de Angular. Quien la usa decide
 * antes si el equipo la soporta (`puedeUsarEscena3D`); si algo falla emite `sinEscena`.
 */
@Component({
  selector: 'app-escena-tienda',
  standalone: true,
  template: '<canvas #lienzo class="escena" aria-hidden="true"></canvas>',
  styleUrl: './escena-tienda.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EscenaTiendaComponent {
  readonly planes = input.required<readonly PlanEscena[]>();
  readonly tiendas = input.required<readonly TiendaEscena[]>();
  readonly marca = input.required<MarcaDemo>();
  /** El usuario hizo clic en un local de la calle: emite el código de la tienda. */
  readonly tiendaElegida = output<string>();
  /** No se pudo crear la escena (sin WebGL, error al cargar three): la página vuelve al diseño clásico. */
  readonly sinEscena = output<void>();

  private readonly zona = inject(NgZone);
  private readonly cargar = inject(CARGAR_ESCENA);
  private readonly lienzo = viewChild.required<ElementRef<HTMLCanvasElement>>('lienzo');

  private escena: EscenaTienda | null = null;
  private observador: ResizeObserver | null = null;
  private destruido = false;

  constructor() {
    // Los datos y la marca se empujan a la escena cada vez que cambian (y una vez al crearla).
    effect(() => {
      const datos = { planes: this.planes(), tiendas: this.tiendas() };
      this.escena?.fijarDatos(datos);
    });
    effect(() => {
      const marca = this.marca();
      this.escena?.fijarMarca(marca);
    });

    afterNextRender(() => {
      void this.zona.runOutsideAngular(() => this.iniciar());
    });

    inject(DestroyRef).onDestroy(() => {
      this.destruido = true;
      this.observador?.disconnect();
      this.observador = null;
      this.escena?.destruir();
      this.escena = null;
    });
  }

  private async iniciar(): Promise<void> {
    try {
      const modulo = await this.cargar();
      if (this.destruido) return;
      const lienzo = this.lienzo().nativeElement;
      const escena = modulo.EscenaTienda.crear({
        canvas: lienzo,
        reducirMovimiento: preferirMenosMovimiento(),
        alElegirTienda: (codigo) => this.zona.run(() => this.tiendaElegida.emit(codigo)),
      });
      this.escena = escena;
      escena.fijarDatos({ planes: this.planes(), tiendas: this.tiendas() });
      escena.fijarMarca(this.marca());
      if (typeof ResizeObserver !== 'undefined') {
        this.observador = new ResizeObserver(() => this.escena?.redimensionar());
        this.observador.observe(lienzo);
      }
    } catch (error) {
      console.error('No se pudo crear la escena 3D de la portada', error);
      this.zona.run(() => this.sinEscena.emit());
    }
  }
}

function preferirMenosMovimiento(): boolean {
  try {
    return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}
