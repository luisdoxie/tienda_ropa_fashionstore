import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map, of } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { ProductoImagenLookupItem } from '../../../core/models/catalogo.models';
import { Sucursal } from '../../../core/models/organizacion.models';
import { Usuario } from '../../../core/models/seguridad.models';
import {
  ConsultaOperacionesSync,
  OperacionSyncDetalle,
  OperacionSyncPagina,
  ResolverOperacionEntrada,
} from '../../../core/models/sincronizacion.models';

/** Lo hace el propio componente: sus errores se explican en pantalla, sin el toast global. */
const SIN_TOAST = () => new HttpContext().set(SIN_TOAST_ERROR, true);

/**
 * Acceso a `/sincronizacion/operaciones` para quien supervisa (permiso `sincronizacion.supervisar`) y resuelve
 * conflictos (`sincronizacion.resolver`). No guarda estado: cada pantalla decide qué conserva. Nada borra una operación.
 */
@Injectable({ providedIn: 'root' })
export class SincronizacionAdminService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/sincronizacion`;

  /** Una página de operaciones (el servidor pagina y filtra; un filtro vacío no se envía). */
  listar(consulta: ConsultaOperacionesSync = {}, silencioso = false): Observable<OperacionSyncPagina> {
    let params = new HttpParams().set('pagina', consulta.pagina ?? 1).set('tamanio', consulta.tamanio ?? 20);
    if (consulta.estado) params = params.set('estado', consulta.estado);
    if (consulta.tipo) params = params.set('tipo', consulta.tipo);
    if (consulta.sucursal_id != null) params = params.set('sucursal_id', consulta.sucursal_id);
    if (consulta.usuario_id != null) params = params.set('usuario_id', consulta.usuario_id);
    if (consulta.desde) params = params.set('desde', consulta.desde);
    if (consulta.hasta) params = params.set('hasta', consulta.hasta);
    return this.http.get<OperacionSyncPagina>(`${this.base}/operaciones`, {
      params,
      ...(silencioso ? { context: SIN_TOAST() } : {}),
    });
  }

  /** Cuántas operaciones esperan una decisión (solo el total: se pide una fila). */
  contarConflictos(): Observable<number> {
    return this.listar({ estado: 'en_conflicto', pagina: 1, tamanio: 1 }, true).pipe(map((pagina) => pagina.total));
  }

  /** El detalle con el `payload` que mandó el dispositivo. */
  obtener(operacionId: string, silencioso = false): Observable<OperacionSyncDetalle> {
    return this.http.get<OperacionSyncDetalle>(`${this.base}/operaciones/${operacionId}`, {
      ...(silencioso ? { context: SIN_TOAST() } : {}),
    });
  }

  /**
   * `forzar` (solo ventas) o `rechazar`. Sus errores (409 "otra persona ya la resolvió", 404) los explica la pantalla:
   * por eso no pasan por el toast global.
   */
  resolver(operacionId: string, entrada: ResolverOperacionEntrada): Observable<OperacionSyncDetalle> {
    return this.http.post<OperacionSyncDetalle>(`${this.base}/operaciones/${operacionId}/resolver`, entrada, {
      context: SIN_TOAST(),
    });
  }

  // ---- Apoyo para mostrar nombres (si fallan, la pantalla muestra "Sucursal n.º 3" y sigue) -----------------------

  sucursales(): Observable<Sucursal[]> {
    const params = new HttpParams().set('pagina', 1).set('tamanio', 100);
    return this.http.get<Sucursal[]>(`${environment.apiUrl}/sucursales`, { params, context: SIN_TOAST() });
  }

  /** Solo quien gestiona usuarios puede listarlos: los demás no ven el filtro por usuario. */
  usuarios(): Observable<Usuario[]> {
    const params = new HttpParams().set('pagina', 1).set('tamanio', 100);
    return this.http.get<Usuario[]>(`${environment.apiUrl}/usuarios`, { params, context: SIN_TOAST() });
  }

  /** Producto, talla y color de cada variante (`GET /catalogo/variantes/detalle`). */
  detallesDeVariantes(ids: number[]): Observable<ProductoImagenLookupItem[]> {
    const unicos = [...new Set(ids)];
    if (unicos.length === 0) return of([]);
    const params = new HttpParams().set('variante_ids', unicos.join(','));
    return this.http.get<ProductoImagenLookupItem[]>(`${environment.apiUrl}/catalogo/variantes/detalle`, {
      params,
      context: SIN_TOAST(),
    });
  }
}
