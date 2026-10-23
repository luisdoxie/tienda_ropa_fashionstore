import { HttpClient } from '@angular/common/http';
import { Component, ViewChild, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { DatePickerModule } from 'primeng/datepicker';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { finalize } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Temporada, TemporadaCrear } from '../../core/models/catalogo.models';
import { DialogoCrudComponent } from '../../shared/tabla-generica/dialogo-crud.component';
import { AriaErrorDirective, ErrorCampoComponent } from '../../shared/tabla-generica/error-campo.component';
import { ColumnaTabla, TablaGenericaComponent } from '../../shared/tabla-generica/tabla-generica.component';

const COLUMNAS: ColumnaTabla<Temporada>[] = [
  { campo: 'nombre', encabezado: 'Nombre' },
  { campo: 'anio', encabezado: 'Año' },
  { campo: 'fecha_inicio', encabezado: 'Desde', tipo: 'fecha' },
  { campo: 'fecha_fin', encabezado: 'Hasta', tipo: 'fecha' },
  { campo: 'activo', encabezado: 'Activa', tipo: 'booleano', femenino: true },
];

// `new Date("2026-08-31")` parsea la fecha-sin-hora como medianoche UTC:
// en un huso horario detrás de UTC, el datepicker (que muestra en hora
// LOCAL) la corre un día para atrás -- mismo problema y misma solución que
// ya usa promociones.component.ts.
function aFechaIso(fecha: Date): string {
  const y = fecha.getFullYear();
  const m = String(fecha.getMonth() + 1).padStart(2, '0');
  const d = String(fecha.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function aFechaLocal(fechaIso: string): Date {
  const [y, m, d] = fechaIso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

@Component({
  selector: 'app-temporadas',
  standalone: true,
  imports: [ReactiveFormsModule, DatePickerModule, InputNumberModule, InputTextModule, TablaGenericaComponent, DialogoCrudComponent, ErrorCampoComponent, AriaErrorDirective],
  templateUrl: './temporadas.component.html',
})
export class TemporadasComponent {
  protected readonly columnas = COLUMNAS;
  protected readonly dialogoVisible = signal(false);
  /** Mientras la petición de guardar está en vuelo, Guardar queda deshabilitado. */
  protected readonly guardando = signal(false);
  protected readonly editando = signal<Temporada | null>(null);

  @ViewChild(TablaGenericaComponent) private tabla!: TablaGenericaComponent<Temporada>;

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', Validators.required],
    anio: [new Date().getFullYear(), [Validators.required, Validators.min(2000), Validators.max(2100)]],
    fecha_inicio: [null as Date | null],
    fecha_fin: [null as Date | null],
  });

  abrirCrear(): void {
    this.editando.set(null);
    this.formulario.reset({ nombre: '', anio: new Date().getFullYear(), fecha_inicio: null, fecha_fin: null });
    this.dialogoVisible.set(true);
  }

  abrirEditar(temporada: Temporada): void {
    this.editando.set(temporada);
    this.formulario.reset({
      nombre: temporada.nombre,
      anio: temporada.anio,
      fecha_inicio: temporada.fecha_inicio ? aFechaLocal(temporada.fecha_inicio) : null,
      fecha_fin: temporada.fecha_fin ? aFechaLocal(temporada.fecha_fin) : null,
    });
    this.dialogoVisible.set(true);
  }

  guardar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const valores = this.formulario.getRawValue();
    const temporada = this.editando();
    const datos: TemporadaCrear = {
      nombre: valores.nombre,
      anio: valores.anio,
      fecha_inicio: valores.fecha_inicio ? aFechaIso(valores.fecha_inicio) : null,
      fecha_fin: valores.fecha_fin ? aFechaIso(valores.fecha_fin) : null,
    };

    const peticion = temporada
      ? this.http.put(`${environment.apiUrl}/temporadas/${temporada.id}`, datos)
      : this.http.post(`${environment.apiUrl}/temporadas`, datos);

    this.guardando.set(true);
    peticion.pipe(finalize(() => this.guardando.set(false))).subscribe(() => {
      this.dialogoVisible.set(false);
      this.tabla.recargar();
    });
  }
}
