import { HttpClient } from '@angular/common/http';
import { Component, OnInit, ViewChild, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { CheckboxModule } from 'primeng/checkbox';
import { InputTextModule } from 'primeng/inputtext';
import { MultiSelectModule } from 'primeng/multiselect';
import { PasswordModule } from 'primeng/password';
import { finalize, switchMap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Rol, Usuario } from '../../core/models/seguridad.models';
import { DialogoCrudComponent } from '../../shared/tabla-generica/dialogo-crud.component';
import { AriaErrorDirective, ErrorCampoComponent } from '../../shared/tabla-generica/error-campo.component';
import { ColumnaTabla, TablaGenericaComponent } from '../../shared/tabla-generica/tabla-generica.component';

const COLUMNAS: ColumnaTabla<Usuario>[] = [
  { campo: 'nombre', encabezado: 'Nombre' },
  { campo: 'apellido', encabezado: 'Apellido' },
  { campo: 'email', encabezado: 'Email' },
  { campo: 'roles', encabezado: 'Roles' },
  { campo: 'activo', encabezado: 'Activo', tipo: 'booleano' },
];

@Component({
  selector: 'app-usuarios',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    InputTextModule,
    PasswordModule,
    CheckboxModule,
    MultiSelectModule,
    TablaGenericaComponent,
    DialogoCrudComponent,
    ErrorCampoComponent, AriaErrorDirective,
  ],
  templateUrl: './usuarios.component.html',
})
export class UsuariosComponent implements OnInit {
  protected readonly columnas = COLUMNAS;
  protected readonly dialogoVisible = signal(false);
  /** Mientras la petición de guardar está en vuelo, Guardar queda deshabilitado. */
  protected readonly guardando = signal(false);
  protected readonly editando = signal<Usuario | null>(null);
  protected readonly roles = signal<Rol[]>([]);

  @ViewChild(TablaGenericaComponent) private tabla!: TablaGenericaComponent<Usuario>;

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', Validators.required],
    apellido: ['', Validators.required],
    email: ['', [Validators.required, Validators.email]],
    telefono: [''],
    password: [''],
    roles: [[] as string[]],
    activo: [true],
  });

  ngOnInit(): void {
    this.http
      .get<Rol[]>(`${environment.apiUrl}/roles?pagina=1&tamanio=100`)
      .subscribe((roles) => this.roles.set(roles.filter((r) => r.activo)));
  }

  abrirCrear(): void {
    this.editando.set(null);
    this.formulario.reset({
      nombre: '',
      apellido: '',
      email: '',
      telefono: '',
      password: '',
      roles: [],
      activo: true,
    });
    this.formulario.controls.email.enable();
    this.formulario.controls.password.setValidators([Validators.required, Validators.minLength(8)]);
    this.formulario.controls.password.updateValueAndValidity();
    this.dialogoVisible.set(true);
  }

  abrirEditar(usuario: Usuario): void {
    this.editando.set(usuario);
    this.formulario.reset({
      nombre: usuario.nombre,
      apellido: usuario.apellido,
      email: usuario.email,
      telefono: usuario.telefono ?? '',
      password: '',
      roles: usuario.roles,
      activo: usuario.activo,
    });
    this.formulario.controls.email.disable(); // el email no se edita, es la identidad de login
    this.formulario.controls.password.clearValidators();
    this.formulario.controls.password.updateValueAndValidity();
    this.dialogoVisible.set(true);
  }

  guardar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const usuario = this.editando();
    const nombresRol = this.formulario.controls.roles.value;
    const peticion = usuario
      ? this.http.put<Usuario>(`${environment.apiUrl}/usuarios/${usuario.id}`, {
          nombre: this.formulario.controls.nombre.value,
          apellido: this.formulario.controls.apellido.value,
          telefono: this.formulario.controls.telefono.value,
          activo: this.formulario.controls.activo.value,
        })
      : this.http.post<Usuario>(`${environment.apiUrl}/usuarios`, {
          nombre: this.formulario.controls.nombre.value,
          apellido: this.formulario.controls.apellido.value,
          email: this.formulario.controls.email.value,
          telefono: this.formulario.controls.telefono.value,
          password: this.formulario.controls.password.value,
        });

    this.guardando.set(true);
    peticion
      .pipe(
        switchMap((guardado) =>
          this.http.put(`${environment.apiUrl}/usuarios/${guardado.id}/roles`, { nombres_rol: nombresRol }),
        ),
        finalize(() => this.guardando.set(false)),
      )
      .subscribe(() => {
        this.dialogoVisible.set(false);
        this.tabla.recargar();
      });
  }
}
