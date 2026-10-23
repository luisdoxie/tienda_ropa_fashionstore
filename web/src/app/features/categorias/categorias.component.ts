import { HttpClient } from '@angular/common/http';
import { Component, OnInit, ViewChild, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { finalize } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Categoria, CategoriaCrear } from '../../core/models/catalogo.models';
import { DialogoCrudComponent } from '../../shared/tabla-generica/dialogo-crud.component';
import { AriaErrorDirective, ErrorCampoComponent } from '../../shared/tabla-generica/error-campo.component';
import { ColumnaTabla, TablaGenericaComponent } from '../../shared/tabla-generica/tabla-generica.component';

const COLUMNAS: ColumnaTabla<Categoria>[] = [
  { campo: 'nombre', encabezado: 'Nombre' },
  { campo: 'descripcion', encabezado: 'Descripción' },
  { campo: 'activo', encabezado: 'Activa', tipo: 'booleano', femenino: true },
];

@Component({
  selector: 'app-categorias',
  standalone: true,
  imports: [ReactiveFormsModule, InputTextModule, SelectModule, TablaGenericaComponent, DialogoCrudComponent, ErrorCampoComponent, AriaErrorDirective],
  templateUrl: './categorias.component.html',
})
export class CategoriasComponent implements OnInit {
  protected readonly columnas = COLUMNAS;
  protected readonly dialogoVisible = signal(false);
  /** Mientras la petición de guardar está en vuelo, Guardar queda deshabilitado. */
  protected readonly guardando = signal(false);
  protected readonly editando = signal<Categoria | null>(null);
  protected readonly categorias = signal<Categoria[]>([]);

  @ViewChild(TablaGenericaComponent) private tabla!: TablaGenericaComponent<Categoria>;

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);

  protected readonly formulario = this.fb.nonNullable.group({
    categoria_padre_id: [null as number | null],
    nombre: ['', Validators.required],
    descripcion: [''],
  });

  ngOnInit(): void {
    this.cargarCategorias();
  }

  private cargarCategorias(): void {
    this.http
      .get<Categoria[]>(`${environment.apiUrl}/categorias?pagina=1&tamanio=100`)
      .subscribe((categorias) => this.categorias.set(categorias));
  }

  abrirCrear(): void {
    this.editando.set(null);
    this.formulario.reset({ categoria_padre_id: null, nombre: '', descripcion: '' });
    this.dialogoVisible.set(true);
  }

  abrirEditar(categoria: Categoria): void {
    this.editando.set(categoria);
    this.formulario.reset({
      categoria_padre_id: categoria.categoria_padre_id,
      nombre: categoria.nombre,
      descripcion: categoria.descripcion ?? '',
    });
    this.dialogoVisible.set(true);
  }

  guardar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const valores = this.formulario.getRawValue();
    const categoria = this.editando();
    const datos: CategoriaCrear = {
      categoria_padre_id: valores.categoria_padre_id,
      nombre: valores.nombre,
      descripcion: valores.descripcion || null,
    };

    const peticion = categoria
      ? this.http.put(`${environment.apiUrl}/categorias/${categoria.id}`, datos)
      : this.http.post(`${environment.apiUrl}/categorias`, datos);

    this.guardando.set(true);
    peticion.pipe(finalize(() => this.guardando.set(false))).subscribe(() => {
      this.dialogoVisible.set(false);
      this.cargarCategorias();
      this.tabla.recargar();
    });
  }
}
