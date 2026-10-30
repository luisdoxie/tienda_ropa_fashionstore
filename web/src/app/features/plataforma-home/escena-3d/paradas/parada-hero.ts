import * as THREE from 'three';
import type { ContextoParada, EstadoCuadro, Parada } from '../contrato';

/** Cuántos radianes gira la polera por cada píxel que arrastra el dedo o el mouse. */
const RADIANES_POR_PIXEL = 0.012;
/** Velocidad de inercia (radianes por cuadro a 60 fps) por cada píxel del último movimiento. */
const INERCIA_POR_PIXEL = 0.0015;
/** Lo que conserva la inercia en cada cuadro a 60 fps. */
const ROZAMIENTO = 0.95;

/** La parada del inicio, más lo que el motor necesita para el arrastre y el paralaje. */
export interface ParadaHero extends Parada {
  /** El usuario arrastra la polera `dx` píxeles (suma al giro y detiene la inercia anterior). */
  rotar(dx: number): void;
  /** El usuario soltó la polera: sigue girando por inercia y se va frenando. */
  soltar(): void;
  /** Inclinación según la altura del mouse (`par.y`, de -0,5 a 0,5). */
  inclinar(parY: number): void;
}

/** 0 · Inicio: la polera de la marca con halo, sombra y tres anillos giratorios sobre el suelo. */
export function crearParadaHero(ctx: ContextoParada): ParadaHero {
  const { ayudas } = ctx;
  const grupo = new THREE.Group();
  grupo.position.z = ctx.z;
  ctx.scene.add(grupo);

  ayudas.brillo(0, 0, -1.6, 9, 0.26, grupo);
  const polera = ctx.crearPolera();
  polera.scale.setScalar(0.82);
  grupo.add(polera);
  const sombra = ayudas.sombra(4.8, 4.8, 0, 0, 0.9, grupo);
  const anillos = [1.9, 2.5, 3.1].map((r, i) => {
    const anillo = new THREE.Mesh(
      new THREE.RingGeometry(r, r + 0.012, 96),
      ayudas.basico({ transparent: true, opacity: 0.5 - i * 0.14, side: THREE.DoubleSide }),
    );
    anillo.rotation.x = -Math.PI / 2;
    anillo.position.y = -2.56;
    grupo.add(anillo);
    return anillo;
  });

  let giro = 0;
  let velocidad = 0;
  let arrastrando = false;
  let inclinacion = 0;

  return {
    grupo,
    x: 2.4,
    escalaAncha: 1,
    escalaAngosta: 0.7,
    yAngosta: 1.5,

    actualizar({ t, dt, reducirMovimiento }: EstadoCuadro): void {
      if (!arrastrando) {
        const cuadros = dt * 60;
        giro += velocidad * cuadros;
        velocidad *= Math.pow(ROZAMIENTO, cuadros);
      }
      polera.rotation.y = giro + (reducirMovimiento ? 0 : Math.sin(t * 0.6) * 0.5);
      polera.rotation.x = inclinacion * 0.12;
      const flota = reducirMovimiento ? 0 : Math.sin(t * 1.1) * 0.08;
      polera.position.y = 0.5 + flota;
      sombra.scale.setScalar(1 - flota * 0.6);
      if (!reducirMovimiento) anillos.forEach((a, i) => (a.rotation.z = t * (0.1 + i * 0.05)));
    },

    rotar(dx: number): void {
      arrastrando = true;
      giro += dx * RADIANES_POR_PIXEL;
      velocidad = dx * INERCIA_POR_PIXEL;
    },

    soltar(): void {
      arrastrando = false;
    },

    inclinar(parY: number): void {
      inclinacion = parY;
    },
  };
}
