import { afterEach, describe, expect, it } from 'vitest';
import { PALETA_RESPALDO, leerPaleta } from './paleta';

describe('leerPaleta', () => {
  let elemento: HTMLElement;

  afterEach(() => elemento?.remove());

  function crear(estilo: string): HTMLElement {
    elemento = document.createElement('div');
    elemento.setAttribute('style', estilo);
    document.body.appendChild(elemento);
    return elemento;
  }

  it('usa los valores de respaldo (los de styles.scss) cuando no hay tokens', () => {
    const paleta = leerPaleta(crear(''));
    expect(paleta).toEqual(PALETA_RESPALDO);
    expect(paleta.carbon).toBe('#1b1916');
    expect(paleta.acento).toBe('#8fae5b');
  });

  it('lee cada token --fs-* con getComputedStyle', () => {
    const paleta = leerPaleta(
      crear(
        [
          '--fs-carbon: #010101',
          '--fs-carbon-2: #020202',
          '--fs-carbon-panel: #030303',
          '--fs-carbon-borde: #040404',
          '--fs-claro: #050505',
          '--fs-claro-tenue: #060606',
          '--fs-acento-oscuro: #070707',
          '--fs-sobre-acento-oscuro: #080808',
        ].join(';'),
      ),
    );
    expect(paleta).toEqual({
      carbon: '#010101',
      profundo: '#020202',
      panel: '#030303',
      borde: '#040404',
      texto: '#050505',
      tenue: '#060606',
      acento: '#070707',
      sobreAcento: '#080808',
    });
  });

  it('expande #rgb, pasa a minúsculas y descarta valores que no son colores hexadecimales', () => {
    const paleta = leerPaleta(crear('--fs-carbon: #ABC; --fs-claro: rgb(1, 2, 3); --fs-acento-oscuro: #8FAE5B'));
    expect(paleta.carbon).toBe('#aabbcc');
    expect(paleta.texto).toBe(PALETA_RESPALDO.texto);
    expect(paleta.acento).toBe('#8fae5b');
  });
});
