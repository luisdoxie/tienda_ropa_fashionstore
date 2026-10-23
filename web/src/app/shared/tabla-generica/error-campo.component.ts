import { ChangeDetectionStrategy, Component, Directive, inject, input } from '@angular/core';
import { AbstractControl, NgControl } from '@angular/forms';
import { IconoComponent } from '../icono/icono.component';

/**
 * Mensaje de error de un campo de formulario (`.fs-error-texto` con ícono de 20 px).
 * Aparece cuando el control es inválido y ya fue tocado, y se anuncia a los
 * lectores de pantalla (`role="alert"`). Su `id` lo referencia el control con
 * `appAriaError`:
 *
 *   <input formControlName="nombre" appAriaError="err-nombre" />
 *   <app-error-campo id="err-nombre" [control]="formulario.controls.nombre">Ingresa el nombre.</app-error-campo>
 */
@Component({
  selector: 'app-error-campo',
  standalone: true,
  imports: [IconoComponent],
  changeDetection: ChangeDetectionStrategy.Default,
  host: { role: 'alert' },
  template: `
    @if (visible()) {
      <small class="fs-error-texto"><fs-icono nombre="alerta" [tam]="20" /><span><ng-content /></span></small>
    }
  `,
  styles: `
    :host {
      display: block;
    }
  `,
})
export class ErrorCampoComponent {
  readonly control = input.required<AbstractControl | null>();

  protected visible(): boolean {
    const control = this.control();
    return !!control && control.invalid && control.touched;
  }
}

/** Marca el control como inválido (`aria-invalid`) y lo enlaza con su mensaje (`aria-describedby`). */
@Directive({
  selector: '[appAriaError]',
  standalone: true,
  host: {
    '[attr.aria-invalid]': 'invalido() ? "true" : null',
    '[attr.aria-describedby]': 'invalido() ? appAriaError() : null',
  },
})
export class AriaErrorDirective {
  private readonly ngControl = inject(NgControl, { optional: true, self: true });

  /** `id` del `app-error-campo` que explica el error. */
  readonly appAriaError = input.required<string>();

  protected invalido(): boolean {
    const control = this.ngControl?.control;
    return !!control && control.invalid && control.touched;
  }
}
