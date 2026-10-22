import { inject } from '@angular/core';
import { Route, Router, UrlTree } from '@angular/router';
import { TiendaActualService } from './state/tienda-actual.service';

/**
 * Las direcciones de antes de las tiendas por empresa (/catalogo, /carrito,
 * /producto/7, ...) siguen funcionando: llevan a la MISMA pantalla dentro de la
 * última tienda visitada, o a la plataforma ("/") si no hay ninguna.
 */

/** Pura. Los segmentos con ':nombre' se reemplazan por el parámetro de la ruta vieja. */
export function destinoLegado(
  ultimaTienda: string | null,
  segmentos: readonly string[],
  parametros: Readonly<Record<string, string>> = {},
): string[] {
  if (!ultimaTienda) return ['/'];
  const reales = segmentos.map((segmento) =>
    segmento.startsWith(':') ? (parametros[segmento.slice(1)] ?? '') : segmento,
  );
  return ['/t', ultimaTienda, ...reales.filter((s) => s !== '')];
}

type DatosRedireccion = { params: Record<string, string>; queryParams: Record<string, string | string[]> };

/** `redirectTo` en forma de función: conserva los query params (returnTo, token). */
export function redirigirALegado(...segmentos: string[]): (datos: DatosRedireccion) => UrlTree {
  return (datos) => {
    const destino = destinoLegado(inject(TiendaActualService).ultimaTienda(), segmentos, datos.params);
    return inject(Router).createUrlTree(destino, { queryParams: datos.queryParams });
  };
}

/** Las rutas viejas de la tienda, cada una redirigida a la nueva (p. ej. 'producto/:id'). */
export const RUTAS_LEGACY: Route[] = [
  { path: 'catalogo', pathMatch: 'full', redirectTo: redirigirALegado() },
  { path: 'producto/:id', pathMatch: 'full', redirectTo: redirigirALegado('producto', ':id') },
  { path: 'carrito', pathMatch: 'full', redirectTo: redirigirALegado('carrito') },
  { path: 'reserva/confirmar', pathMatch: 'full', redirectTo: redirigirALegado('reserva', 'confirmar') },
  { path: 'mis-reservas', pathMatch: 'full', redirectTo: redirigirALegado('mis-reservas') },
  { path: 'mis-reservas/:id', pathMatch: 'full', redirectTo: redirigirALegado('mis-reservas', ':id') },
  { path: 'checkout/entrega', pathMatch: 'full', redirectTo: redirigirALegado('checkout', 'entrega') },
  { path: 'checkout/pago', pathMatch: 'full', redirectTo: redirigirALegado('checkout', 'pago') },
  { path: 'checkout/estado/:pagoId', pathMatch: 'full', redirectTo: redirigirALegado('checkout', 'estado', ':pagoId') },
  { path: 'mis-compras', pathMatch: 'full', redirectTo: redirigirALegado('mis-compras') },
  { path: 'mis-compras/:id', pathMatch: 'full', redirectTo: redirigirALegado('mis-compras', ':id') },
  { path: 'registro', pathMatch: 'full', redirectTo: redirigirALegado('registro') },
  { path: 'recuperar', pathMatch: 'full', redirectTo: redirigirALegado('recuperar') },
];
