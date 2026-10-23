/**
 * Baja a la sección "La colección" de la portada (`#catalogo`) sin cambiar la
 * URL, y opcionalmente deja el cursor en el buscador (`#catalogo-buscar`).
 * Lo usan la cabecera de la tienda y el botón "Explorar colección" del hero.
 */
export function irAColeccion(evento: Event, enfocarBuscador = false): void {
  evento.preventDefault();
  const seccion = document.getElementById('catalogo');
  const reducido = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  seccion?.scrollIntoView?.({ behavior: reducido ? 'auto' : 'smooth', block: 'start' });
  if (enfocarBuscador) document.getElementById('catalogo-buscar')?.focus({ preventScroll: true });
}
