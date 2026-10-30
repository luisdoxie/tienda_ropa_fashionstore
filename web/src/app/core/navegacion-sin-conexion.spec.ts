import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, Routes, provideRouter, withNavigationErrorHandler } from '@angular/router';
import { ConectividadService } from './conectividad.service';
import { alFallarLaNavegacion, destinoInternoSeguro, esErrorDeCargaDeChunk } from './navegacion-sin-conexion';

@Component({ standalone: true, template: '' })
class PaginaVaciaComponent {}

const chunkQueNoCarga = () =>
  Promise.reject(new TypeError('Failed to fetch dynamically imported module: https://x.test/chunk-ABC123.js'));

describe('navegación sin conexión', () => {
  function crearRouter(rutas: Routes): Router {
    TestBed.configureTestingModule({
      providers: [provideRouter(rutas, withNavigationErrorHandler(alFallarLaNavegacion))],
    });
    TestBed.inject(ConectividadService); // escucha los eventos online/offline desde ya
    return TestBed.inject(Router);
  }

  const rutas: Routes = [
    { path: '', component: PaginaVaciaComponent },
    { path: 'sin-conexion', component: PaginaVaciaComponent },
    { path: 'pantalla', loadComponent: chunkQueNoCarga },
    { path: 'otra', loadComponent: () => Promise.reject(new Error('fallo del guardián')) },
  ];

  afterEach(() => {
    delete (navigator as { onLine?: boolean }).onLine;
  });

  it('sin conexión, una pantalla que no carga lleva a /sin-conexion guardando a dónde volver', async () => {
    const router = crearRouter(rutas);
    window.dispatchEvent(new Event('offline'));

    await router.navigateByUrl('/pantalla?tab=2');

    expect(router.url).toBe('/sin-conexion?returnTo=%2Fpantalla%3Ftab%3D2');
  });

  it('con conexión el mismo error NO redirige: la navegación falla como siempre', async () => {
    const router = crearRouter(rutas);

    await expect(router.navigateByUrl('/pantalla')).rejects.toThrow('dynamically imported module');
    expect(router.url).not.toContain('sin-conexion');
  });

  it('sin conexión, un error que no es de carga de archivos tampoco redirige', async () => {
    const router = crearRouter(rutas);
    window.dispatchEvent(new Event('offline'));

    await expect(router.navigateByUrl('/otra')).rejects.toThrow('fallo del guardián');
    expect(router.url).not.toContain('sin-conexion');
  });

  it('si la propia pantalla /sin-conexion no carga no entra en un bucle de redirecciones', async () => {
    const router = crearRouter([
      { path: '', component: PaginaVaciaComponent },
      { path: 'sin-conexion', loadComponent: chunkQueNoCarga },
    ]);
    window.dispatchEvent(new Event('offline'));

    await expect(router.navigateByUrl('/sin-conexion?returnTo=%2Fx')).rejects.toThrow('dynamically imported module');
  });

  describe('esErrorDeCargaDeChunk', () => {
    it('reconoce los mensajes de los navegadores y el ChunkLoadError', () => {
      expect(esErrorDeCargaDeChunk(new TypeError('Failed to fetch dynamically imported module: x'))).toBe(true);
      expect(esErrorDeCargaDeChunk(new TypeError('error loading dynamically imported module'))).toBe(true);
      expect(esErrorDeCargaDeChunk(new TypeError('Importing a module script failed.'))).toBe(true);
      const chunk = new Error('boom');
      chunk.name = 'ChunkLoadError';
      expect(esErrorDeCargaDeChunk(chunk)).toBe(true);
    });

    it('no confunde otros errores', () => {
      expect(esErrorDeCargaDeChunk(new Error('Cannot match any routes'))).toBe(false);
      expect(esErrorDeCargaDeChunk('Failed to fetch')).toBe(false);
      expect(esErrorDeCargaDeChunk(null)).toBe(false);
    });
  });

  describe('destinoInternoSeguro', () => {
    it('acepta rutas internas con su query', () => {
      expect(destinoInternoSeguro('/t/acme/carrito')).toBe('/t/acme/carrito');
      expect(destinoInternoSeguro('/reportes?tipo=ventas')).toBe('/reportes?tipo=ventas');
    });

    it('rechaza otros sitios, esquemas y la propia pantalla: vuelve al inicio', () => {
      expect(destinoInternoSeguro('//malo.example')).toBe('/');
      expect(destinoInternoSeguro('/\\malo.example')).toBe('/');
      expect(destinoInternoSeguro('https://malo.example')).toBe('/');
      expect(destinoInternoSeguro('javascript:alert(1)')).toBe('/');
      expect(destinoInternoSeguro('/sin-conexion?returnTo=%2Fx')).toBe('/');
      expect(destinoInternoSeguro('')).toBe('/');
      expect(destinoInternoSeguro(null)).toBe('/');
    });
  });
});
