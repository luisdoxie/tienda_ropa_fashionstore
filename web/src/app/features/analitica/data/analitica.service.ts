import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import {
  AnomaliasRespuesta,
  DemandaRespuesta,
  EntrenarRespuesta,
  EstadoAnalitica,
  PanelAnalitico,
  ReposicionRespuesta,
  SegmentosRespuesta,
  TipoModeloAnalitico,
} from '../../../core/models/analitica.models';

/** Cada bloque de la pantalla explica su propio fallo (modelo sin entrenar, plan, rol): sin el toast global. */
const SIN_TOAST = () => new HttpContext().set(SIN_TOAST_ERROR, true);

/**
 * Acceso a `/analitica` (CU-24). Solo el plan con `analitica_ml` y solo el administrador de la empresa (sin sucursal
 * asignada); la empresa siempre sale del token. Límites del servidor: 30 consultas por minuto en las GET y 3 por minuto
 * en `entrenar`. No guarda estado ni nada en el navegador.
 */
@Injectable({ providedIn: 'root' })
export class AnaliticaService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/analitica`;

  /** Estado de cada modelo (vigente, desactualizado, sin entrenar...) y con qué datos se puede entrenar. */
  estado(): Observable<EstadoAnalitica> {
    return this.http.get<EstadoAnalitica>(`${this.base}/estado`, { context: SIN_TOAST() });
  }

  /**
   * Entrena en el momento (es síncrono: tarda unos segundos y no hay estado "entrenando"). Sin `tipos` entrena los 3
   * modelos. Un 409 `entrenamiento_en_curso` significa que otra persona ya lo está haciendo.
   */
  entrenar(tipos?: TipoModeloAnalitico[]): Observable<EntrenarRespuesta> {
    const cuerpo = tipos && tipos.length > 0 ? { tipos } : {};
    return this.http.post<EntrenarRespuesta>(`${this.base}/entrenar`, cuerpo, { context: SIN_TOAST() });
  }

  /** Demanda prevista de 1 a 12 semanas, de todas las categorías o de una. 409 `modelo_no_entrenado` si falta entrenar. */
  demanda(semanas = 4, categoriaId?: number | null): Observable<DemandaRespuesta> {
    let params = new HttpParams().set('semanas', semanas);
    if (categoriaId != null) params = params.set('categoria_id', categoriaId);
    return this.http.get<DemandaRespuesta>(`${this.base}/demanda`, { params, context: SIN_TOAST() });
  }

  segmentos(): Observable<SegmentosRespuesta> {
    return this.http.get<SegmentosRespuesta>(`${this.base}/segmentos`, { context: SIN_TOAST() });
  }

  /** Días de ventas inusuales de los últimos 7 a 365 días (por defecto 90). */
  anomalias(dias = 90): Observable<AnomaliasRespuesta> {
    const params = new HttpParams().set('dias', dias);
    return this.http.get<AnomaliasRespuesta>(`${this.base}/anomalias`, { params, context: SIN_TOAST() });
  }

  /** Categorías que se pueden agotar en las próximas 1 a 12 semanas. */
  reposicion(semanas = 4): Observable<ReposicionRespuesta> {
    const params = new HttpParams().set('semanas', semanas);
    return this.http.get<ReposicionRespuesta>(`${this.base}/reposicion`, { params, context: SIN_TOAST() });
  }

  /** Estado, cifras clave y los cuatro bloques en una sola llamada (un bloque es null si su modelo no está entrenado). */
  panel(): Observable<PanelAnalitico> {
    return this.http.get<PanelAnalitico>(`${this.base}/panel`, { context: SIN_TOAST() });
  }
}
