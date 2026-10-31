import { Component, DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ConfirmationService, MessageService } from 'primeng/api';
import { ConfirmDialogModule } from 'primeng/confirmdialog';
import { SelectButtonModule } from 'primeng/selectbutton';
import { Subscription } from 'rxjs';
import { ConectividadService } from '../../core/conectividad.service';
import {
  DemandaRespuesta,
  EstadoAnalitica,
  EstadoVigenciaModelo,
  ResultadoEntrenamiento,
  SegmentosRespuesta,
  TipoModeloAnalitico,
} from '../../core/models/analitica.models';
import { PlanService } from '../../core/plan.service';
import { formatearFechaIso } from '../../shared/graficos/formato-reporte';
import { IconoComponent } from '../../shared/icono/icono.component';
import { NombreIcono } from '../../shared/icono/iconos';
import { BloqueoServidor } from './cargador-bloque';
import { AnaliticaService } from './data/analitica.service';
import { MENSAJE_EN_CURSO, MENSAJE_LIMITE_ENTRENAR, clasificarError } from './errores-analitica';
import { WidgetAnomaliasComponent } from './widget-anomalias.component';
import { WidgetDemandaComponent } from './widget-demanda.component';
import { WidgetMetricasComponent } from './widget-metricas.component';
import { WidgetReposicionComponent } from './widget-reposicion.component';
import { WidgetSegmentosComponent } from './widget-segmentos.component';

export const MENSAJE_CONFIRMAR_ENTRENAMIENTO = 'Se entrenarán los modelos con los datos de tu empresa. Puede tardar unos segundos.';
export const HORIZONTE_POR_DEFECTO = 4;

export const HORIZONTES: { etiqueta: string; valor: number }[] = [
  { etiqueta: '4 semanas', valor: 4 },
  { etiqueta: '8 semanas', valor: 8 },
  { etiqueta: '12 semanas', valor: 12 },
];

/** Los tres modelos, con el nombre que se les dice a las personas (sin siglas ni jerga). */
export const MODELOS: { tipo: TipoModeloAnalitico; titulo: string }[] = [
  { tipo: 'demanda_semanal', titulo: 'Demanda semanal por categoría' },
  { tipo: 'segmentos_rfm', titulo: 'Grupos de clientes' },
  { tipo: 'anomalias_ventas', titulo: 'Días de ventas inusuales' },
];

const TITULO_MODELO = new Map(MODELOS.map((m) => [m.tipo, m.titulo]));

interface VistaVigencia {
  texto: string;
  clase: string;
  icono: NombreIcono;
}

const VISTA_VIGENCIA: Record<EstadoVigenciaModelo, VistaVigencia> = {
  sin_entrenar: { texto: 'Sin entrenar', clase: '', icono: 'reloj' },
  vigente: { texto: 'Vigente', clase: 'fs-chip--exito', icono: 'check' },
  desactualizado: { texto: 'Desactualizado', clase: 'fs-chip--advertencia', icono: 'advertencia' },
  obsoleto: { texto: 'Obsoleto', clase: 'fs-chip--error', icono: 'alerta' },
};

export interface VistaModelo {
  tipo: TipoModeloAnalitico;
  titulo: string;
  estado: EstadoVigenciaModelo;
  etiqueta: string;
  clase: string;
  icono: NombreIcono;
  /** "Entrenado el 30/10/2026 con 144 filas · versión 1", o null si nunca se entrenó. */
  detalle: string | null;
  mensaje: string;
}

/**
 * Analítica (E17b, CU-24): el panel del Machine Learning. Cada bloque (demanda, grupos de clientes, métricas, días
 * inusuales, reposición) pide lo suyo y explica su propio estado, así un fallo no tapa a los demás. Todo el cálculo lo
 * hace el servidor: aquí solo se muestra, se explica y se pide entrenar. Nada se guarda en el navegador.
 */
@Component({
  selector: 'app-analitica',
  standalone: true,
  imports: [
    FormsModule,
    RouterLink,
    ConfirmDialogModule,
    SelectButtonModule,
    IconoComponent,
    WidgetDemandaComponent,
    WidgetSegmentosComponent,
    WidgetMetricasComponent,
    WidgetAnomaliasComponent,
    WidgetReposicionComponent,
  ],
  providers: [ConfirmationService],
  templateUrl: './analitica.component.html',
  styleUrl: './analitica.component.scss',
})
export class AnaliticaComponent {
  private readonly servicio = inject(AnaliticaService);
  private readonly plan = inject(PlanService);
  private readonly conectividad = inject(ConectividadService);
  private readonly mensajes = inject(MessageService);
  private readonly confirmacion = inject(ConfirmationService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly horizontes = HORIZONTES;
  protected readonly semanas = signal(HORIZONTE_POR_DEFECTO);
  /** Sube cada vez que hay que volver a pedir todos los bloques (p. ej. después de entrenar). */
  protected readonly recarga = signal(0);
  protected readonly entrenando = signal(false);

  protected readonly estado = signal<EstadoAnalitica | null>(null);
  protected readonly cargandoEstado = signal(false);
  protected readonly errorEstado = signal<string | null>(null);

  /** Lo que ya cargaron la demanda y los grupos de clientes: de ahí salen las métricas. */
  protected readonly demanda = signal<DemandaRespuesta | null>(null);
  protected readonly segmentos = signal<SegmentosRespuesta | null>(null);

  /** El servidor dijo que el plan o el rol no permiten la analítica (el respaldo de lo que el plan ya sabe). */
  private readonly bloqueoServidor = signal<BloqueoServidor | null>(null);

  protected readonly bloqueo = computed<BloqueoServidor | null>(() =>
    !this.plan.incluye('analitica_ml') ? 'plan' : this.bloqueoServidor(),
  );
  protected readonly sinConexion = computed(() => this.conectividad.estado() !== 'en_linea');
  /** Falso = ningún bloque hace llamadas: se ven apagados. */
  protected readonly activo = computed(() => this.bloqueo() === null && !this.sinConexion());
  protected readonly puedeEntrenar = computed(() => this.activo() && !this.entrenando());

  protected readonly modelos = computed<VistaModelo[]>(() => {
    const e = this.estado();
    if (e === null) return [];
    return MODELOS.map(({ tipo, titulo }) => {
      const m = e.modelos.find((x) => x.tipo === tipo);
      const estado: EstadoVigenciaModelo = m ? (m.entrenado ? m.estado : 'sin_entrenar') : 'sin_entrenar';
      const vista = VISTA_VIGENCIA[estado];
      const detalle =
        m?.entrenado && m.entrenado_en
          ? `Entrenado el ${formatearFechaIso(m.entrenado_en)}${m.filas_entrenamiento != null ? ` con ${m.filas_entrenamiento} filas` : ''}${m.version != null ? ` · versión ${m.version}` : ''}`
          : null;
      return {
        tipo,
        titulo,
        estado,
        etiqueta: vista.texto,
        clase: vista.clase,
        icono: vista.icono,
        detalle,
        mensaje: m?.mensaje ?? 'Aún no hay un modelo entrenado.',
      };
    });
  });
  protected readonly hayEntrenado = computed(() => this.estado()?.modelos.some((m) => m.entrenado) ?? false);

  private suscripcionEstado: Subscription | null = null;

  constructor() {
    this.plan.cargar();
    this.destroyRef.onDestroy(() => this.suscripcionEstado?.unsubscribe());
    // Al abrir (y al volver la conexión) se lee el estado de los modelos; sin plan, rol o conexión no se llama a nada.
    effect(() => {
      const activo = this.activo();
      untracked(() => (activo ? this.cargarEstado() : this.detenerEstado()));
    });
  }

  protected cargarEstado(): void {
    this.suscripcionEstado?.unsubscribe();
    this.cargandoEstado.set(true);
    this.errorEstado.set(null);
    this.suscripcionEstado = this.servicio.estado().subscribe({
      next: (estado) => {
        this.estado.set(estado);
        this.cargandoEstado.set(false);
      },
      error: (error: unknown) => {
        const e = clasificarError(error);
        this.cargandoEstado.set(false);
        if (e.clase === 'plan' || e.clase === 'alcance') this.alBloquear(e.clase);
        else this.errorEstado.set(e.mensaje);
      },
    });
  }

  private detenerEstado(): void {
    this.suscripcionEstado?.unsubscribe();
    this.suscripcionEstado = null;
    this.cargandoEstado.set(false);
  }

  protected alBloquear(motivo: BloqueoServidor): void {
    this.bloqueoServidor.set(motivo);
  }

  protected cambiarSemanas(semanas: number | null): void {
    if (semanas === null || semanas === this.semanas()) return;
    this.semanas.set(semanas);
  }

  // ---- Entrenar ------------------------------------------------------------------------------------------------------

  /** Pide confirmación: entrenar tarda unos segundos y reemplaza los modelos vigentes. */
  protected pedirEntrenar(): void {
    if (!this.puedeEntrenar()) return;
    this.confirmacion.confirm({
      header: this.hayEntrenado() ? 'Reentrenar los modelos' : 'Entrenar los modelos',
      message: MENSAJE_CONFIRMAR_ENTRENAMIENTO,
      icon: 'pi pi-exclamation-triangle',
      acceptLabel: this.hayEntrenado() ? 'Reentrenar' : 'Entrenar',
      rejectLabel: 'Cancelar',
      accept: () => this.entrenar(),
    });
  }

  /** Es síncrono: la respuesta llega cuando termina, así que el botón espera con un indicador y no hay sondeo. */
  private entrenar(): void {
    if (this.entrenando() || !this.activo()) return;
    this.entrenando.set(true);
    this.servicio
      .entrenar()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (respuesta) => {
          this.entrenando.set(false);
          this.avisarResultados(respuesta.resultados);
          this.recargarTodo();
        },
        error: (error: unknown) => {
          this.entrenando.set(false);
          this.avisarErrorDeEntrenamiento(error);
        },
      });
  }

  private recargarTodo(): void {
    this.recarga.update((n) => n + 1);
    this.cargarEstado();
  }

  private avisarResultados(resultados: ResultadoEntrenamiento[]): void {
    for (const r of resultados) {
      const titulo = TITULO_MODELO.get(r.tipo) ?? r.tipo;
      if (r.estado === 'entrenado') {
        this.mensajes.add({
          severity: 'success',
          summary: `${titulo}: entrenado`,
          detail: r.version != null ? `Quedó la versión ${r.version}.` : 'El modelo quedó listo.',
        });
      } else {
        this.mensajes.add({
          severity: 'warn',
          summary: `${titulo}: no se pudo entrenar`,
          detail: r.motivo ?? 'No hay datos suficientes para entrenar este modelo.',
          life: 8000,
        });
      }
    }
  }

  private avisarErrorDeEntrenamiento(error: unknown): void {
    const e = clasificarError(error);
    switch (e.clase) {
      case 'en_curso':
        this.mensajes.add({ severity: 'warn', summary: 'Ya hay un entrenamiento en curso', detail: MENSAJE_EN_CURSO, life: 8000 });
        return;
      case 'limite':
        this.mensajes.add({ severity: 'warn', summary: 'Demasiados intentos', detail: MENSAJE_LIMITE_ENTRENAR, life: 8000 });
        return;
      case 'plan':
      case 'alcance':
        this.alBloquear(e.clase);
        return;
      default:
        this.mensajes.add({ severity: 'error', summary: 'No se pudo entrenar', detail: e.mensaje });
    }
  }
}
