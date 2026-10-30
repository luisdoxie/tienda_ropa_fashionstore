import { inject } from '@angular/core';
import { NavigationError, RedirectCommand, Router } from '@angular/router';
import { ConectividadService } from './conectividad.service';

export const RUTA_SIN_CONEXION = '/sin-conexion';

/** Un `import()` que no pudo descargar su archivo (chunk) falla con estos mensajes, según el navegador. */
const MENSAJES_DE_CHUNK = /dynamically imported module|importing a module script failed|loading chunk|loading css chunk|failed to fetch/i;

export function esErrorDeCargaDeChunk(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return error.name === 'ChunkLoadError' || MENSAJES_DE_CHUNK.test(error.message);
}

function esRutaSinConexion(url: string): boolean {
  return url === RUTA_SIN_CONEXION || url.startsWith(`${RUTA_SIN_CONEXION}?`) || url.startsWith(`${RUTA_SIN_CONEXION}/`);
}

/** Solo rutas internas ("/algo"): nunca otro sitio ("//otro.com", "https://...") ni la propia pantalla. */
export function destinoInternoSeguro(returnTo: string | null | undefined): string {
  if (!returnTo || !/^\/(?![/\\])/.test(returnTo) || esRutaSinConexion(returnTo)) return '/';
  return returnTo;
}

/**
 * Red de seguridad del enrutador (`withNavigationErrorHandler`): si una pantalla no se pudo
 * cargar porque no hay conexión, lleva a "Sin conexión" y guarda a dónde volver. Con el Service
 * Worker precacheando todo el JavaScript esto casi no ocurre. Cualquier otro error de navegación
 * sigue su camino normal.
 */
export function alFallarLaNavegacion(error: NavigationError): RedirectCommand | undefined {
  const conectividad = inject(ConectividadService);
  const router = inject(Router);

  if (conectividad.enLinea() || !esErrorDeCargaDeChunk(error.error)) return undefined;
  // Si la propia pantalla "Sin conexión" no carga no hay a dónde mandar: se evita un bucle.
  if (esRutaSinConexion(error.url)) return undefined;

  return new RedirectCommand(router.createUrlTree([RUTA_SIN_CONEXION], { queryParams: { returnTo: error.url } }));
}
