import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { EMPTY, Observable, defer, expand, map, reduce } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import {
  ConsultaBitacora,
  ConsultaBitacoraPlataforma,
  PaginaBitacora,
} from '../../../core/models/auditoria.models';
import { Usuario } from '../../../core/models/seguridad.models';

/** El backend limita `tamanio` a 100 (`parametros_paginacion`). */
export const TAMANIO_PAGINA_BITACORA = 20;
export const TAMANIO_MAXIMO_BITACORA = 100;

/** Tope de páginas al juntar a los usuarios de la empresa para el filtro. */
const PAGINAS_MAXIMAS_USUARIOS = 5;

/**
 * Acceso a la bitácora de auditoría: de solo lectura. El administrador de una
 * empresa usa `/bitacora`; el superadministrador, `/plataforma/bitacora`. Los
 * errores los muestra la propia pantalla (con "Reintentar"), por eso van sin el
 * toast rojo.
 *
 * `listar` NUNCA manda `empresa_id` ni `sin_empresa`: la empresa de una consulta
 * del administrador sale del token (el backend lo ignoraría de todos modos).
 */
@Injectable({ providedIn: 'root' })
export class BitacoraService {
  private readonly http = inject(HttpClient);
  private readonly contexto = () => new HttpContext().set(SIN_TOAST_ERROR, true);

  /** `GET /bitacora` (permiso `bitacora.ver`, administrador). */
  listar(consulta: ConsultaBitacora): Observable<PaginaBitacora> {
    return this.http.get<PaginaBitacora>(`${environment.apiUrl}/bitacora`, {
      params: this.parametros(consulta),
      context: this.contexto(),
    });
  }

  /** `GET /plataforma/bitacora` (superadministrador): con `empresa_id` o `sin_empresa`. */
  listarPlataforma(consulta: ConsultaBitacoraPlataforma): Observable<PaginaBitacora> {
    let params = this.parametros(consulta);
    if (consulta.empresa_id != null) params = params.set('empresa_id', consulta.empresa_id);
    if (consulta.sin_empresa) params = params.set('sin_empresa', true);
    return this.http.get<PaginaBitacora>(`${environment.apiUrl}/plataforma/bitacora`, {
      params,
      context: this.contexto(),
    });
  }

  /**
   * Quienes pueden aparecer en el filtro "Usuario": el personal de la empresa
   * (sin los clientes de la tienda, que serían miles). Usa `GET /usuarios`,
   * que exige `usuarios.gestionar`; hasta 500 usuarios.
   */
  listarPersonal(): Observable<Usuario[]> {
    return defer(() => {
      let siguiente = 1;
      const pagina = (n: number) =>
        this.http.get<Usuario[]>(`${environment.apiUrl}/usuarios`, {
          params: new HttpParams().set('pagina', n).set('tamanio', TAMANIO_MAXIMO_BITACORA),
          context: this.contexto(),
        });
      return pagina(siguiente).pipe(
        expand((lote) =>
          lote.length === TAMANIO_MAXIMO_BITACORA && siguiente < PAGINAS_MAXIMAS_USUARIOS ? pagina(++siguiente) : EMPTY,
        ),
        reduce((todos, lote) => todos.concat(lote), [] as Usuario[]),
        map((usuarios) => usuarios.filter((u) => !esSoloCliente(u))),
      );
    });
  }

  private parametros(consulta: ConsultaBitacora): HttpParams {
    let params = new HttpParams()
      .set('desde', consulta.desde)
      .set('hasta', consulta.hasta)
      .set('pagina', consulta.pagina ?? 1)
      .set('tamanio', consulta.tamanio ?? TAMANIO_PAGINA_BITACORA);
    if (consulta.entidad) params = params.set('entidad', consulta.entidad);
    if (consulta.accion) params = params.set('accion', consulta.accion);
    if (consulta.usuario_id != null) params = params.set('usuario_id', consulta.usuario_id);
    return params;
  }
}

function esSoloCliente(usuario: Usuario): boolean {
  return usuario.roles.length > 0 && usuario.roles.every((rol) => rol === 'cliente');
}
