import { Component, computed, inject, signal } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AuthService, RUTA_LOGIN_PERSONAL } from '../../core/auth.service';
import { IconoComponent } from '../../shared/icono/icono.component';
import { AccesoPantallaComponent } from '../login/acceso-pantalla.component';
import { mensajeDeCampo } from '../login/mensajes-campo';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';

function passwordsIgualesValidator(grupo: AbstractControl): ValidationErrors | null {
  const password = grupo.get('password')?.value;
  const confirmar = grupo.get('confirmarPassword')?.value;
  return password === confirmar ? null : { passwordsDistintas: true };
}

@Component({
  selector: 'app-restablecer-password',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, AccesoPantallaComponent, IconoComponent],
  templateUrl: './restablecer-password.component.html',
})
export class RestablecerPasswordComponent {
  protected readonly cargando = signal(false);
  protected readonly completado = signal(false);
  protected readonly error = signal<string | null>(null);
  /** Contraseñas visibles (el ojo del primer campo). */
  protected readonly verClave = signal(false);

  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly token = inject(ActivatedRoute).snapshot.queryParamMap.get('token');
  protected readonly sinToken = computed(() => !this.token);
  protected readonly tienda = inject(TiendaActualService);

  /** Con tienda (/t/:codigo/restablecer) los enlaces quedan dentro de ella; suelto (/restablecer) se queda como antes. */
  protected readonly rutaLogin = computed(() => (this.tienda.codigo() ? this.tienda.ruta('login') : [RUTA_LOGIN_PERSONAL]));
  protected readonly rutaRecuperar = computed(() => (this.tienda.codigo() ? this.tienda.ruta('recuperar') : ['/admin/recuperar']));

  /** Sin tienda (/restablecer) es el enlace del personal: pantalla oscura del acceso del personal. */
  protected readonly esPersonal = computed(() => !this.tienda.codigo());

  protected readonly formulario = this.fb.nonNullable.group(
    {
      password: ['', [Validators.required, Validators.minLength(8)]],
      confirmarPassword: ['', [Validators.required]],
    },
    { validators: passwordsIgualesValidator },
  );

  /** Mensaje de un campo inválido y ya tocado; null si está bien. */
  protected errorDe(campo: 'password' | 'confirmarPassword'): string | null {
    if (campo === 'password') {
      return mensajeDeCampo(this.formulario.controls.password, {
        required: 'Escribe una contraseña.',
        minlength: 'La contraseña necesita al menos 8 caracteres.',
      });
    }
    const confirmar = this.formulario.controls.confirmarPassword;
    if (!confirmar.touched) return null;
    if (confirmar.hasError('required')) return 'Repite la contraseña.';
    return this.formulario.hasError('passwordsDistintas') ? 'Las contraseñas no coinciden.' : null;
  }

  enviar(): void {
    if (!this.token || this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    this.cargando.set(true);
    this.error.set(null);
    const { password } = this.formulario.getRawValue();

    this.authService.confirmarRecuperacion(this.token, password).subscribe({
      next: () => {
        this.cargando.set(false);
        this.completado.set(true);
        setTimeout(() => this.router.navigate(this.rutaLogin()), 2500);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set('El enlace de recuperación venció o no es válido. Solicita uno nuevo.');
      },
    });
  }
}
