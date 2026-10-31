import * as THREE from 'three';
import type { EstadoCuadro, FabricaParada } from '../contrato';

/** Tonos de la maqueta de la tienda (no son de la interfaz). */
const MUEBLE_OSCURO = 0x26221c;
const MUEBLE_MEDIO = 0x3b372f;
const MUEBLE_NEGRO = 0x121110;

/** Perfil (radio, altura) del torso del maniquí, girado sobre el eje y. */
const PERFIL_TORSO: ReadonlyArray<readonly [number, number]> = [
  [0.001, -0.78],
  [0.42, -0.74],
  [0.6, -0.4],
  [0.62, 0.0],
  [0.58, 0.35],
  [0.46, 0.62],
  [0.26, 0.74],
  [0.13, 0.84],
  [0.12, 1.0],
  [0.001, 1.02],
];

/** 3 · Probador virtual: maniquí holograma, polera con giro suave, escaneo y teléfono con la app. */
export const crearParadaProbador: FabricaParada = (ctx) => {
  const { ayudas, paleta } = ctx;
  const grupo = new THREE.Group();
  grupo.position.z = ctx.z;
  ctx.scene.add(grupo);

  const oscuro = ayudas.liso(MUEBLE_OSCURO);
  const medio = ayudas.liso(MUEBLE_MEDIO);
  const negro = ayudas.liso(MUEBLE_NEGRO);

  // Maniquí holograma
  const malla = ayudas.basico({ wireframe: true, transparent: true, opacity: 0.5 });
  const torso = new THREE.Mesh(
    new THREE.LatheGeometry(
      PERFIL_TORSO.map(([r, y]) => new THREE.Vector2(r, y)),
      28,
    ),
    malla,
  );
  torso.scale.z = 0.38;
  grupo.add(torso);
  const cabeza = new THREE.Mesh(new THREE.SphereGeometry(0.27, 20, 14), malla);
  cabeza.position.y = 1.28;
  grupo.add(cabeza);
  const poste = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 1.9, 12), medio);
  poste.position.y = -1.7;
  grupo.add(poste);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.85, 0.95, 0.14, 40), oscuro);
  base.position.y = -2.53;
  grupo.add(base);
  const aroBase = new THREE.Mesh(new THREE.RingGeometry(0.8, 0.86, 48), ayudas.basico({ side: THREE.DoubleSide }));
  aroBase.rotation.x = -Math.PI / 2;
  aroBase.position.y = -2.455;
  grupo.add(aroBase);
  ayudas.sombra(2.8, 2.8, 0, 0, 0.9, grupo);

  // Polera sobre el maniquí
  const polera = ctx.crearPolera();
  polera.scale.setScalar(0.42);
  grupo.add(polera);

  // Escaneo: anillo + disco + brillo que suben y bajan
  const anilloEscaneo = new THREE.Mesh(new THREE.TorusGeometry(1.15, 0.012, 8, 96), ayudas.basico());
  anilloEscaneo.rotation.x = Math.PI / 2;
  grupo.add(anilloEscaneo);
  const discoEscaneo = new THREE.Mesh(
    new THREE.CircleGeometry(1.15, 56),
    ayudas.basico({ transparent: true, opacity: 0.14, side: THREE.DoubleSide, depthWrite: false }),
  );
  discoEscaneo.rotation.x = Math.PI / 2;
  grupo.add(discoEscaneo);
  const brilloEscaneo = ayudas.brillo(0, 0, 0, 3.4, 0.28, grupo);

  // Teléfono con la app
  const telefono = new THREE.Group();
  telefono.position.set(1.9, 0, 0.8);
  telefono.rotation.y = -0.4;
  grupo.add(telefono);
  ayudas.cajaR(0.8, 1.6, 0.08, 0.1, negro, 0, 0, 0, telefono);
  const lienzoTel = ayudas.lienzo(256, 512);
  const texTel = new THREE.CanvasTexture(lienzoTel);
  const pantallaTel = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 1.48), new THREE.MeshBasicMaterial({ map: texTel }));
  pantallaTel.position.z = 0.05;
  telefono.add(pantallaTel);

  function dibujarTelefono(): void {
    const c = lienzoTel.getContext('2d');
    if (!c) return;
    const a = `#${ayudas.acentoMeta.getHexString()}`;
    c.fillStyle = paleta.profundo;
    c.fillRect(0, 0, 256, 512);
    c.textAlign = 'center';
    c.fillStyle = paleta.tenue;
    c.font = '600 18px "Public Sans", Arial, sans-serif';
    c.fillText('PROBADOR VIRTUAL', 128, 46);
    // Silueta de polera
    c.fillStyle = a;
    c.beginPath();
    c.moveTo(88, 110);
    c.lineTo(48, 128);
    c.lineTo(24, 186);
    c.lineTo(48, 198);
    c.lineTo(70, 186);
    c.lineTo(70, 330);
    c.lineTo(186, 330);
    c.lineTo(186, 186);
    c.lineTo(208, 198);
    c.lineTo(232, 186);
    c.lineTo(208, 128);
    c.lineTo(168, 110);
    c.quadraticCurveTo(128, 140, 88, 110);
    c.closePath();
    c.fill();
    // Botón
    c.fillStyle = a;
    c.fillRect(28, 400, 200, 56);
    c.fillStyle = paleta.sobreAcento;
    c.font = '700 20px "Public Sans", Arial, sans-serif';
    c.fillText('Probar prenda', 128, 435);
    texTel.needsUpdate = true;
  }
  dibujarTelefono();

  return {
    grupo,
    x: -2.8,
    escalaAncha: 1.4,
    escalaAngosta: 0.7,
    yAngosta: 1.5,
    actualizar(estado: EstadoCuadro): void {
      // Con menos movimiento todo queda en su pose de reposo (tiempo fijo en 0)
      const t = estado.reducirMovimiento ? 0 : estado.t;
      const fase = (Math.sin(t * 0.9) + 1) / 2;
      const yEscaneo = -1.0 + fase * 2.3;
      anilloEscaneo.position.y = yEscaneo;
      discoEscaneo.position.y = yEscaneo;
      brilloEscaneo.position.y = yEscaneo;
      polera.rotation.y = Math.sin(t * 0.5) * 0.6;
      telefono.position.y = Math.sin(t * 1.2) * 0.1;
    },
    redibujar(): void {
      dibujarTelefono();
    },
  };
};
