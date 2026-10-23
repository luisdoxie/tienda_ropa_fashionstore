import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, map, of, switchMap } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { ProductoImagenLookupItem } from '../../../core/models/catalogo.models';
import { Carrito, CarritoLinea, CarritoResumen } from '../../../core/models/ventas.models';

/**
 * Estado del carrito del cliente logueado, con signals (mismo patrón que
 * `AuthService`). El backend no devuelve nombre/foto/talla/color de cada
 * línea -- se resuelven en un solo lookup batch después de cada mutación,
 * igual que hace `carrito_controller.dart` en Flutter.
 */
@Injectable({ providedIn: 'root' })
export class CarritoService {
  private readonly http = inject(HttpClient);

  private readonly lineasState = signal<CarritoLinea[]>([]);
  readonly lineas = this.lineasState.asReadonly();
  readonly cantidadLineas = computed(() => this.lineasState().length);

  // Importes del carrito con las promociones aplicadas (los muestran el carrito y
  // los pasos de entrega y pago). `refrescarResumen()` los vuelve a pedir.
  private readonly resumenState = signal<CarritoResumen | null>(null);
  private readonly calculandoResumenState = signal(false);
  readonly resumen = this.resumenState.asReadonly();
  readonly calculandoResumen = this.calculandoResumenState.asReadonly();

  cargar(): Observable<CarritoLinea[]> {
    return this.http.get<Carrito>(`${environment.apiUrl}/carrito`).pipe(switchMap((carrito) => this.resolver(carrito)));
  }

  agregar(varianteId: number, cantidad = 1): Observable<CarritoLinea[]> {
    return this.http
      .post<Carrito>(`${environment.apiUrl}/carrito`, { variante_id: varianteId, cantidad })
      .pipe(switchMap((carrito) => this.resolver(carrito)));
  }

  actualizarCantidad(varianteId: number, cantidad: number): Observable<CarritoLinea[]> {
    return this.http
      .put<Carrito>(`${environment.apiUrl}/carrito/${varianteId}`, { cantidad })
      .pipe(switchMap((carrito) => this.resolver(carrito)));
  }

  quitar(varianteId: number): Observable<CarritoLinea[]> {
    return this.http
      .delete<Carrito>(`${environment.apiUrl}/carrito/${varianteId}`)
      .pipe(switchMap((carrito) => this.resolver(carrito)));
  }

  /**
   * Pide los importes (POST /carrito/aplicar-promocion). Con el carrito vacío no
   * pide nada: no hay qué calcular. Si falla, el resumen queda en null.
   */
  refrescarResumen(): void {
    if (this.lineasState().length === 0) {
      this.resumenState.set(null);
      this.calculandoResumenState.set(false);
      return;
    }
    this.calculandoResumenState.set(true);
    this.http.post<CarritoResumen>(`${environment.apiUrl}/carrito/aplicar-promocion`, {}).subscribe({
      next: (resumen) => {
        this.resumenState.set(resumen);
        this.calculandoResumenState.set(false);
      },
      error: () => {
        this.resumenState.set(null);
        this.calculandoResumenState.set(false);
      },
    });
  }

  limpiar(): void {
    this.lineasState.set([]);
    this.resumenState.set(null);
    this.calculandoResumenState.set(false);
  }

  private resolver(carrito: Carrito): Observable<CarritoLinea[]> {
    if (carrito.detalle.length === 0) {
      this.lineasState.set([]);
      return of([]);
    }

    const params = new HttpParams().set('variante_ids', carrito.detalle.map((d) => d.variante_id).join(','));
    return this.http
      .get<ProductoImagenLookupItem[]>(`${environment.apiUrl}/catalogo/variantes/detalle`, { params })
      .pipe(
        map((lookup) => {
          const porVariante = new Map(lookup.map((item) => [item.variante_id, item]));
          const lineas: CarritoLinea[] = carrito.detalle.map((linea) => {
            const item = porVariante.get(linea.variante_id);
            return {
              ...linea,
              productoNombre: item?.producto_nombre,
              imagenPrincipal: item?.imagen_principal,
              tallaCodigo: item?.talla_codigo,
              colorNombre: item?.color_nombre,
            };
          });
          this.lineasState.set(lineas);
          return lineas;
        }),
      );
  }
}
