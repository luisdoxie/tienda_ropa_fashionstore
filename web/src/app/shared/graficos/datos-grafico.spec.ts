import { ColumnaReporte, FilaReporte, GraficoSugerido, ReporteEjecutado } from '../../core/models/reportes-ia.models';
import {
  MAX_CATEGORIAS_BARRAS,
  construirDatosGrafico,
  ejesDe,
  graficoInicial,
  opcionesDeGrafico,
  vistaInicial,
} from './datos-grafico';
import { MAX_SERIES, colorDeEntidad, reiniciarColores } from './paleta-graficos';

function reporte(
  columnas: ColumnaReporte[],
  filas: FilaReporte[],
  grafico: Partial<GraficoSugerido> = {},
): ReporteEjecutado {
  return {
    codigo: 'prueba',
    titulo: 'Reporte de prueba',
    columnas,
    filas,
    resumen: {},
    grafico_sugerido: { tipo: 'barras', eje_x: null, eje_y: null, serie: null, ...grafico },
    truncado: false,
    generado_en: '2026-10-20T14:05:00Z',
  };
}

const COL_SUCURSAL: ColumnaReporte = { clave: 'sucursal', titulo: 'Sucursal', tipo: 'texto' };
const COL_TOTAL: ColumnaReporte = { clave: 'total_ventas', titulo: 'Total vendido', tipo: 'moneda' };
const COL_TRANS: ColumnaReporte = { clave: 'transacciones', titulo: 'Transacciones', tipo: 'entero' };

function porSucursal(n: number, valor = (i: number) => (i + 1) * 100): ReporteEjecutado {
  return reporte(
    [COL_SUCURSAL, COL_TRANS, COL_TOTAL],
    Array.from({ length: n }, (_, i) => ({ sucursal: `Sucursal ${i + 1}`, transacciones: i + 2, total_ventas: valor(i) })),
    { tipo: 'barras', eje_x: 'sucursal', eje_y: 'total_ventas' },
  );
}

function porSemana(): ReporteEjecutado {
  return reporte(
    [
      { clave: 'periodo', titulo: 'Periodo', tipo: 'texto' },
      { clave: 'desde', titulo: 'Desde', tipo: 'fecha' },
      COL_TRANS,
      COL_TOTAL,
    ],
    [
      { periodo: 'Sem 1', desde: '2026-09-07', transacciones: 3, total_ventas: 300 },
      { periodo: 'Sem 2', desde: '2026-09-14', transacciones: 5, total_ventas: 520 },
      { periodo: 'Sem 3', desde: '2026-09-21', transacciones: 4, total_ventas: 410 },
    ],
    { tipo: 'linea', eje_x: 'periodo', eje_y: 'total_ventas' },
  );
}

function comparacion(nSucursales: number): ReporteEjecutado {
  const filas: FilaReporte[] = [];
  for (const mes of ['Jul', 'Ago', 'Sep']) {
    for (let s = 1; s <= nSucursales; s++) filas.push({ periodo: mes, sucursal: `Suc ${s}`, total_ventas: 100 * s });
  }
  return reporte([{ clave: 'periodo', titulo: 'Periodo', tipo: 'texto' }, COL_SUCURSAL, COL_TOTAL], filas, {
    tipo: 'barras_agrupadas',
    eje_x: 'periodo',
    eje_y: 'total_ventas',
    serie: 'sucursal',
  });
}

const posible = (r: ReporteEjecutado, tipo: string, metrica?: string) =>
  opcionesDeGrafico(r, metrica).find((o) => o.tipo === tipo)!;

describe('datos-grafico', () => {
  beforeEach(() => reiniciarColores());

  describe('opcionesDeGrafico', () => {
    it('siempre devuelve las 5 opciones', () => {
      expect(opcionesDeGrafico(porSucursal(3)).map((o) => o.tipo)).toEqual([
        'barras',
        'barras_horizontales',
        'barras_agrupadas',
        'linea',
        'torta',
      ]);
    });

    it('una serie temporal admite líneas', () => {
      expect(posible(porSemana(), 'linea').posible).toBe(true);
    });

    it('categorías sin tiempo no admiten líneas y lo explican', () => {
      const o = posible(porSucursal(4), 'linea');
      expect(o.posible).toBe(false);
      expect(o.razon).toMatch(/fechas o periodos/);
    });

    it('hasta 12 categorías admiten barras; sin series no admiten barras agrupadas', () => {
      const r = porSucursal(MAX_CATEGORIAS_BARRAS);
      expect(posible(r, 'barras').posible).toBe(true);
      expect(posible(r, 'barras_horizontales').posible).toBe(true);
      expect(posible(r, 'barras_agrupadas')).toMatchObject({ posible: false, razon: expect.stringMatching(/dos o más series/) });
    });

    it('2 a 6 categorías con valores ≥ 0 admiten circular', () => {
      expect(posible(porSucursal(2), 'torta').posible).toBe(true);
      expect(posible(porSucursal(6), 'torta').posible).toBe(true);
    });

    it('con 1 o 7 categorías el circular no se puede y dice cuántas hay', () => {
      expect(posible(porSucursal(7), 'torta')).toMatchObject({ posible: false, razon: 'Circular necesita entre 2 y 6 categorías (hay 7).' });
      expect(posible(porSucursal(1), 'torta').posible).toBe(false);
    });

    it('un valor negativo impide el circular', () => {
      const r = porSucursal(3, (i) => (i === 1 ? -50 : 100));
      expect(posible(r, 'torta')).toMatchObject({ posible: false, razon: expect.stringMatching(/negativos/) });
    });

    it('con varias series solo caben barras agrupadas y líneas', () => {
      const r = comparacion(3);
      expect(posible(r, 'barras_agrupadas').posible).toBe(true);
      expect(posible(r, 'linea').posible).toBe(true);
      expect(posible(r, 'barras').posible).toBe(false);
      expect(posible(r, 'torta').posible).toBe(false);
    });

    it('sin filas ninguna opción es posible', () => {
      const vacio = reporte([COL_SUCURSAL, COL_TOTAL], [], { eje_x: 'sucursal', eje_y: 'total_ventas' });
      expect(opcionesDeGrafico(vacio).every((o) => !o.posible && o.razon === 'No hay datos para graficar.')).toBe(true);
    });

    it('sin columna numérica no se puede graficar', () => {
      const r = reporte([COL_SUCURSAL, { clave: 'estado', titulo: 'Estado', tipo: 'texto' }], [{ sucursal: 'A', estado: 'ok' }]);
      expect(opcionesDeGrafico(r).every((o) => !o.posible)).toBe(true);
    });
  });

  describe('ejesDe', () => {
    it('usa el eje sugerido y deja la posición fuera de las medidas', () => {
      const r = reporte(
        [
          { clave: 'posicion', titulo: 'Posición', tipo: 'entero' },
          { clave: 'producto', titulo: 'Producto', tipo: 'texto' },
          { clave: 'unidades', titulo: 'Unidades', tipo: 'entero' },
          COL_TOTAL,
        ],
        [{ posicion: 1, producto: 'Polera', unidades: 4, total_ventas: 600 }],
        { tipo: 'barras_horizontales', eje_x: 'producto', eje_y: 'total_ventas' },
      );
      const ejes = ejesDe(r);
      expect(ejes.x?.clave).toBe('producto');
      expect(ejes.metricas.map((m) => m.clave)).toEqual(['unidades', 'total_ventas']);
      expect(ejes.metricaPorDefecto?.clave).toBe('total_ventas');
    });

    it('los decimales que llegan como texto cuentan como medida si todo es numérico', () => {
      const r = reporte(
        [{ clave: 'segmento', titulo: 'Segmento', tipo: 'texto' }, { clave: 'frecuencia_media', titulo: 'Compras', tipo: 'texto' }],
        [
          { segmento: 'A', frecuencia_media: '2.5' },
          { segmento: 'B', frecuencia_media: '4,1' },
        ],
        { tipo: 'tabla', eje_x: 'segmento' },
      );
      expect(ejesDe(r).metricas.map((m) => m.clave)).toEqual(['frecuencia_media']);
    });

    it('pide elegir métrica cuando hay medidas de unidades distintas', () => {
      expect(ejesDe(porSucursal(3)).metricas.map((m) => m.clave)).toEqual(['transacciones', 'total_ventas']);
    });
  });

  describe('graficoInicial y vistaInicial', () => {
    it('toma el gráfico sugerido si se puede', () => {
      expect(graficoInicial(porSemana())).toBe('linea');
      expect(vistaInicial(porSemana())).toBe('grafico');
    });

    it('si el sugerido no se puede toma el primero posible', () => {
      const r = porSucursal(8);
      r.grafico_sugerido = { tipo: 'torta', eje_x: 'sucursal', eje_y: 'total_ventas', serie: null };
      expect(graficoInicial(r)).toBe('barras');
    });

    it('un reporte que el servidor sugiere como tabla arranca en tabla', () => {
      const r = porSucursal(3);
      r.grafico_sugerido = { tipo: 'tabla', eje_x: null, eje_y: null, serie: null };
      expect(graficoInicial(r)).toBeNull();
      expect(vistaInicial(r)).toBe('tabla');
    });
  });

  describe('construirDatosGrafico', () => {
    it('devuelve null si ese gráfico no se puede', () => {
      expect(construirDatosGrafico(porSucursal(8), 'torta')).toBeNull();
    });

    it('barras: etiquetas, valores y formato de moneda', () => {
      const d = construirDatosGrafico(porSucursal(3), 'barras')!;
      expect(d.tipoChart).toBe('bar');
      expect(d.data.labels).toEqual(['Sucursal 1', 'Sucursal 2', 'Sucursal 3']);
      expect(d.data.datasets[0]['data']).toEqual([100, 200, 300]);
      expect(d.metrica.clave).toBe('total_ventas');
      expect(d.formato(1234.5)).toBe('Bs 1.234,50');
      expect(d.conLeyenda).toBe(false);
      expect(d.resumen).toBe('Barras: Total vendido por Sucursal, 3 puntos');
    });

    it('con otra métrica grafica solo esa', () => {
      const d = construirDatosGrafico(porSucursal(3), 'barras', 'transacciones')!;
      expect(d.data.datasets[0]['data']).toEqual([2, 3, 4]);
      expect(d.formato(1234)).toBe('1.234');
    });

    it('barras horizontales se marcan como horizontales', () => {
      expect(construirDatosGrafico(porSucursal(3), 'barras_horizontales')!.horizontal).toBe(true);
    });

    it('líneas: una serie temporal sin leyenda propia', () => {
      const d = construirDatosGrafico(porSemana(), 'linea')!;
      expect(d.tipoChart).toBe('line');
      expect(d.data.labels).toEqual(['Sem 1', 'Sem 2', 'Sem 3']);
      expect(d.data.datasets[0]['data']).toEqual([300, 520, 410]);
    });

    it('circular: un color por categoría y leyenda', () => {
      const d = construirDatosGrafico(porSucursal(3), 'torta')!;
      expect(d.tipoChart).toBe('doughnut');
      expect((d.data.datasets[0]['backgroundColor'] as string[]).length).toBe(3);
      expect(d.conLeyenda).toBe(true);
    });

    it('barras agrupadas: un dataset por serie, alineado por categoría', () => {
      const d = construirDatosGrafico(comparacion(2), 'barras_agrupadas')!;
      expect(d.data.labels).toEqual(['Jul', 'Ago', 'Sep']);
      expect(d.data.datasets.map((s) => s['label'])).toEqual(['Suc 1', 'Suc 2']);
      expect(d.data.datasets[1]['data']).toEqual([200, 200, 200]);
      expect(d.conLeyenda).toBe(true);
    });

    it('más de 6 series: deja las 6 de mayor total y avisa', () => {
      const d = construirDatosGrafico(comparacion(MAX_SERIES + 2), 'barras_agrupadas')!;
      expect(d.data.datasets).toHaveLength(MAX_SERIES);
      expect(d.data.datasets.map((s) => s['label'])).not.toContain('Suc 1');
      expect(d.avisos[0]).toMatch(/6 series con mayor total de 8/);
    });

    it('más de 12 categorías en barras: recorta y avisa; las líneas no se recortan', () => {
      const d = construirDatosGrafico(porSucursal(15), 'barras')!;
      expect(d.data.labels).toHaveLength(MAX_CATEGORIAS_BARRAS);
      expect(d.avisos[0]).toMatch(/primeras 12 de 15/);
    });

    it('una categoría repetida sin serie se suma', () => {
      const r = reporte([COL_SUCURSAL, COL_TOTAL], [
        { sucursal: 'A', total_ventas: 10 },
        { sucursal: 'A', total_ventas: 5 },
        { sucursal: 'B', total_ventas: 1 },
      ], { eje_x: 'sucursal', eje_y: 'total_ventas' });
      expect(construirDatosGrafico(r, 'barras')!.data.datasets[0]['data']).toEqual([15, 1]);
    });
  });

  describe('colorDeEntidad', () => {
    it('la misma entidad conserva su color entre reportes', () => {
      const a = construirDatosGrafico(comparacion(2), 'barras_agrupadas')!;
      const b = construirDatosGrafico(comparacion(3), 'linea')!;
      expect(a.data.datasets[0]['backgroundColor']).toBe(b.data.datasets[0]['backgroundColor']);
      expect(a.data.datasets[1]['backgroundColor']).toBe(b.data.datasets[1]['backgroundColor']);
    });

    it('las primeras 6 entidades no se repiten', () => {
      const colores = Array.from({ length: MAX_SERIES }, (_, i) => colorDeEntidad(`E${i}`));
      expect(new Set(colores).size).toBe(MAX_SERIES);
    });

    it('las barras por sucursal usan el color de esa sucursal', () => {
      const barras = construirDatosGrafico(porSucursal(2), 'barras')!;
      const colores = barras.data.datasets[0]['backgroundColor'] as string[];
      expect(colores[0]).toBe(colorDeEntidad('Sucursal 1'));
    });
  });
});
