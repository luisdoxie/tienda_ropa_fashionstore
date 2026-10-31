import { Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ChartModule } from 'primeng/chart';
import { SelectModule } from 'primeng/select';
import { DemandaRespuesta } from '../../core/models/analitica.models';
import { formatearEntero, formatearPorcentaje } from '../../shared/graficos/formato-reporte';
import { BloqueAnaliticaComponent } from './bloque-analitica.component';
import { BloqueoServidor, CargadorBloque } from './cargador-bloque';
import { AnaliticaService } from './data/analitica.service';
import { construirGraficoDemanda } from './graficos-analitica';

interface OpcionCategoria {
  id: number | null;
  etiqueta: string;
}

/** Las semanas reales con que el servidor compara la demanda prevista (siempre las últimas 4). */
const SEMANAS_DE_COMPARACION = 4;

/**
 * Predicción de demanda (CU-24): histórico real, predicción punteada y su rango estimado. Una sola consulta trae TODAS las
 * categorías y el total de la empresa, así que cambiar de categoría no vuelve a pedir nada; cambiar el horizonte sí.
 */
@Component({
  selector: 'app-widget-demanda',
  standalone: true,
  imports: [FormsModule, ChartModule, SelectModule, BloqueAnaliticaComponent],
  templateUrl: './widget-demanda.component.html',
  styleUrl: './widget-demanda.component.scss',
})
export class WidgetDemandaComponent {
  private readonly servicio = inject(AnaliticaService);

  /** Horizonte de la predicción, en semanas. */
  readonly semanas = input(4);
  /** Cambia cada vez que hay que volver a pedir todo (p. ej. después de entrenar). */
  readonly recarga = input(0);
  /** Falso cuando el plan, el rol o la conexión no permiten consultar: no se hace ninguna llamada. */
  readonly activo = input(true);
  readonly entrenando = input(false);

  readonly entrenar = output<void>();
  readonly bloqueado = output<BloqueoServidor>();
  /** La respuesta ya cargada (null si no hay): la usan las métricas. */
  readonly cargada = output<DemandaRespuesta | null>();

  protected readonly carga = new CargadorBloque<DemandaRespuesta>(
    (motivo) => this.bloqueado.emit(motivo),
    (datos) => this.cargada.emit(datos),
  );
  protected readonly categoriaElegida = signal<number | null>(null);

  protected readonly opciones = computed<OpcionCategoria[]>(() => {
    const d = this.carga.datos();
    if (d === null) return [];
    return [
      { id: null, etiqueta: 'Toda la empresa' },
      ...d.categorias.filter((c) => c.categoria_id !== null).map((c) => ({ id: c.categoria_id, etiqueta: c.categoria })),
    ];
  });

  /** La categoría que se está viendo (sale de la misma respuesta; si desapareció, vuelve a toda la empresa). */
  protected readonly vista = computed(() => {
    const d = this.carga.datos();
    if (d === null) return null;
    const id = this.categoriaElegida();
    return (id === null ? null : d.categorias.find((c) => c.categoria_id === id)) ?? d.total_empresa;
  });
  protected readonly categoriaActual = computed(() => this.vista()?.categoria_id ?? null);
  protected readonly grafico = computed(() => {
    const v = this.vista();
    return v === null ? null : construirGraficoDemanda(v);
  });

  protected readonly resumen = computed(() => {
    const d = this.carga.datos();
    const v = this.vista();
    if (d === null || v === null) return null;
    const n = d.horizonte_semanas;
    const plazo = n === 1 ? 'la próxima semana' : `las próximas ${n} semanas`;
    const sujeto = v.categoria_id === null ? 'En toda la empresa' : `En ${v.categoria}`;
    const base = `${sujeto} se prevén ${formatearEntero(v.total_predicho)} unidades en ${plazo}`;
    const pct = v.variacion_pct_vs_ultimas_semanas;
    if (pct === null) return `${base}.`;
    const comparado = `el promedio de las últimas ${SEMANAS_DE_COMPARACION} semanas`;
    if (pct === 0) return `${base}, igual que ${comparado}.`;
    return `${base}: ${formatearPorcentaje(Math.abs(pct))} ${pct > 0 ? 'más' : 'menos'} que ${comparado}.`;
  });

  /** Avisos del servidor y, si el modelo está desactualizado, su mensaje (con HTTP 200). */
  protected readonly avisos = computed(() => {
    const d = this.carga.datos();
    if (d === null) return [];
    const lista = [...d.avisos];
    if (d.modelo.estado === 'desactualizado' && d.modelo.mensaje && !lista.includes(d.modelo.mensaje)) lista.push(d.modelo.mensaje);
    return lista;
  });

  constructor() {
    effect(() => {
      const semanas = this.semanas();
      this.recarga();
      const activo = this.activo();
      untracked(() => (activo ? this.cargar(semanas) : this.carga.detener()));
    });
  }

  protected cargar(semanas = this.semanas()): void {
    this.carga.cargar(this.servicio.demanda(semanas));
  }

  protected elegirCategoria(id: number | null): void {
    this.categoriaElegida.set(id);
  }
}
