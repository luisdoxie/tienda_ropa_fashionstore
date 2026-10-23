import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { switchMap } from 'rxjs';
import { AuthService, RUTA_LOGIN_PERSONAL } from '../../core/auth.service';
import { navegarDespuesDeLogin } from '../../core/post-login-redirect';
import { IconoComponent } from '../../shared/icono/icono.component';
import { AccesoPantallaComponent } from '../login/acceso-pantalla.component';
import { mensajeDeCampo } from '../login/mensajes-campo';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';

@Component({
  selector: 'app-registro',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, AccesoPantallaComponent, IconoComponent],
  templateUrl: './registro.component.html',
})
export class RegistroComponent {
  protected readonly cargando = signal(false);
  protected readonly error = signal<string | null>(null);
  /** Contraseña visible (el ojo del campo). */
  protected readonly verClave = signal(false);

  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly returnTo = inject(ActivatedRoute).snapshot.queryParamMap.get('returnTo');
  protected readonly tienda = inject(TiendaActualService);

  protected readonly rutaLogin = computed(() => (this.tienda.codigo() ? this.tienda.ruta('login') : [RUTA_LOGIN_PERSONAL]));

  protected readonly queryParamsLogin = this.returnTo ? { returnTo: this.returnTo } : {};

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', Validators.required],
    apellido: ['', Validators.required],
    email: ['', [Validators.required, Validators.email]],
    telefono: [''],
    ciNit: [''],
    password: ['', [Validators.required, Validators.minLength(8)]],
  });

  /** Mensaje de un campo inválido y ya tocado; null si está bien. */
  protected errorDe(campo: 'nombre' | 'apellido' | 'email' | 'password'): string | null {
    const mensajes: Record<string, Record<string, string>> = {
      nombre: { required: 'Escribe tu nombre.' },
      apellido: { required: 'Escribe tu apellido.' },
      email: { required: 'Escribe tu correo electrónico.', email: 'Escribe un correo válido.' },
      password: {
        required: 'Escribe una contraseña.',
        minlength: 'La contraseña necesita al menos 8 caracteres.',
      },
    };
    return mensajeDeCampo(this.formulario.controls[campo], mensajes[campo]);
  }

  enviar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    // Los clientes se registran por tienda: sin tienda no hay a dónde registrarlos.
    const codigoTienda = this.tienda.codigo();
    if (!codigoTienda) {
      this.error.set('Para crear una cuenta entra primero a una tienda.');
      return;
    }

    this.cargando.set(true);
    this.error.set(null);
    const { nombre, apellido, email, telefono, ciNit, password } = this.formulario.getRawValue();

    this.authService
      .registrar(
        {
          nombre,
          apellido,
          email,
          telefono: telefono || null,
          ci_nit: ciNit || null,
          password,
        },
        codigoTienda,
      )
      .pipe(
        switchMap(() => this.authService.login(email, password, codigoTienda)),
        switchMap(() => this.authService.cargarUsuarioActual()),
      )
      .subscribe({
        next: () => {
          this.cargando.set(false);
          navegarDespuesDeLogin(this.router, this.authService, this.returnTo, this.tienda);
        },
        error: (err) => {
          this.cargando.set(false);
          this.error.set(
            err?.status === 409 ? 'Ya existe una cuenta con ese email.' : 'No se pudo completar el registro.',
          );
        },
      });
  }
}
