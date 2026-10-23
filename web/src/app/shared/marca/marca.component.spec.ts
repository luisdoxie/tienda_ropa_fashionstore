import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { MarcaComponent, siglasDe } from './marca.component';

describe('siglasDe', () => {
  it.each([
    ['Boutique Andina', 'BA'],
    ['FashionStore', 'FS'],
    ['moda-norte', 'MN'],
    ['Moda', 'MO'],
    ['', 'FS'],
    [null, 'FS'],
  ])('%s -> %s', (nombre, esperado) => {
    expect(siglasDe(nombre)).toBe(esperado);
  });
});

describe('MarcaComponent', () => {
  function crear(logoUrl: string | null) {
    const fixture = TestBed.createComponent(MarcaComponent);
    fixture.componentRef.setInput('nombre', 'Boutique Andina');
    fixture.componentRef.setInput('logoUrl', logoUrl);
    fixture.detectChanges();
    return fixture;
  }

  it('sin logo muestra el monograma con las siglas y el nombre', () => {
    const el = crear(null).nativeElement as HTMLElement;
    expect(el.querySelector('.marca__monograma')?.textContent?.trim()).toBe('BA');
    expect(el.querySelector('.marca__nombre')?.textContent?.trim()).toBe('Boutique Andina');
    expect(el.querySelector('img')).toBeNull();
  });

  it('con logo muestra la imagen', () => {
    const el = crear('https://ejemplo.test/logo.png').nativeElement as HTMLElement;
    expect(el.querySelector('img')?.getAttribute('src')).toBe('https://ejemplo.test/logo.png');
    expect(el.querySelector('.marca__monograma')).toBeNull();
  });

  it('si el logo no carga, vuelve al monograma', () => {
    const fixture = crear('https://ejemplo.test/roto.png');
    const el = fixture.nativeElement as HTMLElement;
    el.querySelector('img')!.dispatchEvent(new Event('error'));
    fixture.detectChanges();
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('.marca__monograma')?.textContent?.trim()).toBe('BA');
  });
});
