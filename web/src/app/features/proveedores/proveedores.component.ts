import { HttpClient } from '@angular/common/http';
import { Component, OnInit, ViewChild, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { finalize } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Proveedor, ProveedorCrear } from '../../core/models/abastecimiento.models';
import { Usuario } from '../../core/models/seguridad.models';
import { DialogoCrudComponent } from '../../shared/tabla-generica/dialogo-crud.component';
import { AriaErrorDirective, ErrorCampoComponent } from '../../shared/tabla-generica/error-campo.component';
import { ColumnaTabla, TablaGenericaComponent } from '../../shared/tabla-generica/tabla-generica.component';

const COLUMNAS: ColumnaTabla<Proveedor>[] = [
  { campo: 'nombre', encabezado: 'Nombre' },
  { campo: 'nit', encabezado: 'NIT' },
  { campo: 'contacto', encabezado: 'Contacto' },
  { campo: 'telefono', encabezado: 'Teléfono' },
  { campo: 'activo', encabezado: 'Activo', tipo: 'booleano' },
];

@Component({
  selector: 'app-proveedores',
  standalone: true,
  imports: [ReactiveFormsModule, InputTextModule, SelectModule, TablaGenericaComponent, DialogoCrudComponent, ErrorCampoComponent, AriaErrorDirective],
  templateUrl: './proveedores.component.html',
})
export class ProveedoresComponent implements OnInit {
  protected readonly columnas = COLUMNAS;
  protected readonly dialogoVisible = signal(false);
  /** Mientras la petición de guardar está en vuelo, Guardar queda deshabilitado. */
  protected readonly guardando = signal(false);
  protected readonly editando = signal<Proveedor | null>(null);

  private readonly usuarios = signal<Usuario[]>([]);
  protected readonly opcionesUsuario = computed(() =>
    this.usuarios()
      .filter((u) => u.roles.includes('proveedor'))
      .map((u) => ({ id: u.id, etiqueta: `${u.nombre} ${u.apellido} (${u.email})` })),
  );

  @ViewChild(TablaGenericaComponent) private tabla!: TablaGenericaComponent<Proveedor>;

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', Validators.required],
    nit: [''],
    contacto: [''],
    telefono: [''],
    email: ['', Validators.email],
    direccion: [''],
    usuario_id: [null as number | null],
  });

  ngOnInit(): void {
    this.http
      .get<Usuario[]>(`${environment.apiUrl}/usuarios?pagina=1&tamanio=100`)
      .subscribe((usuarios) => this.usuarios.set(usuarios));
  }

  abrirCrear(): void {
    this.editando.set(null);
    this.formulario.reset({
      nombre: '',
      nit: '',
      contacto: '',
      telefono: '',
      email: '',
      direccion: '',
      usuario_id: null,
    });
    this.dialogoVisible.set(true);
  }

  abrirEditar(proveedor: Proveedor): void {
    this.editando.set(proveedor);
    this.formulario.reset({
      nombre: proveedor.nombre,
      nit: proveedor.nit ?? '',
      contacto: proveedor.contacto ?? '',
      telefono: proveedor.telefono ?? '',
      email: proveedor.email ?? '',
      direccion: proveedor.direccion ?? '',
      usuario_id: proveedor.usuario_id,
    });
    this.dialogoVisible.set(true);
  }

  guardar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const valores = this.formulario.getRawValue();
    const proveedor = this.editando();
    const datos: ProveedorCrear = {
      nombre: valores.nombre,
      nit: valores.nit || null,
      contacto: valores.contacto || null,
      telefono: valores.telefono || null,
      email: valores.email || null,
      direccion: valores.direccion || null,
      usuario_id: valores.usuario_id,
    };

    const peticion = proveedor
      ? this.http.put(`${environment.apiUrl}/proveedores/${proveedor.id}`, datos)
      : this.http.post(`${environment.apiUrl}/proveedores`, datos);

    this.guardando.set(true);
    peticion.pipe(finalize(() => this.guardando.set(false))).subscribe(() => {
      this.dialogoVisible.set(false);
      this.tabla.recargar();
    });
  }
}
