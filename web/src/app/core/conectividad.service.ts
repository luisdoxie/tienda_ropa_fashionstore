import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { SwUpdate } from '@angular/service-worker';
import { Observable, Subject } from 'rxjs';
import { environment } from '../../environments/environment';

export type EstadoConexion = 'en_linea' | 'sin_conexion' | 'servidor_no_responde';

/** Cuánto espera `verificarServidor` al servidor antes de darlo por caído. */
export const TIMEOUT_VERIFICACION_MS = 4_000;

/**
 * Estado de la conexión de la app (PWA, E13).
 *
 * - `enLinea`: lo que dice el navegador (`navigator.onLine` y los eventos `online`/`offline`).
 * - `servidorAlcanzable`: resultado de la última prueba a `/health` (`null` = aún no se probó).
 * - `estado`: `sin_conexion` si el navegador no tiene red; `servidor_no_responde` si tiene red
 *   pero la última prueba falló; `en_linea` en cualquier otro caso.
 *
 * Solo se prueba el servidor al volver la red (evento `online`), al reintentar a mano
 * (`verificarServidor`) y al abrir la app instalada. NO hay sondeo continuo: gastaría datos y
 * `/health` toca la base. Tampoco usa `HttpClient`: así la prueba no pasa por los interceptores
 * ni genera el toast de error.
 */
@Injectable({ providedIn: 'root' })
export class ConectividadService {
  private readonly _enLinea = signal(this.navegadorEnLinea());
  private readonly _servidorAlcanzable = signal<boolean | null>(null);
  private readonly _desde = signal<Date | null>(null);
  private readonly _volvioConexion = new Subject<void>();

  /** Hubo un periodo sin conexión o sin servidor del que todavía no se confirmó la recuperación. */
  private pendienteDeRecuperar = false;
  private verificacionEnCurso: Promise<boolean> | null = null;

  readonly enLinea = this._enLinea.asReadonly();
  readonly servidorAlcanzable = this._servidorAlcanzable.asReadonly();
  /** Desde cuándo está en el estado actual (`null` si es el de la apertura y no cambió). */
  readonly desde = this._desde.asReadonly();
  readonly estado = computed<EstadoConexion>(() => {
    if (!this._enLinea()) return 'sin_conexion';
    if (this._servidorAlcanzable() === false) return 'servidor_no_responde';
    return 'en_linea';
  });
  /** Emite al pasar de sin conexión (o servidor caído) a en línea CONFIRMADO por `/health`. */
  readonly volvioConexion$: Observable<void> = this._volvioConexion.asObservable();

  constructor() {
    if (typeof window !== 'undefined') {
      const alVolverLaRed = () => {
        this.aplicar(true, null);
        void this.verificarServidor();
      };
      const alPerderLaRed = () => this.aplicar(false, null);
      window.addEventListener('online', alVolverLaRed);
      window.addEventListener('offline', alPerderLaRed);
      inject(DestroyRef).onDestroy(() => {
        window.removeEventListener('online', alVolverLaRed);
        window.removeEventListener('offline', alPerderLaRed);
      });
    }

    if (!this._enLinea()) {
      this._desde.set(new Date());
      this.pendienteDeRecuperar = true;
    }

    // Al abrir la app instalada (solo existe con Service Worker: compilación optimizada).
    if (inject(SwUpdate, { optional: true })?.isEnabled) {
      void this.verificarServidor();
    }
  }

  /**
   * Pregunta a `/health` si el servidor responde. Nunca lanza: devuelve `false` si falla, si
   * contesta con error o si no contesta en 4 s. Una respuesta correcta también prueba que hay
   * red, aunque el navegador diga lo contrario. Varias llamadas a la vez comparten la prueba.
   */
  verificarServidor(): Promise<boolean> {
    this.verificacionEnCurso ??= this.probarServidor().finally(() => (this.verificacionEnCurso = null));
    return this.verificacionEnCurso;
  }

  private async probarServidor(): Promise<boolean> {
    const controlador = new AbortController();
    const temporizador = setTimeout(() => controlador.abort(), TIMEOUT_VERIFICACION_MS);
    let responde = false;
    try {
      const respuesta = await fetch(urlSalud(), { cache: 'no-store', signal: controlador.signal });
      responde = respuesta.ok;
    } catch {
      responde = false;
    } finally {
      clearTimeout(temporizador);
    }

    if (responde) {
      this.aplicar(true, true);
      if (this.pendienteDeRecuperar) {
        this.pendienteDeRecuperar = false;
        this._volvioConexion.next();
      }
    } else {
      // Si el navegador dice que no hay red, el estado sigue siendo sin_conexion (tiene prioridad).
      this.aplicar(this._enLinea(), false);
    }
    return responde;
  }

  private aplicar(enLinea: boolean, servidorAlcanzable: boolean | null): void {
    const antes = this.estado();
    this._enLinea.set(enLinea);
    this._servidorAlcanzable.set(servidorAlcanzable);
    const despues = this.estado();
    if (despues !== antes) this._desde.set(new Date());
    if (despues !== 'en_linea') this.pendienteDeRecuperar = true;
  }

  private navegadorEnLinea(): boolean {
    return typeof navigator === 'undefined' || navigator.onLine !== false;
  }
}

/** `/health` vive en el origen del servidor (no bajo `/api/v1`); `ngsw-bypass` evita el Service Worker. */
function urlSalud(): string {
  return `${new URL(environment.apiUrl).origin}/health?ngsw-bypass=true`;
}
