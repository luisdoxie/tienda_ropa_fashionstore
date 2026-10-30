import * as THREE from 'three';
import type { Ayudas } from './ayudas';
import type { Paleta } from './contrato';

type Punto = readonly [number, number];

/** Silueta de la polera (frente), en unidades del mundo: cuerpo, mangas y cuello. */
const SILUETA: readonly Punto[] = [
  [-0.45, 1.85],
  [-1.4, 1.55],
  [-2.0, 0.55],
  [-1.55, 0.3],
  [-1.1, 0.5],
  [-1.1, -1.85],
  [1.1, -1.85],
  [1.1, 0.5],
  [1.55, 0.3],
  [2.0, 0.55],
  [1.4, 1.55],
  [0.45, 1.85],
];

/** Puntos de la curva del cuello, de derecha a izquierda (incluye los extremos). */
export const PUNTOS_CUELLO: readonly THREE.Vector2[] = new THREE.QuadraticBezierCurve(
  new THREE.Vector2(0.45, 1.85),
  new THREE.Vector2(0, 1.43),
  new THREE.Vector2(-0.45, 1.85),
).getPoints(14);

/** Contorno cerrado: la silueta más los puntos intermedios del cuello. */
export const CONTORNO: readonly Punto[] = [
  ...SILUETA,
  ...PUNTOS_CUELLO.slice(1, -1).map((p): Punto => [p.x, p.y]),
];

/** ¿El punto (x, y) cae dentro del contorno? (regla par-impar) */
export function dentro(x: number, y: number): boolean {
  let c = false;
  const n = CONTORNO.length;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const [xi, yi] = CONTORNO[i];
    const [xj, yj] = CONTORNO[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}

/** Punto del contorno más cercano a (x, y) y su distancia. */
export function masCercano(x: number, y: number): { d: number; x: number; y: number } {
  let mejor = 1e9;
  let bx = 0;
  let by = 0;
  const n = CONTORNO.length;
  for (let i = 0; i < n; i++) {
    const a = CONTORNO[i];
    const b = CONTORNO[(i + 1) % n];
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)));
    const px = a[0] + t * dx;
    const py = a[1] + t * dy;
    const d = Math.hypot(x - px, y - py);
    if (d < mejor) {
      mejor = d;
      bx = px;
      by = py;
    }
  }
  return { d: mejor, x: bx, y: by };
}

/** Malla "inflada": una cuadrícula recortada por la silueta, con pliegues, doble cara (frente y espalda). */
export function geometriaPolera(): THREE.BufferGeometry {
  const NX = 56;
  const NY = 52;
  const X0 = -2.2;
  const Y0 = -1.95;
  const DX = 4.4 / NX;
  const DY = 3.9 / NY;
  const T = 0.3;
  const D = 0.5;
  const pos: number[][] = [];
  const ins: boolean[] = [];
  for (let iy = 0; iy <= NY; iy++) {
    for (let ix = 0; ix <= NX; ix++) {
      const x = X0 + ix * DX;
      const y = Y0 + iy * DY;
      const c = masCercano(x, y);
      const esta = dentro(x, y);
      if (esta) {
        const s = Math.min(1, c.d / D);
        const z = T * Math.sqrt(1 - (1 - s) * (1 - s));
        const pliegue =
          0.022 * Math.sin(x * 4 + y * 1.6) * Math.sin(y * 3.1 + 0.5) +
          0.03 * Math.sin(y * 6.5 + x * 2.2) * (y < 0.4 ? 1 : 0.25) * Math.min(1, c.d / 0.4);
        pos.push([x, y, z + (c.d > 0.12 ? pliegue : 0)]);
      } else {
        pos.push([c.x, c.y, 0]);
      }
      ins.push(esta);
    }
  }
  const N = pos.length;
  const P = new Float32Array(N * 6);
  pos.forEach((p, i) => {
    P[i * 3] = p[0];
    P[i * 3 + 1] = p[1];
    P[i * 3 + 2] = p[2];
    P[(N + i) * 3] = p[0];
    P[(N + i) * 3 + 1] = p[1];
    P[(N + i) * 3 + 2] = -p[2];
  });
  const idx: number[] = [];
  for (let jy = 0; jy < NY; jy++) {
    for (let jx = 0; jx < NX; jx++) {
      const a = jy * (NX + 1) + jx;
      const b = a + 1;
      const c2 = a + NX + 1;
      const d = c2 + 1;
      if (ins[a] || ins[b] || ins[d]) idx.push(a, b, d, N + a, N + d, N + b);
      if (ins[a] || ins[d] || ins[c2]) idx.push(a, d, c2, N + a, N + c2, N + d);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(P, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

/** Tubo recto (borde cosido) entre dos puntos del plano de la polera. */
function tubo(a: Punto, b: Punto): THREE.TubeGeometry {
  return new THREE.TubeGeometry(
    new THREE.LineCurve3(new THREE.Vector3(a[0], a[1], 0), new THREE.Vector3(b[0], b[1], 0)),
    2,
    0.04,
    8,
    false,
  );
}

/** Luminosidad percibida (0 a 1) de un color. */
export function luminosidad(c: THREE.Color): number {
  return 0.299 * c.r + 0.587 * c.g + 0.114 * c.b;
}

/**
 * La polera 3D de la marca de demostración. Crea geometría, materiales y estampas UNA vez; cada
 * `crear()` entrega un grupo nuevo que los comparte, así que todas las poleras de la escena cambian
 * juntas cuando el visitante cambia el color o el nombre.
 */
export class Polera {
  private readonly geoCuerpo = geometriaPolera();
  private readonly geoCuello = new THREE.TubeGeometry(
    new THREE.CatmullRomCurve3(PUNTOS_CUELLO.map((p) => new THREE.Vector3(p.x, p.y, 0))),
    24,
    0.06,
    8,
    false,
  );
  private readonly geoBordes = [
    tubo([-1.1, -1.85], [1.1, -1.85]),
    tubo([-2.0, 0.55], [-1.55, 0.3]),
    tubo([2.0, 0.55], [1.55, 0.3]),
  ];
  private readonly geoFrente = new THREE.PlaneGeometry(1.15, 1.15);
  private readonly geoEspalda = new THREE.PlaneGeometry(2.0, 1.0);

  private readonly matTela: THREE.MeshStandardMaterial;
  private readonly matCuello: THREE.MeshStandardMaterial;
  private readonly matFrente: THREE.MeshLambertMaterial;
  private readonly matEspalda: THREE.MeshLambertMaterial;
  private readonly lienzoFrente: HTMLCanvasElement;
  private readonly lienzoEspalda: HTMLCanvasElement;
  private readonly texFrente: THREE.CanvasTexture;
  private readonly texEspalda: THREE.CanvasTexture;
  private readonly telaMeta: THREE.Color;
  private nombre = 'Tu tienda';
  private liberada = false;

  constructor(
    private readonly ayudas: Ayudas,
    private readonly paleta: Paleta,
  ) {
    this.telaMeta = new THREE.Color(paleta.acento);
    this.matTela = new THREE.MeshStandardMaterial({ color: paleta.acento, roughness: 0.82, metalness: 0 });
    this.matCuello = new THREE.MeshStandardMaterial({ color: paleta.acento, roughness: 0.9, metalness: 0 });

    this.lienzoFrente = ayudas.lienzo(512, 512);
    this.lienzoEspalda = ayudas.lienzo(1024, 512);
    this.texFrente = new THREE.CanvasTexture(this.lienzoFrente);
    this.texEspalda = new THREE.CanvasTexture(this.lienzoEspalda);
    this.texFrente.anisotropy = 4;
    this.texEspalda.anisotropy = 4;
    this.matFrente = new THREE.MeshLambertMaterial({ map: this.texFrente, transparent: true, depthWrite: false });
    this.matEspalda = new THREE.MeshLambertMaterial({ map: this.texEspalda, transparent: true, depthWrite: false });

    this.dibujarEstampas(this.telaMeta);
    // Las fuentes web llegan después del primer dibujo: se vuelve a estampar cuando estén listas.
    if (typeof document !== 'undefined' && document.fonts?.ready) {
      void document.fonts.ready.then(() => {
        if (!this.liberada) this.redibujarEstampas();
      });
    }
  }

  /** Una polera nueva (grupo de unos 4 x 3,9 unidades) que comparte geometría, materiales y estampas. */
  crear(): THREE.Group {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(this.geoCuerpo, this.matTela));
    g.add(new THREE.Mesh(this.geoCuello, this.matCuello));
    for (const gb of this.geoBordes) g.add(new THREE.Mesh(gb, this.matCuello));
    const frente = new THREE.Mesh(this.geoFrente, this.matFrente);
    frente.position.set(0, 0.3, 0.37);
    g.add(frente);
    const espalda = new THREE.Mesh(this.geoEspalda, this.matEspalda);
    espalda.position.set(0, 0.9, -0.37);
    espalda.rotation.y = Math.PI;
    g.add(espalda);
    return g;
  }

  /**
   * Cambia la marca: la tela se acerca al color nuevo con `avanzar` y las estampas llevan el nombre
   * de inmediato. El color del texto (claro u oscuro) sigue a la tela que se ve ahora; el motor llama
   * a `redibujarEstampas()` un instante después, cuando la tela ya va hacia el color nuevo.
   */
  fijarMarca(nombre: string, tela: string): void {
    this.nombre = nombre.trim().slice(0, 24) || 'Tu tienda';
    this.telaMeta.set(tela);
    this.dibujarEstampas(this.matTela.color);
  }

  /** Vuelve a estampar con el nombre vigente y el color de texto que corresponde a la tela de destino. */
  redibujarEstampas(): void {
    this.dibujarEstampas(this.telaMeta);
  }

  /** Acerca la tela al color objetivo (k de 0 a 1; 1 = de golpe). */
  avanzar(k: number): void {
    this.matTela.color.lerp(this.telaMeta, k);
    this.matCuello.color.copy(this.matTela.color).multiplyScalar(0.8);
  }

  dispose(): void {
    this.liberada = true;
    this.geoCuerpo.dispose();
    this.geoCuello.dispose();
    for (const gb of this.geoBordes) gb.dispose();
    this.geoFrente.dispose();
    this.geoEspalda.dispose();
    this.matTela.dispose();
    this.matCuello.dispose();
    this.matFrente.dispose();
    this.matEspalda.dispose();
    this.texFrente.dispose();
    this.texEspalda.dispose();
  }

  private dibujarEstampas(telaVisible: THREE.Color): void {
    if (this.liberada) return;
    const col = luminosidad(telaVisible) > 0.5 ? this.paleta.carbon : this.paleta.texto;
    const nombre = this.nombre;
    const mayusculas = nombre.toUpperCase();
    const f = this.lienzoFrente.getContext('2d');
    if (f) {
      f.clearRect(0, 0, 512, 512);
      f.strokeStyle = col;
      f.fillStyle = col;
      f.lineWidth = 10;
      f.textAlign = 'center';
      f.textBaseline = 'middle';
      f.strokeRect(126, 60, 260, 260);
      f.font = '800 140px Archivo, Arial, sans-serif';
      f.fillText(this.ayudas.siglas(nombre), 256, 196);
      this.ayudas.ajustarTexto(f, mayusculas, '700 {t}px "Public Sans", Arial, sans-serif', 440, 44);
      f.fillText(mayusculas, 256, 400);
    }
    const e = this.lienzoEspalda.getContext('2d');
    if (e) {
      e.clearRect(0, 0, 1024, 512);
      e.fillStyle = col;
      e.textAlign = 'center';
      e.textBaseline = 'middle';
      this.ayudas.ajustarTexto(e, mayusculas, '800 {t}px Archivo, Arial, sans-serif', 940, 150);
      e.fillText(mayusculas, 512, 256);
    }
    this.texFrente.needsUpdate = true;
    this.texEspalda.needsUpdate = true;
  }
}
