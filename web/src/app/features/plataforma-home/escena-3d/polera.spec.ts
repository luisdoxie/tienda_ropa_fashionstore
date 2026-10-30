import * as THREE from 'three';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Ayudas } from './ayudas';
import { PALETA_RESPALDO } from './paleta';
import { CONTORNO, Polera, dentro, geometriaPolera, luminosidad, masCercano } from './polera';

type MallaMaterial<M extends THREE.Material> = THREE.Mesh<THREE.BufferGeometry, M>;

describe('silueta de la polera', () => {
  it('distingue el interior del exterior', () => {
    expect(dentro(0, -1)).toBe(true); // cuerpo
    expect(dentro(1.7, 0.6)).toBe(true); // manga
    expect(dentro(0, 1.8)).toBe(false); // hueco del cuello
    expect(dentro(-2.1, -1.9)).toBe(false);
    expect(dentro(0, 2.5)).toBe(false);
  });

  it('masCercano devuelve un punto del contorno y la distancia hasta él', () => {
    const c = masCercano(1.5, -1);
    expect(c.x).toBeCloseTo(1.1, 5);
    expect(c.y).toBeCloseTo(-1, 5);
    expect(c.d).toBeCloseTo(0.4, 5);
    expect(masCercano(CONTORNO[0][0], CONTORNO[0][1]).d).toBeCloseTo(0, 6);
  });

  it('la geometría tiene frente y espalda simétricos y mide unos 4 x 3,7', () => {
    const geo = geometriaPolera();
    const pos = geo.getAttribute('position');
    expect(pos.count).toBe(2 * 57 * 53);
    expect(geo.getIndex()!.count % 6).toBe(0);
    geo.computeBoundingBox();
    const caja = geo.boundingBox!;
    expect(caja.max.x - caja.min.x).toBeCloseTo(4, 1);
    expect(caja.max.y - caja.min.y).toBeCloseTo(3.7, 1);
    expect(caja.max.z).toBeGreaterThan(0.2);
    expect(caja.min.z).toBeLessThan(-0.2);
    geo.dispose();
  });

  it('luminosidad separa telas claras de oscuras', () => {
    expect(luminosidad(new THREE.Color('#D8D3C6'))).toBeGreaterThan(0.5);
    expect(luminosidad(new THREE.Color('#7A2638'))).toBeLessThan(0.5);
  });
});

describe('Polera', () => {
  let ayudas: Ayudas;
  let polera: Polera;
  let previo: boolean;

  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    previo = THREE.ColorManagement.enabled;
    THREE.ColorManagement.enabled = false;
    ayudas = new Ayudas();
    polera = new Polera(ayudas, PALETA_RESPALDO);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    polera.dispose();
    ayudas.dispose();
    THREE.ColorManagement.enabled = previo;
  });

  it('crear() entrega grupos nuevos que comparten geometría, materiales y texturas', () => {
    const a = polera.crear();
    const b = polera.crear();
    expect(a).not.toBe(b);
    expect(a.children.length).toBe(7);
    a.children.forEach((hijo, i) => {
      const ma = hijo as THREE.Mesh;
      const mb = b.children[i] as THREE.Mesh;
      expect(ma).not.toBe(mb);
      expect(ma.geometry).toBe(mb.geometry);
      expect(ma.material).toBe(mb.material);
    });
    const frente = a.children[5] as MallaMaterial<THREE.MeshLambertMaterial>;
    expect(frente.material.map).toBeInstanceOf(THREE.CanvasTexture);
  });

  it('fijarMarca no falla sin contexto 2d (jsdom) y avanzar acerca la tela al color nuevo', () => {
    const grupo = polera.crear();
    const tela = (grupo.children[0] as MallaMaterial<THREE.MeshStandardMaterial>).material;
    const cuello = (grupo.children[1] as MallaMaterial<THREE.MeshStandardMaterial>).material;
    expect(() => polera.fijarMarca('Boutique Andina', '#9A3E1F')).not.toThrow();
    expect(tela.color.getHexString()).toBe('8fae5b');
    polera.avanzar(0.5);
    const medio = tela.color.getHexString();
    expect(medio).not.toBe('8fae5b');
    expect(medio).not.toBe('9a3e1f');
    polera.avanzar(1);
    expect(tela.color.getHexString()).toBe('9a3e1f');
    // El cuello es la misma tela, un 20 % más oscura.
    expect(cuello.color.r).toBeCloseTo(tela.color.r * 0.8, 5);
    expect(() => polera.redibujarEstampas()).not.toThrow();
  });

  it('estampa el nombre con las siglas y elige el color del texto según la tela (contexto 2d simulado)', () => {
    const llamadas: { texto: string; color: string }[] = [];
    const g = {
      clearRect: vi.fn(),
      strokeRect: vi.fn(),
      measureText: () => ({ width: 10 }),
      fillText(texto: string) {
        llamadas.push({ texto, color: String(this.fillStyle) });
      },
      fillStyle: '',
      strokeStyle: '',
      lineWidth: 0,
      textAlign: '',
      textBaseline: '',
      font: '',
    };
    const espia = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(g as never);
    try {
      polera.fijarMarca('Mi Boutique', '#D8D3C6');
      polera.redibujarEstampas();
      expect(llamadas.map((l) => l.texto)).toContain('MB');
      expect(llamadas.map((l) => l.texto)).toContain('MI BOUTIQUE');
      expect(llamadas.at(-1)!.color).toBe(PALETA_RESPALDO.carbon); // tela clara -> texto oscuro
      llamadas.length = 0;
      polera.fijarMarca('Mi Boutique', '#7A2638');
      polera.redibujarEstampas();
      expect(llamadas.at(-1)!.color).toBe(PALETA_RESPALDO.texto); // tela oscura -> texto claro
    } finally {
      espia.mockRestore();
    }
  });

  it('un nombre vacío vuelve al nombre por omisión y uno largo se recorta a 24 caracteres', () => {
    const textos: string[] = [];
    const g = {
      clearRect: () => undefined,
      strokeRect: () => undefined,
      measureText: () => ({ width: 10 }),
      fillText: (t: string) => textos.push(t),
    };
    const espia = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(g as never);
    try {
      polera.fijarMarca('   ', '#8FAE5B');
      expect(textos).toContain('TU TIENDA');
      textos.length = 0;
      polera.fijarMarca('x'.repeat(40), '#8FAE5B');
      expect(textos).toContain('X'.repeat(24));
    } finally {
      espia.mockRestore();
    }
  });

  it('dispose libera geometrías, materiales y texturas y no vuelve a dibujar', () => {
    const grupo = polera.crear();
    const mallas = grupo.children as THREE.Mesh<THREE.BufferGeometry, THREE.Material>[];
    const alLiberar = vi.fn();
    mallas[0].geometry.addEventListener('dispose', alLiberar);
    mallas[0].material.addEventListener('dispose', alLiberar);
    const mapa = (mallas[5].material as THREE.MeshLambertMaterial).map!;
    mapa.addEventListener('dispose', alLiberar);
    polera.dispose();
    expect(alLiberar).toHaveBeenCalledTimes(3);
    expect(() => polera.fijarMarca('Otra', '#000000')).not.toThrow();
  });
});
