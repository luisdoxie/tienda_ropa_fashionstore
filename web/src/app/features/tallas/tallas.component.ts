import { HttpClient } from '@angular/common/http';
import { Component, ViewChild, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { InputNumberModule } from 'primeng/inputnumber';
import { InputTextModule } from 'primeng/inputtext';
import { finalize } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Talla, TallaCrear } from '../../core/models/catalogo.models';
import { DialogoCrudComponent } from '../../shared/tabla-generica/dialogo-crud.component';
import { AriaErrorDirective, ErrorCampoComponent } from '../../shared/tabla-generica/error-campo.component';
import { ColumnaTabla, TablaGenericaComponent } from '../../shared/tabla-generica/tabla-generica.component';

const COLUMNAS: ColumnaTabla<Talla>[] = [
  { campo: 'codigo', encabezado: 'Código' },
  { campo: 'descripcion', encabezado: 'Descripción' },
  { campo: 'orden', encabezado: 'Orden' },
];

@Component({
  selector: 'app-tallas',
  standalone: true,
  imports: [ReactiveFormsModule, InputNumberModule, InputTextModule, TablaGenericaComponent, DialogoCrudComponent, ErrorCampoComponent, AriaErrorDirective],
  templateUrl: './tallas.component.html',
})
export class TallasComponent {
  protected readonly columnas = COLUMNAS;
  protected readonly dialogoVisible = signal(false);
  /** Mientras la petición de guardar está en vuelo, Guardar queda deshabilitado. */
  protected readonly guardando = signal(false);
  protected readonly editando = signal<Talla | null>(null);

  @ViewChild(TablaGenericaComponent) private tabla!: TablaGenericaComponent<Talla>;

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);

  protected readonly formulario = this.fb.nonNullable.group({
    codigo: ['', Validators.required],
    descripcion: [''],
    orden: [0],
  });

  abrirCrear(): void {
    this.editando.set(null);
    this.formulario.reset({ codigo: '', descripcion: '', orden: 0 });
    this.dialogoVisible.set(true);
  }

  abrirEditar(talla: Talla): void {
    this.editando.set(talla);
    this.formulario.reset({ codigo: talla.codigo, descripcion: talla.descripcion ?? '', orden: talla.orden });
    this.dialogoVisible.set(true);
  }

  guardar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const valores = this.formulario.getRawValue();
    const talla = this.editando();
    const datos: TallaCrear = { codigo: valores.codigo, descripcion: valores.descripcion || null, orden: valores.orden };

    const peticion = talla
      ? this.http.put(`${environment.apiUrl}/tallas/${talla.id}`, datos)
      : this.http.post(`${environment.apiUrl}/tallas`, datos);

    this.guardando.set(true);
    peticion.pipe(finalize(() => this.guardando.set(false))).subscribe(() => {
      this.dialogoVisible.set(false);
      this.tabla.recargar();
    });
  }
}
