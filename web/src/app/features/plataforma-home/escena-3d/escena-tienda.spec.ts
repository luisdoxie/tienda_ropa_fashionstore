import * as THREE from 'three';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import type { ContextoParada, FabricaParada, Interactivo, Parada } from './contrato';
import {
  EscenaTienda,
  RETRASO_REDIBUJO_MS,
  type RendererEscena,
  calcularProgreso,
  colocarParada,
  debeDibujar,
  esPantallaAncha,
  factorSuavizado,
  objetivosCamara,
  posicionesCamara,
} from './escena-tienda';

// ---- Dobles de prueba: no hay WebGL en jsdom, y las otras paradas las construyen otros archivos ----

interface FalsaParada extends Parada {
  escalaAncha: number;
  actualizar: ReturnType<typeof vi.fn<Parada['actualizar']>>;
  fijarDatos: ReturnType<typeof vi.fn<NonNullable<Parada['fijarDatos']>>>;
  redibujar: ReturnType<typeof vi.fn<NonNullable<Parada['redibujar']>>>;
  interactivo?: Interactivo;
}

interface RendererFalso {
  outputColorSpace: string;
  setPixelRatio: Mock<(valor: number) => void>;
  setSize: Mock<(ancho: number, alto: number, estilo?: boolean) => void>;
  render: Mock<() => void>;
  dispose: Mock<() => void>;
  forceContextLoss: Mock<() => void>;
}
const falsos = {
  renderers: [] as RendererFalso[],
  paradas: {} as Record<string, FalsaParada>,
  contextos: {} as Record<string, ContextoParada>,
};

function crearRendererFalso(): RendererEscena {
  const r = {
    outputColorSpace: '',
    setPixelRatio: vi.fn(),
    setSize: vi.fn(),
    render: vi.fn(),
    dispose: vi.fn(),
    forceContextLoss: vi.fn(),
  } as unknown as RendererFalso;
  falsos.renderers.push(r);
  return r as unknown as RendererEscena;
}

/** Fábrica de una parada falsa: un grupo en su z, con espías en actualizar, fijarDatos y redibujar. */
function fabricaFalsa(archivo: string, x: number): FabricaParada {
  return (ctx) => {
    const grupo = new THREE.Group();
    grupo.position.z = ctx.z;
    ctx.scene.add(grupo);
    const parada: FalsaParada = {
      grupo,
      x,
      escalaAncha: 1.15,
      escalaAngosta: 0.7,
      yAngosta: 1.5,
      actualizar: vi.fn(),
      fijarDatos: vi.fn(),
      redibujar: vi.fn(),
    };
    falsos.paradas[archivo] = parada;
    falsos.contextos[archivo] = ctx;
    return parada;
  };
}

const FABRICAS_FALSAS: FabricaParada[] = [
  fabricaFalsa('caja', -2.8),
  fabricaFalsa('inventario', 2.2),
  fabricaFalsa('probador', 2.6),
  fabricaFalsa('planes', 0),
  fabricaFalsa('calle', 0),
];

// ---- Lógica pura ----

describe('lógica pura del motor', () => {
  it('calcularProgreso: scroll / (5 pantallas), acotado a [0, 1]', () => {
    expect(calcularProgreso(0, 800)).toBe(0);
    expect(calcularProgreso(2000, 800)).toBeCloseTo(0.5, 10);
    expect(calcularProgreso(4000, 800)).toBe(1);
    expect(calcularProgreso(99999, 800)).toBe(1);
    expect(calcularProgreso(-50, 800)).toBe(0);
    expect(calcularProgreso(100, 0)).toBe(0);
  });

  it('esPantallaAncha: aspecto > 1,15 y más de 860 px', () => {
    expect(esPantallaAncha(1.78, 1280)).toBe(true);
    expect(esPantallaAncha(1.15, 1280)).toBe(false);
    expect(esPantallaAncha(1.16, 1280)).toBe(true);
    expect(esPantallaAncha(1.78, 860)).toBe(false);
    expect(esPantallaAncha(1.78, 861)).toBe(true);
    expect(esPantallaAncha(0.5, 400)).toBe(false);
  });

  it('colocarParada: ancha sube el grupo 2,6 por cada punto de escala; angosta lo centra', () => {
    const p = { x: -2.8, escalaAncha: 1.15, escalaAngosta: 0.7, yAngosta: 1.5 };
    const ancha = colocarParada(p, true);
    expect(ancha.x).toBe(-2.8);
    expect(ancha.y).toBeCloseTo(2.6 * 0.15, 10);
    expect(ancha.escala).toBe(1.15);
    expect(colocarParada(p, false)).toEqual({ x: 0, y: 1.5, escala: 0.7 });
    expect(colocarParada({ ...p, escalaAncha: 1 }, true).y).toBeCloseTo(0, 10);
  });

  it('debeDibujar: no pasada la escena (6 pantallas más 5 %) ', () => {
    expect(debeDibujar(0, 800, 6)).toBe(true);
    expect(debeDibujar(6.05 * 800, 800, 6)).toBe(true);
    expect(debeDibujar(6.06 * 800, 800, 6)).toBe(false);
    expect(debeDibujar(3 * 800, 800, 2)).toBe(false);
  });

  it('factorSuavizado: 1 sin movimiento; entre 0 y 1 con él', () => {
    expect(factorSuavizado(0.016, 0.002, true)).toBe(1);
    const k = factorSuavizado(0.016, 0.002, false);
    expect(k).toBeGreaterThan(0);
    expect(k).toBeLessThan(1);
    expect(factorSuavizado(0, 0.002, false)).toBe(0);
  });

  it('la cámara pasa por las seis paradas (usa Z_PARADAS)', () => {
    const pos = posicionesCamara();
    const obj = objetivosCamara();
    expect(pos.map((v) => v.z)).toEqual([9.5, -27, -63, -99, -133.5, -169.5]);
    expect(obj.map((v) => v.z)).toEqual([0, -36, -72, -108, -144, -180]);
    expect(obj[4].y).toBe(-1.9);
  });
});

// ---- Motor completo con un renderer simulado ----

describe('EscenaTienda', () => {
  let canvas: HTMLCanvasElement;
  let escena: EscenaTienda | null;
  let cola: Map<number, FrameRequestCallback>;
  let siguienteId: number;
  let alElegirTienda: ReturnType<typeof vi.fn<(codigo: string) => void>>;
  let tiempo: number;
  const original = { scrollY: 0, innerWidth: 1024, innerHeight: 768, colorGestion: true };

  function ventana(ancho: number, alto: number, scroll = 0): void {
    Object.defineProperty(window, 'innerWidth', { value: ancho, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: alto, configurable: true });
    Object.defineProperty(window, 'scrollY', { value: scroll, configurable: true });
  }

  /** Corre un cuadro (avanza `dt` segundos). */
  function cuadro(dt = 0.016): void {
    tiempo += dt * 1000;
    const pendientes = [...cola.entries()];
    cola.clear();
    for (const [, cb] of pendientes) cb(tiempo);
  }

  function crear(extra: Partial<Parameters<typeof EscenaTienda.crear>[0]> = {}): EscenaTienda {
    escena = EscenaTienda.crear({
      canvas,
      reducirMovimiento: true,
      alElegirTienda,
      perfil: { pixelRatioMax: 1.5, particulas: 260 },
      crearRenderer: crearRendererFalso,
      fabricas: FABRICAS_FALSAS,
      ...extra,
    });
    return escena;
  }

  const renderer = () => falsos.renderers.at(-1)!;
  const contexto = (k: string) => falsos.contextos[k];
  const hero = () => escena!['hero'] as unknown as Parada;
  const camara = () => escena!['camera'] as THREE.PerspectiveCamera;

  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    original.colorGestion = THREE.ColorManagement.enabled;
    THREE.ColorManagement.enabled = true;
    falsos.renderers.length = 0;
    falsos.paradas = {};
    canvas = document.createElement('canvas');
    document.body.appendChild(canvas);
    alElegirTienda = vi.fn<(codigo: string) => void>();
    cola = new Map();
    siguienteId = 1;
    tiempo = 1000;
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      const id = siguienteId++;
      cola.set(id, cb);
      return id;
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => cola.delete(id));
    ventana(1280, 720);
    escena = null;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    escena?.destruir();
    canvas.remove();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    ventana(original.innerWidth, original.innerHeight, original.scrollY);
    THREE.ColorManagement.enabled = original.colorGestion;
  });

  it('configura el renderer como en r128: sin gestión de color y salida lineal', () => {
    crear();
    expect(THREE.ColorManagement.enabled).toBe(false);
    expect(renderer().outputColorSpace).toBe(THREE.LinearSRGBColorSpace);
    expect(renderer().setPixelRatio).toHaveBeenCalledWith(1);
    expect(renderer().setSize).toHaveBeenCalledWith(1280, 720, false);
    escena!.destruir();
    expect(THREE.ColorManagement.enabled).toBe(true);
  });

  it('tope de densidad de píxeles según el perfil', () => {
    vi.stubGlobal('devicePixelRatio', 3);
    crear({ perfil: { pixelRatioMax: 1.5, particulas: 260 } });
    expect(renderer().setPixelRatio).toHaveBeenCalledWith(1.5);
  });

  it('compensa la luz de r155 (π veces más débil) y usa solo colores de la paleta', () => {
    crear();
    const luces = escena!['scene'].children.filter((o): o is THREE.Light => (o as THREE.Light).isLight);
    expect(luces.map((l) => l.intensity)).toEqual([1.05 * Math.PI, 1.05 * Math.PI, 0.9 * Math.PI]);
    expect((escena!['scene'].background as THREE.Color).getHexString()).toBe('1b1916');
  });

  it('crea seis paradas, cada una en su z y con los datos vigentes, y la polera compartida', () => {
    crear();
    const ctx = falsos.contextos['caja'];
    expect(ctx.z).toBe(-36);
    expect((falsos.contextos['calle']).z).toBe(-180);
    expect(hero().grupo.position.z).toBe(0);
    const a = ctx.crearPolera();
    const b = ctx.crearPolera();
    expect(a).not.toBe(b);
    expect((a.children[0] as THREE.Mesh).geometry).toBe((b.children[0] as THREE.Mesh).geometry);
    expect(falsos.paradas['caja'].fijarDatos).toHaveBeenCalledWith({ planes: [], tiendas: [] });
  });

  it('el clic en un local de la calle llega a alElegirTienda', () => {
    crear();
    (falsos.contextos['calle']).alElegirTienda('boutique-andina');
    expect(alElegirTienda).toHaveBeenCalledWith('boutique-andina');
  });

  it('fijarDatos reenvía a las paradas y vuelve a acomodar (escalaAncha puede cambiar con los datos)', () => {
    crear();
    const caja = falsos.paradas['caja'];
    expect(caja.grupo.position.y).toBeCloseTo(2.6 * 0.15, 10);
    expect(caja.grupo.scale.x).toBeCloseTo(1.15, 10);
    caja.escalaAncha = 1.4;
    const datos = { planes: [{ codigo: 'basico', nombre: 'Básico', sucursales: 2 }], tiendas: [] };
    escena!.fijarDatos(datos);
    expect(caja.fijarDatos).toHaveBeenLastCalledWith(datos);
    expect(caja.grupo.position.y).toBeCloseTo(2.6 * 0.4, 10);
    expect(caja.grupo.scale.x).toBeCloseTo(1.4, 10);
  });

  it('ancho: x propia, y = 2,6*(escala-1); angosto: centrado, yAngosta y escalaAngosta; reacciona al tamaño', () => {
    crear();
    expect(hero().grupo.position.x).toBe(2.4);
    expect(hero().grupo.position.y).toBeCloseTo(0, 10);
    expect(falsos.paradas['caja'].grupo.position.x).toBe(-2.8);
    ventana(400, 800);
    window.dispatchEvent(new Event('resize'));
    expect(hero().grupo.position.x).toBe(0);
    expect(hero().grupo.position.y).toBe(1.5);
    expect(hero().grupo.scale.x).toBeCloseTo(0.7, 10);
    expect(falsos.paradas['caja'].grupo.position.x).toBe(0);
    expect(renderer().setSize).toHaveBeenLastCalledWith(400, 800, false);
    ventana(1280, 720);
    window.dispatchEvent(new Event('resize'));
    expect(hero().grupo.position.x).toBe(2.4);
  });

  it('cada cuadro: progreso según el scroll, cámara sobre la curva y paradas con el estado', () => {
    crear();
    cuadro();
    expect(camara().position.z).toBeCloseTo(9.5, 5);
    const estadoInicial = falsos.paradas['caja'].actualizar.mock.calls.at(-1)![0];
    expect(estadoInicial.progreso).toBe(0);
    expect(estadoInicial.reducirMovimiento).toBe(true);

    ventana(1280, 720, 5 * 720); // fin del recorrido; sin movimiento reducido el progreso salta de una
    cuadro();
    const estado = falsos.paradas['calle'].actualizar.mock.calls.at(-1)![0];
    expect(estado.progreso).toBe(1);
    expect(estado.dt).toBeLessThanOrEqual(0.05);
    expect(camara().position.z).toBeCloseTo(-169.5, 5);
    expect(renderer().render).toHaveBeenCalled();
  });

  it('con movimiento normal el progreso se acerca poco a poco al del scroll', () => {
    crear({ reducirMovimiento: false });
    cuadro();
    ventana(1280, 720, 5 * 720);
    cuadro();
    const p1 = falsos.paradas['caja'].actualizar.mock.calls.at(-1)![0].progreso;
    expect(p1).toBeGreaterThan(0);
    expect(p1).toBeLessThan(1);
    for (let i = 0; i < 120; i++) cuadro();
    expect(falsos.paradas['caja'].actualizar.mock.calls.at(-1)![0].progreso).toBeGreaterThan(0.99);
  });

  it('no dibuja pasada la escena ni con la pestaña oculta', () => {
    crear({ tramosVh: 6 });
    cuadro();
    const dibujos = renderer().render.mock.calls.length;
    expect(dibujos).toBe(1);
    ventana(1280, 720, 6.1 * 720);
    cuadro();
    expect(renderer().render.mock.calls.length).toBe(dibujos);
    ventana(1280, 720, 0);
    cuadro();
    expect(renderer().render.mock.calls.length).toBe(dibujos + 1);
    const oculto = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    cuadro();
    expect(renderer().render.mock.calls.length).toBe(dibujos + 1);
    oculto.mockRestore();
  });

  it('arrastrar con el puntero gira la polera del inicio solo cerca del inicio', () => {
    crear();
    cuadro();
    const polera = hero().grupo.children.find((o) => o.children.length >= 7)!;
    canvas.dispatchEvent(new MouseEvent('pointerdown', { clientX: 100 }));
    canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: 140 }));
    cuadro();
    expect(polera.rotation.y).toBeCloseTo(40 * 0.012, 5);
    expect(canvas.style.cursor).toBe('grabbing');
    canvas.dispatchEvent(new MouseEvent('pointerup'));
    cuadro();
    expect(polera.rotation.y).toBeGreaterThan(40 * 0.012); // inercia
    expect(canvas.style.cursor).toBe('grab');

    // Lejos del inicio el arrastre no hace nada.
    ventana(1280, 720, 2 * 720);
    for (let i = 0; i < 400; i++) cuadro(0.05); // la inercia se agota
    const antes = polera.rotation.y;
    canvas.dispatchEvent(new MouseEvent('pointerdown', { clientX: 100 }));
    canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: 300 }));
    cuadro();
    expect(polera.rotation.y).toBeCloseTo(antes, 4);
    expect(canvas.style.cursor).toBe('default');
  });

  it('raycast sobre parada.interactivo: alPasar al entrar y salir, alClic con el objeto, cursor "pointer"', () => {
    crear();
    const calle = falsos.paradas['calle'];
    const local = new THREE.Mesh(new THREE.BoxGeometry(4, 4, 4), new THREE.MeshBasicMaterial());
    local.position.set(0.2, 0, 0); // justo donde mira la cámara al inicio
    escena!['scene'].add(local);
    const alPasar = vi.fn();
    const alClic = vi.fn();
    calle.interactivo = { objetos: [local], alPasar, alClic, desdeProgreso: 0.85 };

    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 640, clientY: 360 }));
    cuadro();
    expect(alPasar).not.toHaveBeenCalled(); // progreso 0 < desdeProgreso

    calle.interactivo.desdeProgreso = -1;
    cuadro();
    expect(alPasar).toHaveBeenCalledTimes(1);
    expect(alPasar).toHaveBeenLastCalledWith(local);
    expect(canvas.style.cursor).toBe('pointer');
    cuadro();
    expect(alPasar).toHaveBeenCalledTimes(1); // sin cambio, sin aviso repetido

    canvas.dispatchEvent(new MouseEvent('click', { clientX: 640, clientY: 360 }));
    expect(alClic).toHaveBeenCalledWith(local);

    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 5, clientY: 5 }));
    cuadro();
    expect(alPasar).toHaveBeenLastCalledWith(null);
    expect(canvas.style.cursor).toBe('grab');
  });

  it('fijarMarca: la primera vez es inmediata; las siguientes redibujan tras ~450 ms y se limpian', () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    crear();
    const caja = falsos.paradas['caja'];
    escena!.fijarMarca({ nombre: 'Chaski', tela: '#9A3E1F', acento: '#E27B55' });
    expect(escena!['ayudas'].acento.getHexString()).toBe('e27b55');
    expect(caja.redibujar).toHaveBeenCalledTimes(1);

    escena!.fijarMarca({ nombre: 'Chaski', tela: '#1F5F73', acento: '#58B0CC' });
    expect(escena!['ayudas'].acentoMeta.getHexString()).toBe('58b0cc');
    expect(escena!['ayudas'].acento.getHexString()).toBe('e27b55'); // se acerca con el tiempo
    vi.advanceTimersByTime(RETRASO_REDIBUJO_MS - 1);
    expect(caja.redibujar).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(caja.redibujar).toHaveBeenCalledTimes(2);

    escena!.fijarMarca({ nombre: 'Otra', tela: '#7A2638', acento: '#E0607A' });
    expect(vi.getTimerCount()).toBe(1);
    escena!.destruir();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('destruir cancela el bucle, quita las escuchas y libera la escena y el contexto', () => {
    const wRemove = vi.spyOn(window, 'removeEventListener');
    const dRemove = vi.spyOn(document, 'removeEventListener');
    const cRemove = vi.spyOn(canvas, 'removeEventListener');
    const quitadas = (): string[] => [wRemove, dRemove, cRemove].flatMap((e) => e.mock.calls.map((c) => c[0]));
    try {
      crear();
      const geo = (escena!['scene'].children.find((o) => (o as THREE.Mesh).isMesh) as THREE.Mesh).geometry;
      const alLiberar = vi.fn();
      geo.addEventListener('dispose', alLiberar);
      const dispAyudas = vi.spyOn(escena!['ayudas'], 'dispose');
      const dispPolera = vi.spyOn(escena!['polera'], 'dispose');
      expect(cola.size).toBe(1);

      escena!.destruir();
      expect(cola.size).toBe(0);
      expect(alLiberar).toHaveBeenCalled();
      expect(dispAyudas).toHaveBeenCalled();
      expect(dispPolera).toHaveBeenCalled();
      expect(renderer().dispose).toHaveBeenCalled();
      expect(renderer().forceContextLoss).toHaveBeenCalled();
      expect(escena!['scene'].children.length).toBe(0);
      expect(quitadas()).toEqual(
        expect.arrayContaining([
          'resize',
          'visibilitychange',
          'pointermove',
          'pointerdown',
          'pointerup',
          'pointercancel',
          'click',
        ]),
      );
      // Repetir destruir() o usar la escena después no hace nada.
      expect(() => {
        escena!.destruir();
        escena!.fijarDatos({ planes: [], tiendas: [] });
        escena!.redimensionar();
      }).not.toThrow();
    } finally {
      wRemove.mockRestore();
      dRemove.mockRestore();
      cRemove.mockRestore();
    }
  });

  it('el cambio de visibilidad detiene y reanuda el bucle', () => {
    crear();
    expect(cola.size).toBe(1);
    const oculto = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    document.dispatchEvent(new Event('visibilitychange'));
    expect(cola.size).toBe(0);
    oculto.mockReturnValue(false);
    document.dispatchEvent(new Event('visibilitychange'));
    expect(cola.size).toBe(1);
    oculto.mockRestore();
  });
});
