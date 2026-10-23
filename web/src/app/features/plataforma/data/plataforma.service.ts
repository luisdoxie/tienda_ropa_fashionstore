import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { EMPTY, Observable, expand, reduce } from 'rxjs';
import { environment } from '../../../../environments/environment';
import {
  ConsultaEmpresas,
  ConsultaSuscripciones,
  EmpresaActualizar,
  EmpresaPlataforma,
  EmpresaRegistrar,
  EmpresaResumen,
  EstadoSuscripcionPedido,
  PlanPlataforma,
  PlanPlataformaActualizar,
  SuscripcionAsignar,
  SuscripcionPlataforma,
} from '../../../core/models/plataforma.models';

/** El backend limita `tamanio` a 100 (`parametros_paginacion`). */
export const TAMANIO_MAXIMO = 100;

/** Tope de páginas al juntar listas completas (empresas para el selector). */
const PAGINAS_MAXIMAS = 20;

/**
 * Acceso a `/plataforma/*` (solo superadministrador, permiso `plataforma.gestionar`).
 * No guarda estado: cada pantalla decide qué conserva. Nunca recibe ni
 * conserva la clave inicial de un administrador más allá de la petición.
 */
@Injectable({ providedIn: 'root' })
export class PlataformaService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/plataforma`;

  // ---- Planes ---------------------------------------------------------------

  listarPlanes(pagina = 1, tamanio = TAMANIO_MAXIMO): Observable<PlanPlataforma[]> {
    const params = new HttpParams().set('pagina', pagina).set('tamanio', tamanio);
    return this.http.get<PlanPlataforma[]>(`${this.base}/planes`, { params });
  }

  actualizarPlan(id: number, cambios: PlanPlataformaActualizar): Observable<PlanPlataforma> {
    return this.http.put<PlanPlataforma>(`${this.base}/planes/${id}`, cambios);
  }

  // ---- Empresas -------------------------------------------------------------

  listarEmpresas(consulta: ConsultaEmpresas = {}): Observable<EmpresaPlataforma[]> {
    let params = new HttpParams();
    const q = consulta.q?.trim();
    if (q) params = params.set('q', q);
    if (consulta.activo !== undefined) params = params.set('activo', consulta.activo);
    params = params.set('pagina', consulta.pagina ?? 1).set('tamanio', consulta.tamanio ?? 20);
    return this.http.get<EmpresaPlataforma[]>(`${this.base}/empresas`, { params });
  }

  /** Todas las empresas (para selectores y para mostrar el nombre de una suscripción). */
  listarTodasEmpresas(): Observable<EmpresaPlataforma[]> {
    const pagina = (n: number) => this.listarEmpresas({ pagina: n, tamanio: TAMANIO_MAXIMO });
    let siguiente = 1;
    return pagina(siguiente).pipe(
      expand((lote) => (lote.length === TAMANIO_MAXIMO && siguiente < PAGINAS_MAXIMAS ? pagina(++siguiente) : EMPTY)),
      reduce((todas, lote) => todas.concat(lote), [] as EmpresaPlataforma[]),
    );
  }

  resumenEmpresa(id: number): Observable<EmpresaResumen> {
    return this.http.get<EmpresaResumen>(`${this.base}/empresas/${id}/resumen`);
  }

  registrarEmpresa(datos: EmpresaRegistrar): Observable<EmpresaPlataforma> {
    return this.http.post<EmpresaPlataforma>(`${this.base}/empresas`, datos);
  }

  actualizarEmpresa(id: number, cambios: EmpresaActualizar): Observable<EmpresaPlataforma> {
    return this.http.put<EmpresaPlataforma>(`${this.base}/empresas/${id}`, cambios);
  }

  // ---- Suscripciones --------------------------------------------------------

  listarSuscripciones(consulta: ConsultaSuscripciones = {}): Observable<SuscripcionPlataforma[]> {
    let params = new HttpParams();
    if (consulta.empresa_id !== undefined) params = params.set('empresa_id', consulta.empresa_id);
    if (consulta.estado !== undefined) params = params.set('estado', consulta.estado);
    params = params.set('pagina', consulta.pagina ?? 1).set('tamanio', consulta.tamanio ?? 20);
    return this.http.get<SuscripcionPlataforma[]>(`${this.base}/suscripciones`, { params });
  }

  /** Todas las suscripciones de una empresa, cerradas incluidas (historial). */
  historialDeEmpresa(empresaId: number): Observable<SuscripcionPlataforma[]> {
    return this.listarSuscripciones({ empresa_id: empresaId, pagina: 1, tamanio: TAMANIO_MAXIMO });
  }

  /** Asigna un plan o cambia el vigente (el backend cierra la anterior y crea otra). */
  asignarPlan(datos: SuscripcionAsignar): Observable<SuscripcionPlataforma> {
    return this.http.post<SuscripcionPlataforma>(`${this.base}/suscripciones`, datos);
  }

  renovar(id: number, fechaVencimiento: string): Observable<SuscripcionPlataforma> {
    return this.http.put<SuscripcionPlataforma>(`${this.base}/suscripciones/${id}/renovar`, {
      fecha_vencimiento: fechaVencimiento,
    });
  }

  cambiarEstado(id: number, estado: EstadoSuscripcionPedido): Observable<SuscripcionPlataforma> {
    return this.http.put<SuscripcionPlataforma>(`${this.base}/suscripciones/${id}/estado`, { estado });
  }
}
