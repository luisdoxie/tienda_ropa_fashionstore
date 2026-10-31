import { ColumnaReporte, ReporteEjecutado, TipoGraficoServidor } from '../../core/models/reportes-ia.models';
import { aNumero, formatearCelda, formateadorDe } from './formato-reporte';
import { FormatoValor } from './opciones-grafico';
import { ESTILO_BARRA, MAX_SERIES, colorDeEntidad, estiloAnillo, paletaSeries } from './paleta-graficos';

/**
 * Qué gráficos admite un reporte y cómo armar sus datos. Funciones PURAS: el web no decide qué se calcula (eso lo
 * hace el servidor) sino cómo se dibuja lo que llegó. `grafico_sugerido` es solo una sugerencia: aquí se valida contra
 * los datos y nunca se confía en que sea posible.
 */

export type TipoGraficoUi = 'barras' | 'barras_horizontales' | 'barras_agrupadas' | 'linea' | 'torta';

export const TIPOS_GRAFICO: readonly TipoGraficoUi[] = ['barras', 'barras_horizontales', 'barras_agrupadas', 'linea', 'torta'];

export const ETIQUETA_GRAFICO: Record<TipoGraficoUi, string> = {
  barras: 'Barras',
  barras_horizontales: 'Barras horizontales',
  barras_agrupadas: 'Barras agrupadas',
  linea: 'Líneas',
  torta: 'Circular',
};

export const MAX_CATEGORIAS_BARRAS = 12;
export const MIN_CATEGORIAS_TORTA = 2;
export const MAX_CATEGORIAS_TORTA = 6;

/** Columnas cuyo valor es una entidad con color propio (la misma sucursal conserva su color entre reportes). */
const EJES_CON_COLOR = new Set(['sucursal', 'categoria', 'segmento']);
/** Columnas de tiempo: lo que se grafica en líneas. */
const EJES_TEMPORALES = new Set(['periodo', 'fecha', 'desde', 'semana', 'mes', 'dia']);
/** Numéricas que no son una medida (un número de orden no se grafica). */
const NO_SON_MEDIDAS = new Set(['posicion']);

export interface OpcionGrafico {
  tipo: TipoGraficoUi;
  etiqueta: string;
  posible: boolean;
  /** Por qué no se puede (null si se puede). */
  razon: string | null;
}

export interface EjesReporte {
  x: ColumnaReporte | null;
  serie: ColumnaReporte | null;
  /** Medidas que se pueden graficar (de a una por vez: no se mezclan unidades distintas). */
  metricas: ColumnaReporte[];
  /** La que sugiere el servidor si es graficable; si no, la primera. */
  metricaPorDefecto: ColumnaReporte | null;
}

export interface DatosGrafico {
  /** Tipo de `p-chart`. */
  tipoChart: 'bar' | 'line' | 'doughnut';
  data: { labels: string[]; datasets: Record<string, unknown>[] };
  horizontal: boolean;
  conLeyenda: boolean;
  formato: FormatoValor;
  metrica: ColumnaReporte;
  /** Resumen para el `aria-label`: un canvas no lo lee un lector de pantalla (la vista Tabla siempre existe). */
  resumen: string;
  /** Recortes hechos (más de 12 categorías, más de 6 series...). */
  avisos: string[];
}

function esNumerica(columna: ColumnaReporte, reporte: ReporteEjecutado): boolean {
  if (columna.tipo === 'entero' || columna.tipo === 'moneda' || columna.tipo === 'porcentaje') return true;
  if (columna.tipo !== 'texto') return false;
  // Los decimales de los reportes de ML llegan como texto: cuenta como medida si TODO lo que trae es un número.
  const valores = reporte.filas.map((f) => f[columna.clave]).filter((v) => v !== null && v !== undefined && v !== '');
  return valores.length > 0 && valores.every((v) => aNumero(v) !== null);
}

export function ejesDe(reporte: ReporteEjecutado): EjesReporte {
  const g = reporte.grafico_sugerido;
  const columnas = reporte.columnas;
  const porClave = (clave: string | null) => columnas.find((c) => c.clave === clave) ?? null;

  const x = porClave(g.eje_x) ?? columnas.find((c) => c.tipo === 'texto' || c.tipo === 'fecha') ?? null;
  const serie = g.serie ? porClave(g.serie) : null;
  const metricas = columnas.filter(
    (c) => c !== x && c !== serie && !NO_SON_MEDIDAS.has(c.clave) && esNumerica(c, reporte),
  );
  const metricaPorDefecto = metricas.find((c) => c.clave === g.eje_y) ?? metricas[0] ?? null;
  return { x, serie, metricas, metricaPorDefecto };
}

function esTemporal(x: ColumnaReporte | null, sugerido: TipoGraficoServidor): boolean {
  if (x === null) return false;
  return x.tipo === 'fecha' || EJES_TEMPORALES.has(x.clave) || sugerido === 'linea';
}

function distintos(valores: string[]): string[] {
  return [...new Set(valores)];
}

function textoDe(columna: ColumnaReporte, fila: ReporteEjecutado['filas'][number]): string {
  return formatearCelda(fila[columna.clave], columna.tipo);
}

/** Qué gráficos se pueden dibujar con estos datos, cada uno con la razón si no se puede. Siempre las 5 opciones. */
export function opcionesDeGrafico(reporte: ReporteEjecutado, metricaClave?: string): OpcionGrafico[] {
  const ejes = ejesDe(reporte);
  const metrica = ejes.metricas.find((m) => m.clave === metricaClave) ?? ejes.metricaPorDefecto;
  const todas = (razon: string | null): OpcionGrafico[] =>
    TIPOS_GRAFICO.map((tipo) => ({ tipo, etiqueta: ETIQUETA_GRAFICO[tipo], posible: razon === null, razon }));

  if (reporte.filas.length === 0) return todas('No hay datos para graficar.');
  if (ejes.x === null) return todas('El reporte no tiene una columna para el eje horizontal.');
  if (metrica === null) return todas('El reporte no tiene una columna numérica para graficar.');

  const x = ejes.x;
  const categorias = distintos(reporte.filas.map((f) => textoDe(x, f)));
  const series = ejes.serie ? distintos(reporte.filas.map((f) => textoDe(ejes.serie!, f))) : [];
  const variasSeries = series.length >= 2;
  const valores = reporte.filas.map((f) => aNumero(f[metrica.clave])).filter((v): v is number => v !== null);

  const razon: Record<TipoGraficoUi, string | null> = {
    barras: variasSeries ? 'Hay varias series: usa barras agrupadas o líneas.' : null,
    barras_horizontales: variasSeries ? 'Hay varias series: usa barras agrupadas o líneas.' : null,
    barras_agrupadas: variasSeries ? null : 'Necesita comparar dos o más series.',
    linea: !esTemporal(x, reporte.grafico_sugerido.tipo)
      ? 'Las líneas necesitan una columna de fechas o periodos.'
      : categorias.length < 2
        ? 'Las líneas necesitan al menos 2 puntos.'
        : null,
    torta: variasSeries
      ? 'El gráfico circular no admite varias series.'
      : valores.some((v) => v < 0)
        ? 'El gráfico circular no admite valores negativos.'
        : valores.reduce((a, b) => a + b, 0) <= 0
          ? 'El gráfico circular necesita que el total sea mayor que cero.'
          : categorias.length < MIN_CATEGORIAS_TORTA || categorias.length > MAX_CATEGORIAS_TORTA
            ? `Circular necesita entre ${MIN_CATEGORIAS_TORTA} y ${MAX_CATEGORIAS_TORTA} categorías (hay ${categorias.length}).`
            : null,
  };
  return TIPOS_GRAFICO.map((tipo) => ({ tipo, etiqueta: ETIQUETA_GRAFICO[tipo], posible: razon[tipo] === null, razon: razon[tipo] }));
}

/** El gráfico con que arranca la vista: el que sugiere el servidor si se puede; si no, el primero posible; null = solo tabla. */
export function graficoInicial(reporte: ReporteEjecutado, metricaClave?: string): TipoGraficoUi | null {
  const sugerido = reporte.grafico_sugerido.tipo;
  if (sugerido === 'tabla') return null;
  const opciones = opcionesDeGrafico(reporte, metricaClave);
  const delServidor = opciones.find((o) => o.tipo === sugerido && o.posible);
  return delServidor?.tipo ?? opciones.find((o) => o.posible)?.tipo ?? null;
}

/** La vista con que arranca un reporte: el gráfico sugerido (si se puede) o la tabla. */
export function vistaInicial(reporte: ReporteEjecutado): 'tabla' | 'grafico' {
  return graficoInicial(reporte) === null ? 'tabla' : 'grafico';
}

function recortar<T>(lista: T[], maximo: number): { lista: T[]; recortado: boolean } {
  return lista.length > maximo ? { lista: lista.slice(0, maximo), recortado: true } : { lista, recortado: false };
}

/**
 * Los datos de un gráfico para `p-chart`, o null si ese tipo no se puede con estos datos. Más de 12 categorías en
 * barras o más de 6 series se recortan (las primeras en el orden del servidor, o las de mayor total) y se avisa: la
 * tabla siempre tiene todo.
 */
export function construirDatosGrafico(reporte: ReporteEjecutado, tipo: TipoGraficoUi, metricaClave?: string): DatosGrafico | null {
  const opcion = opcionesDeGrafico(reporte, metricaClave).find((o) => o.tipo === tipo);
  if (!opcion?.posible) return null;

  const ejes = ejesDe(reporte);
  const x = ejes.x!;
  const metrica = ejes.metricas.find((m) => m.clave === metricaClave) ?? ejes.metricaPorDefecto!;
  const avisos: string[] = [];
  const porColorDeEntidad = EJES_CON_COLOR.has(x.clave);

  const puntos = reporte.filas.map((fila) => ({
    x: textoDe(x, fila),
    serie: ejes.serie ? textoDe(ejes.serie, fila) : null,
    valor: aNumero(fila[metrica.clave]),
  }));

  let categorias = distintos(puntos.map((p) => p.x));
  if (tipo !== 'linea' && tipo !== 'torta' && categorias.length > MAX_CATEGORIAS_BARRAS) {
    const total = categorias.length;
    categorias = recortar(categorias, MAX_CATEGORIAS_BARRAS).lista;
    avisos.push(`Se muestran las primeras ${MAX_CATEGORIAS_BARRAS} de ${total} categorías; la tabla tiene todas.`);
  }

  const agrupado = tipo === 'barras_agrupadas' || (tipo === 'linea' && ejes.serie !== null);
  let nombresSerie: string[] = [];
  if (agrupado) {
    const totalPorSerie = new Map<string, number>();
    for (const p of puntos) totalPorSerie.set(p.serie!, (totalPorSerie.get(p.serie!) ?? 0) + (p.valor ?? 0));
    const todas = [...totalPorSerie.keys()];
    if (todas.length > MAX_SERIES) {
      nombresSerie = [...todas].sort((a, b) => totalPorSerie.get(b)! - totalPorSerie.get(a)!).slice(0, MAX_SERIES);
      avisos.push(`Se muestran las ${MAX_SERIES} series con mayor total de ${todas.length}; la tabla tiene todas.`);
    } else {
      nombresSerie = todas;
    }
  }

  const valorEn = (categoria: string, serie: string | null): number | null => {
    const encontrados = puntos.filter((p) => p.x === categoria && (serie === null || p.serie === serie));
    if (encontrados.length === 0) return null;
    // Una categoría repetida (sin serie) se suma: es la misma medida en filas distintas.
    return encontrados.reduce((suma, p) => suma + (p.valor ?? 0), 0);
  };

  const paleta = paletaSeries();
  let datasets: Record<string, unknown>[];

  if (tipo === 'torta') {
    datasets = [
      {
        label: metrica.titulo,
        data: categorias.map((c) => valorEn(c, null) ?? 0),
        backgroundColor: categorias.map((c) => colorDeEntidad(c)),
        ...estiloAnillo(),
      },
    ];
  } else if (agrupado) {
    datasets = nombresSerie.map((nombre) => {
      const color = colorDeEntidad(nombre);
      const datos = categorias.map((c) => valorEn(c, nombre));
      return tipo === 'linea'
        ? { label: nombre, data: datos, borderColor: color, backgroundColor: color, tension: 0.25, pointRadius: 3, fill: false, spanGaps: true }
        : { label: nombre, data: datos, backgroundColor: color, ...ESTILO_BARRA };
    });
  } else if (tipo === 'linea') {
    datasets = [
      {
        label: metrica.titulo,
        data: categorias.map((c) => valorEn(c, null)),
        borderColor: paleta[0],
        backgroundColor: paleta[0],
        tension: 0.25,
        pointRadius: 3,
        fill: false,
        spanGaps: true,
      },
    ];
  } else {
    datasets = [
      {
        label: metrica.titulo,
        data: categorias.map((c) => valorEn(c, null)),
        backgroundColor: porColorDeEntidad ? categorias.map((c) => colorDeEntidad(c)) : paleta[0],
        ...ESTILO_BARRA,
      },
    ];
  }

  const nPuntos = categorias.length;
  const resumen =
    `${ETIQUETA_GRAFICO[tipo]}: ${metrica.titulo} por ${x.titulo}, ` +
    `${nPuntos} ${nPuntos === 1 ? 'punto' : 'puntos'}` +
    (agrupado ? `, ${nombresSerie.length} series` : '');

  return {
    tipoChart: tipo === 'linea' ? 'line' : tipo === 'torta' ? 'doughnut' : 'bar',
    data: { labels: categorias, datasets },
    horizontal: tipo === 'barras_horizontales',
    conLeyenda: agrupado || tipo === 'torta',
    formato: formateadorDe(metrica.tipo),
    metrica,
    resumen,
    avisos,
  };
}
