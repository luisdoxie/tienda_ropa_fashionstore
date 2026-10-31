import {
  ETIQUETA_CALIDAD,
  UMBRALES,
  calidadDeMetrica,
  interpretarMetrica,
  maeRelativo,
} from './explicacion-metricas';

describe('umbrales documentados', () => {
  it('son los que dice el encabezado del archivo', () => {
    expect(UMBRALES.r2).toEqual({ buena: 0.6, aceptable: 0.3 });
    expect(UMBRALES.silhouette).toEqual({ buena: 0.5, aceptable: 0.25 });
    expect(UMBRALES.mejora).toEqual({ buena: 10, aceptable: 3 });
    expect(UMBRALES.maeRelativo).toEqual({ buena: 0.15, aceptable: 0.3 });
  });
});

describe('interpretarMetrica: R²', () => {
  it.each([
    [0.6, 'Buena'],
    [0.95, 'Buena'],
    [0.5999, 'Aceptable'],
    [0.3, 'Aceptable'],
    [0.2999, 'Débil'],
    [0, 'Débil'],
    [-0.5, 'Débil'],
  ])('R² %s es %s', (valor, etiqueta) => {
    expect(interpretarMetrica('r2', valor).etiqueta).toBe(etiqueta);
  });

  it('con R² positivo dice cuánto explica; con R² negativo dice la verdad', () => {
    expect(interpretarMetrica('r2', 0.42).frase).toBe('El modelo explica el 42 % de las variaciones de la demanda.');
    const negativo = interpretarMetrica('r2', -0.00328);
    expect(negativo.frase).toBe('Todavía no explica la demanda mejor que un promedio simple.');
    // Un valor que redondea a cero no se muestra como "-0,00".
    expect(negativo.valorTexto).toBe('0,00');
    expect(negativo.etiqueta).toBe('Débil');
  });
});

describe('interpretarMetrica: silhouette', () => {
  it.each([
    [0.5, 'Buena'],
    [0.553603, 'Buena'],
    [0.4999, 'Aceptable'],
    [0.25, 'Aceptable'],
    [0.2499, 'Débil'],
    [-0.1, 'Débil'],
  ])('silhouette %s es %s', (valor, etiqueta) => {
    expect(interpretarMetrica('silhouette', valor).etiqueta).toBe(etiqueta);
  });

  it('explica el rango y el umbral en una línea', () => {
    expect(interpretarMetrica('silhouette', 0.55).frase).toContain('de −1 a 1');
    expect(interpretarMetrica('silhouette', 0.55).frase).toContain('más de 0,5 es bueno');
  });
});

describe('interpretarMetrica: mejora contra el promedio móvil', () => {
  it.each([
    [10, 'Buena'],
    [25, 'Buena'],
    [9.99, 'Aceptable'],
    [3, 'Aceptable'],
    [2.99, 'Débil'],
    [0, 'Débil'],
    [-4, 'Débil'],
  ])('una mejora de %s por ciento es %s', (valor, etiqueta) => {
    expect(interpretarMetrica('mejora_mae_pct', valor).etiqueta).toBe(etiqueta);
  });

  it('una mejora positiva se dice con su porcentaje', () => {
    const m = interpretarMetrica('mejora_mae_pct', 5.224);
    expect(m.frase).toBe('El modelo mejora en 5,2 % al promedio móvil simple.');
    expect(m.valorTexto).toBe('5,2 %');
  });

  it('una mejora negativa NO dice que mejora: dice "todavía no supera al promedio móvil"', () => {
    const m = interpretarMetrica('mejora_mae_pct', -3.5);
    expect(m.frase).toMatch(/^Todavía no supera al promedio móvil/);
    expect(m.frase).not.toMatch(/mejora en/);
    expect(m.etiqueta).toBe('Débil');
  });

  it('una mejora de cero no inventa ventaja', () => {
    expect(interpretarMetrica('mejora_mae_pct', 0).frase).toBe('Rinde igual que el promedio móvil simple.');
  });
});

describe('interpretarMetrica: MAE relativo', () => {
  it('maeRelativo divide el MAE entre el promedio semanal y no inventa con datos faltantes', () => {
    expect(maeRelativo(3, 10)).toBeCloseTo(0.3, 10);
    expect(maeRelativo(null, 10)).toBeNull();
    expect(maeRelativo(3, null)).toBeNull();
    expect(maeRelativo(3, 0)).toBeNull();
    expect(maeRelativo(3, -2)).toBeNull();
  });

  it.each([
    [15, 'Buena'], // 0,15 exacto
    [14, 'Buena'],
    [16, 'Aceptable'],
    [30, 'Aceptable'], // 0,30 exacto
    [31, 'Débil'],
    [90, 'Débil'],
  ])('MAE %s con promedio semanal de 100 es %s', (mae, etiqueta) => {
    expect(interpretarMetrica('mae', mae, { promedioSemanal: 100 }).etiqueta).toBe(etiqueta);
  });

  it('sin promedio semanal el MAE se muestra pero NO se califica', () => {
    const m = interpretarMetrica('mae', 2.88);
    expect(m.etiqueta).toBeNull();
    expect(m.calidad).toBeNull();
    expect(m.frase).toBe('En promedio la predicción se equivoca en 2,9 unidades por categoría y semana.');
  });

  it('con promedio semanal la frase dice a cuánto equivale', () => {
    const m = interpretarMetrica('mae', 2.88, { promedioSemanal: 7 });
    expect(m.frase).toContain('2,9 unidades por categoría y semana');
    expect(m.frase).toContain('41 % de lo que vende una categoría en una semana típica');
    expect(m.etiqueta).toBe('Débil');
  });
});

describe('interpretarMetrica: RMSE y datos faltantes', () => {
  it('el RMSE nunca lleva etiqueta (depende de la escala)', () => {
    const m = interpretarMetrica('rmse', 3.88, { promedioSemanal: 10 });
    expect(m.etiqueta).toBeNull();
    expect(m.valorTexto).toBe('3,88');
    expect(m.frase).toBe('Parecido al MAE, pero castiga más los errores grandes.');
  });

  it('un valor nulo o no numérico se muestra como "—" y sin etiqueta', () => {
    for (const nombre of ['mae', 'rmse', 'r2', 'silhouette', 'mejora_mae_pct'] as const) {
      const m = interpretarMetrica(nombre, null);
      expect(m.valorTexto).toBe('—');
      expect(m.etiqueta).toBeNull();
      expect(m.valor).toBeNull();
    }
    expect(interpretarMetrica('r2', Number.NaN).valorTexto).toBe('—');
    expect(calidadDeMetrica('r2', Number.POSITIVE_INFINITY)).toBeNull();
  });

  it('todas las métricas traen título y ayuda para el tooltip', () => {
    for (const nombre of ['mae', 'rmse', 'r2', 'silhouette', 'mejora_mae_pct'] as const) {
      const m = interpretarMetrica(nombre, 1);
      expect(m.titulo.length).toBeGreaterThan(3);
      expect(m.ayuda.length).toBeGreaterThan(20);
    }
  });

  it('las etiquetas de calidad son las tres del diseño', () => {
    expect(ETIQUETA_CALIDAD).toEqual({ buena: 'Buena', aceptable: 'Aceptable', debil: 'Débil' });
  });

  it('nunca habla de "intervalo de confianza"', () => {
    for (const nombre of ['mae', 'rmse', 'r2', 'silhouette', 'mejora_mae_pct'] as const) {
      const m = interpretarMetrica(nombre, 0.4, { promedioSemanal: 5 });
      expect(`${m.titulo} ${m.frase} ${m.ayuda}`.toLowerCase()).not.toContain('intervalo de confianza');
    }
  });
});
