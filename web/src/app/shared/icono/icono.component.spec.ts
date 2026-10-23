import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { IconoComponent } from './icono.component';
import { ICONOS } from './iconos';

@Component({
  standalone: true,
  imports: [IconoComponent],
  template: `<fs-icono nombre="carrito" [tam]="28" /><fs-icono nombre="check" />`,
})
class AnfitrionComponent {}

describe('IconoComponent', () => {
  it('dibuja el trazo del nombre pedido con el tamaño dado y es decorativo', () => {
    const fixture = TestBed.createComponent(AnfitrionComponent);
    fixture.detectChanges();
    const svgs = (fixture.nativeElement as HTMLElement).querySelectorAll('svg');
    expect(svgs).toHaveLength(2);
    expect(svgs[0].getAttribute('width')).toBe('28');
    expect(svgs[0].querySelector('path')?.getAttribute('d')).toBe(ICONOS.carrito);
    expect(svgs[0].getAttribute('aria-hidden')).toBe('true');
    // Tamaño por defecto: el de los botones (24).
    expect(svgs[1].getAttribute('width')).toBe('24');
  });

  it('todos los íconos del catálogo tienen un trazo', () => {
    for (const [nombre, trazo] of Object.entries(ICONOS)) {
      expect(trazo.length, nombre).toBeGreaterThan(5);
    }
  });
});
