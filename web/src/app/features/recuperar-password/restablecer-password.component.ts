import { Component, computed, inject, signal } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { PasswordModule } from 'primeng/password';
import { AuthService } from '../../core/auth.service';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';

function passwordsIgualesValidator(grupo: AbstractControl): ValidationErrors | null {
  const password = grupo.get('password')?.value;
  const confirmar = grupo.get('confirmarPassword')?.value;
  return password === confirmar ? null : { passwordsDistintas: true };
}

@Component({
  selector: 'app-restablecer-password',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, ButtonModule, PasswordModule],
  templateUrl: './restablecer-password.component.html',
})
export class RestablecerPasswordComponent {
  protected readonly cargando = signal(false);
  protected readonly completado = signal(false);
  protected readonly error = signal<string | null>(null);

  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly token = inject(ActivatedRoute).snapshot.queryParamMap.get('token');
  protected readonly sinToken = computed(() => !this.token);
  private readonly tienda = inject(TiendaActualService);

  /** Con tienda (/t/:codigo/restablecer) los enlaces quedan dentro de ella; suelto (/restablecer) se queda como antes. */
  protected readonly rutaLogin = computed(() => (this.tienda.codigo() ? this.tienda.ruta('login') : ['/login']));
  protected readonly rutaRecuperar = computed(() => (this.tienda.codigo() ? this.tienda.ruta('recuperar') : ['/recuperar']));

  protected readonly formulario = this.fb.nonNullable.group(
    {
      password: ['', [Validators.required, Validators.minLength(8)]],
      confirmarPassword: ['', [Validators.required]],
    },
    { validators: passwordsIgualesValidator },
  );

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
        this.error.set('El enlace de recuperación venció o no es válido. Solicitá uno nuevo.');
      },
    });
  }
}
