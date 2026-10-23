import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { MiEmpresa, MiEmpresaActualizar } from '../../../core/models/plan.models';

/**
 * Identidad de la empresa de la sesión (`/mi-empresa`). El plan y la suscripción
 * los trae `PlanService`. Los errores se muestran en la propia pantalla, por eso
 * las dos peticiones van sin el toast rojo.
 */
@Injectable({ providedIn: 'root' })
export class MiEmpresaService {
  private readonly http = inject(HttpClient);

  private readonly url = `${environment.apiUrl}/mi-empresa`;

  obtener(): Observable<MiEmpresa> {
    return this.http.get<MiEmpresa>(this.url, { context: new HttpContext().set(SIN_TOAST_ERROR, true) });
  }

  /** Solo identidad visual: nombre, logo y color de acento (`null` los quita). */
  actualizar(datos: MiEmpresaActualizar): Observable<MiEmpresa> {
    return this.http.put<MiEmpresa>(this.url, datos, { context: new HttpContext().set(SIN_TOAST_ERROR, true) });
  }
}
