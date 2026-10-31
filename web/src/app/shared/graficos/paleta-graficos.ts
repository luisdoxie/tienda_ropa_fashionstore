/**
 * Colores y estilo común de los gráficos (chart.js vía `p-chart`). Todo sale de los tokens `--fs-*` en el momento de
 * dibujar (nunca hex sueltos en los componentes). Sobre fondo claro la serie principal va en oliva; la lima solo
 * aparece como un color más, con borde. Las series se distinguen por luminosidad y SIEMPRE llevan leyenda o tabla al
 * lado: el color nunca es la única pista.
 */

/** Más series que esto se recortan (y se avisa): la paleta no distingue más. */
export const MAX_SERIES = 6;

export function token(nombre: string, respaldo: string): string {
  if (typeof document === 'undefined') return respaldo;
  const valor = getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
  return valor || respaldo;
}

export interface ColoresBase {
  tinta: string;
  lima: string;
  oliva: string;
  neutro: string;
  tenue: string;
  texto: string;
  advertencia: string;
  exito: string;
  error: string;
  rejilla: string;
  superficie: string;
  carbon: string;
}

/** Los colores del sistema de diseño, leídos del documento en este instante. */
export function coloresBase(): ColoresBase {
  return {
    tinta: token('--fs-tinta', '#151515'),
    lima: token('--fs-acento-oscuro', '#8fae5b'),
    oliva: token('--fs-acento', '#5d6b34'),
    neutro: token('--fs-campo-borde', '#c9c2b6'),
    tenue: token('--fs-texto-tenue', '#6b645c'),
    texto: token('--fs-texto', '#161412'),
    advertencia: token('--fs-advertencia', '#a4480a'),
    exito: token('--fs-exito', '#15803d'),
    error: token('--fs-error', '#c62828'),
    rejilla: token('--fs-fondo-alt', '#efebe4'),
    superficie: token('--fs-superficie', '#ffffff'),
    carbon: token('--fs-carbon', '#1b1916'),
  };
}

/** Los colores de las series, en orden: oliva, tinta, advertencia, lima, tenue y neutro. */
export function paletaSeries(): string[] {
  const c = coloresBase();
  return [c.oliva, c.tinta, c.advertencia, c.lima, c.tenue, c.neutro];
}

// ---- Color estable por entidad -------------------------------------------------------------------------------------
// La misma sucursal (o categoría, o segmento) conserva su color entre reportes durante toda la sesión. Cada entidad
// nueva toma el siguiente color libre, así las primeras 6 nunca chocan; a partir de la séptima se reutilizan.

const indicePorEntidad = new Map<string, number>();

export function colorDeEntidad(clave: string | number): string {
  const paleta = paletaSeries();
  const id = String(clave);
  let indice = indicePorEntidad.get(id);
  if (indice === undefined) {
    indice = indicePorEntidad.size % paleta.length;
    indicePorEntidad.set(id, indice);
  }
  return paleta[indice];
}

/** Solo para las pruebas (o al cerrar sesión): olvida los colores asignados. */
export function reiniciarColores(): void {
  indicePorEntidad.clear();
}

// ---- Estilo común --------------------------------------------------------------------------------------------------

export const FUENTE = { family: 'Public Sans, sans-serif', size: 12 };

export function estiloTooltip() {
  return {
    backgroundColor: coloresBase().carbon,
    titleFont: { family: 'Public Sans, sans-serif', size: 12, weight: 'bold' as const },
    bodyFont: { family: 'Public Sans, sans-serif', size: 12 },
    padding: 10,
    cornerRadius: 4,
    boxPadding: 4,
  };
}

/** Barras finas con extremo redondeado. */
export const ESTILO_BARRA = { borderRadius: 2, borderSkipped: 'start' as const, maxBarThickness: 26 };

/** Anillo o torta: borde grueso del color de la superficie, para separar segmentos parecidos. */
export function estiloAnillo() {
  return { borderColor: coloresBase().superficie, borderWidth: 3, hoverOffset: 6 };
}
