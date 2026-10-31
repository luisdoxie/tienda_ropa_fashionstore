import { describe, expect, it, vi } from 'vitest';
import { entornoReal, perfilRendimiento, puedeUsarEscena3D, type Entorno } from './capacidades';

const BUENO: Entorno = {
  tieneWebGL: true,
  reducirMovimiento: false,
  ahorroDeDatos: false,
  memoriaGb: 8,
  nucleos: 8,
};

describe('puedeUsarEscena3D', () => {
  it('es verdadero en un equipo capaz', () => {
    expect(puedeUsarEscena3D(BUENO)).toBe(true);
  });

  it('es verdadero cuando el navegador no informa memoria ni núcleos', () => {
    expect(puedeUsarEscena3D({ ...BUENO, memoriaGb: undefined, nucleos: undefined })).toBe(true);
  });

  it('es verdadero justo en el límite (4 GB y 4 núcleos)', () => {
    expect(puedeUsarEscena3D({ ...BUENO, memoriaGb: 4, nucleos: 4 })).toBe(true);
  });

  it('es falso sin WebGL', () => {
    expect(puedeUsarEscena3D({ ...BUENO, tieneWebGL: false })).toBe(false);
  });

  it('es falso con "reducir movimiento"', () => {
    expect(puedeUsarEscena3D({ ...BUENO, reducirMovimiento: true })).toBe(false);
  });

  it('es falso con ahorro de datos', () => {
    expect(puedeUsarEscena3D({ ...BUENO, ahorroDeDatos: true })).toBe(false);
  });

  it('es falso con menos de 4 GB de memoria', () => {
    expect(puedeUsarEscena3D({ ...BUENO, memoriaGb: 2 })).toBe(false);
    expect(puedeUsarEscena3D({ ...BUENO, memoriaGb: 0.5 })).toBe(false);
  });

  it('es falso con menos de 4 núcleos', () => {
    expect(puedeUsarEscena3D({ ...BUENO, nucleos: 2 })).toBe(false);
  });
});

describe('perfilRendimiento', () => {
  it('gama alta: densidad 2 y 520 partículas', () => {
    expect(perfilRendimiento(BUENO)).toEqual({ pixelRatioMax: 2, particulas: 520 });
    expect(perfilRendimiento({ ...BUENO, memoriaGb: undefined, nucleos: undefined })).toEqual({
      pixelRatioMax: 2,
      particulas: 520,
    });
  });

  it('gama media baja la densidad a 1,5 y las partículas a 260', () => {
    expect(perfilRendimiento({ ...BUENO, memoriaGb: 4 })).toEqual({ pixelRatioMax: 1.5, particulas: 260 });
    expect(perfilRendimiento({ ...BUENO, nucleos: 6 })).toEqual({ pixelRatioMax: 1.5, particulas: 260 });
  });

  it('gama baja baja la densidad a 1', () => {
    expect(perfilRendimiento({ ...BUENO, memoriaGb: 2 })).toEqual({ pixelRatioMax: 1, particulas: 260 });
    expect(perfilRendimiento({ ...BUENO, nucleos: 2 })).toEqual({ pixelRatioMax: 1, particulas: 260 });
  });
});

describe('entornoReal', () => {
  it('en jsdom no hay WebGL y no revienta', () => {
    const contexto = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const entorno = entornoReal();
    expect(entorno.tieneWebGL).toBe(false);
    expect(entorno.reducirMovimiento).toBe(false);
    expect(puedeUsarEscena3D()).toBe(false);
    expect(contexto).toHaveBeenCalledWith('webgl2');
    expect(contexto).toHaveBeenCalledWith('webgl');
    contexto.mockRestore();
  });

  it('hay WebGL si el navegador entrega un contexto', () => {
    const contexto = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as never);
    expect(entornoReal().tieneWebGL).toBe(true);
    contexto.mockRestore();
  });
});
