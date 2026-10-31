import { aNumero, formatearCelda, formatearFechaIso, formateadorDe } from './formato-reporte';

describe('formato-reporte', () => {
  describe('aNumero', () => {
    it('acepta números y textos con punto o coma', () => {
      expect(aNumero(12.5)).toBe(12.5);
      expect(aNumero('12.5')).toBe(12.5);
      expect(aNumero('12,5')).toBe(12.5);
      expect(aNumero('+8.3%')).toBe(8.3);
    });

    it('devuelve null si no es un número', () => {
      expect(aNumero('leve')).toBeNull();
      expect(aNumero('')).toBeNull();
      expect(aNumero(null)).toBeNull();
      expect(aNumero(true)).toBeNull();
      expect(aNumero(Number.NaN)).toBeNull();
    });
  });

  describe('formatearCelda', () => {
    it('dinero con Bs y dos decimales', () => {
      expect(formatearCelda(1234.5, 'moneda')).toBe('Bs 1.234,50');
    });

    it('enteros con separador de miles', () => {
      expect(formatearCelda(12345, 'entero')).toBe('12.345');
    });

    it('el porcentaje llega en escala 0 a 100', () => {
      expect(formatearCelda(37.5, 'porcentaje')).toBe('37,5 %');
    });

    it('las fechas se muestran dd/mm/aaaa sin pasar por la zona horaria', () => {
      expect(formatearCelda('2026-09-30', 'fecha')).toBe('30/09/2026');
      expect(formatearFechaIso('2026-10-20T03:00:00Z')).toBe('20/10/2026');
    });

    it('booleanos y vacíos', () => {
      expect(formatearCelda(true, 'booleano')).toBe('Sí');
      expect(formatearCelda(false, 'booleano')).toBe('No');
      expect(formatearCelda(null, 'moneda')).toBe('—');
      expect(formatearCelda('', 'texto')).toBe('—');
    });

    it('un valor que no se puede dar formato se muestra tal cual', () => {
      expect(formatearCelda('n/d', 'moneda')).toBe('n/d');
    });
  });

  it('formateadorDe: texto con decimales y enteros', () => {
    expect(formateadorDe('texto')(3)).toBe('3');
    expect(formateadorDe('texto')(2.5)).toBe('2,50');
  });
});
