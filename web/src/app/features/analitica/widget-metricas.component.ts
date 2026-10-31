import { Component, computed, input } from '@angular/core';
import { TooltipModule } from 'primeng/tooltip';
import { DemandaRespuesta, SegmentosRespuesta } from '../../core/models/analitica.models';
import { NombreIcono } from '../../shared/icono/iconos';
import { IconoComponent } from '../../shared/icono/icono.component';
import { BloqueAnaliticaComponent } from './bloque-analitica.component';
import { CalidadMetrica, InterpretacionMetrica, interpretarMetrica } from './explicacion-metricas';

interface VistaCalidad {
  clase: string;
  icono: NombreIcono;
}

const VISTA_CALIDAD: Record<CalidadMetrica, VistaCalidad> = {
  buena: { clase: 'fs-chip--exito', icono: 'check' },
  aceptable: { clase: 'fs-chip--advertencia', icono: 'advertencia' },
  debil: { clase: 'fs-chip--error', icono: 'alerta' },
};

/** Promedio de unidades que vende UNA categoría en una semana típica (con lo que se compara el MAE, que es por categoría). */
export function promedioSemanalPorCategoria(demanda: DemandaRespuesta): number | null {
  const series = demanda.categorias.length > 0 ? demanda.categorias : [demanda.total_empresa];
  const valores = series.flatMap((c) => c.historico.map((p) => p.valor)).filter((v) => Number.isFinite(v));
  if (valores.length === 0) return null;
  return valores.reduce((suma, v) => suma + v, 0) / valores.length;
}

/**
 * Qué tan bien funcionan los modelos, en lenguaje simple (E17b). Las cifras salen de lo que ya trajeron la demanda y los
 * grupos de clientes (nada se calcula aquí) y se muestran tal cual, también las flojas.
 */
@Component({
  selector: 'app-widget-metricas',
  standalone: true,
  imports: [TooltipModule, IconoComponent, BloqueAnaliticaComponent],
  templateUrl: './widget-metricas.component.html',
  styleUrl: './widget-metricas.component.scss',
})
export class WidgetMetricasComponent {
  readonly demanda = input<DemandaRespuesta | null>(null);
  readonly segmentos = input<SegmentosRespuesta | null>(null);
  readonly activo = input(true);

  protected readonly fichas = computed<InterpretacionMetrica[]>(() => {
    const demanda = this.demanda();
    const segmentos = this.segmentos();
    const lista: InterpretacionMetrica[] = [];
    if (demanda !== null) {
      const m = demanda.metricas;
      const contexto = { promedioSemanal: promedioSemanalPorCategoria(demanda) };
      lista.push(
        interpretarMetrica('mejora_mae_pct', m.mejora_mae_pct, contexto),
        interpretarMetrica('mae', m.mae, contexto),
        interpretarMetrica('rmse', m.rmse, contexto),
        interpretarMetrica('r2', m.r2, contexto),
      );
    }
    if (segmentos !== null) lista.push(interpretarMetrica('silhouette', segmentos.silhouette));
    return lista;
  });

  protected readonly vistaCalidad = (calidad: CalidadMetrica) => VISTA_CALIDAD[calidad];
}
