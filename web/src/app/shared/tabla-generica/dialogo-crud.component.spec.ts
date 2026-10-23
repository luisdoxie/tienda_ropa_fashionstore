import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { DialogoCrudComponent } from './dialogo-crud.component';
import { AriaErrorDirective, ErrorCampoComponent } from './error-campo.component';

@Component({
  standalone: true,
  imports: [DialogoCrudComponent, ReactiveFormsModule, ErrorCampoComponent, AriaErrorDirective],
  template: `
    <app-dialogo-crud
      [titulo]="'Nueva cosa'"
      formId="form-cosa"
      [guardando]="guardando()"
      [(visible)]="visible"
      (cancelado)="cancelados = cancelados + 1"
    >
      <form id="form-cosa" [formGroup]="formulario" (ngSubmit)="enviar()" class="formulario">
        <input id="nombre" formControlName="nombre" appAriaError="err-nombre" />
        <app-error-campo id="err-nombre" [control]="formulario.controls.nombre">Ingresa el nombre.</app-error-campo>
      </form>
    </app-dialogo-crud>
  `,
})
class AnfitrionComponent {
  visible = signal(true);
  guardando = signal(false);
  cancelados = 0;
  envios = 0;
  formulario = new FormGroup({ nombre: new FormControl('', { nonNullable: true, validators: Validators.required }) });
  enviar(): void {
    this.formulario.markAllAsTouched();
    if (this.formulario.valid) this.envios++;
  }
}

describe('DialogoCrudComponent', () => {
  function crear() {
    TestBed.configureTestingModule({ imports: [AnfitrionComponent] });
    const fixture = TestBed.createComponent(AnfitrionComponent);
    fixture.detectChanges();
    return { fixture, anfitrion: fixture.componentInstance };
  }
  const q = <T extends Element>(selector: string) => document.body.querySelector<T>(selector);

  it('muestra el título, el formulario y el pie Cancelar / Guardar asociado por formId', () => {
    const { fixture } = crear();

    expect(q('.p-dialog-title')?.textContent).toContain('Nueva cosa');
    expect(q('form#form-cosa')).not.toBeNull();
    const guardar = q<HTMLButtonElement>('[data-testid="dialogo-guardar"]')!;
    expect(guardar.getAttribute('form')).toBe('form-cosa');
    expect(guardar.type).toBe('submit');
    expect(guardar.querySelector('svg')?.getAttribute('width')).toBe('24');
    expect(q('[data-testid="dialogo-cancelar"]')?.textContent).toContain('Cancelar');
    fixture.destroy();
  });

  it('Cancelar cierra el diálogo y avisa', () => {
    const { fixture, anfitrion } = crear();

    q<HTMLButtonElement>('[data-testid="dialogo-cancelar"]')!.click();
    fixture.detectChanges();

    expect(anfitrion.visible()).toBe(false);
    expect(anfitrion.cancelados).toBe(1);
    fixture.destroy();
  });

  it('la X de cierre del encabezado también lo cierra', () => {
    const { fixture, anfitrion } = crear();

    const cerrar = q<HTMLButtonElement>('.p-dialog-close-button');
    expect(cerrar).not.toBeNull();
    cerrar!.click();
    fixture.detectChanges();

    expect(anfitrion.visible()).toBe(false);
    fixture.destroy();
  });

  it('Guardar envía el formulario: sin datos muestra el error del campo (con aria) y no envía', () => {
    const { fixture, anfitrion } = crear();

    q<HTMLButtonElement>('[data-testid="dialogo-guardar"]')!.click();
    fixture.detectChanges();

    expect(anfitrion.envios).toBe(0);
    const entrada = q<HTMLInputElement>('#nombre')!;
    expect(entrada.getAttribute('aria-invalid')).toBe('true');
    expect(entrada.getAttribute('aria-describedby')).toBe('err-nombre');
    const error = q('#err-nombre')!;
    expect(error.getAttribute('role')).toBe('alert');
    expect(error.textContent).toContain('Ingresa el nombre.');
    fixture.destroy();
  });

  it('con datos válidos, el envío del formulario (Enter) llama a ngSubmit', () => {
    const { fixture, anfitrion } = crear();
    anfitrion.formulario.patchValue({ nombre: 'Algo' });

    q<HTMLFormElement>('form#form-cosa')!.dispatchEvent(new Event('submit'));
    fixture.detectChanges();

    expect(anfitrion.envios).toBe(1);
    expect(q('#nombre')!.getAttribute('aria-invalid')).toBeNull();
    fixture.destroy();
  });

  it('mientras guarda, Guardar queda deshabilitado (sin doble envío)', () => {
    const { fixture, anfitrion } = crear();
    const guardar = q<HTMLButtonElement>('[data-testid="dialogo-guardar"]')!;
    expect(guardar.disabled).toBe(false);

    anfitrion.guardando.set(true);
    fixture.detectChanges();
    expect(guardar.disabled).toBe(true);
    expect(guardar.getAttribute('aria-busy')).toBe('true');

    anfitrion.guardando.set(false);
    fixture.detectChanges();
    expect(guardar.disabled).toBe(false);
    fixture.destroy();
  });
});
