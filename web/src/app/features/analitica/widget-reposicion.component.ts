import { Component, computed, effect, inject, input, output, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TableModule } from 'primeng/table';
import { EstadoReposicion, ItemReposicion, ReposicionRespuesta } from '../../core/models/analitica.models';
import { formatearEntero } from '../../shared/graficos/formato-reporte';
import { IconoComponent } from '../../shared/icono/icono.component';
import { NombreIcono } from '../../shared/icono/iconos';
import { BloqueAnaliticaComponent } from './bloque-analitica.component';
import { BloqueoServidor, CargadorBloque } from './cargador-bloque';
import { AnaliticaService } from './data/analitica.service';

interface VistaEstadoReposicion {
  texto: string;
  clase: string;
  icono: NombreIcono;
  orden: number;
}

const VISTA_ESTADO: Record<EstadoReposicion, VistaEstadoReposicion> = {
  critico: { texto: 'Crítico', clase: 'fs-chip--error', icono: 'alerta', orden: 0 },
  atencion: { texto: 'Atención', clase: 'fs-chip--advertencia', icono: 'advertencia', orden: 1 },
  ok: { texto: 'Con stock', clase: 'fs-chip--exito', icono: 'check', orden: 2 },
};

/** Primero lo más urgente; dentro de cada estado, lo que antes se agota. Sin demanda prevista va al final. */
export function ordenarReposicion(items: ItemReposicion[]): ItemReposicion[] {
  const cobertura = (i: ItemReposicion) => i.semanas_cobertura ?? Number.POSITIVE_INFINITY;
  return [...items].sort(
    (a, b) => VISTA_ESTADO[a.estado].orden - VISTA_ESTADO[b.estado].orden || cobertura(a) - cobertura(b) || a.categoria.localeCompare(b.categoria),
  );
}

function decimal(n: number, decimales = 1): string {
  return n.toLocaleString('es-BO', { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
}

/**
 * Reposición sugerida (CU-24): cruza la demanda prevista con lo que hay disponible hoy, POR CATEGORÍA (no por variante ni
 * por sucursal). Es una guía: no descuenta órdenes de compra en camino ni transferencias.
 */
@Component({
  selector: 'app-widget-reposicion',
  standalone: true,
  imports: [RouterLink, TableModule, IconoComponent, BloqueAnaliticaComponent],
  templateUrl: './widget-reposicion.component.html',
  styleUrl: './widget-reposicion.component.scss',
})
export class WidgetReposicionComponent {
  private readonly servicio = inject(AnaliticaService);

  /** Horizonte, en semanas (el mismo que la predicción de demanda). */
  readonly semanas = input(4);
  readonly recarga = input(0);
  readonly activo = input(true);
  readonly entrenando = input(false);

  readonly entrenar = output<void>();
  readonly bloqueado = output<BloqueoServidor>();

  protected readonly carga = new CargadorBloque<ReposicionRespuesta>((motivo) => this.bloqueado.emit(motivo));

  protected readonly filas = computed(() => ordenarReposicion(this.carga.datos()?.items ?? []));
  protected readonly avisos = computed(() => {
    const d = this.carga.datos();
    if (d === null) return [];
    const lista = [...d.avisos];
    if (d.modelo.estado === 'desactualizado' && d.modelo.mensaje && !lista.includes(d.modelo.mensaje)) lista.push(d.modelo.mensaje);
    return lista;
  });

  protected readonly entero = formatearEntero;
  protected readonly vistaEstado = (e: EstadoReposicion) => VISTA_ESTADO[e];
  protected readonly cobertura = (i: ItemReposicion): string =>
    i.semanas_cobertura === null ? 'Sin demanda prevista' : `${decimal(i.semanas_cobertura)} semanas`;
  protected readonly demandaSemanal = (i: ItemReposicion): string => `${decimal(i.demanda_semanal_promedio)} por semana`;

  constructor() {
    effect(() => {
      const semanas = this.semanas();
      this.recarga();
      const activo = this.activo();
      untracked(() => (activo ? this.cargar(semanas) : this.carga.detener()));
    });
  }

  protected cargar(semanas = this.semanas()): void {
    this.carga.cargar(this.servicio.reposicion(semanas));
  }
}
