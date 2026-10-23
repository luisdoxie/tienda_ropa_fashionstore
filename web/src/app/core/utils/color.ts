/**
 * Paleta de acento de una tienda a partir de su color de marca. Funciones puras
 * (sin DOM): la tienda las aplica como variables CSS en su propio elemento.
 */

/** El acento de la empresa sobre las superficies oscuras (portada, acceso, barra lateral). */
export interface AcentoSobreOscuro {
  acento: string;
  hover: string;
  /** Color del texto de un botón relleno con este acento. */
  textoSobreAcento: string;
}

export interface PaletaAcento {
  acento: string;
  acentoHover: string;
  acentoSuave: string;
  textoSobreAcento: string;
  sobreOscuro: AcentoSobreOscuro;
}

/** Contraste mínimo del acento contra blanco (WCAG, texto grande / controles). */
export const CONTRASTE_MINIMO = 3;

/** Contraste mínimo del acento contra el carbón de las superficies oscuras. */
export const CONTRASTE_MINIMO_SOBRE_OSCURO = 4.5;

const BLANCO = '#ffffff';
const TEXTO_OSCURO = '#1c1713';
/** Fondo oscuro de la tienda (--fs-carbon) y texto de un botón relleno con acento. */
const CARBON = '#1b1916';
const TEXTO_SOBRE_ACENTO_OSCURO = '#121110';

/** '#abc' / 'ABC' / '#AABBCC' -> '#aabbcc'; null si no es un hexadecimal válido. */
export function normalizarHex(valor: string | null | undefined): string | null {
  if (typeof valor !== 'string') return null;
  const limpio = valor.trim().replace(/^#/, '').toLowerCase();
  if (/^[0-9a-f]{3}$/.test(limpio)) {
    return '#' + limpio.split('').map((c) => c + c).join('');
  }
  if (/^[0-9a-f]{6}$/.test(limpio)) return '#' + limpio;
  return null;
}

function canales(hex: string): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];
}

function aHex(rgb: number[]): string {
  return '#' + rgb.map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, '0')).join('');
}

/** Luminancia relativa WCAG de un hexadecimal normalizado (0 negro, 1 blanco). */
export function luminancia(hex: string): number {
  const [r, g, b] = canales(hex).map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Razón de contraste WCAG entre dos hexadecimales normalizados (1 a 21). */
export function contraste(a: string, b: string): number {
  const la = luminancia(a);
  const lb = luminancia(b);
  const [claro, oscuro] = la >= lb ? [la, lb] : [lb, la];
  return (claro + 0.05) / (oscuro + 0.05);
}

/** Mezcla el color con negro: `cantidad` 0..1. */
export function oscurecer(hex: string, cantidad: number): string {
  return aHex(canales(hex).map((c) => c * (1 - cantidad)));
}

/** Mezcla el color con blanco: `cantidad` 0..1. */
export function aclarar(hex: string, cantidad: number): string {
  return aHex(canales(hex).map((c) => c + (255 - c) * cantidad));
}

/**
 * El acento sobre fondo oscuro: el mismo color si ya contrasta con el carbón; si
 * no, se aclara de a poco hasta que contraste. Así un azul marino de empresa
 * sigue legible sobre la portada oscura.
 */
export function acentoSobreOscuro(acento: string): AcentoSobreOscuro {
  let color = acento;
  for (let paso = 1; paso <= 10 && contraste(color, CARBON) < CONTRASTE_MINIMO_SOBRE_OSCURO; paso++) {
    color = aclarar(acento, paso * 0.1);
  }
  return {
    acento: color,
    hover: aclarar(color, 0.15),
    textoSobreAcento:
      contraste(color, TEXTO_SOBRE_ACENTO_OSCURO) >= contraste(color, BLANCO) ? TEXTO_SOBRE_ACENTO_OSCURO : BLANCO,
  };
}

/**
 * La paleta de la tienda, o null si el color no es válido o no contrasta lo
 * suficiente contra blanco: en ese caso se queda el acento base de la app.
 */
export function calcularPaletaAcento(color: string | null | undefined): PaletaAcento | null {
  const acento = normalizarHex(color);
  if (acento === null) return null;
  const contraBlanco = contraste(acento, BLANCO);
  if (contraBlanco < CONTRASTE_MINIMO) return null;

  return {
    acento,
    acentoHover: oscurecer(acento, 0.25),
    acentoSuave: aclarar(acento, 0.82),
    textoSobreAcento: contraBlanco >= contraste(acento, TEXTO_OSCURO) ? BLANCO : TEXTO_OSCURO,
    sobreOscuro: acentoSobreOscuro(acento),
  };
}
