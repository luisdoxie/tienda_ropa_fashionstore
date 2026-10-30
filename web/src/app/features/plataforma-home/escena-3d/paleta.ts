import type { Paleta } from './contrato';

/** Valores de respaldo: los mismos que los tokens `--fs-*` de `web/src/styles.scss`. */
export const PALETA_RESPALDO: Readonly<Paleta> = {
  carbon: '#1b1916',
  profundo: '#121110',
  panel: '#232019',
  borde: '#2f2c27',
  texto: '#f2f2f0',
  tenue: '#b5b2aa',
  acento: '#8fae5b',
  sobreAcento: '#121110',
};

/** Qué token alimenta cada color de la paleta. */
const TOKENS: Readonly<Record<keyof Paleta, string>> = {
  carbon: '--fs-carbon',
  profundo: '--fs-carbon-2',
  panel: '--fs-carbon-panel',
  borde: '--fs-carbon-borde',
  texto: '--fs-claro',
  tenue: '--fs-claro-tenue',
  acento: '--fs-acento-oscuro',
  sobreAcento: '--fs-sobre-acento-oscuro',
};

/**
 * Lee los colores base de la escena 3D desde los tokens `--fs-*` (con `getComputedStyle`). Si un token
 * no existe, o no es un color #rgb / #rrggbb, usa el respaldo. Todo color del motor sale de aquí.
 */
export function leerPaleta(raiz: HTMLElement = document.documentElement): Paleta {
  const estilos = typeof getComputedStyle === 'function' ? getComputedStyle(raiz) : null;
  const paleta = { ...PALETA_RESPALDO };
  for (const clave of Object.keys(TOKENS) as (keyof Paleta)[]) {
    const valor = estilos?.getPropertyValue(TOKENS[clave]).trim() ?? '';
    const hex = normalizarHex(valor);
    if (hex) paleta[clave] = hex;
  }
  return paleta;
}

/** "#abc" → "#aabbcc"; devuelve null si no es un color hexadecimal. */
function normalizarHex(valor: string): string | null {
  if (/^#[0-9a-f]{6}$/i.test(valor)) return valor.toLowerCase();
  if (/^#[0-9a-f]{3}$/i.test(valor)) {
    return ('#' + [...valor.slice(1)].map((c) => c + c).join('')).toLowerCase();
  }
  return null;
}
