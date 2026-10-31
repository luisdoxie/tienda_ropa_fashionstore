import { Component, computed, effect, inject, input, output, untracked } from '@angular/core';
import { ChartModule } from 'primeng/chart';
import { SegmentosRespuesta } from '../../core/models/analitica.models';
import { formatearEntero, formatearMoneda, formatearPorcentaje } from '../../shared/graficos/formato-reporte';
import { colorDeEntidad } from '../../shared/graficos/paleta-graficos';
import { BloqueAnaliticaComponent } from './bloque-analitica.component';
import { BloqueoServidor, CargadorBloque } from './cargador-bloque';
import { AnaliticaService } from './data/analitica.service';
import { construirGraficoSegmentos } from './graficos-analitica';

function numeroDecimal(n: number, decimales = 1): string {
  return n.toLocaleString('es-BO', { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
}

/**
 * Grupos de clientes (CU-24): una tarjeta por grupo con su comportamiento de compra y lo que conviene hacer, más un anillo
 * con el tamaño de cada uno. Los clientes son anónimos: el servidor nunca manda quién es cada uno.
 */
@Component({
  selector: 'app-widget-segmentos',
  standalone: true,
  imports: [ChartModule, BloqueAnaliticaComponent],
  templateUrl: './widget-segmentos.component.html',
  styleUrl: './widget-segmentos.component.scss',
})
export class WidgetSegmentosComponent {
  private readonly servicio = inject(AnaliticaService);

  readonly recarga = input(0);
  readonly activo = input(true);
  readonly entrenando = input(false);

  readonly entrenar = output<void>();
  readonly bloqueado = output<BloqueoServidor>();
  /** La respuesta ya cargada (null si no hay): la usan las métricas. */
  readonly cargada = output<SegmentosRespuesta | null>();

  protected readonly carga = new CargadorBloque<SegmentosRespuesta>(
    (motivo) => this.bloqueado.emit(motivo),
    (datos) => this.cargada.emit(datos),
  );

  protected readonly grafico = computed(() => {
    const d = this.carga.datos();
    return d === null || d.segmentos.length === 0 ? null : construirGraficoSegmentos(d.segmentos);
  });

  protected readonly color = colorDeEntidad;
  protected readonly entero = formatearEntero;
  protected readonly moneda = formatearMoneda;
  protected readonly porcentaje = formatearPorcentaje;
  protected readonly decimal = numeroDecimal;

  constructor() {
    effect(() => {
      this.recarga();
      const activo = this.activo();
      untracked(() => (activo ? this.cargar() : this.carga.detener()));
    });
  }

  protected cargar(): void {
    this.carga.cargar(this.servicio.segmentos());
  }
}
