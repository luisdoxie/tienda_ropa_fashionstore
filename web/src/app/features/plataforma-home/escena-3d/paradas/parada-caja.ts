import * as THREE from 'three';
import type { EstadoCuadro, FabricaParada } from '../contrato';

/** Tonos de la maqueta de la tienda (no son de la interfaz). */
const MUEBLE_OSCURO = 0x26221c;
const MUEBLE_MEDIO = 0x3b372f;
const MUEBLE_HUESO = 0xd8d3c6;
const MUEBLE_NEGRO = 0x121110;
/** Barras apagadas del gráfico de la pantalla (oliva de los tokens `--fs-*` sobre claro). */
const BARRA_APAGADA = '#5D6B34';

const ANCHO_PANEL = 1024;
const ALTO_PANEL = 560;
/** Con el scroll a esta distancia (en progreso) de la parada se redibuja el panel. */
const TRAMOS = 5;
const PARADA = 1;
const INTERVALO_PANEL = 0.1;
const BARRAS_BASE = [0.38, 0.55, 0.46, 0.7, 0.9, 1, 0.52];

/** 1 · Caja y ventas: mostrador, pantalla con el panel de ventas del día, caja registradora y bolsas. */
export const crearParadaCaja: FabricaParada = (ctx) => {
  const { ayudas, paleta } = ctx;
  const grupo = new THREE.Group();
  grupo.position.z = ctx.z;
  ctx.scene.add(grupo);

  const oscuro = ayudas.liso(MUEBLE_OSCURO);
  const medio = ayudas.liso(MUEBLE_MEDIO);
  const hueso = ayudas.liso(MUEBLE_HUESO);
  const negro = ayudas.liso(MUEBLE_NEGRO);

  // Mostrador, tapa, franja de acento y pantalla trasera
  ayudas.cajaR(5, 1.3, 1.6, 0.2, oscuro, 0, -1.95, 0, grupo);
  ayudas.cajaR(5.3, 0.14, 1.9, 0.07, medio, 0, -1.22, 0, grupo);
  ayudas.cajaR(4.6, 0.07, 0.04, 0.02, ayudas.basico(), 0, -1.95, 0.81, grupo);
  ayudas.cajaR(6.2, 3.6, 0.2, 0.08, negro, 0, 0.2, -1.9, grupo);
  ayudas.sombra(6.4, 3.4, 0, -0.1, 0.8, grupo);

  const lienzoPanel = ayudas.lienzo(ANCHO_PANEL, ALTO_PANEL);
  const texPanel = new THREE.CanvasTexture(lienzoPanel);
  const pantalla = new THREE.Mesh(new THREE.PlaneGeometry(5.7, 3.1), new THREE.MeshBasicMaterial({ map: texPanel }));
  pantalla.position.set(0, 0.2, -1.78);
  grupo.add(pantalla);
  ayudas.brillo(0, 0.2, -1.2, 8, 0.12, grupo);

  // Caja registradora
  ayudas.cajaR(0.9, 0.6, 0.7, 0.1, medio, -1.3, -0.84, 0, grupo);
  const pantallaCaja = ayudas.cajaR(0.7, 0.4, 0.07, 0.03, ayudas.basico(), -1.3, -0.35, -0.12, grupo);
  pantallaCaja.rotation.x = -0.3;

  // Bolsas con asas
  ayudas.cajaR(0.7, 0.9, 0.45, 0.08, ayudas.lisoAcento(), 1.2, -0.7, 0.1, grupo);
  ayudas.cajaR(0.6, 0.75, 0.4, 0.08, hueso, 1.95, -0.77, 0.2, grupo);
  const geoAsa = new THREE.TorusGeometry(0.17, 0.018, 6, 20, Math.PI);
  [1.2, 1.95].forEach((x, k) => {
    const asa = new THREE.Mesh(geoAsa, medio);
    asa.position.set(x, k ? -0.35 : -0.2, k ? 0.2 : 0.1);
    grupo.add(asa);
  });

  /** Dibuja el panel de ventas; `t` mueve las barras (0 = quietas). */
  function dibujarPanel(t: number): void {
    const c = lienzoPanel.getContext('2d');
    if (!c) return;
    const W = ANCHO_PANEL;
    const H = ALTO_PANEL;
    const a = `#${ayudas.acento.getHexString()}`;
    c.fillStyle = paleta.profundo;
    c.fillRect(0, 0, W, H);
    c.strokeStyle = paleta.borde;
    c.lineWidth = 2;
    c.strokeRect(1, 1, W - 2, H - 2);
    c.textAlign = 'left';
    c.textBaseline = 'alphabetic';
    c.fillStyle = paleta.tenue;
    c.font = '500 26px "Public Sans", Arial, sans-serif';
    c.fillText('Ventas de hoy', 48, 70);
    c.fillStyle = paleta.texto;
    c.font = '800 78px Archivo, Arial, sans-serif';
    c.fillText('Bs 3.450', 48, 154);
    c.globalAlpha = 0.2;
    c.fillStyle = a;
    c.fillRect(W - 214, 40, 166, 44);
    c.globalAlpha = 1;
    c.fillStyle = a;
    c.font = '600 24px "Public Sans", Arial, sans-serif';
    c.fillText('Activa', W - 186, 72);
    BARRAS_BASE.forEach((base, i) => {
      const h = base * (0.9 + 0.1 * Math.sin(t * 1.6 + i * 0.9)) * 250;
      c.fillStyle = i === 4 || i === 5 ? a : BARRA_APAGADA;
      c.fillRect(60 + i * 130, 500 - h, 92, h);
    });
    c.fillStyle = 'rgba(242,242,240,.25)';
    c.fillRect(40, 500, W - 80, 2);
    texPanel.needsUpdate = true;
  }

  let ultimoPanel = -1;
  let tReciente = 0;
  dibujarPanel(0);

  return {
    grupo,
    x: -2.8,
    escalaAncha: 1.15,
    escalaAngosta: 0.7,
    yAngosta: 1.5,
    actualizar(estado: EstadoCuadro): void {
      const t = estado.reducirMovimiento ? 0 : estado.t;
      tReciente = t;
      if (Math.abs(estado.progreso - PARADA / TRAMOS) < 0.2 && estado.t - ultimoPanel > INTERVALO_PANEL) {
        dibujarPanel(t);
        ultimoPanel = estado.t;
      }
    },
    redibujar(): void {
      dibujarPanel(tReciente);
    },
  };
};
