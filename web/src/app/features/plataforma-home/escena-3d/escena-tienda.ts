import * as THREE from 'three';
import { Ayudas } from './ayudas';
import { PERFIL_ALTO, perfilRendimiento, type PerfilRendimiento } from './capacidades';
import {
  Y_SUELO,
  Z_PARADAS,
  type ContextoParada,
  type DatosEscena,
  type EstadoCuadro,
  type FabricaParada,
  type Interactivo,
  type MarcaDemo,
  type Paleta,
  type Parada,
} from './contrato';
import { crearParadaCalle } from './paradas/parada-calle';
import { crearParadaCaja } from './paradas/parada-caja';
import { crearParadaHero, type ParadaHero } from './paradas/parada-hero';
import { crearParadaInventario } from './paradas/parada-inventario';
import { crearParadaPlanes } from './paradas/parada-planes';
import { crearParadaProbador } from './paradas/parada-probador';
import { leerPaleta } from './paleta';
import { Polera } from './polera';

// ---- Lógica pura (se prueba sin WebGL) ------------------------------------------------------------

/** Tramos de scroll del recorrido: 6 paradas = 5 tramos de una pantalla. */
export const TRAMOS_RECORRIDO = 5;
/** Alto de pantallas de scroll que ocupa la escena antes de que la lista de tiendas la tape. */
export const TRAMOS_VH_POR_OMISION = 6;
/** Por debajo de este progreso la polera del inicio se puede girar con el dedo o el mouse. */
export const PROGRESO_ARRASTRE = 0.12;
/** Pausa antes de volver a estampar lo que depende del color (la tela ya va hacia el color nuevo). */
export const RETRASO_REDIBUJO_MS = 450;

/** Progreso objetivo (0 a 1) del recorrido según el scroll. */
export function calcularProgreso(scrollY: number, altoVentana: number, tramos = TRAMOS_RECORRIDO): number {
  if (!(altoVentana > 0)) return 0;
  return Math.min(1, Math.max(0, scrollY / (tramos * altoVentana)));
}

/** Pantalla ancha: más ancha que alta (aspecto > 1,15) y de más de 860 px. */
export function esPantallaAncha(aspecto: number, anchoVentana: number): boolean {
  return aspecto > 1.15 && anchoVentana > 860;
}

/** ¿Hay que dibujar? No cuando la lista de tiendas ya tapa la escena (scroll más allá de su fin). */
export function debeDibujar(scrollY: number, altoVentana: number, tramosVh: number): boolean {
  return scrollY <= (tramosVh + 0.05) * altoVentana;
}

export interface Colocacion {
  x: number;
  y: number;
  escala: number;
}

/** Dónde va el grupo de una parada: pantalla ancha (a un lado) o angosta (centrado y más chico). */
export function colocarParada(
  parada: Pick<Parada, 'x' | 'escalaAncha' | 'escalaAngosta' | 'yAngosta'>,
  ancha: boolean,
): Colocacion {
  if (ancha) {
    return { x: parada.x, y: -Y_SUELO * (parada.escalaAncha - 1), escala: parada.escalaAncha };
  }
  return { x: 0, y: parada.yAngosta, escala: parada.escalaAngosta };
}

/** Factor de acercamiento por cuadro (0 a 1) con suavizado exponencial independiente de los fps. */
export function factorSuavizado(dt: number, base: number, reducirMovimiento: boolean): number {
  return reducirMovimiento ? 1 : 1 - Math.pow(base, dt);
}

/** Posición de la cámara en cada parada: x, y y distancia por delante de la parada. */
const CAMARA_POSICIONES: readonly (readonly [number, number, number])[] = [
  [0, 0.3, 9.5],
  [1.2, 0.9, 9],
  [-1.2, 0.6, 9],
  [1.0, 0.9, 9],
  [0, 1.6, 10.5],
  [0, 1.0, 10.5],
];
/** A dónde mira la cámara en cada parada: x e y (la z es la de la parada). */
const CAMARA_OBJETIVOS: readonly (readonly [number, number])[] = [
  [0.2, 0],
  [-0.2, 0],
  [0.2, 0],
  [-0.2, 0],
  [0, -1.9],
  [0, 0],
];

export function posicionesCamara(): THREE.Vector3[] {
  return CAMARA_POSICIONES.map(([x, y, delante], i) => new THREE.Vector3(x, y, Z_PARADAS[i] + delante));
}

export function objetivosCamara(): THREE.Vector3[] {
  return CAMARA_OBJETIVOS.map(([x, y], i) => new THREE.Vector3(x, y, Z_PARADAS[i]));
}

// ---- Motor ----------------------------------------------------------------------------------------

export interface OpcionesEscena {
  canvas: HTMLCanvasElement;
  reducirMovimiento: boolean;
  /** El visitante eligió un local de la calle de tiendas. */
  alElegirTienda(codigo: string): void;
  /** Calidad según la potencia del equipo (por omisión se mide el equipo). */
  perfil?: PerfilRendimiento;
  /** Pantallas de scroll que ocupa la escena (por omisión 6). Pasado ese punto no se dibuja. */
  tramosVh?: number;
  /** Para pruebas: otra manera de crear el renderer (por omisión, un `WebGLRenderer` sobre el lienzo). */
  crearRenderer?: (canvas: HTMLCanvasElement) => RendererEscena;
  /** Para pruebas: otras fábricas para las cinco paradas que siguen al inicio (por omisión, las reales). */
  fabricas?: readonly FabricaParada[];
}

/** Lo único que el motor usa del renderer. */
export type RendererEscena = Pick<
  THREE.WebGLRenderer,
  'outputColorSpace' | 'setPixelRatio' | 'setSize' | 'render' | 'dispose' | 'forceContextLoss'
>;

/** Fábricas de las paradas que siguen al inicio, en el orden del recorrido (el inicio es propio del motor). */
const FABRICAS: readonly FabricaParada[] = [
  crearParadaCaja,
  crearParadaInventario,
  crearParadaProbador,
  crearParadaPlanes,
  crearParadaCalle,
];

/**
 * La escena 3D de la portada: una cámara avanza por una tienda con seis paradas según el scroll.
 * Sin estado global: cada instancia crea y libera todo lo suyo (`destruir()`).
 */
export class EscenaTienda {
  static crear(opciones: OpcionesEscena): EscenaTienda {
    return new EscenaTienda(opciones);
  }

  private readonly canvas: HTMLCanvasElement;
  private readonly reducir: boolean;
  private readonly tramosVh: number;
  private readonly perfil: PerfilRendimiento;
  private readonly gestionColorPrevio: boolean;
  private readonly paleta: Paleta;
  private readonly renderer: RendererEscena;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(40, 1, 0.1, 220);
  private readonly ayudas: Ayudas;
  private readonly polera: Polera;
  private readonly luzBorde: THREE.DirectionalLight;
  private readonly paradas: Parada[] = [];
  private readonly hero: ParadaHero;
  private readonly curvaPos = new THREE.CatmullRomCurve3(posicionesCamara());
  private readonly curvaObj = new THREE.CatmullRomCurve3(objetivosCamara());
  private readonly vp = new THREE.Vector3();
  private readonly vo = new THREE.Vector3();
  private readonly rayo = new THREE.Raycaster();
  private readonly ndc = new THREE.Vector2(2, 2);
  private readonly estado: EstadoCuadro;

  private datos: DatosEscena = { planes: [], tiendas: [] };
  private ancha = true;
  private anchoPx = 0;
  private altoPx = 0;
  private progreso = 0;
  private paralaje = { x: 0, y: 0 };
  private puntero = { x: 0, y: 0 };
  private arrastrando = false;
  private ultimoX = 0;
  private ultimoT = 0;
  private inicioMs: number | null = null;
  private raf = 0;
  private temporizadorRedibujo: ReturnType<typeof setTimeout> | undefined;
  private primeraMarca = true;
  private destruida = false;
  private cursor = '';
  private readonly bajo = new Map<Interactivo, THREE.Object3D | null>();

  private readonly alCambiarTamano = (): void => this.redimensionar();
  private readonly alCambiarVisibilidad = (): void => {
    if (document.hidden) {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    } else if (!this.raf && !this.destruida) {
      this.raf = requestAnimationFrame(this.cuadro);
    }
  };
  private readonly alMoverPuntero = (e: PointerEvent): void => this.leerPuntero(e);
  private readonly alAgarrar = (e: PointerEvent): void => {
    if (this.progreso > PROGRESO_ARRASTRE) return;
    this.arrastrando = true;
    this.ultimoX = e.clientX;
    this.hero.rotar(0);
    this.fijarCursor('grabbing');
    try {
      this.canvas.setPointerCapture(e.pointerId);
    } catch {
      // Sin captura el arrastre igual funciona mientras el puntero siga sobre el lienzo.
    }
  };
  private readonly alArrastrar = (e: PointerEvent): void => {
    if (!this.arrastrando) return;
    const dx = e.clientX - this.ultimoX;
    this.ultimoX = e.clientX;
    this.hero.rotar(dx);
  };
  private readonly alSoltar = (): void => {
    if (!this.arrastrando) return;
    this.arrastrando = false;
    this.hero.soltar();
  };
  private readonly alHacerClic = (e: MouseEvent): void => {
    this.actualizarNdc(e.clientX, e.clientY);
    for (const parada of this.paradas) {
      const inter = parada.interactivo;
      if (!inter || this.progreso <= inter.desdeProgreso) continue;
      const objeto = this.sondear(inter);
      if (objeto) inter.alClic(objeto);
    }
  };

  private constructor(private readonly opciones: OpcionesEscena) {
    this.canvas = opciones.canvas;
    this.reducir = opciones.reducirMovimiento;
    this.tramosVh = opciones.tramosVh ?? TRAMOS_VH_POR_OMISION;
    this.perfil = opciones.perfil ?? perfilSeguro();
    this.paleta = leerPaleta();

    // Los colores hex deben verse como en three r128: sin gestión de color ni conversión de salida.
    this.gestionColorPrevio = THREE.ColorManagement.enabled;
    THREE.ColorManagement.enabled = false;

    this.renderer = opciones.crearRenderer
      ? opciones.crearRenderer(this.canvas)
      : new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true });
    this.renderer.outputColorSpace = THREE.LinearSRGBColorSpace;

    this.ayudas = new Ayudas();
    this.ayudas.fijarAcento(this.paleta.acento);
    this.ayudas.avanzarAcento(1);
    this.polera = new Polera(this.ayudas, this.paleta);
    this.estado = { t: 0, dt: 0, progreso: 0, reducirMovimiento: this.reducir };

    this.armarMundo();
    this.luzBorde = this.armarLuces();
    this.hero = this.armarParadas();

    this.redimensionar(true);
    this.agregarListeners();
    this.raf = requestAnimationFrame(this.cuadro);
    // Las fuentes web llegan tarde: lo que se estampa o se escribe en lienzos debe repetirse.
    if (document.fonts?.ready) {
      void document.fonts.ready.then(() => {
        if (!this.destruida) this.redibujarParadas();
      });
    }
  }

  // ---- API pública ----

  /** Llegan o cambian los planes y las tiendas: las paradas se actualizan y se vuelve a acomodar todo. */
  fijarDatos(datos: DatosEscena): void {
    if (this.destruida) return;
    this.datos = datos;
    for (const parada of this.paradas) parada.fijarDatos?.(datos);
    // `escalaAncha` de una parada puede depender de los datos.
    this.adaptar();
  }

  /** La marca de la demo: el acento y la tela se acercan al color nuevo; las estampas se rehacen. */
  fijarMarca(marca: MarcaDemo): void {
    if (this.destruida) return;
    this.ayudas.fijarAcento(marca.acento);
    this.polera.fijarMarca(marca.nombre, marca.tela);
    if (this.primeraMarca) {
      // La marca de arranque se ve de entrada, sin transición desde el color por omisión.
      this.primeraMarca = false;
      this.ayudas.avanzarAcento(1);
      this.polera.avanzar(1);
      this.polera.redibujarEstampas();
      this.redibujarParadas();
      return;
    }
    clearTimeout(this.temporizadorRedibujo);
    this.temporizadorRedibujo = setTimeout(() => {
      this.temporizadorRedibujo = undefined;
      if (this.destruida) return;
      this.polera.redibujarEstampas();
      this.redibujarParadas();
    }, RETRASO_REDIBUJO_MS);
  }

  /** Ajusta el tamaño del dibujo al del lienzo y vuelve a acomodar las paradas. */
  redimensionar(forzar = false): void {
    if (this.destruida) return;
    const w = this.canvas.clientWidth || window.innerWidth;
    const h = this.canvas.clientHeight || window.innerHeight;
    if (!forzar && w === this.anchoPx && h === this.altoPx) return;
    this.anchoPx = w;
    this.altoPx = h;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, this.perfil.pixelRatioMax));
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / Math.max(1, h);
    this.camera.updateProjectionMatrix();
    this.adaptar();
  }

  /** Libera todo: bucle, escuchas, geometrías, materiales, texturas y el contexto de WebGL. */
  destruir(): void {
    if (this.destruida) return;
    this.destruida = true;
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    clearTimeout(this.temporizadorRedibujo);
    this.temporizadorRedibujo = undefined;
    this.quitarListeners();
    this.scene.traverse(liberarObjeto);
    this.scene.clear();
    this.ayudas.dispose();
    this.polera.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.canvas.style.cursor = '';
    THREE.ColorManagement.enabled = this.gestionColorPrevio;
  }

  // ---- Armado del mundo ----

  private armarMundo(): void {
    const { paleta, scene, ayudas } = this;
    scene.background = new THREE.Color(paleta.carbon);
    scene.fog = new THREE.Fog(paleta.carbon, 18, 80);

    // Suelo, rejilla y polvo en suspensión.
    const suelo = new THREE.Mesh(
      new THREE.PlaneGeometry(320, 460),
      new THREE.MeshStandardMaterial({ color: paleta.profundo, roughness: 1 }),
    );
    suelo.rotation.x = -Math.PI / 2;
    suelo.position.set(0, Y_SUELO, -85);
    scene.add(suelo);

    const rejilla = new THREE.GridHelper(460, 153, 0xffffff, 0xffffff);
    const matRejilla = rejilla.material as THREE.LineBasicMaterial;
    matRejilla.transparent = true;
    matRejilla.opacity = 0.12;
    rejilla.position.set(0, -2.59, -85);
    ayudas.acentuar(matRejilla);
    scene.add(rejilla);

    const n = this.perfil.particulas;
    const puntos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      puntos[i * 3] = (ayudas.azar() - 0.5) * 30;
      puntos[i * 3 + 1] = -2.4 + ayudas.azar() * 7.5;
      puntos[i * 3 + 2] = 12 - ayudas.azar() * 205;
    }
    const geoPolvo = new THREE.BufferGeometry();
    geoPolvo.setAttribute('position', new THREE.BufferAttribute(puntos, 3));
    const matPolvo = ayudas.acentuar(
      new THREE.PointsMaterial({
        color: ayudas.acento.clone(),
        size: 0.07,
        transparent: true,
        opacity: 0.55,
        depthWrite: false,
      }),
    );
    scene.add(new THREE.Points(geoPolvo, matPolvo));
  }

  /** Desde r155 las luces hemisférica y direccional son π veces más débiles: se compensa para ver lo de r128. */
  private armarLuces(): THREE.DirectionalLight {
    const { paleta, scene } = this;
    scene.add(new THREE.HemisphereLight(paleta.texto, paleta.borde, 1.05 * Math.PI));
    const sol = new THREE.DirectionalLight(0xffffff, 1.05 * Math.PI);
    sol.position.set(3, 6, 8);
    scene.add(sol);
    const luzBorde = new THREE.DirectionalLight(paleta.acento, 0.9 * Math.PI);
    luzBorde.position.set(-5, 2, -6);
    scene.add(luzBorde);
    return luzBorde;
  }

  private armarParadas(): ParadaHero {
    const contexto = (i: number): ContextoParada => ({
      ayudas: this.ayudas,
      scene: this.scene,
      paleta: this.paleta,
      crearPolera: () => this.polera.crear(),
      z: Z_PARADAS[i],
      datos: this.datos,
      alElegirTienda: (codigo) => this.opciones.alElegirTienda(codigo),
    });
    const hero = crearParadaHero(contexto(0));
    this.paradas.push(hero);
    (this.opciones.fabricas ?? FABRICAS).forEach((fabrica, k) => this.paradas.push(fabrica(contexto(k + 1))));
    for (const parada of this.paradas) parada.fijarDatos?.(this.datos);
    return hero;
  }

  // ---- Acomodo según la pantalla ----

  private adaptar(): void {
    const aspecto = this.camera.aspect;
    this.ancha = esPantallaAncha(aspecto, window.innerWidth);
    for (const parada of this.paradas) {
      const c = colocarParada(parada, this.ancha);
      parada.grupo.position.x = c.x;
      parada.grupo.position.y = c.y;
      parada.grupo.scale.setScalar(c.escala);
    }
  }

  private redibujarParadas(): void {
    for (const parada of this.paradas) parada.redibujar?.();
  }

  // ---- Escuchas ----

  private agregarListeners(): void {
    window.addEventListener('resize', this.alCambiarTamano);
    document.addEventListener('visibilitychange', this.alCambiarVisibilidad);
    window.addEventListener('pointermove', this.alMoverPuntero, { passive: true });
    window.addEventListener('pointerdown', this.alMoverPuntero, { passive: true });
    this.canvas.addEventListener('pointerdown', this.alAgarrar);
    this.canvas.addEventListener('pointermove', this.alArrastrar);
    this.canvas.addEventListener('pointerup', this.alSoltar);
    this.canvas.addEventListener('pointercancel', this.alSoltar);
    this.canvas.addEventListener('click', this.alHacerClic);
  }

  private quitarListeners(): void {
    window.removeEventListener('resize', this.alCambiarTamano);
    document.removeEventListener('visibilitychange', this.alCambiarVisibilidad);
    window.removeEventListener('pointermove', this.alMoverPuntero);
    window.removeEventListener('pointerdown', this.alMoverPuntero);
    this.canvas.removeEventListener('pointerdown', this.alAgarrar);
    this.canvas.removeEventListener('pointermove', this.alArrastrar);
    this.canvas.removeEventListener('pointerup', this.alSoltar);
    this.canvas.removeEventListener('pointercancel', this.alSoltar);
    this.canvas.removeEventListener('click', this.alHacerClic);
  }

  private leerPuntero(e: PointerEvent): void {
    this.actualizarNdc(e.clientX, e.clientY);
    // El paralaje sigue al mouse; con el dedo la cámara no debe quedar ladeada.
    if (e.pointerType !== 'touch') {
      this.puntero.x = e.clientX / window.innerWidth - 0.5;
      this.puntero.y = e.clientY / window.innerHeight - 0.5;
    }
  }

  private actualizarNdc(clientX: number, clientY: number): void {
    this.ndc.x = (clientX / window.innerWidth) * 2 - 1;
    this.ndc.y = -((clientY / window.innerHeight) * 2 - 1);
  }

  private fijarCursor(cursor: string): void {
    if (cursor === this.cursor) return;
    this.cursor = cursor;
    this.canvas.style.cursor = cursor;
  }

  // ---- Interacción con objetos ----

  /** Raíz de `inter.objetos` bajo el puntero, o null. */
  private sondear(inter: Interactivo): THREE.Object3D | null {
    this.rayo.setFromCamera(this.ndc, this.camera);
    const impactos = this.rayo.intersectObjects(inter.objetos as THREE.Object3D[], true);
    if (!impactos.length) return null;
    let o: THREE.Object3D | null = impactos[0].object;
    while (o && !inter.objetos.includes(o)) o = o.parent;
    return o;
  }

  private actualizarHover(): void {
    let sobreObjeto = false;
    for (const parada of this.paradas) {
      const inter = parada.interactivo;
      if (!inter) continue;
      const objeto = this.progreso > inter.desdeProgreso ? this.sondear(inter) : null;
      if (objeto) sobreObjeto = true;
      if ((this.bajo.get(inter) ?? null) !== objeto) {
        this.bajo.set(inter, objeto);
        inter.alPasar(objeto);
      }
    }
    if (sobreObjeto) this.fijarCursor('pointer');
    else if (this.progreso < PROGRESO_ARRASTRE) this.fijarCursor(this.arrastrando ? 'grabbing' : 'grab');
    else this.fijarCursor('default');
  }

  // ---- Bucle ----

  private readonly cuadro = (ms: number): void => {
    this.raf = requestAnimationFrame(this.cuadro);
    if (document.hidden) return;
    // La lista de tiendas tapa la escena: no se dibuja.
    if (!debeDibujar(window.scrollY, window.innerHeight, this.tramosVh)) return;

    if (this.inicioMs === null) this.inicioMs = ms;
    const t = (ms - this.inicioMs) / 1000;
    const dt = Math.min(0.05, Math.max(0, t - this.ultimoT));
    this.ultimoT = t;

    const reducir = this.reducir;
    const k = factorSuavizado(dt, 0.002, reducir);
    this.ayudas.avanzarAcento(k);
    this.polera.avanzar(k);
    this.luzBorde.color.copy(this.ayudas.acento);

    const meta = calcularProgreso(window.scrollY, window.innerHeight);
    this.progreso += (meta - this.progreso) * factorSuavizado(dt, 0.0008, reducir);
    this.paralaje.x += (this.puntero.x - this.paralaje.x) * 0.05;
    this.paralaje.y += (this.puntero.y - this.paralaje.y) * 0.05;
    this.curvaPos.getPoint(this.progreso, this.vp);
    this.curvaObj.getPoint(this.progreso, this.vo);
    this.camera.position.set(this.vp.x + this.paralaje.x * 0.7, this.vp.y - this.paralaje.y * 0.45, this.vp.z);
    this.camera.lookAt(this.vo);
    this.camera.updateMatrixWorld();

    this.hero.inclinar(this.paralaje.y);
    this.estado.t = t;
    this.estado.dt = dt;
    this.estado.progreso = this.progreso;
    for (const parada of this.paradas) parada.actualizar(this.estado);

    this.actualizarHover();
    this.renderer.render(this.scene, this.camera);
  };
}

function perfilSeguro(): PerfilRendimiento {
  try {
    return perfilRendimiento();
  } catch {
    return { ...PERFIL_ALTO };
  }
}

/** Libera geometría, materiales y texturas de un objeto de la escena. */
function liberarObjeto(objeto: THREE.Object3D): void {
  const con = objeto as THREE.Object3D & {
    geometry?: THREE.BufferGeometry;
    material?: THREE.Material | THREE.Material[];
  };
  con.geometry?.dispose();
  const materiales = Array.isArray(con.material) ? con.material : con.material ? [con.material] : [];
  for (const material of materiales) {
    for (const valor of Object.values(material)) {
      if (valor instanceof THREE.Texture) valor.dispose();
    }
    material.dispose();
  }
}
