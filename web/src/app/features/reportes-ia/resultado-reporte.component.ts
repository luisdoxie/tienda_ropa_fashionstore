import { Component, computed, input, linkedSignal, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { ChartData } from 'chart.js';
import { SortEvent } from 'primeng/api';
import { ChartModule } from 'primeng/chart';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { ErrorLeido } from '../../core/utils/http-blob';
import {
  ColumnaReporte,
  FilaReporte,
  FormatoExportacion,
  ReporteEjecutado,
  SolicitudResuelta,
  ValorCelda,
} from '../../core/models/reportes-ia.models';
import { IconoComponent } from '../../shared/icono/icono.component';
import {
  OpcionGrafico,
  TipoGraficoUi,
  construirDatosGrafico,
  ejesDe,
  graficoInicial,
  opcionesDeGrafico,
  vistaInicial,
} from '../../shared/graficos/datos-grafico';
import { aNumero, formatearCelda } from '../../shared/graficos/formato-reporte';
import { opcionesBarras, opcionesCircular, opcionesLineas } from '../../shared/graficos/opciones-grafico';
import { fechaHoraLocal, textoFiltrosAplicados } from './reportes-ia.util';

export type VistaResultado = 'tabla' | 'grafico';

/** Filas por página de la tabla: con menos de esto no hay paginador. */
export const FILAS_POR_PAGINA = 20;

const NUMERICAS = new Set(['entero', 'moneda', 'porcentaje']);

interface CeldaTotal {
  clave: string;
  texto: string | null;
}

/**
 * Resultado de un reporte generado por el servidor: encabezado, tabla o gráfico (cambiar de uno a otro, de tipo de
 * gráfico o de medida es instantáneo y NO consulta al servidor), resumen automático y botones de exportación.
 */
@Component({
  selector: 'app-resultado-reporte',
  standalone: true,
  imports: [FormsModule, ChartModule, SelectModule, SelectButtonModule, TableModule, IconoComponent],
  templateUrl: './resultado-reporte.component.html',
  styleUrl: './resultado-reporte.component.scss',
})
export class ResultadoReporteComponent {
  readonly reporte = input.required<ReporteEjecutado>();
  readonly solicitud = input<SolicitudResuelta | null>(null);
  readonly narrativa = input<string | null>(null);
  readonly exportando = input<FormatoExportacion | null>(null);
  readonly errorExportacion = input<ErrorLeido | null>(null);
  readonly deshabilitado = input(false);

  readonly exportar = output<FormatoExportacion>();

  protected readonly filasPorPagina = FILAS_POR_PAGINA;
  protected readonly formato = formatearCelda;
  protected readonly opcionesVista = [
    { label: 'Tabla', value: 'tabla' },
    { label: 'Gráfico', value: 'grafico' },
  ];

  protected readonly sinFilas = computed(() => this.reporte().filas.length === 0);
  protected readonly generadoEn = computed(() => fechaHoraLocal(this.reporte().generado_en));
  protected readonly filtrosTexto = computed(() => textoFiltrosAplicados(this.solicitud()));

  /** Copia para la tabla: ordenar por una columna no debe cambiar el orden de las filas que usa el gráfico. */
  protected readonly filasTabla = computed<FilaReporte[]>(() => [...this.reporte().filas]);

  // ---- Gráfico ------------------------------------------------------------------------------------------------------

  protected readonly metricas = computed<ColumnaReporte[]>(() => ejesDe(this.reporte()).metricas);

  /** La medida graficada. Al llegar un reporte del mismo tipo (p. ej. tras actualizar filtros) se conserva la elegida. */
  protected readonly metricaClave = linkedSignal<ReporteEjecutado, string | undefined>({
    source: this.reporte,
    computation: (nuevo, previo) => {
      const ejes = ejesDe(nuevo);
      if (previo && previo.source.codigo === nuevo.codigo && ejes.metricas.some((m) => m.clave === previo.value)) {
        return previo.value;
      }
      return ejes.metricaPorDefecto?.clave;
    },
  });

  /** Siempre las 5 opciones; las imposibles llevan su razón. */
  protected readonly opciones = computed<OpcionGrafico[]>(() => opcionesDeGrafico(this.reporte(), this.metricaClave()));
  protected readonly razones = computed(() => this.opciones().filter((o) => !o.posible && o.razon));
  protected readonly hayGrafico = computed(() => this.opciones().some((o) => o.posible));

  protected readonly tipoGrafico = linkedSignal<{ codigo: string; opciones: OpcionGrafico[] }, TipoGraficoUi | null>({
    source: () => ({ codigo: this.reporte().codigo, opciones: this.opciones() }),
    computation: (origen, previo) => {
      if (previo && previo.source.codigo === origen.codigo) {
        const actual = origen.opciones.find((o) => o.tipo === previo.value);
        if (actual?.posible) return previo.value;
      }
      // Sin gráfico sugerido por el servidor, si el usuario pide ver Gráfico arranca con el primero posible.
      return graficoInicial(this.reporte(), this.metricaClave()) ?? origen.opciones.find((o) => o.posible)?.tipo ?? null;
    },
  });

  protected readonly vista = linkedSignal<ReporteEjecutado, VistaResultado>({
    source: this.reporte,
    computation: (nuevo, previo) => {
      if (previo && previo.source.codigo === nuevo.codigo) {
        const hayGrafico = opcionesDeGrafico(nuevo).some((o) => o.posible);
        return previo.value === 'grafico' && !hayGrafico ? 'tabla' : previo.value;
      }
      return vistaInicial(nuevo);
    },
  });

  protected readonly datos = computed(() => {
    const tipo = this.tipoGrafico();
    return tipo === null ? null : construirDatosGrafico(this.reporte(), tipo, this.metricaClave());
  });

  /** `p-chart` tipa los datos de chart.js de forma más estricta que `construirDatosGrafico`; son los mismos datos. */
  protected readonly datosChart = computed(() => (this.datos()?.data ?? { labels: [], datasets: [] }) as unknown as ChartData);

  protected readonly opcionesChart = computed(() => {
    const d = this.datos();
    if (d === null) return {};
    if (d.tipoChart === 'line') return opcionesLineas(d.formato, d.conLeyenda);
    if (d.tipoChart === 'doughnut') return opcionesCircular(d.formato);
    return opcionesBarras(d.horizontal, d.formato, d.conLeyenda);
  });

  /** Por qué no hay gráfico cuando ninguno es posible (la razón es la misma para todos). */
  protected readonly razonSinGrafico = computed(() => this.opciones().find((o) => o.razon)?.razon ?? null);

  // ---- Tabla --------------------------------------------------------------------------------------------------------

  /** Fila de totales: solo con las claves del resumen que son columnas (un reporte recortado no lleva totales). */
  protected readonly totales = computed<CeldaTotal[] | null>(() => {
    const r = this.reporte();
    if (r.truncado || r.filas.length === 0) return null;
    const celdas = r.columnas.map((c) => ({
      clave: c.clave,
      texto: c.clave in r.resumen && r.resumen[c.clave] != null ? formatearCelda(r.resumen[c.clave], c.tipo) : null,
    }));
    return celdas.some((c) => c.texto !== null) ? celdas : null;
  });

  private readonly clavesNumericas = computed(() => {
    const r = this.reporte();
    const claves = new Set(this.metricas().map((m) => m.clave));
    for (const c of r.columnas) if (NUMERICAS.has(c.tipo)) claves.add(c.clave);
    return claves;
  });

  protected esNumerica(columna: ColumnaReporte): boolean {
    return this.clavesNumericas().has(columna.clave);
  }

  protected ordenar(evento: SortEvent): void {
    const campo = evento.field;
    if (!campo) return;
    const sentido = evento.order ?? 1;
    evento.data?.sort((a: FilaReporte, b: FilaReporte) => comparar(a[campo], b[campo]) * sentido);
  }
}

/** Números como números (también los decimales que llegan como texto), el resto como texto en español; vacíos al final. */
function comparar(a: ValorCelda | undefined, b: ValorCelda | undefined): number {
  const vacioA = a === null || a === undefined || a === '';
  const vacioB = b === null || b === undefined || b === '';
  if (vacioA || vacioB) return vacioA === vacioB ? 0 : vacioA ? 1 : -1;
  const na = aNumero(a);
  const nb = aNumero(b);
  if (na !== null && nb !== null) return na - nb;
  return String(a).localeCompare(String(b), 'es');
}
