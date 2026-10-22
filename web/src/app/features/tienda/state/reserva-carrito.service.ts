import { Injectable, computed, signal } from '@angular/core';

export interface ItemReservaTemporal {
  varianteId: number;
  productoNombre: string;
  tallaCodigo: string;
  colorNombre: string;
  imagenPrincipal: string | null;
}

/**
 * Carrito de "quiero probarme esto en tienda", efímero -- se pierde al
 * recargar la página, igual que `carrito_reserva_controller.dart` en
 * Flutter (mismo criterio: es distinto del carrito de compra, que sí
 * persiste en el backend).
 *
 * Los ítems se guardan POR TIENDA (código de la empresa): volver a otra tienda
 * no mezcla ni pierde lo que se había elegido en la anterior. `lista()` y
 * `cantidad()` leen siempre la tienda actual (`cambiarTienda`).
 */
@Injectable({ providedIn: 'root' })
export class ReservaCarritoService {
  private readonly porTienda = signal<Record<string, ItemReservaTemporal[]>>({});
  private readonly codigoActual = signal<string | null>(null);

  readonly lista = computed(() => {
    const codigo = this.codigoActual();
    return codigo === null ? [] : (this.porTienda()[codigo] ?? []);
  });
  readonly cantidad = computed(() => this.lista().length);

  /** Apunta el servicio a otra tienda (null = ninguna). No borra lo de las demás. */
  cambiarTienda(codigo: string | null): void {
    this.codigoActual.set(codigo);
  }

  contiene(varianteId: number): boolean {
    return this.lista().some((item) => item.varianteId === varianteId);
  }

  agregar(item: ItemReservaTemporal): void {
    if (this.contiene(item.varianteId)) return;
    this.actualizarActual((actual) => [...actual, item]);
  }

  quitar(varianteId: number): void {
    this.actualizarActual((actual) => actual.filter((item) => item.varianteId !== varianteId));
  }

  /** Vacía solo la tienda actual. */
  vaciar(): void {
    this.actualizarActual(() => []);
  }

  private actualizarActual(cambio: (actual: ItemReservaTemporal[]) => ItemReservaTemporal[]): void {
    const codigo = this.codigoActual();
    if (codigo === null) return;
    this.porTienda.update((mapa) => ({ ...mapa, [codigo]: cambio(mapa[codigo] ?? []) }));
  }
}
