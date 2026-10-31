import { HttpClient, HttpContext, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import {
  ArchivoDescargado,
  EntradaEjecutarReporte,
  EntradaExportarReporte,
  FormatoExportacion,
  ReporteCatalogo,
  ReporteGenerativoRespuesta,
} from '../../../core/models/reportes-ia.models';

/** Las pantallas de reportes explican sus propios fallos (plan, límite de consultas, red): sin el toast global. */
const SIN_TOAST = () => new HttpContext().set(SIN_TOAST_ERROR, true);

const EXTENSION: Record<FormatoExportacion, string> = { xlsx: 'xlsx', pdf: 'pdf' };

/** Deja solo caracteres seguros: el nombre lo sugiere el servidor, pero nunca se usa tal cual como ruta. */
function nombreSeguro(nombre: string): string {
  return nombre.replace(/[^A-Za-z0-9._-]/g, '_').replace(/^\.+/, '');
}

/** Saca el nombre de `Content-Disposition` (`filename*=UTF-8''...` o `filename="..."`); null si no viene. */
export function nombreDeContentDisposition(cabecera: string | null): string | null {
  if (!cabecera) return null;
  const extendido = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(cabecera);
  if (extendido) {
    try {
      const nombre = nombreSeguro(decodeURIComponent(extendido[1].trim()));
      if (nombre) return nombre;
    } catch {
      // Cae al nombre simple.
    }
  }
  const simple = /filename\s*=\s*"?([^";]+)"?/.exec(cabecera);
  const nombre = simple ? nombreSeguro(simple[1].trim()) : '';
  return nombre || null;
}

/**
 * Acceso a `/reportes-ia` (CU-23): el catálogo del plan, la ejecución de un reporte y su exportación a Excel o PDF.
 * No guarda estado y no conserva el texto de las consultas ni los resultados. La IA solo traduce a una solicitud; el
 * web nunca arma consultas.
 */
@Injectable({ providedIn: 'root' })
export class ReportesIaService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/reportes-ia`;

  /** Los reportes que el plan de la empresa permite, con sus filtros, columnas y ejemplos. */
  catalogo(): Observable<ReporteCatalogo[]> {
    return this.http.get<ReporteCatalogo[]>(`${this.base}/catalogo`, { context: SIN_TOAST() });
  }

  /**
   * Interpreta la frase (o usa la solicitud ya armada) y ejecuta el reporte en una sola llamada. Con `solicitud` no
   * interviene la IA: es lo que usa "Actualizar reporte" tras editar los filtros.
   */
  ejecutar(entrada: EntradaEjecutarReporte): Observable<ReporteGenerativoRespuesta> {
    return this.http.post<ReporteGenerativoRespuesta>(`${this.base}/ejecutar`, entrada, { context: SIN_TOAST() });
  }

  /**
   * Descarga el reporte como `.xlsx` o `.pdf`. Un estado que no es `ok` responde 422 `reporte_no_exportable`: la
   * pantalla lo lee con `leerErrorBlob`.
   */
  exportar(entrada: EntradaExportarReporte): Observable<ArchivoDescargado> {
    return this.http
      .post(`${this.base}/exportar`, entrada, { observe: 'response', responseType: 'blob', context: SIN_TOAST() })
      .pipe(map((respuesta) => this.aArchivo(respuesta, entrada)));
  }

  private aArchivo(respuesta: HttpResponse<Blob>, entrada: EntradaExportarReporte): ArchivoDescargado {
    const sugerido = nombreDeContentDisposition(respuesta.headers.get('Content-Disposition'));
    const tipo = entrada.resuelta?.tipo_reporte ?? entrada.solicitud?.tipo_reporte ?? 'ia';
    const fecha = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const nombre = sugerido ?? `reporte-${nombreSeguro(tipo)}-${fecha}.${EXTENSION[entrada.formato]}`;
    return { blob: respuesta.body ?? new Blob(), nombre };
  }
}
