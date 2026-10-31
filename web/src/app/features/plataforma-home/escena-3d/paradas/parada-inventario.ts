import * as THREE from 'three';
import type { EstadoCuadro, FabricaParada } from '../contrato';

/** Tonos de la maqueta de la tienda (no son de la interfaz). */
const MUEBLE_OSCURO = 0x26221c;
const MUEBLE_MEDIO = 0x3b372f;
const MUEBLE_NEGRO = 0x121110;
/** Telas de las prendas dobladas: lima, hueso, terracota, azul petróleo, mostaza y vino. */
const COLORES_PRENDAS = ['#8FAE5B', '#D8D3C6', '#9A3E1F', '#1F5F73', '#C99A2E', '#7A2638'];
/** Altura de cada repisa. */
const REPISAS = [-1.6, -0.3, 1.0];
const PRENDAS_POR_REPISA = 8;

/** 2 · Inventario: estante de 3 repisas con prendas dobladas y un marcador flotante por sucursal. */
export const crearParadaInventario: FabricaParada = (ctx) => {
  const { ayudas } = ctx;
  const grupo = new THREE.Group();
  grupo.position.z = ctx.z;
  ctx.scene.add(grupo);

  const oscuro = ayudas.liso(MUEBLE_OSCURO);
  const medio = ayudas.liso(MUEBLE_MEDIO);
  const negro = ayudas.liso(MUEBLE_NEGRO);

  // Repisas, laterales y fondo
  REPISAS.forEach((y) => ayudas.cajaR(5, 0.12, 1.2, 0.05, medio, 0, y - 0.1, 0, grupo));
  ayudas.cajaR(0.14, 4.0, 1.2, 0.06, oscuro, -2.55, -0.3, 0, grupo);
  ayudas.cajaR(0.14, 4.0, 1.2, 0.06, oscuro, 2.55, -0.3, 0, grupo);
  ayudas.cajaR(5.3, 4.1, 0.1, 0.04, negro, 0, -0.3, -0.62, grupo);
  ayudas.sombra(5.6, 2.2, 0, 0, 0.8, grupo);

  // Prendas dobladas (azar repetible: la escena se ve igual en cada carga)
  const telas = COLORES_PRENDAS.map((hex) => ayudas.liso(hex));
  REPISAS.forEach((y) => {
    for (let i = 0; i < PRENDAS_POR_REPISA; i++) {
      const h = 0.18 + ayudas.azar() * 0.22;
      const tela = telas[Math.floor(ayudas.azar() * telas.length)];
      ayudas.cajaR(0.46, h, 0.8, 0.05, tela, -2.1 + i * 0.6, y - 0.04 + h / 2, 0.05, grupo);
    }
  });

  // Marcadores de sucursal: gota (cono invertido + esfera) que sigue al acento
  const geoCono = new THREE.ConeGeometry(0.13, 0.3, 14);
  const geoBola = new THREE.SphereGeometry(0.13, 16, 12);
  const pines = REPISAS.map((y, i) => {
    const pin = new THREE.Group();
    const mat = ayudas.basico();
    const cono = new THREE.Mesh(geoCono, mat);
    cono.rotation.x = Math.PI;
    const bola = new THREE.Mesh(geoBola, mat);
    bola.position.y = 0.22;
    pin.add(cono);
    pin.add(bola);
    const base = y + 0.85;
    pin.userData['base'] = base;
    pin.position.set(-1.5 + i * 1.5, base, 0.1);
    grupo.add(pin);
    return { pin, base };
  });
  ayudas.brillo(0, 0.4, 0.4, 9, 0.1, grupo);

  return {
    grupo,
    x: 3,
    escalaAncha: 1.15,
    escalaAngosta: 0.7,
    yAngosta: 1.5,
    actualizar(estado: EstadoCuadro): void {
      // Con menos movimiento los marcadores quedan quietos (tiempo fijo en 0)
      const t = estado.reducirMovimiento ? 0 : estado.t;
      pines.forEach(({ pin, base }, i) => {
        pin.position.y = base + Math.sin(t * 1.6 + i * 1.3) * 0.12;
        pin.rotation.y = t * 0.8;
      });
    },
  };
};
