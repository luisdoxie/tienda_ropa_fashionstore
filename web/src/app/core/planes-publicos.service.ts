import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { environment } from '../../environments/environment';
import { SIN_TOAST_ERROR } from './http-contexts';
import { PlanPublico } from './models/plan.models';

/**
 * Planes que ofrece la plataforma (`GET /public/planes`, sin token): la portada los compara. No hay
 * textos de respaldo: si la petición falla, la pantalla lo dice y ofrece reintentar.
 */
@Injectable({ providedIn: 'root' })
export class PlanesPublicosService {
  private readonly http = inject(HttpClient);
  private peticion?: Subscription;

  /** Ya vienen ordenados por cantidad de sucursales, de menor a mayor. */
  readonly planes = signal<PlanPublico[]>([]);
  readonly cargando = signal(false);
  readonly error = signal(false);

  /** Pide los planes (también sirve para reintentar). Una petición nueva cancela la anterior. */
  cargar(): void {
    this.peticion?.unsubscribe();
    this.cargando.set(true);
    this.error.set(false);
    // Sin toast: el error se muestra en la propia pantalla, con "Reintentar".
    const context = new HttpContext().set(SIN_TOAST_ERROR, true);
    this.peticion = this.http.get<PlanPublico[]>(`${environment.apiUrl}/public/planes`, { context }).subscribe({
      next: (planes) => {
        this.planes.set(planes);
        this.cargando.set(false);
      },
      error: () => {
        this.planes.set([]);
        this.cargando.set(false);
        this.error.set(true);
      },
    });
  }
}
