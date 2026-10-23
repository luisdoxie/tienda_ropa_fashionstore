import { DatePipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { AbstractControl, FormBuilder, FormsModule, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { ConfirmationService, MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { ConfirmDialogModule } from 'primeng/confirmdialog';
import { DatePickerModule } from 'primeng/datepicker';
import { DialogModule } from 'primeng/dialog';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { fechaDesdeIso, fechaLocalIso } from '../../../core/date-utils';
import {
  EmpresaPlataforma,
  EstadoSuscripcionPedido,
  EstadoSuscripcionPlataforma,
  PlanPlataforma,
  SuscripcionPlataforma,
  etiquetaEstadoSuscripcion,
} from '../../../core/models/plataforma.models';
import { diasHasta, fechaPosteriorAHoy, hoyLocal, sumarDias, sumarMeses } from '../data/fechas-plataforma';
import { claseChipEstado } from '../data/chip-estado';
import { PlataformaService } from '../data/plataforma.service';

const TAMANIO_PAGINA = 20;
const DIAS_VIGENCIA_INICIAL = 30;

/** Qué botones ofrece cada fila. El backend vuelve a validar cada transición. */
export interface AccionesPermitidas {
  cambiarPlan: boolean;
  renovar: boolean;
  suspender: boolean;
  reactivar: boolean;
  cancelar: boolean;
  asignarPlan: boolean;
}

/**
 * Según el estado EFECTIVO (una activa con la fecha pasada ya es vencida) y lo
 * que permite `GestionarSuscripciones` del backend:
 * - activa: cambiar plan, renovar, suspender, cancelar.
 * - vencida: renovar, cambiar plan, cancelar (no se reactiva: se renueva).
 * - suspendida: reactivar (solo si la fecha no pasó), cancelar, y renovar si ya
 *   pasó (renovar una suspendida solo mueve la fecha).
 * - cancelada: es final; solo se asigna un plan nuevo, y únicamente si la
 *   empresa no tiene otra suscripción vigente (si la tiene, se cambia ESA).
 */
export function accionesPermitidas(
  suscripcion: Pick<SuscripcionPlataforma, 'estado_efectivo' | 'fecha_vencimiento'>,
  empresaTieneVigente: boolean,
  hoy: Date = hoyLocal(),
): AccionesPermitidas {
  const ninguna: AccionesPermitidas = {
    cambiarPlan: false,
    renovar: false,
    suspender: false,
    reactivar: false,
    cancelar: false,
    asignarPlan: false,
  };
  switch (suscripcion.estado_efectivo) {
    case 'activa':
      return { ...ninguna, cambiarPlan: true, renovar: true, suspender: true, cancelar: true };
    case 'vencida':
      return { ...ninguna, renovar: true, cambiarPlan: true, cancelar: true };
    case 'suspendida': {
      const pasada = diasHasta(fechaDesdeIso(suscripcion.fecha_vencimiento), hoy) < 0;
      return { ...ninguna, reactivar: !pasada, renovar: pasada, cancelar: true };
    }
    case 'cancelada':
      return { ...ninguna, asignarPlan: !empresaTieneVigente };
    default:
      return ninguna;
  }
}

export type OpcionRenovacion = '1m' | '3m' | '1a' | 'libre';

const OPCIONES_RENOVACION: { label: string; value: OpcionRenovacion }[] = [
  { label: '1 mes más', value: '1m' },
  { label: '3 meses más', value: '3m' },
  { label: '1 año más', value: '1a' },
  { label: 'Otra fecha', value: 'libre' },
];

const MESES_POR_OPCION: Record<Exclude<OpcionRenovacion, 'libre'>, number> = { '1m': 1, '3m': 3, '1a': 12 };

/** Desde dónde se cuenta una renovación: el vencimiento, o hoy si ya venció. */
export function baseDeRenovacion(fechaVencimiento: Date, hoy: Date = hoyLocal()): Date {
  return diasHasta(fechaVencimiento, hoy) > 0 ? fechaVencimiento : hoy;
}

export function nuevoVencimiento(
  opcion: Exclude<OpcionRenovacion, 'libre'>,
  fechaVencimiento: Date,
  hoy: Date = hoyLocal(),
): Date {
  return sumarMeses(baseDeRenovacion(fechaVencimiento, hoy), MESES_POR_OPCION[opcion]);
}

function vencimientoNoAnterior(grupo: AbstractControl): ValidationErrors | null {
  const inicio = grupo.get('fecha_inicio')?.value;
  const vence = grupo.get('fecha_vencimiento')?.value;
  if (!(inicio instanceof Date) || !(vence instanceof Date)) return null;
  return diasHasta(vence, inicio) < 0 ? { vencimientoAnterior: true } : null;
}

interface FilaSuscripcion {
  suscripcion: SuscripcionPlataforma;
  empresa: string;
  vence: Date;
  restante: string;
  acciones: AccionesPermitidas;
}

type TipoDialogoPlan = 'cambiar' | 'asignar';

/**
 * Suscripciones de la plataforma (CU-04, solo superadministrador). Muestra el
 * estado EFECTIVO y ofrece solo las acciones que el backend permite; las
 * reglas (límites de sucursales, transiciones) las decide el backend y sus
 * rechazos se muestran tal cual.
 */
@Component({
  selector: 'app-suscripciones',
  standalone: true,
  imports: [
    DatePipe,
    FormsModule,
    ReactiveFormsModule,
    ButtonModule,
    ConfirmDialogModule,
    DatePickerModule,
    DialogModule,
    SelectModule,
    TableModule,
  ],
  providers: [ConfirmationService],
  templateUrl: './suscripciones.component.html',
  styleUrl: './suscripciones.component.scss',
})
export class SuscripcionesComponent implements OnInit {
  private readonly servicio = inject(PlataformaService);
  private readonly fb = inject(FormBuilder);
  private readonly messageService = inject(MessageService);
  private readonly confirmationService = inject(ConfirmationService);

  protected readonly opcionesRenovacion = OPCIONES_RENOVACION;
  protected readonly manana = sumarDias(hoyLocal(), 1);
  protected readonly etiquetaEstado = etiquetaEstadoSuscripcion;
  protected readonly claseChip = claseChipEstado;
  protected readonly opcionesEstado: { label: string; value: EstadoSuscripcionPlataforma | null }[] = [
    { label: 'Cualquier estado', value: null },
    { label: 'Activa', value: 'activa' },
    { label: 'Vencida', value: 'vencida' },
    { label: 'Suspendida', value: 'suspendida' },
    { label: 'Cancelada', value: 'cancelada' },
  ];

  // ---- Datos ----
  protected readonly suscripciones = signal<SuscripcionPlataforma[]>([]);
  protected readonly empresas = signal<EmpresaPlataforma[]>([]);
  protected readonly planes = signal<PlanPlataforma[]>([]);
  protected readonly cargando = signal(false);
  protected readonly trabajando = signal(false);
  protected readonly pagina = signal(1);
  protected readonly hayPaginaSiguiente = signal(false);

  protected readonly filtroEmpresa = signal<number | null>(null);
  protected readonly filtroEstado = signal<EstadoSuscripcionPlataforma | null>(null);
  protected readonly filtroPlan = signal<string | null>(null);

  private readonly nombresEmpresa = computed(() => new Map(this.empresas().map((e) => [e.id, e.nombre])));

  protected readonly opcionesEmpresa = computed(() => [
    { label: 'Todas las empresas', value: null as number | null },
    ...this.empresas().map((e) => ({ label: e.nombre, value: e.id as number | null })),
  ]);
  protected readonly opcionesPlanFiltro = computed(() => [
    { label: 'Cualquier plan', value: null as string | null },
    ...this.planes().map((p) => ({ label: p.nombre, value: p.codigo as string | null })),
  ]);

  protected readonly filas = computed<FilaSuscripcion[]>(() => {
    const todas = this.suscripciones();
    const conVigente = new Set(todas.filter((s) => s.estado_efectivo !== 'cancelada').map((s) => s.empresa_id));
    const plan = this.filtroPlan();
    return todas
      .filter((s) => plan === null || s.plan_codigo === plan)
      .map((s) => ({
        suscripcion: s,
        empresa: this.nombreEmpresa(s.empresa_id),
        vence: fechaDesdeIso(s.fecha_vencimiento),
        restante: this.textoRestante(s),
        acciones: accionesPermitidas(s, conVigente.has(s.empresa_id)),
      }));
  });

  // ---- Historial ----
  protected readonly dialogoHistorialVisible = signal(false);
  protected readonly historialEmpresa = signal<string>('');
  protected readonly historial = signal<SuscripcionPlataforma[]>([]);
  protected readonly cargandoHistorial = signal(false);

  // ---- Cambiar plan / asignar plan ----
  protected readonly dialogoPlanVisible = signal(false);
  protected readonly tipoDialogoPlan = signal<TipoDialogoPlan>('cambiar');
  protected readonly objetivo = signal<SuscripcionPlataforma | null>(null);

  protected readonly formularioPlan = this.fb.group(
    {
      plan_codigo: this.fb.nonNullable.control('', Validators.required),
      fecha_inicio: this.fb.control<Date | null>(null, Validators.required),
      fecha_vencimiento: this.fb.control<Date | null>(null, [Validators.required, fechaPosteriorAHoy]),
    },
    { validators: vencimientoNoAnterior },
  );

  protected readonly opcionesPlanDialogo = computed(() => {
    const actual = this.tipoDialogoPlan() === 'cambiar' ? this.objetivo()?.plan_codigo : null;
    return this.planes()
      .filter((p) => p.activo && p.codigo !== actual)
      .map((p) => ({ label: `${p.nombre} (hasta ${p.max_sucursales} sucursales)`, value: p.codigo }));
  });

  // ---- Renovar ----
  protected readonly dialogoRenovarVisible = signal(false);
  protected readonly opcionRenovar = signal<OpcionRenovacion>('1m');
  protected readonly fechaLibre = signal<Date | null>(null);

  protected readonly fechaRenovada = computed<Date | null>(() => {
    const s = this.objetivo();
    if (s === null) return null;
    const opcion = this.opcionRenovar();
    return opcion === 'libre' ? this.fechaLibre() : nuevoVencimiento(opcion, fechaDesdeIso(s.fecha_vencimiento));
  });
  protected readonly renovacionValida = computed(() => {
    const fecha = this.fechaRenovada();
    return fecha !== null && diasHasta(fecha) > 0;
  });

  ngOnInit(): void {
    this.servicio.listarPlanes().subscribe({ next: (p) => this.planes.set(p), error: () => undefined });
    this.servicio.listarTodasEmpresas().subscribe({ next: (e) => this.empresas.set(e), error: () => undefined });
    this.cargar();
  }

  // ---- Lista ----

  protected cargar(): void {
    this.cargando.set(true);
    this.servicio
      .listarSuscripciones({
        empresa_id: this.filtroEmpresa() ?? undefined,
        estado: this.filtroEstado() ?? undefined,
        pagina: this.pagina(),
        tamanio: TAMANIO_PAGINA,
      })
      .subscribe({
        next: (lista) => {
          this.suscripciones.set(lista);
          this.hayPaginaSiguiente.set(lista.length === TAMANIO_PAGINA);
          this.cargando.set(false);
        },
        error: () => this.cargando.set(false),
      });
  }

  protected cambiarFiltroEmpresa(id: number | null): void {
    this.filtroEmpresa.set(id);
    this.pagina.set(1);
    this.cargar();
  }

  protected cambiarFiltroEstado(estado: EstadoSuscripcionPlataforma | null): void {
    this.filtroEstado.set(estado);
    this.pagina.set(1);
    this.cargar();
  }

  protected irAPaginaAnterior(): void {
    if (this.pagina() > 1) {
      this.pagina.update((p) => p - 1);
      this.cargar();
    }
  }

  protected irAPaginaSiguiente(): void {
    if (this.hayPaginaSiguiente()) {
      this.pagina.update((p) => p + 1);
      this.cargar();
    }
  }

  protected nombreEmpresa(id: number): string {
    return this.nombresEmpresa().get(id) ?? `Empresa #${id}`;
  }

  protected fecha(iso: string): Date {
    return fechaDesdeIso(iso);
  }

  private textoRestante(s: SuscripcionPlataforma): string {
    if (s.estado_efectivo === 'cancelada') return '—';
    const dias = diasHasta(fechaDesdeIso(s.fecha_vencimiento));
    if (dias === 0) return 'Vence hoy';
    if (dias === 1) return '1 día';
    if (dias > 1) return `${dias} días`;
    return dias === -1 ? 'Venció hace 1 día' : `Venció hace ${-dias} días`;
  }

  // ---- Historial ----

  protected abrirHistorial(suscripcion: SuscripcionPlataforma): void {
    this.historialEmpresa.set(this.nombreEmpresa(suscripcion.empresa_id));
    this.historial.set([]);
    this.cargandoHistorial.set(true);
    this.dialogoHistorialVisible.set(true);
    this.servicio.historialDeEmpresa(suscripcion.empresa_id).subscribe({
      next: (lista) => {
        this.historial.set(lista);
        this.cargandoHistorial.set(false);
      },
      error: () => {
        this.cargandoHistorial.set(false);
        this.dialogoHistorialVisible.set(false);
      },
    });
  }

  // ---- Cambiar plan / asignar plan ----

  protected abrirCambiarPlan(suscripcion: SuscripcionPlataforma): void {
    this.prepararDialogoPlan(suscripcion, 'cambiar');
  }

  /**
   * Sobre una suscripción cancelada. Antes de abrir se mira el historial de la
   * empresa: si ya tiene otra vigente, asignar otro plan la cerraría, y eso es
   * "cambiar plan" sobre ESA fila.
   */
  protected abrirAsignarPlan(suscripcion: SuscripcionPlataforma): void {
    this.trabajando.set(true);
    this.servicio.historialDeEmpresa(suscripcion.empresa_id).subscribe({
      next: (lista) => {
        this.trabajando.set(false);
        const vigente = lista.find((s) => s.estado_efectivo !== 'cancelada');
        if (vigente) {
          this.messageService.add({
            severity: 'info',
            summary: 'Esa empresa ya tiene una suscripción vigente',
            detail: `Usa "Cambiar plan" sobre la suscripción ${etiquetaEstadoSuscripcion(vigente.estado_efectivo).toLowerCase()} (${vigente.plan_nombre}).`,
          });
          return;
        }
        this.prepararDialogoPlan(suscripcion, 'asignar');
      },
      error: () => this.trabajando.set(false),
    });
  }

  private prepararDialogoPlan(suscripcion: SuscripcionPlataforma, tipo: TipoDialogoPlan): void {
    this.objetivo.set(suscripcion);
    this.tipoDialogoPlan.set(tipo);
    const hoy = hoyLocal();
    this.formularioPlan.reset({
      plan_codigo: '',
      fecha_inicio: hoy,
      fecha_vencimiento: sumarDias(hoy, DIAS_VIGENCIA_INICIAL),
    });
    this.dialogoPlanVisible.set(true);
  }

  protected guardarPlan(): void {
    const objetivo = this.objetivo();
    if (objetivo === null || this.trabajando()) return;
    if (this.formularioPlan.invalid) {
      this.formularioPlan.markAllAsTouched();
      return;
    }
    const v = this.formularioPlan.getRawValue();
    this.trabajando.set(true);
    this.servicio
      .asignarPlan({
        empresa_id: objetivo.empresa_id,
        plan_codigo: v.plan_codigo,
        fecha_inicio: fechaLocalIso(v.fecha_inicio!),
        fecha_vencimiento: fechaLocalIso(v.fecha_vencimiento!),
      })
      .subscribe({
        next: (nueva) => {
          this.trabajando.set(false);
          this.dialogoPlanVisible.set(false);
          this.messageService.add({
            severity: 'success',
            summary: this.tipoDialogoPlan() === 'cambiar' ? 'Plan cambiado' : 'Plan asignado',
            detail: `${this.nombreEmpresa(nueva.empresa_id)}: ${nueva.plan_nombre}.`,
          });
          this.cargar();
        },
        // 409 (mismo plan, límite_plan_excedido) y 422: los muestra el manejo global.
        error: () => this.trabajando.set(false),
      });
  }

  // ---- Renovar ----

  protected abrirRenovar(suscripcion: SuscripcionPlataforma): void {
    this.objetivo.set(suscripcion);
    this.opcionRenovar.set('1m');
    this.fechaLibre.set(null);
    this.dialogoRenovarVisible.set(true);
  }

  protected guardarRenovacion(): void {
    const objetivo = this.objetivo();
    const fecha = this.fechaRenovada();
    if (objetivo === null || fecha === null || !this.renovacionValida() || this.trabajando()) return;
    this.trabajando.set(true);
    this.servicio.renovar(objetivo.id, fechaLocalIso(fecha)).subscribe({
      next: () => {
        this.trabajando.set(false);
        this.dialogoRenovarVisible.set(false);
        this.messageService.add({
          severity: 'success',
          summary: 'Suscripción renovada',
          detail: `${this.nombreEmpresa(objetivo.empresa_id)} vence el ${fechaLocalIso(fecha).split('-').reverse().join('/')}.`,
        });
        this.cargar();
      },
      error: () => this.trabajando.set(false),
    });
  }

  // ---- Estado ----

  protected reactivar(suscripcion: SuscripcionPlataforma): void {
    this.cambiarEstado(suscripcion, 'activa', 'Suscripción reactivada');
  }

  protected pedirSuspender(suscripcion: SuscripcionPlataforma): void {
    const empresa = this.nombreEmpresa(suscripcion.empresa_id);
    this.confirmationService.confirm({
      header: `Suspender a ${empresa}`,
      icon: 'pi pi-exclamation-triangle',
      message: 'La tienda y su personal quedan sin acceso hasta que reactives la suscripción.',
      acceptLabel: 'Sí, suspender',
      rejectLabel: 'Cancelar',
      accept: () => this.cambiarEstado(suscripcion, 'suspendida', 'Suscripción suspendida'),
    });
  }

  protected pedirCancelar(suscripcion: SuscripcionPlataforma): void {
    const empresa = this.nombreEmpresa(suscripcion.empresa_id);
    this.confirmationService.confirm({
      header: `Cancelar la suscripción de ${empresa}`,
      icon: 'pi pi-exclamation-triangle',
      message: 'La cancelación no se puede deshacer: para darle servicio otra vez hay que asignarle un plan nuevo.',
      acceptLabel: 'Sí, cancelar',
      rejectLabel: 'Volver',
      accept: () => this.cambiarEstado(suscripcion, 'cancelada', 'Suscripción cancelada'),
    });
  }

  private cambiarEstado(suscripcion: SuscripcionPlataforma, estado: EstadoSuscripcionPedido, resumen: string): void {
    if (this.trabajando()) return;
    this.trabajando.set(true);
    this.servicio.cambiarEstado(suscripcion.id, estado).subscribe({
      next: () => {
        this.trabajando.set(false);
        this.messageService.add({
          severity: 'success',
          summary: resumen,
          detail: this.nombreEmpresa(suscripcion.empresa_id),
        });
        this.cargar();
      },
      error: () => this.trabajando.set(false),
    });
  }
}
