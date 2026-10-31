import { DemandaCategoria, PuntoSerie, SegmentoCliente } from '../../core/models/analitica.models';
import { reiniciarColores } from '../../shared/graficos/paleta-graficos';
import {
  ETIQUETA_PREDICCION,
  ETIQUETA_RANGO,
  ETIQUETA_RANGO_MINIMO,
  ETIQUETA_REAL,
  conAlfa,
  construirGraficoDemanda,
  construirGraficoSegmentos,
  etiquetaSemana,
} from './graficos-analitica';

function real(etiqueta: string, valor: number): PuntoSerie {
  return { etiqueta, valor, minimo: null, maximo: null, es_prediccion: false };
}
function prevista(etiqueta: string, valor: number, minimo: number, maximo: number): PuntoSerie {
  return { etiqueta, valor, minimo, maximo, es_prediccion: true };
}

const CATEGORIA: DemandaCategoria = {
  categoria_id: 4,
  categoria: 'Camisetas deportivas',
  historico: [real('2026-10-05', 7), real('2026-10-12', 6), real('2026-10-19', 8)],
  prediccion: [prevista('2026-10-26', 14, 10, 18), prevista('2026-11-02', 15, 11, 19)],
  total_predicho: 29,
  variacion_pct_vs_ultimas_semanas: 19.1,
};

describe('etiquetaSemana y conAlfa', () => {
  it('la fecha ISO se escribe dd/mm', () => {
    expect(etiquetaSemana('2026-10-26')).toBe('26/10');
    expect(etiquetaSemana('algo raro')).toBe('algo raro');
  });

  it('un color hexadecimal se vuelve rgba y lo demás se deja igual', () => {
    expect(conAlfa('#5d6b34', 0.16)).toBe('rgba(93, 107, 52, 0.16)');
    expect(conAlfa('#fff', 0.5)).toBe('rgba(255, 255, 255, 0.5)');
    expect(conAlfa('rgb(1, 2, 3)', 0.5)).toBe('rgb(1, 2, 3)');
  });
});

describe('construirGraficoDemanda', () => {
  const g = construirGraficoDemanda(CATEGORIA);
  const datasets = g.data.datasets as unknown as { label: string; data: (number | null)[]; borderDash?: number[]; borderColor: string; fill: unknown }[];
  const porNombre = (nombre: string) => datasets.find((d) => d.label === nombre)!;

  it('las etiquetas son las semanas del histórico y de la predicción, en dd/mm', () => {
    expect(g.data.labels).toEqual(['05/10', '12/10', '19/10', '26/10', '02/11']);
  });

  it('el histórico es una línea sólida y la predicción una línea punteada del mismo tono', () => {
    const reales = porNombre(ETIQUETA_REAL);
    const futura = porNombre(ETIQUETA_PREDICCION);
    expect(reales.borderDash).toBeUndefined();
    expect(futura.borderDash).toEqual([6, 4]);
    expect(futura.borderColor).toBe(reales.borderColor);
    expect(reales.data).toEqual([7, 6, 8, null, null]);
  });

  it('la predicción arranca en el último punto real para verse unida', () => {
    expect(porNombre(ETIQUETA_PREDICCION).data).toEqual([null, null, 8, 14, 15]);
  });

  it('el rango estimado es una banda entre el máximo y el mínimo', () => {
    const maximo = porNombre(ETIQUETA_RANGO);
    const minimo = porNombre(ETIQUETA_RANGO_MINIMO);
    expect(maximo.data).toEqual([null, null, 8, 18, 19]);
    expect(minimo.data).toEqual([null, null, 8, 10, 11]);
    // Rellena hacia el dataset siguiente (el mínimo).
    expect(maximo.fill).toBe('+1');
    expect(datasets.indexOf(minimo)).toBe(datasets.indexOf(maximo) + 1);
    expect(minimo.fill).toBe(false);
  });

  it('nada del gráfico habla de "intervalo de confianza"', () => {
    const texto = JSON.stringify({ labels: g.data.labels, datasets: datasets.map((d) => d.label) }) + g.resumen;
    expect(texto.toLowerCase()).not.toContain('intervalo de confianza');
    expect(g.resumen).toContain('rango estimado');
    expect(g.resumen).toContain('Camisetas deportivas');
  });

  it('el tooltip esconde la parte baja de la banda y el empalme, y escribe el rango completo', () => {
    const tooltip = (g.options as { plugins: { tooltip: { filter: (i: unknown) => boolean; callbacks: { label: (c: unknown) => string } } } }).plugins.tooltip;
    const item = (label: string, dataIndex: number) => ({ dataset: { label }, dataIndex });
    expect(tooltip.filter(item(ETIQUETA_RANGO_MINIMO, 3))).toBe(false);
    expect(tooltip.filter(item(ETIQUETA_PREDICCION, 2))).toBe(false); // el empalme con el último real
    expect(tooltip.filter(item(ETIQUETA_PREDICCION, 3))).toBe(true);
    expect(tooltip.filter(item(ETIQUETA_REAL, 2))).toBe(true);

    const contexto = { dataset: { label: ETIQUETA_RANGO }, dataIndex: 3, parsed: { y: 18 }, chart: { data: { datasets } } };
    expect(tooltip.callbacks.label(contexto)).toBe('Rango estimado: de 10 a 18');
    expect(tooltip.callbacks.label({ dataset: { label: ETIQUETA_PREDICCION }, dataIndex: 3, parsed: { y: 14 }, chart: { data: { datasets } } })).toBe(
      'Predicción: 14',
    );
  });

  it('sin histórico no se rompe: solo se ve la predicción', () => {
    const sin = construirGraficoDemanda({ ...CATEGORIA, historico: [] });
    const futura = (sin.data.datasets as unknown as { label: string; data: (number | null)[] }[]).find((d) => d.label === ETIQUETA_PREDICCION)!;
    expect(sin.data.labels).toEqual(['26/10', '02/11']);
    expect(futura.data).toEqual([14, 15]);
  });
});

describe('construirGraficoSegmentos', () => {
  beforeEach(() => reiniciarColores());

  function segmento(id: number, nombre: string, clientes: number): SegmentoCliente {
    return {
      id,
      nombre,
      descripcion: 'd',
      accion_sugerida: 'a',
      clientes,
      porcentaje_clientes: 10,
      recencia_media_dias: 10,
      frecuencia_media: 2,
      monto_medio: 100,
      monto_total: 1000,
      porcentaje_monto: 10,
    };
  }

  it('dibuja un anillo con los clientes de cada segmento y un color estable por nombre', () => {
    const g = construirGraficoSegmentos([segmento(0, 'Campeones', 22), segmento(1, 'En riesgo', 16)]);
    expect(g.data.labels).toEqual(['Campeones', 'En riesgo']);
    const ds = g.data.datasets[0] as unknown as { data: number[]; backgroundColor: string[] };
    expect(ds.data).toEqual([22, 16]);
    expect(ds.backgroundColor[0]).not.toBe(ds.backgroundColor[1]);
    // El mismo nombre conserva el color en otra construcción.
    const otra = construirGraficoSegmentos([segmento(5, 'En riesgo', 3), segmento(6, 'Campeones', 4)]);
    const ds2 = otra.data.datasets[0] as unknown as { backgroundColor: string[] };
    expect(ds2.backgroundColor).toEqual([ds.backgroundColor[1], ds.backgroundColor[0]]);
    expect(g.resumen).toContain('Campeones 22 clientes');
    expect(g.recortado).toBe(false);
  });

  it('recorta a 6 segmentos y lo avisa; la leyenda del canvas se apaga (va una de texto aparte)', () => {
    const muchos = Array.from({ length: 8 }, (_, i) => segmento(i, `Grupo ${i}`, 10 + i));
    const g = construirGraficoSegmentos(muchos);
    expect(g.segmentos.length).toBe(6);
    expect(g.recortado).toBe(true);
    expect((g.options as { plugins: { legend: { display: boolean } } }).plugins.legend.display).toBe(false);
  });
});
