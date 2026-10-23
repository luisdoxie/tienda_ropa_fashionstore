import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

/** "Boutique Andina" -> "BA"; "FashionStore" -> "FS"; "Moda" -> "MO". */
export function siglasDe(nombre: string | null | undefined): string {
  const limpio = (nombre ?? '').trim();
  if (limpio === '') return 'FS';
  // Separa por espacios, guiones y por cambios de minúscula a mayúscula (CamelCase).
  const palabras = limpio
    .replace(/([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])/g, '$1 $2')
    .split(/[^A-Za-zÁÉÍÓÚÑáéíóúñ0-9]+/)
    .filter(Boolean);
  if (palabras.length >= 2) return (palabras[0][0] + palabras[1][0]).toUpperCase();
  return palabras[0].slice(0, 2).toUpperCase();
}

/**
 * Marca de una empresa (o de la plataforma): su logo si lo subió y carga; si
 * no, un monograma con sus siglas y el nombre. `oscuro` es para fondos oscuros
 * (monograma en el acento lima o el de la empresa); `claro` para fondos claros
 * (monograma en tinta).
 */
@Component({
  selector: 'fs-marca',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (urlLogo(); as url) {
      <img class="marca__logo" [src]="url" [alt]="nombre()" (error)="logoFallo.set(true)" />
    } @else {
      <span class="marca__monograma" aria-hidden="true">{{ siglas() }}</span>
      @if (!soloMonograma()) {
        <span class="marca__nombre">{{ nombre() }}</span>
      }
    }
  `,
  styleUrl: './marca.component.scss',
  host: {
    '[class.marca--oscuro]': 'variante() === "oscuro"',
    '[class.marca--claro]': 'variante() === "claro"',
    '[class.marca--pequena]': 'tam() === "sm"',
    '[class.marca--envolver]': 'envolver()',
    '[attr.aria-label]': 'nombre()',
    role: 'img',
  },
})
export class MarcaComponent {
  readonly nombre = input.required<string>();
  readonly logoUrl = input<string | null | undefined>(null);
  readonly variante = input<'oscuro' | 'claro'>('claro');
  readonly tam = input<'md' | 'sm'>('md');
  readonly soloMonograma = input(false);
  /** Un nombre largo pasa a la línea siguiente en vez de recortarse (barra lateral). */
  readonly envolver = input(false);

  /** Se pone en true si la imagen del logo no cargó: queda el monograma. */
  protected readonly logoFallo = signal(false);
  protected readonly siglas = computed(() => siglasDe(this.nombre()));
  protected readonly urlLogo = computed(() => {
    const url = this.logoUrl();
    return url && !this.logoFallo() ? url : null;
  });
}
