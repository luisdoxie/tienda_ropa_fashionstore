import { FUENTE, coloresBase, estiloTooltip } from './paleta-graficos';

/** Cómo escribir una cifra en el tooltip y en el eje de valores (p. ej. "Bs 1.234,50"). */
export type FormatoValor = (n: number) => string;

const IDENTIDAD: FormatoValor = (n) => String(n);

interface ContextoTooltip {
  dataset?: { label?: string };
  label?: string;
  parsed?: number | { x?: number | null; y?: number | null };
}

/** El valor numérico de un punto sin importar si el gráfico es de barras horizontales, de líneas o de torta. */
function valorDe(ctx: ContextoTooltip, horizontal: boolean): number | null {
  const p = ctx.parsed;
  if (typeof p === 'number') return p;
  if (p == null) return null;
  const v = horizontal ? p.x : p.y;
  return typeof v === 'number' ? v : null;
}

function tooltipConFormato(formato: FormatoValor, horizontal = false) {
  return {
    ...estiloTooltip(),
    callbacks: {
      label: (ctx: ContextoTooltip) => {
        const valor = valorDe(ctx, horizontal);
        const texto = valor === null ? '—' : formato(valor);
        const nombre = ctx.dataset?.label ?? ctx.label;
        return nombre ? `${nombre}: ${texto}` : texto;
      },
    },
  };
}

function leyenda(mostrar: boolean, posicion: 'top' | 'right' | 'bottom' = 'top') {
  const c = coloresBase();
  return {
    display: mostrar,
    position: posicion,
    labels: { color: c.texto, font: FUENTE, usePointStyle: true, pointStyle: 'circle' as const, boxWidth: 8, boxHeight: 8, padding: 14 },
  };
}

/** Barras con rejilla suave. Leyenda solo si hay varias series (barras agrupadas). */
export function opcionesBarras(horizontal: boolean, formato: FormatoValor = IDENTIDAD, conLeyenda = false) {
  const c = coloresBase();
  const ejeValor = {
    beginAtZero: true,
    grid: { color: c.rejilla },
    border: { display: false },
    ticks: { color: c.tenue, font: FUENTE, callback: (valor: string | number) => formato(Number(valor)) },
  };
  const ejeCategoria = {
    grid: { display: false },
    border: { color: c.rejilla },
    ticks: { color: c.tenue, font: FUENTE, autoSkip: false },
  };
  return {
    maintainAspectRatio: false,
    indexAxis: horizontal ? ('y' as const) : ('x' as const),
    plugins: { legend: leyenda(conLeyenda), tooltip: tooltipConFormato(formato, horizontal) },
    scales: horizontal ? { x: ejeValor, y: ejeCategoria } : { x: ejeCategoria, y: ejeValor },
  };
}

/** Líneas con puntos visibles (hay pocos puntos y cada uno es un dato). */
export function opcionesLineas(formato: FormatoValor = IDENTIDAD, conLeyenda = true) {
  const c = coloresBase();
  return {
    maintainAspectRatio: false,
    interaction: { mode: 'index' as const, intersect: false },
    plugins: { legend: leyenda(conLeyenda), tooltip: tooltipConFormato(formato) },
    scales: {
      x: { grid: { display: false }, border: { color: c.rejilla }, ticks: { color: c.tenue, font: FUENTE, maxRotation: 0, autoSkipPadding: 12 } },
      y: {
        beginAtZero: true,
        grid: { color: c.rejilla },
        border: { display: false },
        ticks: { color: c.tenue, font: FUENTE, callback: (valor: string | number) => formato(Number(valor)) },
      },
    },
  };
}

/** Anillo delgado con la leyenda al costado. */
export function opcionesCircular(formato: FormatoValor = IDENTIDAD) {
  return {
    maintainAspectRatio: false,
    cutout: '64%',
    layout: { padding: 8 },
    plugins: { legend: leyenda(true, 'right'), tooltip: tooltipConFormato(formato) },
  };
}
