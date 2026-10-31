import type { ChartData } from 'chart.js';
import { DemandaCategoria, SegmentoCliente } from '../../core/models/analitica.models';
import { formatearEntero } from '../../shared/graficos/formato-reporte';
import { opcionesCircular, opcionesLineas } from '../../shared/graficos/opciones-grafico';
import { MAX_SERIES, colorDeEntidad, estiloAnillo, paletaSeries } from '../../shared/graficos/paleta-graficos';

/**
 * Arma los datos de los gráficos de la analítica. Funciones PURAS: solo dibujan lo que llegó del servidor. El "rango
 * estimado" es la banda entre el mínimo y el máximo que manda el servidor para cada semana prevista (± el error típico
 * del modelo); no se presenta como una garantía.
 */

export const ETIQUETA_REAL = 'Ventas reales';
export const ETIQUETA_PREDICCION = 'Predicción';
export const ETIQUETA_RANGO = 'Rango estimado';
/** La parte de abajo de la banda: existe para rellenar entre los dos bordes y no sale en la leyenda ni en el tooltip. */
export const ETIQUETA_RANGO_MINIMO = 'Rango estimado (mínimo)';

/** `2026-10-26` → `26/10`. Un texto que no es una fecha ISO se deja tal cual. */
export function etiquetaSemana(iso: string): string {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[2]}/${m[1]}` : iso;
}

/** Un color `#rgb`/`#rrggbb` con transparencia; cualquier otro formato se devuelve igual. */
export function conAlfa(color: string, alfa: number): string {
  const corto = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(color);
  const largo = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color);
  let canales: number[] | null = null;
  if (largo) canales = [largo[1], largo[2], largo[3]].map((h) => parseInt(h, 16));
  else if (corto) canales = [corto[1], corto[2], corto[3]].map((h) => parseInt(h + h, 16));
  return canales ? `rgba(${canales[0]}, ${canales[1]}, ${canales[2]}, ${alfa})` : color;
}

interface ContextoTooltip {
  dataset: { label?: string };
  dataIndex: number;
  parsed?: { y?: number | null } | number;
  chart: { data: { datasets: { data: (number | null)[] }[] } };
}

export interface GraficoDemanda {
  data: ChartData;
  options: Record<string, unknown>;
  /** Para el `aria-label` del canvas (un lector de pantalla no lee un gráfico). */
  resumen: string;
}

/**
 * Histórico (línea sólida) + predicción (línea punteada del mismo tono, unida al último punto real) + el rango estimado
 * como banda suave. Los puntos de la predicción nunca se mezclan con los reales.
 */
export function construirGraficoDemanda(categoria: DemandaCategoria): GraficoDemanda {
  const historico = categoria.historico;
  const prediccion = categoria.prediccion;
  const n = historico.length;
  const m = prediccion.length;
  const labels = [...historico, ...prediccion].map((p) => etiquetaSemana(p.etiqueta));

  const hueco = (cuantos: number): null[] => Array.from({ length: Math.max(0, cuantos) }, () => null);
  const ultimoReal = n > 0 ? historico[n - 1].valor : null;
  // La línea punteada y la banda arrancan en el último punto real para que se vean unidas.
  const empalme = ultimoReal === null ? [] : [ultimoReal];

  const reales = [...historico.map((p) => p.valor), ...hueco(m)];
  const prevista = [...hueco(n - 1), ...empalme, ...prediccion.map((p) => p.valor)];
  const maximos = [...hueco(n - 1), ...empalme, ...prediccion.map((p) => p.maximo ?? p.valor)];
  const minimos = [...hueco(n - 1), ...empalme, ...prediccion.map((p) => p.minimo ?? p.valor)];

  const color = paletaSeries()[0];
  const banda = conAlfa(color, 0.16);
  const indiceEmpalme = n - 1;

  const datasets: Record<string, unknown>[] = [
    {
      label: ETIQUETA_REAL,
      data: reales,
      borderColor: color,
      backgroundColor: color,
      tension: 0.25,
      pointRadius: 3,
      fill: false,
      spanGaps: false,
    },
    {
      label: ETIQUETA_PREDICCION,
      data: prevista,
      borderColor: color,
      backgroundColor: color,
      borderDash: [6, 4],
      tension: 0.25,
      pointRadius: 3,
      pointStyle: 'rectRot',
      fill: false,
      spanGaps: false,
    },
    {
      label: ETIQUETA_RANGO,
      data: maximos,
      borderColor: 'transparent',
      backgroundColor: banda,
      pointRadius: 0,
      pointHoverRadius: 0,
      tension: 0.25,
      fill: '+1',
      spanGaps: false,
    },
    {
      label: ETIQUETA_RANGO_MINIMO,
      data: minimos,
      borderColor: 'transparent',
      backgroundColor: 'transparent',
      pointRadius: 0,
      pointHoverRadius: 0,
      tension: 0.25,
      fill: false,
      spanGaps: false,
    },
  ];

  const base = opcionesLineas(formatearEntero, false);
  const options = {
    ...base,
    plugins: {
      ...base.plugins,
      tooltip: {
        ...base.plugins.tooltip,
        // Sin la parte de abajo de la banda y sin repetir el empalme (ya sale como venta real).
        filter: (item: ContextoTooltip) =>
          item.dataset.label !== ETIQUETA_RANGO_MINIMO && !(item.dataset.label === ETIQUETA_PREDICCION && item.dataIndex === indiceEmpalme),
        callbacks: {
          label: (ctx: ContextoTooltip) => {
            const valor = typeof ctx.parsed === 'number' ? ctx.parsed : (ctx.parsed?.y ?? null);
            if (valor === null) return '';
            if (ctx.dataset.label === ETIQUETA_RANGO) {
              const minimo = ctx.chart.data.datasets[3]?.data[ctx.dataIndex];
              return typeof minimo === 'number'
                ? `${ETIQUETA_RANGO}: de ${formatearEntero(minimo)} a ${formatearEntero(valor)}`
                : `${ETIQUETA_RANGO}: hasta ${formatearEntero(valor)}`;
            }
            return `${ctx.dataset.label}: ${formatearEntero(valor)}`;
          },
        },
      },
    },
  };

  const resumen =
    `Gráfico de líneas de ${categoria.categoria}: unidades vendidas por semana en las últimas ${n} semanas ` +
    `y predicción de las próximas ${m}, con su rango estimado. Total previsto: ${formatearEntero(categoria.total_predicho)} unidades.`;

  return { data: { labels, datasets } as unknown as ChartData, options, resumen };
}

export interface GraficoSegmentos {
  data: ChartData;
  options: Record<string, unknown>;
  resumen: string;
  /** Los que se dibujan (máximo 6, la paleta no distingue más). */
  segmentos: SegmentoCliente[];
  recortado: boolean;
}

/** Anillo con el tamaño de cada segmento. La leyenda va aparte, en texto, con las cantidades. */
export function construirGraficoSegmentos(segmentos: SegmentoCliente[]): GraficoSegmentos {
  const dibujados = segmentos.slice(0, MAX_SERIES);
  const base = opcionesCircular(formatearEntero);
  const options = { ...base, plugins: { ...base.plugins, legend: { ...base.plugins.legend, display: false } } };
  const resumen =
    `Gráfico circular de los grupos de clientes: ` +
    dibujados.map((s) => `${s.nombre} ${formatearEntero(s.clientes)} clientes`).join(', ') +
    '.';
  return {
    data: {
      labels: dibujados.map((s) => s.nombre),
      datasets: [
        {
          data: dibujados.map((s) => s.clientes),
          backgroundColor: dibujados.map((s) => colorDeEntidad(s.nombre)),
          ...estiloAnillo(),
        },
      ],
    } as ChartData,
    options,
    resumen,
    segmentos: dibujados,
    recortado: segmentos.length > dibujados.length,
  };
}
