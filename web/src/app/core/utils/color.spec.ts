import {
  CONTRASTE_MINIMO,
  CONTRASTE_MINIMO_SOBRE_OSCURO,
  aclarar,
  acentoSobreOscuro,
  calcularPaletaAcento,
  contraste,
  luminancia,
  normalizarHex,
  oscurecer,
} from './color';

describe('color', () => {
  describe('normalizarHex', () => {
    it('expande y normaliza los formatos válidos', () => {
      expect(normalizarHex('#abc')).toBe('#aabbcc');
      expect(normalizarHex('ABC')).toBe('#aabbcc');
      expect(normalizarHex('#AABBCC')).toBe('#aabbcc');
      expect(normalizarHex('  #9A3E1F ')).toBe('#9a3e1f');
    });

    it('devuelve null para valores inválidos', () => {
      for (const invalido of ['', '#', '#12', '#12345', '#1234567', '#ggg', 'rojo', 'rgb(1,2,3)', '#zzzzzz']) {
        expect(normalizarHex(invalido), invalido).toBeNull();
      }
    });

    it('devuelve null para null, undefined y no strings', () => {
      expect(normalizarHex(null)).toBeNull();
      expect(normalizarHex(undefined)).toBeNull();
      expect(normalizarHex(123 as unknown as string)).toBeNull();
    });
  });

  describe('luminancia y contraste', () => {
    it('luminancia de blanco es 1 y de negro es 0', () => {
      expect(luminancia('#ffffff')).toBeCloseTo(1, 5);
      expect(luminancia('#000000')).toBeCloseTo(0, 5);
    });

    it('contraste blanco vs negro es 21 (en ambos sentidos)', () => {
      expect(contraste('#ffffff', '#000000')).toBeCloseTo(21, 5);
      expect(contraste('#000000', '#ffffff')).toBeCloseTo(21, 5);
    });

    it('contraste de un color consigo mismo es 1', () => {
      expect(contraste('#9a3e1f', '#9a3e1f')).toBeCloseTo(1, 5);
    });
  });

  describe('oscurecer y aclarar', () => {
    it('oscurecer reduce la luminancia y 1 llega a negro', () => {
      expect(luminancia(oscurecer('#9a3e1f', 0.25))).toBeLessThan(luminancia('#9a3e1f'));
      expect(oscurecer('#9a3e1f', 1)).toBe('#000000');
      expect(oscurecer('#9a3e1f', 0)).toBe('#9a3e1f');
    });

    it('aclarar aumenta la luminancia y 1 llega a blanco', () => {
      expect(luminancia(aclarar('#9a3e1f', 0.5))).toBeGreaterThan(luminancia('#9a3e1f'));
      expect(aclarar('#9a3e1f', 1)).toBe('#ffffff');
      expect(aclarar('#9a3e1f', 0)).toBe('#9a3e1f');
    });
  });

  describe('calcularPaletaAcento', () => {
    it('hex inválido -> null', () => {
      expect(calcularPaletaAcento('nada')).toBeNull();
      expect(calcularPaletaAcento(null)).toBeNull();
      expect(calcularPaletaAcento(undefined)).toBeNull();
    });

    it('color claro con poco contraste -> null', () => {
      expect(calcularPaletaAcento('#ffee88')).toBeNull();
      expect(calcularPaletaAcento('#ffffff')).toBeNull();
    });

    it.each(['#9a3e1f', '#2563eb', '#1a2b3c'])('color válido %s genera paleta coherente', (color) => {
      const paleta = calcularPaletaAcento(color);
      expect(paleta).not.toBeNull();
      const p = paleta!;
      expect(p.acento).toBe(normalizarHex(color));
      expect(luminancia(p.acentoHover)).toBeLessThan(luminancia(p.acento));
      expect(luminancia(p.acentoSuave)).toBeGreaterThan(luminancia(p.acento));
      expect(contraste(p.acento, '#ffffff')).toBeGreaterThanOrEqual(CONTRASTE_MINIMO);
      expect(p.textoSobreAcento).toBeTruthy();
    });

    it('acepta formato corto y normaliza el acento', () => {
      expect(calcularPaletaAcento('#036')?.acento).toBe('#003366');
    });

    it('el texto sobre el acento es blanco en un acento oscuro', () => {
      expect(calcularPaletaAcento('#9a3e1f')?.textoSobreAcento).toBe('#ffffff');
    });
  });

  describe('acentoSobreOscuro', () => {
    it('un acento que ya contrasta con el carbón se queda igual', () => {
      expect(acentoSobreOscuro('#8fae5b').acento).toBe('#8fae5b');
    });

    it.each(['#036', '#1a2b3c', '#9a3e1f'])('un acento oscuro (%s) se aclara hasta contrastar con el carbón', (color) => {
      const normal = normalizarHex(color)!;
      const sobre = acentoSobreOscuro(normal);
      expect(luminancia(sobre.acento)).toBeGreaterThan(luminancia(normal));
      expect(contraste(sobre.acento, '#1b1916')).toBeGreaterThanOrEqual(CONTRASTE_MINIMO_SOBRE_OSCURO);
    });

    it('el hover es más claro y el texto del botón contrasta con el relleno', () => {
      const sobre = acentoSobreOscuro('#8fae5b');
      expect(luminancia(sobre.hover)).toBeGreaterThan(luminancia(sobre.acento));
      expect(contraste(sobre.acento, sobre.textoSobreAcento)).toBeGreaterThanOrEqual(4.5);
    });

    it('la paleta de la tienda incluye la variante sobre oscuro', () => {
      expect(calcularPaletaAcento('#2563eb')?.sobreOscuro.acento).toBeTruthy();
    });
  });
});
