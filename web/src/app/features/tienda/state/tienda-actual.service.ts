import { HttpClient, HttpContext, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, catchError, map, of, tap } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { codigoFuncional } from '../../../core/errores-funcionales';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { EmpresaPublica } from '../../../core/models/empresa.models';
import { CarritoService } from '../data/carrito.service';
import { CheckoutService } from './checkout.service';
import { ReservaCarritoService } from './reserva-carrito.service';

export type EstadoTienda = 'sin_tienda' | 'cargando' | 'lista' | 'no_encontrada' | 'no_disponible' | 'error';

export const CLAVE_ULTIMA_TIENDA = 'fs_ultima_tienda';

/**
 * La tienda (empresa) en la que está parado el comprador: /t/:codigo. Es la
 * única fuente del código para armar rutas del web y URLs públicas de la API.
 * Al cambiar de tienda se limpia todo el estado del comprador (carrito,
 * reserva temporal y checkout) para que nunca se mezcle con el de otra.
 */
@Injectable({ providedIn: 'root' })
export class TiendaActualService {
  private readonly http = inject(HttpClient);
  private readonly carritoService = inject(CarritoService);
  private readonly reservaCarritoService = inject(ReservaCarritoService);
  private readonly checkoutService = inject(CheckoutService);

  private readonly codigoState = signal<string | null>(null);
  private readonly empresaState = signal<EmpresaPublica | null>(null);
  private readonly estadoState = signal<EstadoTienda>('sin_tienda');

  readonly codigo = this.codigoState.asReadonly();
  readonly empresa = this.empresaState.asReadonly();
  readonly estado = this.estadoState.asReadonly();

  /** Segmentos para `[routerLink]` y `router.navigate`: ['/t', codigo, ...]. Sin tienda, ['/']. */
  ruta(...segmentos: string[]): string[] {
    const codigo = this.codigoState();
    return codigo === null ? ['/'] : ['/t', codigo, ...segmentos];
  }

  /** URL de la API pública de la tienda actual: `{apiUrl}/public/{codigo}/{ruta}`. */
  urlPublica(ruta: string): string {
    const codigo = this.codigoState() ?? '';
    return `${environment.apiUrl}/public/${encodeURIComponent(codigo)}/${ruta.replace(/^\/+/, '')}`;
  }

  /**
   * Fija la tienda actual. Si el código cambió, limpia carrito, reserva
   * temporal y checkout. Solo una tienda que cargó bien ('lista') se recuerda
   * como "última tienda" (para los enlaces viejos y "Volver a ...").
   */
  fijar(codigo: string | null, estado: EstadoTienda, empresa: EmpresaPublica | null = null): void {
    if (codigo !== this.codigoState()) {
      this.carritoService.limpiar();
      this.reservaCarritoService.cambiarTienda(codigo);
      this.checkoutService.reiniciar();
    }
    this.codigoState.set(codigo);
    this.empresaState.set(empresa);
    this.estadoState.set(codigo === null ? 'sin_tienda' : estado);
    if (codigo !== null && estado === 'lista') this.recordar(codigo);
  }

  /** Al salir de /t/:codigo (plataforma, back office). */
  salir(): void {
    this.fijar(null, 'sin_tienda');
  }

  ultimaTienda(): string | null {
    try {
      return localStorage.getItem(CLAVE_ULTIMA_TIENDA);
    } catch {
      return null;
    }
  }

  /**
   * GET /public/{codigo}/tienda y deja el estado fijado. No lanza: devuelve el
   * estado para que la pantalla lo muestre (sin toast de error).
   *   200 -> 'lista' (o 'no_disponible' si la suscripción no está activa)
   *   404 -> 'no_encontrada'; 403 suscripcion_no_activa -> 'no_disponible'
   *   otro -> 'error'
   */
  cargar(codigo: string): Observable<EstadoTienda> {
    this.fijar(codigo, 'cargando');
    const contexto = new HttpContext().set(SIN_TOAST_ERROR, true);
    return this.http
      .get<EmpresaPublica>(`${environment.apiUrl}/public/${encodeURIComponent(codigo)}/tienda`, { context: contexto })
      .pipe(
        map((empresa): [EstadoTienda, EmpresaPublica | null] => [
          empresa.disponible === false ? 'no_disponible' : 'lista',
          empresa,
        ]),
        catchError((error: unknown): Observable<[EstadoTienda, EmpresaPublica | null]> => {
          if (error instanceof HttpErrorResponse && error.status === 404) return of(['no_encontrada', null]);
          if (error instanceof HttpErrorResponse && error.status === 403 && codigoFuncional(error) === 'suscripcion_no_activa') {
            return of(['no_disponible', null]);
          }
          return of(['error', null]);
        }),
        tap(([estado, empresa]) => this.fijar(codigo, estado, empresa)),
        map(([estado]) => estado),
      );
  }

  private recordar(codigo: string): void {
    try {
      localStorage.setItem(CLAVE_ULTIMA_TIENDA, codigo);
    } catch {
      // Sin localStorage (modo privado, cuota): simplemente no se recuerda.
    }
  }
}
