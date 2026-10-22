import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { PasswordModule } from 'primeng/password';
import { switchMap } from 'rxjs';
import { AuthService } from '../../core/auth.service';
import { navegarDespuesDeLogin } from '../../core/post-login-redirect';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, ButtonModule, InputTextModule, PasswordModule],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
})
export class LoginComponent {
  protected readonly cargando = signal(false);
  protected readonly errorLogin = signal<string | null>(null);

  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly returnTo = inject(ActivatedRoute).snapshot.queryParamMap.get('returnTo');
  protected readonly tienda = inject(TiendaActualService);

  /** Con tienda, el registro y la recuperación viven bajo /t/:codigo; sin tienda (login del personal) se queda como antes. */
  protected readonly rutaRecuperar = computed(() => (this.tienda.codigo() ? this.tienda.ruta('recuperar') : ['/recuperar']));
  protected readonly rutaRegistro = computed(() => (this.tienda.codigo() ? this.tienda.ruta('registro') : ['/registro']));

  protected readonly queryParamsRegistro = this.returnTo ? { returnTo: this.returnTo } : {};

  protected readonly formulario = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });

  enviar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    this.cargando.set(true);
    this.errorLogin.set(null);
    const { email, password } = this.formulario.getRawValue();

    this.authService
      .login(email, password, this.tienda.codigo())
      .pipe(switchMap(() => this.authService.cargarUsuarioActual()))
      .subscribe({
        next: () => {
          this.cargando.set(false);
          navegarDespuesDeLogin(this.router, this.authService, this.returnTo, this.tienda);
        },
        error: () => {
          this.cargando.set(false);
          this.errorLogin.set('Email o contraseña incorrectos.');
        },
      });
  }
}
