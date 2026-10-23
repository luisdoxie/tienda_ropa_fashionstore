import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';
import { fechaDesdeIso, fechaLocalIso } from './date-utils';
import { SIN_TOAST_ERROR } from './http-contexts';
import { FuncionPlan, MiSuscripcion } from './models/plan.models';

/** Permiso del administrador de la empresa: el único que puede leer `/mi-empresa`. */
export const PERMISO_MI_EMPRESA = 'empresa.gestionar';

/** Días de aviso antes del vencimiento. */
export const DIAS_AVISO_VENCIMIENTO = 7;

const MS_POR_DIA = 86_400_000;

/**
 * Plan y suscripción de la empresa de la sesión. Solo MUESTRA lo que decide el
 * backend: el web no bloquea nada por su cuenta.
 *
 * `GET /mi-empresa/suscripcion` lo puede leer solo el administrador de la
 * empresa. El resto del personal no conoce su plan: para ellos `incluye()` es
 * verdadero (no se deshabilita nada) y el aviso de suscripción aparece cuando
 * el backend rechaza una operación con `suscripcion_no_activa`
 * (`marcarBloqueada`).
 */
@Injectable({ providedIn: 'root' })
export class PlanService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);

  readonly suscripcion = signal<MiSuscripcion | null>(null);
  readonly cargando = signal(false);
  readonly error = signal(false);
  /** Estado que el backend informó en un 403 `suscripcion_no_activa`. */
  private readonly estadoBloqueado = signal<string | null>(null);

  readonly nombrePlan = computed(() => this.suscripcion()?.plan_nombre ?? null);
  readonly estado = computed<string | null>(() => this.estadoBloqueado() ?? this.suscripcion()?.estado ?? null);
  /** Verdadero mientras no se sepa lo contrario. */
  readonly estadoActivo = computed(() => {
    const estado = this.estado();
    return estado === null || estado === 'activa';
  });
  readonly fechaVencimiento = computed(() => this.suscripcion()?.fecha_vencimiento ?? null);
  /** Días que faltan para el vencimiento (negativo = ya venció); null si no se conoce. */
  readonly diasParaVencer = computed<number | null>(() => {
    const iso = this.fechaVencimiento();
    if (!iso) return null;
    const hoy = fechaDesdeIso(fechaLocalIso(new Date()));
    return Math.round((fechaDesdeIso(iso).getTime() - hoy.getTime()) / MS_POR_DIA);
  });

  constructor() {
    // Al cerrar sesión no queda nada de la empresa anterior.
    let teniaSesion = false;
    effect(() => {
      const tieneSesion = this.auth.estaAutenticado();
      if (teniaSesion && !tieneSesion) this.limpiar();
      teniaSesion = tieneSesion;
    });
  }

  /** ¿El plan incluye la funcionalidad? Sin datos del plan no se deshabilita nada. */
  incluye(funcion: FuncionPlan): boolean {
    const suscripcion = this.suscripcion();
    if (suscripcion === null) return true;
    return suscripcion.funcionalidades.includes(funcion);
  }

  /** Carga el plan si hace falta y la persona puede verlo. */
  cargar(): void {
    if (this.suscripcion() !== null || this.cargando()) return;
    this.refrescar();
  }

  /** Vuelve a pedir el plan (p. ej. tras un cambio de plan o un 403 de suscripción). */
  refrescar(): void {
    if (!this.puedeConsultar()) return;
    this.consultar().subscribe({ error: () => undefined });
  }

  /** Pide el plan y lo guarda; lo usa también "Mi empresa", que muestra el error. */
  consultar(): Observable<MiSuscripcion> {
    this.cargando.set(true);
    this.error.set(false);
    const context = new HttpContext().set(SIN_TOAST_ERROR, true);
    return this.http.get<MiSuscripcion>(`${environment.apiUrl}/mi-empresa/suscripcion`, { context }).pipe(
      tap({
        next: (suscripcion) => {
          this.suscripcion.set(suscripcion);
          this.estadoBloqueado.set(null);
          this.cargando.set(false);
        },
        error: () => {
          this.cargando.set(false);
          this.error.set(true);
        },
      }),
    );
  }

  /** El backend rechazó una operación por la suscripción (`estado` viene en el error). */
  marcarBloqueada(estado: string | null | undefined): void {
    this.estadoBloqueado.set(estado && estado !== 'activa' ? estado : 'vencida');
    this.refrescar();
  }

  limpiar(): void {
    this.suscripcion.set(null);
    this.estadoBloqueado.set(null);
    this.cargando.set(false);
    this.error.set(false);
  }

  private puedeConsultar(): boolean {
    return this.auth.estaAutenticado() && !this.auth.esSuperadmin() && this.auth.tienePermiso(PERMISO_MI_EMPRESA);
  }
}
