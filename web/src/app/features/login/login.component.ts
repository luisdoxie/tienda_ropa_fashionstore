import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { switchMap } from 'rxjs';
import { AuthService } from '../../core/auth.service';
import { codigoFuncional } from '../../core/errores-funcionales';
import { navegarDespuesDeLogin } from '../../core/post-login-redirect';
import { IconoComponent } from '../../shared/icono/icono.component';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';
import { AccesoPantallaComponent } from './acceso-pantalla.component';
import { mensajeDeCampo, sinSoloEspacios } from './mensajes-campo';

/** Última empresa con la que entró el personal en este navegador. */
export const CLAVE_ULTIMA_EMPRESA_PERSONAL = 'fs_ultima_empresa_personal';

export const RUTA_RECUPERAR_PERSONAL = '/admin/recuperar';

export const MENSAJE_LOGIN_PERSONAL = 'Empresa, correo o contraseña incorrectos.';
export const MENSAJE_LOGIN_CLIENTE = 'Email o contraseña incorrectos.';
export const MENSAJE_SUSCRIPCION_INACTIVA =
  'La suscripción de tu empresa no está activa. Avisa al administrador de la plataforma.';
export const MENSAJE_CUENTA_DE_CLIENTE = 'Esta cuenta es de cliente: ingresa desde la tienda.';
export const MENSAJE_DEMASIADOS_INTENTOS = 'Demasiados intentos. Prueba de nuevo en unos minutos.';

function leerUltimaEmpresa(): string {
  try {
    return localStorage.getItem(CLAVE_ULTIMA_EMPRESA_PERSONAL) ?? '';
  } catch {
    return '';
  }
}

function guardarUltimaEmpresa(empresa: string): void {
  try {
    localStorage.setItem(CLAVE_ULTIMA_EMPRESA_PERSONAL, empresa);
  } catch {
    // Sin almacenamiento: simplemente no se recuerda.
  }
}

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, AccesoPantallaComponent, IconoComponent],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
})
export class LoginComponent {
  protected readonly cargando = signal(false);
  protected readonly errorLogin = signal<string | null>(null);
  /** Contraseña visible (el ojo del campo). */
  protected readonly verClave = signal(false);

  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly returnTo = this.route.snapshot.queryParamMap.get('returnTo');
  protected readonly tienda = inject(TiendaActualService);

  /** 'personal' = /admin/login (empresa + correo + clave); si no, el login del comprador de una tienda. */
  protected readonly modo: 'cliente' | 'personal' = this.route.snapshot.data['modo'] === 'personal' ? 'personal' : 'cliente';
  protected readonly esPersonal = this.modo === 'personal';

  /** "Soy administrador de la plataforma": entra sin empresa. */
  protected readonly comoPlataforma = signal(false);

  /** Con tienda, el registro y la recuperación viven bajo /t/:codigo; el personal recupera en /admin/recuperar. */
  protected readonly rutaRecuperar = computed(() =>
    this.tienda.codigo() ? this.tienda.ruta('recuperar') : [RUTA_RECUPERAR_PERSONAL],
  );
  protected readonly rutaRegistro = computed(() => (this.tienda.codigo() ? this.tienda.ruta('registro') : ['/registro']));

  protected readonly queryParamsRegistro = this.returnTo ? { returnTo: this.returnTo } : {};

  protected readonly formulario = this.fb.nonNullable.group({
    empresa: [this.esPersonal ? leerUltimaEmpresa() : '', this.esPersonal ? [sinSoloEspacios] : []],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });

  /** Mensaje de un campo inválido y ya tocado; null si está bien. */
  protected errorDe(campo: 'empresa' | 'email' | 'password'): string | null {
    const mensajes: Record<string, Record<string, string>> = {
      empresa: { required: 'Escribe el nombre o el código de tu empresa.' },
      email: { required: 'Escribe tu correo electrónico.', email: 'Escribe un correo válido.' },
      password: { required: 'Escribe tu contraseña.' },
    };
    return mensajeDeCampo(this.formulario.controls[campo], mensajes[campo]);
  }

  /** Alterna entre entrar con una empresa y entrar como administrador de la plataforma. */
  protected alternarPlataforma(): void {
    const comoPlataforma = !this.comoPlataforma();
    this.comoPlataforma.set(comoPlataforma);
    this.errorLogin.set(null);
    const control = this.formulario.controls.empresa;
    if (comoPlataforma) {
      control.clearValidators();
    } else {
      control.setValidators([sinSoloEspacios]);
    }
    control.updateValueAndValidity();
  }

  enviar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    this.cargando.set(true);
    this.errorLogin.set(null);
    const { empresa, email, password } = this.formulario.getRawValue();
    const empresaIngresada = this.esPersonal && !this.comoPlataforma() ? empresa.trim() : null;
    // En una tienda manda su código; en /admin/login, lo que escribió el personal.
    const empresaDelLogin = this.esPersonal ? empresaIngresada : this.tienda.codigo();

    this.authService
      .login(email, password, empresaDelLogin)
      .pipe(switchMap(() => this.authService.cargarUsuarioActual()))
      .subscribe({
        next: () => {
          this.cargando.set(false);
          if (this.esPersonal && this.authService.esSoloCliente()) {
            // Una cuenta de comprador no entra al back office.
            this.authService.limpiarSesion();
            this.errorLogin.set(MENSAJE_CUENTA_DE_CLIENTE);
            return;
          }
          if (empresaIngresada) guardarUltimaEmpresa(empresaIngresada);
          navegarDespuesDeLogin(this.router, this.authService, this.returnTo, this.tienda);
        },
        error: (error: unknown) => {
          this.cargando.set(false);
          this.errorLogin.set(this.mensajeDeError(error));
        },
      });
  }

  private mensajeDeError(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      if (codigoFuncional(error) === 'suscripcion_no_activa') return MENSAJE_SUSCRIPCION_INACTIVA;
      if (error.status === 429) return MENSAJE_DEMASIADOS_INTENTOS;
    }
    // Un solo mensaje: no revela si falló la empresa, el correo o la clave.
    return this.esPersonal ? MENSAJE_LOGIN_PERSONAL : MENSAJE_LOGIN_CLIENTE;
  }
}
