import { HttpClient } from '@angular/common/http';
import { Component, ViewChild, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { InputTextModule } from 'primeng/inputtext';
import { finalize } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Ciudad } from '../../core/models/organizacion.models';
import { DialogoCrudComponent } from '../../shared/tabla-generica/dialogo-crud.component';
import { AriaErrorDirective, ErrorCampoComponent } from '../../shared/tabla-generica/error-campo.component';
import { ColumnaTabla, TablaGenericaComponent } from '../../shared/tabla-generica/tabla-generica.component';

const COLUMNAS: ColumnaTabla<Ciudad>[] = [
  { campo: 'nombre', encabezado: 'Nombre' },
  { campo: 'departamento', encabezado: 'Departamento' },
  { campo: 'activo', encabezado: 'Activo', tipo: 'booleano' },
];

@Component({
  selector: 'app-ciudades',
  standalone: true,
  imports: [ReactiveFormsModule, InputTextModule, TablaGenericaComponent, DialogoCrudComponent, ErrorCampoComponent, AriaErrorDirective],
  templateUrl: './ciudades.component.html',
})
export class CiudadesComponent {
  protected readonly columnas = COLUMNAS;
  protected readonly dialogoVisible = signal(false);
  /** Mientras la petición de guardar está en vuelo, Guardar queda deshabilitado. */
  protected readonly guardando = signal(false);
  protected readonly editando = signal<Ciudad | null>(null);

  @ViewChild(TablaGenericaComponent) private tabla!: TablaGenericaComponent<Ciudad>;

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', Validators.required],
    departamento: [''],
  });

  abrirCrear(): void {
    this.editando.set(null);
    this.formulario.reset({ nombre: '', departamento: '' });
    this.dialogoVisible.set(true);
  }

  abrirEditar(ciudad: Ciudad): void {
    this.editando.set(ciudad);
    this.formulario.reset({ nombre: ciudad.nombre, departamento: ciudad.departamento ?? '' });
    this.dialogoVisible.set(true);
  }

  guardar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const datos = this.formulario.getRawValue();
    const ciudad = this.editando();
    const peticion = ciudad
      ? this.http.put(`${environment.apiUrl}/ciudades/${ciudad.id}`, datos)
      : this.http.post(`${environment.apiUrl}/ciudades`, datos);

    this.guardando.set(true);
    peticion.pipe(finalize(() => this.guardando.set(false))).subscribe(() => {
      this.dialogoVisible.set(false);
      this.tabla.recargar();
    });
  }
}
