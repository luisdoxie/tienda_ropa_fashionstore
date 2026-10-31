import { Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { AnomaliaVenta, AnomaliasRespuesta, SeveridadAnomalia } from '../../core/models/analitica.models';
import { formatearFechaIso, formatearMoneda, formatearPorcentaje } from '../../shared/graficos/formato-reporte';
import { IconoComponent } from '../../shared/icono/icono.component';
import { NombreIcono } from '../../shared/icono/iconos';
import { BloqueAnaliticaComponent } from './bloque-analitica.component';
import { BloqueoServidor, CargadorBloque } from './cargador-bloque';
import { AnaliticaService } from './data/analitica.service';

/** Filas por página: pasado esto la tabla se pagina. */
export const FILAS_POR_PAGINA = 10;
export const DIAS_POR_DEFECTO = 90;

export const PERIODOS_ANOMALIAS: { etiqueta: string; valor: number }[] = [
  { etiqueta: 'Últimos 30 días', valor: 30 },
  { etiqueta: 'Últimos 90 días', valor: 90 },
  { etiqueta: 'Últimos 180 días', valor: 180 },
  { etiqueta: 'Últimos 365 días', valor: 365 },
];

interface VistaSeveridad {
  texto: string;
  clase: string;
  icono: NombreIcono;
}

const VISTA_SEVERIDAD: Record<SeveridadAnomalia, VistaSeveridad> = {
  leve: { texto: 'Leve', clase: 'fs-chip--advertencia', icono: 'advertencia' },
  fuerte: { texto: 'Fuerte', clase: 'fs-chip--error', icono: 'alerta' },
};

/** Del más desviado al menos desviado, sin importar si vendió de más o de menos. */
export function ordenarPorDesviacion(anomalias: AnomaliaVenta[]): AnomaliaVenta[] {
  return [...anomalias].sort((a, b) => Math.abs(b.desviacion_pct) - Math.abs(a.desviacion_pct));
}

/** "+594,5 %" o "−12,0 %": el signo siempre se escribe. */
export function textoDesviacion(pct: number): string {
  return `${pct >= 0 ? '+' : '−'}${formatearPorcentaje(Math.abs(pct))}`;
}

function plural(n: number, singular: string, pluralTexto: string): string {
  return `${n} ${n === 1 ? singular : pluralTexto}`;
}

/**
 * Días de ventas inusuales (CU-24): cada fila es un día de una sucursal que vendió bastante más o menos de lo esperado
 * para ese día de la semana. Un día inusual no es necesariamente un error.
 */
@Component({
  selector: 'app-widget-anomalias',
  standalone: true,
  imports: [FormsModule, SelectModule, TableModule, IconoComponent, BloqueAnaliticaComponent],
  templateUrl: './widget-anomalias.component.html',
  styleUrl: './widget-anomalias.component.scss',
})
export class WidgetAnomaliasComponent {
  private readonly servicio = inject(AnaliticaService);

  readonly recarga = input(0);
  readonly activo = input(true);
  readonly entrenando = input(false);

  readonly entrenar = output<void>();
  readonly bloqueado = output<BloqueoServidor>();

  protected readonly periodos = PERIODOS_ANOMALIAS;
  protected readonly filasPorPagina = FILAS_POR_PAGINA;
  protected readonly dias = signal(DIAS_POR_DEFECTO);

  protected readonly carga = new CargadorBloque<AnomaliasRespuesta>((motivo) => this.bloqueado.emit(motivo));

  protected readonly filas = computed(() => ordenarPorDesviacion(this.carga.datos()?.anomalias ?? []));
  protected readonly totales = computed(() => {
    const d = this.carga.datos();
    return d === null ? null : `${plural(d.total, 'día inusual', 'días inusuales')}, ${plural(d.fuertes, 'fuerte', 'fuertes')}`;
  });
  protected readonly avisos = computed(() => {
    const d = this.carga.datos();
    if (d === null) return [];
    const lista = [...d.avisos];
    if (d.modelo.estado === 'desactualizado' && d.modelo.mensaje && !lista.includes(d.modelo.mensaje)) lista.push(d.modelo.mensaje);
    return lista;
  });

  protected readonly fecha = formatearFechaIso;
  protected readonly moneda = formatearMoneda;
  protected readonly textoDesviacion = textoDesviacion;
  protected readonly vistaSeveridad = (s: SeveridadAnomalia) => VISTA_SEVERIDAD[s];

  constructor() {
    effect(() => {
      this.recarga();
      const activo = this.activo();
      untracked(() => (activo ? this.cargar() : this.carga.detener()));
    });
  }

  protected cargar(): void {
    this.carga.cargar(this.servicio.anomalias(this.dias()));
  }

  protected cambiarDias(dias: number): void {
    this.dias.set(dias);
    this.cargar();
  }
}
