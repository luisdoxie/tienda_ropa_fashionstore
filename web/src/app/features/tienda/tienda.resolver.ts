import { inject } from '@angular/core';
import { ResolveFn } from '@angular/router';
import { EstadoTienda, TiendaActualService } from './state/tienda-actual.service';

/**
 * Resuelve la empresa de /t/:codigo antes de mostrar nada. No lanza: devuelve
 * el estado ('lista', 'no_encontrada', 'no_disponible' o 'error') para que
 * `TiendaRaizComponent` muestre la pantalla que corresponde.
 */
export const tiendaResolver: ResolveFn<EstadoTienda> = (route) =>
  inject(TiendaActualService).cargar(route.paramMap.get('codigo') ?? '');
