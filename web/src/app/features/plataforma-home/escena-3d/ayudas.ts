import * as THREE from 'three';

type MaterialConColor = THREE.Material & { color: THREE.Color };

/**
 * Utilidades que comparten el motor y todas las paradas: materiales que siguen el color de acento,
 * cajas de esquinas redondeadas, sombras suaves, brillos, etiquetas y un azar repetible.
 *
 * Sin estado global: cada escena crea su propia instancia y la libera con `dispose()`.
 */
export class Ayudas {
  /** Acento vigente (se acerca poco a poco al objetivo cuando el usuario cambia de color). */
  readonly acento = new THREE.Color('#8FAE5B');
  readonly acentoMeta = new THREE.Color('#8FAE5B');

  private readonly acentuados: MaterialConColor[] = [];
  private readonly geometrias = new Map<string, THREE.BufferGeometry>();
  private semilla = 11;
  private texSombra?: THREE.CanvasTexture;
  private texBrillo?: THREE.CanvasTexture;

  /** Azar repetible (misma secuencia en cada carga): la escena se ve igual siempre. */
  azar(): number {
    this.semilla = (this.semilla * 16807) % 2147483647;
    return this.semilla / 2147483647;
  }

  // ---- Acento -------------------------------------------------------------------------------

  /** Registra un material para que su `color` siga al acento vigente. */
  acentuar<T extends MaterialConColor>(material: T): T {
    this.acentuados.push(material);
    return material;
  }

  /** Deja de seguir al acento (p. ej. un resplandor que conserva el color de su tienda). */
  desacentuar(material: MaterialConColor): void {
    const i = this.acentuados.indexOf(material);
    if (i >= 0) this.acentuados.splice(i, 1);
  }

  fijarAcento(hex: string): void {
    this.acentoMeta.set(hex);
  }

  /** Acerca el acento al objetivo (k de 0 a 1; 1 = de golpe) y lo copia a todo lo registrado. */
  avanzarAcento(k: number): void {
    this.acento.lerp(this.acentoMeta, k);
    for (const material of this.acentuados) material.color.copy(this.acento);
  }

  // ---- Materiales ---------------------------------------------------------------------------

  /** Material sin luz que sigue al acento. */
  basico(extra: THREE.MeshBasicMaterialParameters = {}): THREE.MeshBasicMaterial {
    return this.acentuar(new THREE.MeshBasicMaterial({ color: this.acento.clone(), ...extra }));
  }

  /** Material con luz, suave, de un color fijo. */
  liso(hex: THREE.ColorRepresentation): THREE.MeshStandardMaterial {
    return new THREE.MeshStandardMaterial({ color: hex, roughness: 0.72, metalness: 0.1 });
  }

  /** Material con luz que sigue al acento. */
  lisoAcento(): THREE.MeshStandardMaterial {
    return this.acentuar(
      new THREE.MeshStandardMaterial({ color: this.acento.clone(), roughness: 0.6, metalness: 0.12 }),
    );
  }

  // ---- Formas -------------------------------------------------------------------------------

  /** Caja de esquinas y bordes redondeados (extrusión con bisel); las medidas iguales comparten geometría. */
  cajaR(
    w: number,
    h: number,
    d: number,
    r: number,
    material: THREE.Material,
    x: number,
    y: number,
    z: number,
    padre: THREE.Object3D,
  ): THREE.Mesh {
    const malla = new THREE.Mesh(this.geometriaR(w, h, d, r), material);
    malla.position.set(x, y, z);
    padre.add(malla);
    return malla;
  }

  /** Caja de aristas vivas. */
  caja(
    w: number,
    h: number,
    d: number,
    material: THREE.Material,
    x: number,
    y: number,
    z: number,
    padre: THREE.Object3D,
  ): THREE.Mesh {
    const malla = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
    malla.position.set(x, y, z);
    padre.add(malla);
    return malla;
  }

  private geometriaR(w: number, h: number, d: number, r: number): THREE.BufferGeometry {
    const clave = [w, h, d, r].join('|');
    const guardada = this.geometrias.get(clave);
    if (guardada) return guardada;
    const b = Math.min(r, w / 4, h / 4, d / 4);
    const iw = w - 2 * b;
    const ih = h - 2 * b;
    const rr = Math.min(Math.max(b * 0.8, 0.001), iw / 2, ih / 2);
    const x0 = -iw / 2;
    const y0 = -ih / 2;
    const forma = new THREE.Shape();
    forma.moveTo(x0 + rr, y0);
    forma.lineTo(x0 + iw - rr, y0);
    forma.quadraticCurveTo(x0 + iw, y0, x0 + iw, y0 + rr);
    forma.lineTo(x0 + iw, y0 + ih - rr);
    forma.quadraticCurveTo(x0 + iw, y0 + ih, x0 + iw - rr, y0 + ih);
    forma.lineTo(x0 + rr, y0 + ih);
    forma.quadraticCurveTo(x0, y0 + ih, x0, y0 + ih - rr);
    forma.lineTo(x0, y0 + rr);
    forma.quadraticCurveTo(x0, y0, x0 + rr, y0);
    const profundidad = Math.max(0.001, d - 2 * b);
    const geo = new THREE.ExtrudeGeometry(forma, {
      depth: profundidad,
      bevelEnabled: true,
      bevelThickness: b,
      bevelSize: b,
      bevelSegments: 3,
      curveSegments: 5,
    });
    geo.translate(0, 0, -profundidad / 2);
    this.geometrias.set(clave, geo);
    return geo;
  }

  // ---- Sombras, brillos y etiquetas -----------------------------------------------------------

  lienzo(ancho: number, alto: number): HTMLCanvasElement {
    const c = document.createElement('canvas');
    c.width = ancho;
    c.height = alto;
    return c;
  }

  /** Sombra suave sobre el suelo (no recibe rayos del mouse). */
  sombra(w: number, d: number, x: number, z: number, opacidad: number, padre: THREE.Object3D): THREE.Mesh {
    if (!this.texSombra) {
      const c = this.lienzo(128, 128);
      const g2 = c.getContext('2d');
      if (g2) {
        const g = g2.createRadialGradient(64, 64, 4, 64, 64, 62);
        g.addColorStop(0, 'rgba(0,0,0,.6)');
        g.addColorStop(1, 'rgba(0,0,0,0)');
        g2.fillStyle = g;
        g2.fillRect(0, 0, 128, 128);
      }
      this.texSombra = new THREE.CanvasTexture(c);
    }
    const malla = new THREE.Mesh(
      new THREE.PlaneGeometry(w, d),
      new THREE.MeshBasicMaterial({
        map: this.texSombra,
        transparent: true,
        depthWrite: false,
        opacity: opacidad,
        polygonOffset: true,
        polygonOffsetFactor: -2,
      }),
    );
    malla.rotation.x = -Math.PI / 2;
    malla.position.set(x, -2.585, z);
    malla.raycast = () => undefined;
    padre.add(malla);
    return malla;
  }

  /** Halo luminoso aditivo que sigue al acento (no recibe rayos del mouse). */
  brillo(x: number, y: number, z: number, tam: number, opacidad: number, padre: THREE.Object3D): THREE.Sprite {
    if (!this.texBrillo) {
      const c = this.lienzo(128, 128);
      const g2 = c.getContext('2d');
      if (g2) {
        const g = g2.createRadialGradient(64, 64, 0, 64, 64, 64);
        g.addColorStop(0, 'rgba(255,255,255,1)');
        g.addColorStop(0.35, 'rgba(255,255,255,.35)');
        g.addColorStop(1, 'rgba(255,255,255,0)');
        g2.fillStyle = g;
        g2.fillRect(0, 0, 128, 128);
      }
      this.texBrillo = new THREE.CanvasTexture(c);
    }
    const material = this.acentuar(
      new THREE.SpriteMaterial({
        map: this.texBrillo,
        color: this.acento.clone(),
        transparent: true,
        opacity: opacidad,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    const sprite = new THREE.Sprite(material);
    sprite.position.set(x, y, z);
    sprite.scale.set(tam, tam, 1);
    sprite.raycast = () => undefined;
    padre.add(sprite);
    return sprite;
  }

  /** Etiqueta de dos líneas (una chica en tenue, una grande en claro). Colores = los de la paleta. */
  etiqueta(linea1: string, linea2: string, colorTenue: string, colorTexto: string): THREE.Sprite {
    const c = this.lienzo(512, 160);
    const g = c.getContext('2d');
    if (g) {
      g.textAlign = 'center';
      g.fillStyle = colorTenue;
      g.font = '600 30px "Public Sans", Arial, sans-serif';
      g.fillText(linea1, 256, 50);
      g.fillStyle = colorTexto;
      g.font = '800 54px Archivo, Arial, sans-serif';
      g.fillText(linea2, 256, 118);
    }
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }),
    );
    sprite.scale.set(2.8, 0.875, 1);
    sprite.raycast = () => undefined;
    return sprite;
  }

  // ---- Texto ----------------------------------------------------------------------------------

  /** "Mi Boutique" → "MB"; "Chaski" → "CH". */
  siglas(nombre: string): string {
    const palabras = nombre.split(/\s+/).filter(Boolean);
    if (palabras.length >= 2) return (palabras[0][0] + palabras[1][0]).toUpperCase();
    return nombre.slice(0, 2).toUpperCase();
  }

  /** Reduce el tamaño de la fuente hasta que `texto` quepa en `ancho`. `fuente` lleva `{t}` donde va el tamaño. */
  ajustarTexto(g: CanvasRenderingContext2D, texto: string, fuente: string, ancho: number, tam: number): void {
    let t = tam;
    do {
      g.font = fuente.replace('{t}', String(t));
      t -= 4;
    } while (g.measureText(texto).width > ancho && t > 14);
  }

  // ---- Ciclo de vida --------------------------------------------------------------------------

  dispose(): void {
    for (const geo of this.geometrias.values()) geo.dispose();
    this.geometrias.clear();
    this.texSombra?.dispose();
    this.texBrillo?.dispose();
    this.acentuados.length = 0;
  }
}
