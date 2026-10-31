/**
 * Las métricas de los modelos en lenguaje simple (E17b). Funciones PURAS: el web no calcula nada de Machine Learning, solo
 * traduce las cifras que el servidor ya calculó a una frase, una ayuda y una etiqueta de calidad (Buena, Aceptable, Débil).
 *
 * UMBRALES (están aquí, a la vista, y `explicacion-metricas.spec.ts` los prueba en sus bordes):
 *
 * - R² (cuánto de la variación de la demanda explica el modelo): >= 0,60 Buena; >= 0,30 Aceptable; si no, Débil.
 *   Un R² negativo significa que no explica la demanda mejor que un promedio simple.
 * - Silhouette (qué tan separados están los grupos de clientes, de -1 a 1): >= 0,50 Buena; >= 0,25 Aceptable (0,25 es el
 *   mínimo que exige el backend para dar un modelo por válido); si no, Débil.
 * - Mejora contra el promedio móvil de 4 semanas (en %): >= 10 Buena; >= 3 Aceptable; si no, Débil. Negativa = el modelo
 *   se equivoca MÁS que el promedio móvil simple.
 * - MAE relativo = MAE / promedio semanal histórico de una categoría: <= 0,15 Buena; <= 0,30 Aceptable; si no, Débil.
 *   El MAE del servidor es POR CATEGORÍA Y SEMANA, así que se compara con lo que vende una categoría en una semana típica
 *   (no con el total de la empresa, que lo haría parecer mucho mejor de lo que es).
 * - RMSE: sin etiqueta, porque depende de la escala de las unidades.
 */

export type NombreMetrica = 'mae' | 'rmse' | 'r2' | 'silhouette' | 'mejora_mae_pct';
export type CalidadMetrica = 'buena' | 'aceptable' | 'debil';

export const UMBRALES = {
  /** R²: mayor o igual es mejor. */
  r2: { buena: 0.6, aceptable: 0.3 },
  /** Silhouette: mayor o igual es mejor. */
  silhouette: { buena: 0.5, aceptable: 0.25 },
  /** Mejora del MAE contra el promedio móvil, en %: mayor o igual es mejor. */
  mejora: { buena: 10, aceptable: 3 },
  /** MAE / promedio semanal de una categoría: MENOR o igual es mejor. */
  maeRelativo: { buena: 0.15, aceptable: 0.3 },
} as const;

export const ETIQUETA_CALIDAD: Record<CalidadMetrica, string> = {
  buena: 'Buena',
  aceptable: 'Aceptable',
  debil: 'Débil',
};

export interface ContextoMetrica {
  /** Promedio de unidades que vende una categoría en una semana (de su historial real). Sin él, el MAE no lleva etiqueta. */
  promedioSemanal?: number | null;
}

export interface InterpretacionMetrica {
  nombre: NombreMetrica;
  titulo: string;
  valor: number | null;
  /** El valor como se muestra ("2,88", "-0,10", "5,2 %", "—"). */
  valorTexto: string;
  /** Una línea en lenguaje simple. */
  frase: string;
  /** Explicación para el tooltip. */
  ayuda: string;
  calidad: CalidadMetrica | null;
  /** "Buena", "Aceptable", "Débil" o null cuando la métrica no se califica. */
  etiqueta: string | null;
}

const TITULOS: Record<NombreMetrica, string> = {
  mae: 'Error promedio (MAE)',
  rmse: 'Error con peso en los grandes (RMSE)',
  r2: 'Variación explicada (R²)',
  silhouette: 'Separación de los grupos (silhouette)',
  mejora_mae_pct: 'Mejora contra el promedio móvil',
};

const AYUDAS: Record<NombreMetrica, string> = {
  mae: 'Cuántas unidades se equivoca la predicción, en promedio, por categoría y semana. Cuanto menos, mejor.',
  rmse: 'Como el MAE, pero los errores grandes pesan más. Cuanto menos, mejor; depende de la escala de las unidades.',
  r2: 'Qué parte de las subidas y bajadas de la demanda explica el modelo. Va hasta 1; si es negativo, un promedio simple lo hace mejor.',
  silhouette: 'Qué tan separados están los grupos de clientes, de -1 a 1. Más de 0,5 es bueno; menos de 0,25 no se considera válido.',
  mejora_mae_pct: 'Compara el error del modelo con el de un promedio móvil simple de las últimas 4 semanas. Positivo: el modelo lo mejora.',
};

/** Un número en es-BO con los decimales pedidos; un valor que redondea a cero nunca sale como "-0,00". */
function numero(n: number, decimales: number): string {
  const factor = 10 ** decimales;
  const redondeado = Math.round(n * factor) / factor;
  return (redondeado === 0 ? 0 : redondeado).toLocaleString('es-BO', {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

function calidadMayorEsMejor(valor: number, buena: number, aceptable: number): CalidadMetrica {
  if (valor >= buena) return 'buena';
  if (valor >= aceptable) return 'aceptable';
  return 'debil';
}

function calidadMenorEsMejor(valor: number, buena: number, aceptable: number): CalidadMetrica {
  if (valor <= buena) return 'buena';
  if (valor <= aceptable) return 'aceptable';
  return 'debil';
}

/** MAE / promedio semanal, o null si no hay un promedio con el que compararlo. */
export function maeRelativo(mae: number | null, promedioSemanal: number | null | undefined): number | null {
  if (mae === null || !Number.isFinite(mae)) return null;
  if (promedioSemanal == null || !Number.isFinite(promedioSemanal) || promedioSemanal <= 0) return null;
  return mae / promedioSemanal;
}

/** La calidad de una métrica según los umbrales de este archivo; null si no se califica o no hay dato. */
export function calidadDeMetrica(nombre: NombreMetrica, valor: number | null, contexto: ContextoMetrica = {}): CalidadMetrica | null {
  if (valor === null || !Number.isFinite(valor)) return null;
  switch (nombre) {
    case 'r2':
      return calidadMayorEsMejor(valor, UMBRALES.r2.buena, UMBRALES.r2.aceptable);
    case 'silhouette':
      return calidadMayorEsMejor(valor, UMBRALES.silhouette.buena, UMBRALES.silhouette.aceptable);
    case 'mejora_mae_pct':
      return calidadMayorEsMejor(valor, UMBRALES.mejora.buena, UMBRALES.mejora.aceptable);
    case 'mae': {
      const relativo = maeRelativo(valor, contexto.promedioSemanal);
      return relativo === null ? null : calidadMenorEsMejor(relativo, UMBRALES.maeRelativo.buena, UMBRALES.maeRelativo.aceptable);
    }
    case 'rmse':
      return null;
  }
}

function frase(nombre: NombreMetrica, valor: number, contexto: ContextoMetrica): string {
  switch (nombre) {
    case 'mae': {
      const base = `En promedio la predicción se equivoca en ${numero(valor, 1)} unidades por categoría y semana`;
      const relativo = maeRelativo(valor, contexto.promedioSemanal);
      return relativo === null
        ? `${base}.`
        : `${base} (${numero(relativo * 100, 0)} % de lo que vende una categoría en una semana típica).`;
    }
    case 'rmse':
      return 'Parecido al MAE, pero castiga más los errores grandes.';
    case 'r2':
      return valor < 0
        ? 'Todavía no explica la demanda mejor que un promedio simple.'
        : `El modelo explica el ${numero(valor * 100, 0)} % de las variaciones de la demanda.`;
    case 'silhouette':
      return 'Qué tan separados están los grupos de clientes, de −1 a 1; más de 0,5 es bueno.';
    case 'mejora_mae_pct':
      if (valor < 0) return `Todavía no supera al promedio móvil simple: se equivoca ${numero(-valor, 1)} % más.`;
      if (valor === 0) return 'Rinde igual que el promedio móvil simple.';
      return `El modelo mejora en ${numero(valor, 1)} % al promedio móvil simple.`;
  }
}

function valorTexto(nombre: NombreMetrica, valor: number): string {
  switch (nombre) {
    case 'mae':
    case 'rmse':
      return numero(valor, 2);
    case 'mejora_mae_pct':
      return `${numero(valor, 1)} %`;
    default:
      return numero(valor, 2);
  }
}

/** Una métrica lista para mostrar: valor, frase de una línea, ayuda y etiqueta de calidad. Pura y sin efectos. */
export function interpretarMetrica(nombre: NombreMetrica, valor: number | null, contexto: ContextoMetrica = {}): InterpretacionMetrica {
  const base = { nombre, titulo: TITULOS[nombre], ayuda: AYUDAS[nombre] };
  if (valor === null || !Number.isFinite(valor)) {
    return { ...base, valor: null, valorTexto: '—', frase: 'Todavía no hay un dato para esta métrica.', calidad: null, etiqueta: null };
  }
  const calidad = calidadDeMetrica(nombre, valor, contexto);
  return {
    ...base,
    valor,
    valorTexto: valorTexto(nombre, valor),
    frase: frase(nombre, valor, contexto),
    calidad,
    etiqueta: calidad === null ? null : ETIQUETA_CALIDAD[calidad],
  };
}
