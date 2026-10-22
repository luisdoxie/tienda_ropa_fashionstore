import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { AuthService } from '../../core/auth.service';
import { TiendaActualService } from '../tienda/state/tienda-actual.service';

@Component({
  selector: 'app-solicitar-recuperacion',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, ButtonModule, InputTextModule],
  templateUrl: './solicitar-recuperacion.component.html',
})
export class SolicitarRecuperacionComponent {
  protected readonly cargando = signal(false);
  protected readonly enviado = signal(false);
  protected readonly enlaceDev = signal<string | null>(null);

  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  protected readonly tienda = inject(TiendaActualService);

  protected readonly rutaLogin = computed(() => (this.tienda.codigo() ? this.tienda.ruta('login') : ['/login']));

  protected readonly formulario = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
  });

  protected readonly mostrarEnlaceDev = computed(() => this.enlaceDev() !== null);

  enviar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    this.cargando.set(true);
    const { email } = this.formulario.getRawValue();

    const codigoTienda = this.tienda.codigo();

    this.authService.solicitarRecuperacion(email, codigoTienda).subscribe({
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
