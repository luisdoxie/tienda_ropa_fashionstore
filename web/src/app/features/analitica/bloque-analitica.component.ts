import { Component, input, output } from '@angular/core';
import { IconoComponent } from '../../shared/icono/icono.component';
import { NombreIcono } from '../../shared/icono/iconos';

/** En qué momento está un bloque: cada uno tiene la suya, así un fallo no tapa a los demás. */
export type FaseBloque =
  | 'inactivo' // todavía no se pidió (plan, rol o conexión lo impiden)
  | 'cargando'
  | 'listo'
  | 'sin_modelo' // 409 modelo_no_entrenado
  | 'obsoleto' // 409 modelo_obsoleto
  | 'en_curso' // 409 entrenamiento_en_curso
  | 'limite' // 429
  | 'error';

/**
 * Marco común de cada bloque de la analítica: título, controles propios y el cuerpo según la fase. Cuando el bloque está
 * `listo` muestra su contenido; en cualquier otro caso explica qué pasó y qué hacer (entrenar, reintentar).
 */
@Component({
  selector: 'app-bloque-analitica',
  standalone: true,
  imports: [IconoComponent],
  template: `
    <section class="bloque" [class.bloque--deshabilitado]="deshabilitado()" [attr.aria-busy]="fase() === 'cargando'">
      <header class="bloque__cab">
        <h2 class="bloque__titulo">
          <fs-icono [nombre]="icono()" [tam]="24" />
          {{ titulo() }}
        </h2>
        <div class="bloque__controles">
          <ng-content select="[controles]" />
        </div>
      </header>
      @if (subtitulo(); as sub) {
        <p class="bloque__sub">{{ sub }}</p>
      }

      @switch (fase()) {
        @case ('listo') {
          <ng-content />
        }
        @case ('cargando') {
          <div class="estado" role="status" data-estado="cargando">
            <fs-icono nombre="reloj-arena" [tam]="36" />
            <p>Cargando…</p>
          </div>
        }
        @case ('sin_modelo') {
          <div class="estado" data-estado="sin-modelo">
            <fs-icono nombre="destellos" [tam]="36" />
            <p class="estado__titulo">Todavía no hay predicciones. Entrena los modelos para verlas.</p>
            <button
              type="button"
              class="fs-btn fs-btn--primario fs-btn--sm"
              data-accion="entrenar-vacio"
              [disabled]="entrenando() || deshabilitado()"
              (click)="entrenar.emit()"
            >
              Entrenar modelos
            </button>
          </div>
        }
        @case ('obsoleto') {
          <div class="estado" role="alert" data-estado="obsoleto">
            <fs-icono nombre="advertencia" [tam]="36" />
            <p class="estado__titulo">Este modelo quedó obsoleto.</p>
            <p>{{ mensaje() ?? 'Se entrenó con otra versión del sistema. Vuelve a entrenarlo para usarlo.' }}</p>
            <button
              type="button"
              class="fs-btn fs-btn--primario fs-btn--sm"
              data-accion="reentrenar-vacio"
              [disabled]="entrenando() || deshabilitado()"
              (click)="entrenar.emit()"
            >
              Reentrenar
            </button>
          </div>
        }
        @case ('en_curso') {
          <div class="estado" role="status" data-estado="en-curso">
            <fs-icono nombre="reloj-arena" [tam]="36" />
            <p>{{ mensaje() }}</p>
            <button type="button" class="fs-btn fs-btn--secundario fs-btn--sm" data-accion="reintentar" [disabled]="deshabilitado()" (click)="reintentar.emit()">
              Reintentar
            </button>
          </div>
        }
        @case ('limite') {
          <div class="estado" role="status" data-estado="limite">
            <fs-icono nombre="reloj" [tam]="36" />
            <p>{{ mensaje() }}</p>
            <button type="button" class="fs-btn fs-btn--secundario fs-btn--sm" data-accion="reintentar" [disabled]="deshabilitado()" (click)="reintentar.emit()">
              Reintentar
            </button>
          </div>
        }
        @case ('error') {
          <div class="estado" role="alert" data-estado="error">
            <fs-icono nombre="alerta" [tam]="36" />
            <p>{{ mensaje() ?? 'No pudimos cargar este bloque.' }}</p>
            <button type="button" class="fs-btn fs-btn--secundario fs-btn--sm" data-accion="reintentar" [disabled]="deshabilitado()" (click)="reintentar.emit()">
              Reintentar
            </button>
          </div>
        }
        @default {
          <div class="estado" data-estado="inactivo">
            <fs-icono nombre="candado" [tam]="36" />
            <p>Este bloque no está disponible ahora.</p>
          </div>
        }
      }
    </section>
  `,
  styleUrl: './bloque-analitica.component.scss',
})
export class BloqueAnaliticaComponent {
  readonly titulo = input.required<string>();
  readonly icono = input<NombreIcono>('grafico');
  readonly subtitulo = input<string | null>(null);
  readonly fase = input<FaseBloque>('cargando');
  readonly mensaje = input<string | null>(null);
  /** Hay un entrenamiento en curso: los botones de entrenar esperan. */
  readonly entrenando = input(false);
  /** Plan, rol o conexión no lo permiten: se ve apagado y sin controles. */
  readonly deshabilitado = input(false);

  readonly entrenar = output<void>();
  readonly reintentar = output<void>();
}
