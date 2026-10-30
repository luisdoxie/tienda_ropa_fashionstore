import * as THREE from 'three';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Ayudas } from '../ayudas';
import type { ContextoParada, EstadoCuadro } from '../contrato';
import { PALETA_RESPALDO } from '../paleta';
import { Polera } from '../polera';
import { crearParadaHero } from './parada-hero';

function montar() {
  const ayudas = new Ayudas();
  const polera = new Polera(ayudas, PALETA_RESPALDO);
  const scene = new THREE.Scene();
  const ctx: ContextoParada = {
    ayudas,
    scene,
    paleta: PALETA_RESPALDO,
    crearPolera: () => polera.crear(),
    z: 0,
    datos: { planes: [], tiendas: [] },
    alElegirTienda: () => undefined,
  };
  const parada = crearParadaHero(ctx);
  const modelo = parada.grupo.children.find((o) => o.children.length >= 7)!;
  const cuadro = (extra: Partial<EstadoCuadro> = {}): void =>
    parada.actualizar({ t: 1, dt: 1 / 60, progreso: 0, reducirMovimiento: false, ...extra });
  return { ayudas, polera, scene, parada, modelo, cuadro };
}

describe('parada del inicio', () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });

  it('cumple el contrato de Parada y se agrega a la escena', () => {
    const { parada, scene } = montar();
    expect(parada.x).toBe(2.4);
    expect(parada.escalaAncha).toBe(1);
    expect(parada.escalaAngosta).toBe(0.7);
    expect(parada.yAngosta).toBe(1.5);
    expect(scene.children).toContain(parada.grupo);
  });

  it('arma la polera a escala 0,82 elevada 0,5, el halo, la sombra y tres anillos', () => {
    const { parada, modelo, cuadro } = montar();
    expect(modelo.scale.x).toBeCloseTo(0.82, 10);
    cuadro({ reducirMovimiento: true });
    expect(modelo.position.y).toBe(0.5);
    const anillos = parada.grupo.children.filter((o) => (o as THREE.Mesh).geometry instanceof THREE.RingGeometry);
    expect(anillos.length).toBe(3);
    expect(parada.grupo.children.some((o) => (o as THREE.Sprite).isSprite)).toBe(true);
  });

  it('flota y se balancea con movimiento normal, y se queda quieta con "reducir movimiento"', () => {
    const { modelo, parada, cuadro } = montar();
    cuadro({ t: 1.5 });
    expect(modelo.position.y).not.toBe(0.5);
    expect(modelo.rotation.y).not.toBe(0);
    const anillo = parada.grupo.children.find((o) => (o as THREE.Mesh).geometry instanceof THREE.RingGeometry)!;
    expect(anillo.rotation.z).not.toBe(0);

    cuadro({ t: 2.5, reducirMovimiento: true });
    expect(modelo.position.y).toBe(0.5);
    expect(modelo.rotation.y).toBe(0);
  });

  it('rotar suma al giro, soltar deja inercia que se va frenando', () => {
    const { parada, modelo, cuadro } = montar();
    parada.rotar(50);
    cuadro({ reducirMovimiento: true });
    expect(modelo.rotation.y).toBeCloseTo(50 * 0.012, 8);
    // Mientras se arrastra no hay inercia.
    cuadro({ reducirMovimiento: true });
    expect(modelo.rotation.y).toBeCloseTo(50 * 0.012, 8);

    parada.soltar();
    cuadro({ reducirMovimiento: true });
    const g1 = modelo.rotation.y;
    expect(g1).toBeGreaterThan(50 * 0.012);
    for (let i = 0; i < 300; i++) cuadro({ reducirMovimiento: true });
    const final = modelo.rotation.y;
    cuadro({ reducirMovimiento: true });
    expect(modelo.rotation.y - final).toBeLessThan(1e-6); // ya casi no gira
    expect(final).toBeGreaterThan(g1);
  });

  it('inclinar mueve la polera con la altura del mouse', () => {
    const { parada, modelo, cuadro } = montar();
    parada.inclinar(0.5);
    cuadro();
    expect(modelo.rotation.x).toBeCloseTo(0.06, 10);
  });
});
