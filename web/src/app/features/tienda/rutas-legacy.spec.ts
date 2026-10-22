import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RUTAS_LEGACY, destinoLegado, redirigirALegado } from './rutas-legacy';
import { CLAVE_ULTIMA_TIENDA } from './state/tienda-actual.service';

describe('destinoLegado', () => {
  it('arma ["/t", tienda, ...segmentos]', () => {
    expect(destinoLegado('acme', ['carrito'])).toEqual(['/t', 'acme', 'carrito']);
  });

  it('sin última tienda lleva a la plataforma', () => {
    expect(destinoLegado(null, ['carrito'])).toEqual(['/']);
    expect(destinoLegado('', ['carrito'])).toEqual(['/']);
  });

  it('reemplaza los segmentos ":nombre" por el parámetro', () => {
    expect(destinoLegado('acme', ['producto', ':id'], { id: '7' })).toEqual(['/t', 'acme', 'producto', '7']);
    expect(destinoLegado('acme', ['checkout', 'estado', ':pagoId'], { pagoId: 'abc' })).toEqual([
      '/t',
      'acme',
      'checkout',
      'estado',
      'abc',
    ]);
  });

  it('sin segmentos lleva a la raíz de la tienda', () => {
    expect(destinoLegado('acme', [])).toEqual(['/t', 'acme']);
  });

  it('un parámetro que falta se omite', () => {
    expect(destinoLegado('acme', ['producto', ':id'], {})).toEqual(['/t', 'acme', 'producto']);
  });
});

describe('redirigirALegado', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
  });

  afterEach(() => localStorage.clear());

  function serializar(fn: ReturnType<typeof redirigirALegado>, datos: Parameters<typeof fn>[0]): string {
    const arbol = TestBed.runInInjectionContext(() => fn(datos));
    return TestBed.inject(Router).serializeUrl(arbol);
  }

  it('conserva los query params y usa la última tienda', () => {
    localStorage.setItem(CLAVE_ULTIMA_TIENDA, 'acme');
    const url = serializar(redirigirALegado('carrito'), { params: {}, queryParams: { returnTo: '/x' } });
    expect(url).toBe('/t/acme/carrito?returnTo=%2Fx');
  });

  it('sin última tienda lleva a "/"', () => {
    expect(serializar(redirigirALegado('carrito'), { params: {}, queryParams: {} })).toBe('/');
  });

  it('conserva el id de la ruta vieja', () => {
    localStorage.setItem(CLAVE_ULTIMA_TIENDA, 'acme');
    expect(serializar(redirigirALegado('producto', ':id'), { params: { id: '7' }, queryParams: {} })).toBe(
      '/t/acme/producto/7',
    );
  });

  it('funciona aunque localStorage lance', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('bloqueado');
    });
    try {
      expect(serializar(redirigirALegado('carrito'), { params: {}, queryParams: {} })).toBe('/');
    } finally {
      vi.restoreAllMocks();
    }
  });
});

describe('RUTAS_LEGACY', () => {
  const paths = RUTAS_LEGACY.map((r) => r.path);

  it('cubre todas las rutas viejas de la tienda', () => {
    const esperadas = [
      'catalogo',
      'producto/:id',
      'carrito',
      'reserva/confirmar',
      'mis-reservas',
      'mis-reservas/:id',
      'checkout/entrega',
      'checkout/pago',
      'checkout/estado/:pagoId',
      'mis-compras',
      'mis-compras/:id',
      'registro',
      'recuperar',
    ];
    for (const ruta of esperadas) expect(paths, ruta).toContain(ruta);
  });

  it('todas son redirecciones con pathMatch full', () => {
    for (const ruta of RUTAS_LEGACY) {
      expect(ruta.pathMatch, ruta.path).toBe('full');
      expect(typeof ruta.redirectTo, ruta.path).toBe('function');
    }
  });

  it('las redirecciones llevan al equivalente dentro de la tienda', () => {
    localStorage.setItem(CLAVE_ULTIMA_TIENDA, 'acme');
    TestBed.configureTestingModule({ providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()] });
    const router = TestBed.inject(Router);
    const destino = (path: string, params: Record<string, string> = {}) => {
      const ruta = RUTAS_LEGACY.find((r) => r.path === path)!;
      const fn = ruta.redirectTo as (d: unknown) => ReturnType<Router['createUrlTree']>;
      return router.serializeUrl(TestBed.runInInjectionContext(() => fn({ params, queryParams: {} })));
    };
    try {
      expect(destino('catalogo')).toBe('/t/acme');
      expect(destino('producto/:id', { id: '9' })).toBe('/t/acme/producto/9');
      expect(destino('reserva/confirmar')).toBe('/t/acme/reserva/confirmar');
      expect(destino('mis-compras/:id', { id: '3' })).toBe('/t/acme/mis-compras/3');
      expect(destino('checkout/estado/:pagoId', { pagoId: '5' })).toBe('/t/acme/checkout/estado/5');
    } finally {
      localStorage.clear();
    }
  });
});
