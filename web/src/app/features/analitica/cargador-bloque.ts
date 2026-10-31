import { DestroyRef, inject, signal } from '@angular/core';
import { Observable, Subscription } from 'rxjs';
import { FaseBloque } from './bloque-analitica.component';
import { ErrorAnalitica, clasificarError } from './errores-analitica';

export type BloqueoServidor = 'plan' | 'alcance';

/**
 * El estado de carga de UN bloque: fase, datos y mensaje en signals propios, así un fallo no tapa a los demás. Una
 * consulta nueva cancela la anterior (la respuesta vieja nunca pisa a la nueva) y todo se cancela al destruir el
 * componente. Se crea en el inicializador de un campo (necesita el contexto de inyección).
 */
export class CargadorBloque<T> {
  readonly fase = signal<FaseBloque>('inactivo');
  readonly datos = signal<T | null>(null);
  readonly mensaje = signal<string | null>(null);
  private suscripcion: Subscription | null = null;

  constructor(
    /** El servidor dijo que el plan o el rol no permiten la analítica: toda la pantalla lo explica. */
    private readonly alBloquear: (motivo: BloqueoServidor) => void,
    /** Cada vez que cambian los datos del bloque (null = ya no hay). */
    private readonly alCambiar?: (datos: T | null) => void,
  ) {
    inject(DestroyRef).onDestroy(() => this.suscripcion?.unsubscribe());
  }

  cargar(origen: Observable<T>): void {
    this.suscripcion?.unsubscribe();
    this.fase.set('cargando');
    this.mensaje.set(null);
    this.suscripcion = origen.subscribe({
      next: (datos) => {
        this.datos.set(datos);
        this.fase.set('listo');
        this.alCambiar?.(datos);
      },
      error: (error: unknown) => this.fallar(clasificarError(error)),
    });
  }

  /** Deja de esperar (cambió el plan, el rol o la conexión). Lo ya cargado se queda a la vista. */
  detener(): void {
    this.suscripcion?.unsubscribe();
    this.suscripcion = null;
    if (this.fase() === 'cargando') this.fase.set(this.datos() === null ? 'inactivo' : 'listo');
  }

  private fallar(error: ErrorAnalitica): void {
    this.datos.set(null);
    this.alCambiar?.(null);
    this.mensaje.set(error.mensaje);
    switch (error.clase) {
      case 'plan':
      case 'alcance':
        this.fase.set('inactivo');
        this.alBloquear(error.clase);
        break;
      case 'sin_modelo':
        this.fase.set('sin_modelo');
        break;
      case 'obsoleto':
        this.fase.set('obsoleto');
        break;
      case 'en_curso':
        this.fase.set('en_curso');
        break;
      case 'limite':
        this.fase.set('limite');
        break;
      default:
        this.fase.set('error');
    }
  }
}
