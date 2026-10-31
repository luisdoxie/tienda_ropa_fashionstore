import { HttpClient, HttpContext, HttpParams, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { CopiaDescargada, CopiaPagina, CopiaTablas } from '../../../core/models/copias.models';
import { nombreDeContentDisposition } from '../../reportes-ia/data/reportes-ia.service';

/** La pantalla explica sus propios fallos (plan, rol, límite, red): sin el toast global. */
const SIN_TOAST = () => new HttpContext().set(SIN_TOAST_ERROR, true);

const SHA256_HEX = /^[0-9a-fA-F]{64}$/;

function dosDigitos(n: number): string {
  return String(n).padStart(2, '0');
}

/** Respaldo si el servidor no manda `Content-Disposition`: `fashionstore-copia-AAAAMMDD-HHMM.zip` (hora local). */
function nombrePorDefecto(ahora = new Date()): string {
  const fecha = `${ahora.getFullYear()}${dosDigitos(ahora.getMonth() + 1)}${dosDigitos(ahora.getDate())}`;
  return `fashionstore-copia-${fecha}-${dosDigitos(ahora.getHours())}${dosDigitos(ahora.getMinutes())}.zip`;
}

/**
 * Acceso a `/copias-seguridad` (E22). Solo el administrador de la empresa y un plan con `copias_seguridad`. La copia NO se
 * guarda en el servidor: `crear` la entrega en la misma respuesta y no existe "descargar de nuevo". No guarda nada en el
 * navegador.
 */
@Injectable({ providedIn: 'root' })
export class CopiasSeguridadService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/copias-seguridad`;

  /**
   * Crea la copia y devuelve el ZIP. Tarda de unos segundos a cerca de un minuto, por eso no lleva tiempo límite propio
   * (el servidor corta con 504 `copia_tiempo_agotado`). Los errores llegan con el cuerpo como `Blob`: se leen con
   * `leerErrorBlob`.
   */
  crear(): Observable<CopiaDescargada> {
    return this.http
      .post(this.base, null, { observe: 'response', responseType: 'blob', context: SIN_TOAST() })
      .pipe(map((respuesta) => this.aCopia(respuesta)));
  }

  /** Historial visible (el plan limita cuántas copias se conservan), la más reciente primero. */
  listar(pagina = 1, tamanio = 20): Observable<CopiaPagina> {
    const params = new HttpParams().set('pagina', pagina).set('tamanio', tamanio);
    return this.http.get<CopiaPagina>(this.base, { params, context: SIN_TOAST() });
  }

  /** Qué tablas y columnas incluye la copia y cuáles no. */
  tablas(): Observable<CopiaTablas> {
    return this.http.get<CopiaTablas>(`${this.base}/tablas`, { context: SIN_TOAST() });
  }

  private aCopia(respuesta: HttpResponse<Blob>): CopiaDescargada {
    const id = Number.parseInt(respuesta.headers.get('X-Copia-Id') ?? '', 10);
    const checksum = (respuesta.headers.get('X-Checksum-SHA256') ?? '').trim();
    return {
      blob: respuesta.body ?? new Blob(),
      nombre: nombreDeContentDisposition(respuesta.headers.get('Content-Disposition')) ?? nombrePorDefecto(),
      copiaId: Number.isFinite(id) ? id : null,
      checksum: SHA256_HEX.test(checksum) ? checksum.toLowerCase() : null,
    };
  }
}
