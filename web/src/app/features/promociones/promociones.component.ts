import { HttpClient } from '@angular/common/http';
import { Component, ViewChild, inject, signal } from '@angular/core';
import { FormArray, FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DatePickerModule } from 'primeng/datepicker';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { finalize } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Promocion, PromocionActualizar, PromocionCrear, TipoPromocion } from '../../core/models/ventas.models';
import { DialogoCrudComponent } from '../../shared/tabla-generica/dialogo-crud.component';
import { AriaErrorDirective, ErrorCampoComponent } from '../../shared/tabla-generica/error-campo.component';
import { ColumnaTabla, TablaGenericaComponent } from '../../shared/tabla-generica/tabla-generica.component';

type TipoAlcance = 'producto' | 'categoria' | 'temporada';

const COLUMNAS: ColumnaTabla<Promocion>[] = [
  { campo: 'nombre', encabezado: 'Nombre' },
  { campo: 'tipo', encabezado: 'Tipo' },
  { campo: 'valor', encabezado: 'Valor' },
  { campo: 'fecha_inicio', encabezado: 'Desde', tipo: 'fecha' },
  { campo: 'fecha_fin', encabezado: 'Hasta', tipo: 'fecha' },
  { campo: 'activo', encabezado: 'Activa', tipo: 'booleano', femenino: true },
];

const OPCIONES_TIPO: { label: string; value: TipoPromocion }[] = [
  { label: 'Porcentaje', value: 'porcentaje' },
  { label: 'Monto fijo', value: 'monto' },
];

const OPCIONES_ALCANCE: { label: string; value: TipoAlcance }[] = [
  { label: 'Producto', value: 'producto' },
  { label: 'Categoría', value: 'categoria' },
  { label: 'Temporada', value: 'temporada' },
];

function aFechaIso(fecha: Date): string {
  const y = fecha.getFullYear();
  const m = String(fecha.getMonth() + 1).padStart(2, '0');
  const d = String(fecha.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

// `new Date("2026-08-31")` parsea la fecha-sin-hora como medianoche UTC:
// en un huso horario detrás de UTC, el datepicker (que muestra en hora
// LOCAL) la corre un día para atrás. Se arman los componentes a mano para
// que quede en el mismo día local que mandó el backend.
function aFechaLocal(fechaIso: string): Date {
  const [y, m, d] = fechaIso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

@Component({
  selector: 'app-promociones',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    ButtonModule,
    CheckboxModule,
    DatePickerModule,
    InputNumberModule,
    InputTextModule,
    SelectModule,
    TablaGenericaComponent,
    DialogoCrudComponent,
    ErrorCampoComponent, AriaErrorDirective,
  ],
  templateUrl: './promociones.component.html',
  styleUrl: './promociones.component.scss',
})
export class PromocionesComponent {
  protected readonly columnas = COLUMNAS;
  protected readonly opcionesTipo = OPCIONES_TIPO;
  protected readonly opcionesAlcance = OPCIONES_ALCANCE;
  protected readonly dialogoVisible = signal(false);
  /** Mientras la petición de guardar está en vuelo, Guardar queda deshabilitado. */
  protected readonly guardando = signal(false);
  protected readonly editando = signal<Promocion | null>(null);

  @ViewChild(TablaGenericaComponent) private tabla!: TablaGenericaComponent<Promocion>;

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);
  private readonly messageService = inject(MessageService);

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', Validators.required],
    tipo: ['porcentaje' as TipoPromocion, Validators.required],
    valor: [0, [Validators.required, Validators.min(0.01)]],
    fecha_inicio: [null as Date | null, Validators.required],
    fecha_fin: [null as Date | null, Validators.required],
    activo: [true],
    alcances: this.fb.array([this.crearLineaAlcance()]),
  });

  private crearLineaAlcance() {
    return this.fb.nonNullable.group({
      tipo: ['producto' as TipoAlcance, Validators.required],
      id: [null as number | null, Validators.required],
    });
  }

  protected get lineasAlcance(): FormArray {
    return this.formulario.get('alcances') as FormArray;
  }

  agregarAlcance(): void {
    this.lineasAlcance.push(this.crearLineaAlcance());
  }

  quitarAlcance(indice: number): void {
    if (this.lineasAlcance.length > 1) {
      this.lineasAlcance.removeAt(indice);
    }
  }

  abrirCrear(): void {
    this.editando.set(null);
    this.formulario.reset({
      nombre: '',
      tipo: 'porcentaje',
      valor: 0,
      fecha_inicio: null,
      fecha_fin: null,
      activo: true,
    });
    while (this.lineasAlcance.length > 1) {
      this.lineasAlcance.removeAt(this.lineasAlcance.length - 1);
    }
    this.lineasAlcance.at(0).reset({ tipo: 'producto', id: null });
    this.lineasAlcance.enable();
    this.dialogoVisible.set(true);
  }

  abrirEditar(promocion: Promocion): void {
    this.editando.set(promocion);
    // El bloque de alcance se oculta al editar (el alcance no se puede
    // cambiar después de creada la promoción, ver PromocionActualizar):
    // sin deshabilitarlo, su control "id" sigue siendo required aunque no
    // se vea, e invalida el formulario entero y "Guardar" no hace nada.
    this.lineasAlcance.disable();
    this.formulario.reset({
      nombre: promocion.nombre,
      tipo: promocion.tipo,
      valor: promocion.valor,
      fecha_inicio: aFechaLocal(promocion.fecha_inicio),
      fecha_fin: aFechaLocal(promocion.fecha_fin),
      activo: promocion.activo,
    });
    this.dialogoVisible.set(true);
  }

  guardar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const valores = this.formulario.getRawValue();
    const promocion = this.editando();

    if (promocion) {
      const payload: PromocionActualizar = {
        nombre: valores.nombre,
        valor: valores.valor,
        fecha_inicio: aFechaIso(valores.fecha_inicio!),
        fecha_fin: aFechaIso(valores.fecha_fin!),
        activo: valores.activo,
      };
      this.guardando.set(true);
      this.http
        .put(`${environment.apiUrl}/promociones/${promocion.id}`, payload)
        .pipe(finalize(() => this.guardando.set(false)))
        .subscribe(() => {
        this.dialogoVisible.set(false);
        this.tabla.recargar();
      });
      return;
    }

    const payload: PromocionCrear = {
      nombre: valores.nombre,
      tipo: valores.tipo,
      valor: valores.valor,
      fecha_inicio: aFechaIso(valores.fecha_inicio!),
      fecha_fin: aFechaIso(valores.fecha_fin!),
      alcances: valores.alcances.map((linea) => ({
        producto_id: linea.tipo === 'producto' ? linea.id! : undefined,
        categoria_id: linea.tipo === 'categoria' ? linea.id! : undefined,
        temporada_id: linea.tipo === 'temporada' ? linea.id! : undefined,
      })),
    };
    this.guardando.set(true);
    this.http
      .post(`${environment.apiUrl}/promociones`, payload)
      .pipe(finalize(() => this.guardando.set(false)))
      .subscribe(() => {
      this.messageService.add({ severity: 'success', summary: 'Promoción creada' });
      this.dialogoVisible.set(false);
      this.tabla.recargar();
    });
  }
}
