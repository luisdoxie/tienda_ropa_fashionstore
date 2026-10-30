import { Injectable, inject } from '@angular/core';
import { VarianteBusqueda } from '../models/catalogo.models';
import { normalizarTexto } from './normalizar';
import type { FilaCategoria, FilaCliente, FilaSucursal, ProductoLocal } from './offline.models';
import { SesionOfflineService } from './sesion-offline.service';

/**
 * Una variante encontrada en el catálogo descargado. Es lo mismo que devuelve `GET /catalogo/variantes/buscar` (Caja),
 * más el descuento vigente al momento de la descarga: `precio_efectivo` es el precio de lista (igual que en línea,
 * donde el descuento se aplica después, al calcular la venta) y el descuento va aparte.
 */
export interface VarianteBusquedaLocal extends VarianteBusqueda {
  descuento_unitario: number;
}

/**
 * Consulta de SOLO LECTURA del catálogo, el stock y los clientes descargados en este equipo. Es una fachada sobre el
 * repositorio de la sesión (única puerta a IndexedDB): sin empresa y usuario en la sesión no hay repositorio y todas las
 * consultas devuelven listas vacías, nunca lanzan por eso.
 *
 * Los errores reales de lectura (la base no abre, cuota, bloqueo) sí se propagan: quien consulta decide qué mostrar.
 */
@Injectable({ providedIn: 'root' })
export class CatalogoLocalService {
  private readonly sesion = inject(SesionOfflineService);

  /** Productos por nombre, código, SKU o código de barras, con variantes, tallas, colores y stock por sucursal. */
  async buscarProductos(texto = '', categoriaId?: number | null): Promise<ProductoLocal[]> {
    const repo = this.sesion.repositorio();
    return repo === null ? [] : repo.buscarProductos(texto, categoriaId);
  }

  /** Las variantes de un producto del paquete (vacío si el producto no está). */
  async variantesDeProducto(productoId: number): Promise<ProductoLocal['variantes']> {
    const repo = this.sesion.repositorio();
    if (repo === null) return [];
    return (await repo.producto(productoId))?.variantes ?? [];
  }

  /**
   * Variantes que coinciden con el texto, una fila por variante (la búsqueda de Caja). Como en el servidor: el código de
   * barras debe ser exacto; el SKU, el nombre y el código del producto coinciden por contenido, sin tildes ni mayúsculas.
   * Si coincide el producto, salen todas sus variantes; si solo coincide una variante (SKU o barras), sale solo esa.
   * Una variante cuyo precio no es un número válido no se ofrece: venderla en cero sería peor que no encontrarla.
   */
  async buscarVariantes(texto: string): Promise<VarianteBusquedaLocal[]> {
    const busqueda = normalizarTexto(texto);
    if (!busqueda) return [];
    const repo = this.sesion.repositorio();
    if (repo === null) return [];

    const exacto = texto.trim();
    const encontradas: VarianteBusquedaLocal[] = [];
    for (const producto of await repo.buscarProductos(texto)) {
      const coincideProducto = producto.nombre_norm.includes(busqueda) || normalizarTexto(producto.codigo).includes(busqueda);
      for (const variante of producto.variantes) {
        const coincideVariante = variante.codigo_barras === exacto || normalizarTexto(variante.sku).includes(busqueda);
        if (!coincideProducto && !coincideVariante) continue;
        const precio = aDecimal(variante.precio);
        if (precio === null) continue;
        encontradas.push({
          variante_id: variante.id,
          producto_id: producto.id,
          producto_nombre: producto.nombre,
          producto_codigo: producto.codigo,
          talla_codigo: variante.talla ?? '',
          color_nombre: variante.color ?? '',
          sku: variante.sku,
          codigo_barras: variante.codigo_barras,
          precio_efectivo: precio,
          descuento_unitario: aDecimal(variante.descuento_unitario) ?? 0,
        });
      }
    }
    return encontradas;
  }

  /** Stock conocido de una variante por sucursal (`sucursal_id` -> unidades). Es el de la última descarga. */
  async stockPorSucursal(varianteId: number): Promise<Record<number, number>> {
    const repo = this.sesion.repositorio();
    return repo === null ? {} : repo.stockDeVariante(varianteId);
  }

  async clientes(texto = ''): Promise<FilaCliente[]> {
    const repo = this.sesion.repositorio();
    return repo === null ? [] : repo.clientes(texto);
  }

  async categorias(): Promise<FilaCategoria[]> {
    const repo = this.sesion.repositorio();
    return repo === null ? [] : repo.categorias();
  }

  async sucursales(): Promise<FilaSucursal[]> {
    const repo = this.sesion.repositorio();
    return repo === null ? [] : repo.sucursales();
  }
}

/** Decimal en texto ("149.00") a número con 2 decimales; `null` si no es un número finito y no negativo. */
function aDecimal(texto: string | null | undefined): number | null {
  if (texto === null || texto === undefined || texto.trim() === '') return null;
  const numero = Number(texto);
  if (!Number.isFinite(numero) || numero < 0) return null;
  // Se redondea sobre el TEXTO ("10.005e2" = 1000.5 exacto): multiplicar por 100 en coma flotante daría 1000.4999...
  const centavos = Number(`${texto.trim()}e2`);
  return Math.round(Number.isFinite(centavos) ? centavos : numero * 100) / 100;
}
