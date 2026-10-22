import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, forkJoin, map, of } from 'rxjs';
import { Disponibilidad } from '../../../core/models/inventario.models';
import { Sucursal } from '../../../core/models/organizacion.models';
import { TiendaActualService } from '../state/tienda-actual.service';

/**
 * No hay un endpoint de backend para "sucursales con stock de varias
 * variantes a la vez" -- ver GET /inventario/disponibilidad, que solo
 * acepta un variante_id por llamada. Se replica acá el mismo patrón que ya
 * usa Flutter (`sucursalesConStockCarritoProvider`): una llamada por línea
 * en paralelo + intersección de sucursales.
 */
@Injectable({ providedIn: 'root' })
export class DisponibilidadService {
  private readonly http = inject(HttpClient);
  private readonly tienda = inject(TiendaActualService);

  porVariante(varianteId: number): Observable<Disponibilidad[]> {
    return this.http.get<Disponibilidad[]>(this.tienda.urlPublica('inventario/disponibilidad'), {
      params: { variante_id: varianteId },
    });
  }

  sucursales(): Observable<Sucursal[]> {
    return this.http.get<Sucursal[]>(this.tienda.urlPublica('sucursales'), { params: { tamanio: 100 } });
  }

  /** Sucursales donde hay stock >= cantidad para TODAS las líneas dadas. */
  sucursalesConStock(lineas: { varianteId: number; cantidad: number }[]): Observable<Sucursal[]> {
    if (lineas.length === 0) {
      return of([]);
    }

    return forkJoin({
      sucursales: this.sucursales(),
      disponibilidades: forkJoin(lineas.map((linea) => this.porVariante(linea.varianteId))),
    }).pipe(
      map(({ sucursales, disponibilidades }) => {
        const idsPorLinea = disponibilidades.map((filas, indice) => {
          const cantidadRequerida = lineas[indice].cantidad;
          return new Set(
            filas.filter((fila) => fila.cantidad_disponible >= cantidadRequerida).map((fila) => fila.sucursal_id),
          );
        });
        const interseccion = idsPorLinea.reduce(
          (acumulado, ids) => new Set([...acumulado].filter((id) => ids.has(id))),
        );
        return sucursales.filter((sucursal) => interseccion.has(sucursal.id));
      }),
    );
  }
}
