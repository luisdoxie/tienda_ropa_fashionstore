import { ChangeDetectionStrategy, Component, ViewEncapsulation, input, model, output } from '@angular/core';
import { DialogModule } from 'primeng/dialog';
import { IconoComponent } from '../icono/icono.component';

/**
 * Diálogo de crear/editar de las pantallas CRUD (patrón `Crud` del canvas):
 * encabezado con el título, campos y pie con Cancelar / Guardar.
 *
 * El formulario (`<form [formGroup] id="...">`) lo pone cada pantalla dentro
 * de este componente; Guardar es un botón de envío asociado a ese formulario
 * por su `id` (atributo `form`), así que el `ngSubmit` y la tecla Enter siguen
 * funcionando igual que con un botón dentro del formulario. Con `[guardando]`
 * el botón se deshabilita mientras la petición está en vuelo.
 *
 *   <app-dialogo-crud [titulo]="editando() ? 'Editar talla' : 'Nueva talla'"
 *                     formId="form-talla" [(visible)]="dialogoVisible">
 *     <form id="form-talla" class="formulario" [formGroup]="formulario" (ngSubmit)="guardar()"> ... </form>
 *   </app-dialogo-crud>
 */
@Component({
  selector: 'app-dialogo-crud',
  standalone: true,
  imports: [DialogModule, IconoComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <p-dialog
      [header]="titulo()"
      [visible]="visible()"
      (visibleChange)="visible.set($event)"
      [modal]="true"
      [draggable]="false"
      [style]="{ width: ancho(), maxWidth: '96vw' }"
      styleClass="dialogo-crud"
    >
      <ng-content />
      <ng-template #footer>
        <button type="button" class="fs-btn fs-btn--secundario" data-testid="dialogo-cancelar" (click)="cancelar()">
          Cancelar
        </button>
        <button
          type="submit"
          class="fs-btn fs-btn--primario"
          data-testid="dialogo-guardar"
          [attr.form]="formId()"
          [disabled]="guardando()"
          [attr.aria-busy]="guardando() ? 'true' : null"
        >
          <fs-icono nombre="check" [tam]="24" />
          {{ etiquetaGuardar() }}
        </button>
      </ng-template>
    </p-dialog>
  `,
  styles: `
    .dialogo-crud .p-dialog-footer {
      gap: 10px;
    }

    .dialogo-crud .formulario {
      gap: 6px;
    }

    .dialogo-crud .formulario label {
      margin-top: 12px;
    }

    .dialogo-crud .formulario label:first-child {
      margin-top: 0;
    }

    .dialogo-crud .formulario p-select,
    .dialogo-crud .formulario p-inputnumber,
    .dialogo-crud .formulario p-datepicker,
    .dialogo-crud .formulario p-multiselect,
    .dialogo-crud .formulario p-password {
      width: 100%;
    }

    .dialogo-crud .formulario .fs-error-texto {
      margin-top: 2px;
    }

    /* Campo con error: borde rojo del sistema. */
    .dialogo-crud .formulario input.ng-invalid.ng-touched,
    .dialogo-crud .formulario .p-select.ng-invalid.ng-touched,
    .dialogo-crud .formulario .p-inputnumber.ng-invalid.ng-touched input,
    .dialogo-crud .formulario .p-multiselect.ng-invalid.ng-touched {
      border-color: var(--fs-error);
    }
  `,
})
export class DialogoCrudComponent {
  readonly titulo = input.required<string>();
  /** `id` del formulario que envía el botón Guardar. */
  readonly formId = input.required<string>();
  readonly ancho = input('480px');
  readonly etiquetaGuardar = input('Guardar');
  /** Petición en vuelo: Guardar queda deshabilitado para evitar un doble envío. */
  readonly guardando = input(false);
  readonly visible = model(false);

  /** El usuario pulsó Cancelar (el diálogo ya se cerró). */
  readonly cancelado = output<void>();

  protected cancelar(): void {
    this.visible.set(false);
    this.cancelado.emit();
  }
}
