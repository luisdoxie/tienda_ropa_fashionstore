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
  selector: 'app-registro',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, ButtonModule, InputTextModule, PasswordModule],
  templateUrl: './registro.component.html',
})
export class RegistroComponent {
  protected readonly cargando = signal(false);
  protected readonly error = signal<string | null>(null);

  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly returnTo = inject(ActivatedRoute).snapshot.queryParamMap.get('returnTo');
  protected readonly tienda = inject(TiendaActualService);

  protected readonly rutaLogin = computed(() => (this.tienda.codigo() ? this.tienda.ruta('login') : ['/login']));

  protected readonly queryParamsLogin = this.returnTo ? { returnTo: this.returnTo } : {};

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', Validators.required],
    apellido: ['', Validators.required],
    email: ['', [Validators.required, Validators.email]],
    telefono: [''],
    ciNit: [''],
    password: ['', [Validators.required, Validators.minLength(8)]],
  });

  enviar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    // Los clientes se registran por tienda: sin tienda no hay a dónde registrarlos.
    const codigoTienda = this.tienda.codigo();
    if (!codigoTienda) {
      this.error.set('Para crear una cuenta entrá primero a una tienda.');
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
