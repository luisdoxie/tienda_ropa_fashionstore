import { Component, OnInit, inject, signal } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputNumberModule } from 'primeng/inputnumber';
import { TableModule } from 'primeng/table';
import { FUNCIONES_PLAN, FuncionPlan } from '../../../core/models/plan.models';
import { PlanPlataforma, PlanPlataformaActualizar } from '../../../core/models/plataforma.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { PlataformaService } from '../data/plataforma.service';

/** Rangos que valida el backend (`PlanActualizar` en plataforma/schemas.py). */
export const LIMITES_PLAN = {
  max_sucursales: { min: 1, max: 1000 },
  max_copias_historial: { min: 0, max: 1000 },
  plazo_cambio_horas_defecto: { min: 0, max: 8760 },
} as const;

type CampoNumerico = keyof typeof LIMITES_PLAN;

const CAMPOS_NUMERICOS = Object.keys(LIMITES_PLAN) as CampoNumerico[];

function entero(control: AbstractControl): ValidationErrors | null {
  const valor = control.value;
  return valor === null || valor === undefined || Number.isInteger(valor) ? null : { entero: true };
}

function validadoresNumero(campo: CampoNumerico) {
  const { min, max } = LIMITES_PLAN[campo];
  return [Validators.required, Validators.min(min), Validators.max(max), entero];
}

/**
 * Planes de la plataforma (CU-04, solo superadministrador): límites y
 * funcionalidades. La interfaz no crea ni borra planes, y el código y el
 * nombre no se editan. Los rangos los valida también el backend.
 */
@Component({
  selector: 'app-planes',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    ButtonModule,
    CheckboxModule,
    DialogModule,
    InputNumberModule,
    TableModule,
    IconoComponent,
  ],
  templateUrl: './planes.component.html',
  styleUrl: './planes.component.scss',
})
export class PlanesComponent implements OnInit {
  private readonly servicio = inject(PlataformaService);
  private readonly fb = inject(FormBuilder);
  private readonly messageService = inject(MessageService);

  protected readonly funciones = FUNCIONES_PLAN;
  protected readonly limites = LIMITES_PLAN;

  protected readonly planes = signal<PlanPlataforma[]>([]);
  protected readonly cargando = signal(false);
  protected readonly guardando = signal(false);
  protected readonly dialogoVisible = signal(false);
  protected readonly editando = signal<PlanPlataforma | null>(null);

  protected readonly formulario = this.fb.group({
    max_sucursales: this.fb.control<number | null>(1, validadoresNumero('max_sucursales')),
    max_copias_historial: this.fb.control<number | null>(0, validadoresNumero('max_copias_historial')),
    plazo_cambio_horas_defecto: this.fb.control<number | null>(24, validadoresNumero('plazo_cambio_horas_defecto')),
    gestion_productos: this.fb.nonNullable.control(false),
    gestion_ventas: this.fb.nonNullable.control(false),
    reservas: this.fb.nonNullable.control(false),
    reportes_convencionales: this.fb.nonNullable.control(false),
    operacion_offline: this.fb.nonNullable.control(false),
    reportes_ia: this.fb.nonNullable.control(false),
    analitica_ml: this.fb.nonNullable.control(false),
    copias_seguridad: this.fb.nonNullable.control(false),
  });

  ngOnInit(): void {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    this.servicio.listarPlanes().subscribe({
      next: (planes) => {
        this.planes.set(planes);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  protected abrirEditar(plan: PlanPlataforma): void {
    this.editando.set(plan);
    this.formulario.reset({
      max_sucursales: plan.max_sucursales,
      max_copias_historial: plan.max_copias_historial,
      plazo_cambio_horas_defecto: plan.plazo_cambio_horas_defecto,
      gestion_productos: plan.gestion_productos,
      gestion_ventas: plan.gestion_ventas,
      reservas: plan.reservas,
      reportes_convencionales: plan.reportes_convencionales,
      operacion_offline: plan.operacion_offline,
      reportes_ia: plan.reportes_ia,
      analitica_ml: plan.analitica_ml,
      copias_seguridad: plan.copias_seguridad,
    });
    this.dialogoVisible.set(true);
  }

  protected hayError(campo: CampoNumerico): boolean {
    const control = this.formulario.controls[campo];
    return control.invalid && (control.touched || control.dirty);
  }

  /** Solo los campos que cambiaron respecto del plan abierto. */
  protected cambios(): PlanPlataformaActualizar {
    const plan = this.editando();
    if (plan === null) return {};
    const valores = this.formulario.getRawValue();
    const cambios: PlanPlataformaActualizar = {};
    for (const campo of CAMPOS_NUMERICOS) {
      const valor = valores[campo];
      if (valor !== null && valor !== plan[campo]) cambios[campo] = valor;
    }
    for (const { id } of FUNCIONES_PLAN) {
      const valor: boolean = valores[id as FuncionPlan];
      if (valor !== plan[id]) cambios[id] = valor;
    }
    return cambios;
  }

  protected guardar(): void {
    const plan = this.editando();
    if (plan === null || this.guardando()) return;
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const cambios = this.cambios();
    if (Object.keys(cambios).length === 0) {
      this.dialogoVisible.set(false);
      this.messageService.add({ severity: 'info', summary: 'Sin cambios', detail: `El plan ${plan.nombre} quedó como estaba.` });
      return;
    }

    this.guardando.set(true);
    this.servicio.actualizarPlan(plan.id, cambios).subscribe({
      next: () => {
        this.guardando.set(false);
        this.dialogoVisible.set(false);
        this.messageService.add({ severity: 'success', summary: 'Plan actualizado', detail: `Se guardaron los cambios del plan ${plan.nombre}.` });
        this.cargar();
      },
      // El rechazo del backend (409, 422) ya lo muestra el manejo global de errores.
      error: () => this.guardando.set(false),
    });
  }
}
