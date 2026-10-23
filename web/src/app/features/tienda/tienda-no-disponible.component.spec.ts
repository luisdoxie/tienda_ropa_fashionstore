import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TiendaNoDisponibleComponent } from './tienda-no-disponible.component';

describe('TiendaNoDisponibleComponent', () => {
  function crear(motivo: 'no_encontrada' | 'no_disponible'): HTMLElement {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    const fixture = TestBed.createComponent(TiendaNoDisponibleComponent);
    fixture.componentRef.setInput('motivo', motivo);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('tienda no disponible: título, texto y enlace a las otras tiendas', () => {
    const el = crear('no_disponible');

    expect(el.querySelector('h1')?.textContent).toContain('Tienda no disponible');
    expect(el.textContent).toContain('Esta tienda no está disponible por el momento.');
    expect(el.querySelector('[role="alert"]')).not.toBeNull();
    expect(el.querySelector('a.fs-btn')?.getAttribute('href')).toBe('/');
  });

  it('tienda no encontrada: título y texto en tuteo', () => {
    const el = crear('no_encontrada');

    expect(el.querySelector('h1')?.textContent).toContain('Tienda no encontrada');
    expect(el.textContent).toContain('No encontramos esta tienda. Revisa el enlace o busca otra.');
    expect(el.textContent).not.toContain('Revisá');
  });
});
