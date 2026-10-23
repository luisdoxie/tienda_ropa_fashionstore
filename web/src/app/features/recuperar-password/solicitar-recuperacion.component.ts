import { Component, computed, inject, signal } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthService, RUTA_LOGIN_PERSONAL } from '../../core/auth.service';
import { IconoComponent } from '../../shared/icono/icono.component';
import { AccesoPantallaComponent } from '../login/acceso-pantalla.component';
import { mensajeDeCampo, sinSoloEspacios } from '../login/mensajes-campo';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';

@Component({
  selector: 'app-solicitar-recuperacion',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, AccesoPantallaComponent, IconoComponent],
  templateUrl: './solicitar-recuperacion.component.html',
})
export class SolicitarRecuperacionComponent {
  protected readonly cargando = signal(false);
  protected readonly enviado = signal(false);
  protected readonly enlaceDev = signal<string | null>(null);

  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  protected readonly tienda = inject(TiendaActualService);

  protected readonly rutaLogin = computed(() => (this.tienda.codigo() ? this.tienda.ruta('login') : [RUTA_LOGIN_PERSONAL]));

  /** Fuera de una tienda (personal de una empresa) hay que decir de qué empresa es la cuenta. */
  protected readonly pideEmpresa = computed(() => !this.tienda.codigo());

  /** Sin tienda es la recuperación del personal: se muestra la pantalla oscura del acceso del personal. */
  protected readonly esPersonal = computed(() => !this.tienda.codigo());

  protected readonly formulario = this.fb.nonNullable.group({
    // Solo se exige fuera de una tienda; "   " cuenta como vacío.
    empresa: ['', [(control: AbstractControl) => (this.pideEmpresa() ? sinSoloEspacios(control) : null)]],
    email: ['', [Validators.required, Validators.email]],
  });

  protected readonly mostrarEnlaceDev = computed(() => this.enlaceDev() !== null);

  /** Mensaje de un campo inválido y ya tocado; null si está bien. */
  protected errorDe(campo: 'empresa' | 'email'): string | null {
    const mensajes: Record<string, Record<string, string>> = {
      empresa: { required: 'Escribe el nombre o el código de tu empresa.' },
      email: { required: 'Escribe tu correo electrónico.', email: 'Escribe un correo válido.' },
    };
    return mensajeDeCampo(this.formulario.controls[campo], mensajes[campo]);
  }

  enviar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const { email, empresa } = this.formulario.getRawValue();
    const codigoTienda = this.tienda.codigo();

    this.cargando.set(true);

    this.authService.solicitarRecuperacion(email, codigoTienda ?? empresa.trim()).subscribe({
      next: (respuesta) => {
        this.cargando.set(false);
        this.enviado.set(true);
        const rutaRestablecer = codigoTienda ? `/t/${encodeURIComponent(codigoTienda)}/restablecer` : '/restablecer';
        this.enlaceDev.set(
          respuesta.token_dev
            ? `${window.location.origin}${rutaRestablecer}?token=${encodeURIComponent(respuesta.token_dev)}`
            : null,
        );
      },
      error: () => {
        // El backend responde genérico incluso para emails no registrados;
        // un error acá solo puede ser de red, así que se muestra igual el
        // mensaje de éxito para no revelar nada sobre el email.
        this.cargando.set(false);
        this.enviado.set(true);
      },
    });
  }
}
