import * as THREE from 'three';
import { Ayudas } from '../ayudas';
import type { ContextoParada, EstadoCuadro, FabricaParada, Paleta, Parada } from '../contrato';
import { crearParadaCaja } from './parada-caja';
import { crearParadaInventario } from './parada-inventario';
import { crearParadaProbador } from './parada-probador';

const PALETA: Paleta = {
  carbon: '#1B1916',
  profundo: '#121110',
  panel: '#232019',
  borde: '#2F2C27',
  texto: '#F2F2F0',
  tenue: '#B5B2AA',
  acento: '#8FAE5B',
  sobreAcento: '#151515',
};

function estado(parcial: Partial<EstadoCuadro> = {}): EstadoCuadro {
  return { t: 0, dt: 0.016, progreso: 0, reducirMovimiento: false, ...parcial };
}

interface Montaje {
  parada: Parada;
  scene: THREE.Scene;
  ayudas: Ayudas;
  contexto: ContextoParada;
}

function montar(fabrica: FabricaParada, z = -36): Montaje {
  const scene = new THREE.Scene();
  const ayudas = new Ayudas();
  const contexto: ContextoParada = {
    ayudas,
    scene,
    paleta: PALETA,
    crearPolera: () => new THREE.Group(),
    z,
    datos: { planes: [], tiendas: [] },
    alElegirTienda: () => undefined,
  };
  return { parada: fabrica(contexto), scene, ayudas, contexto };
}

/** Contexto 2d falso: acepta cualquier llamada y cuenta los `fillRect`. */
function simular2d(): { llamadas: { fillRect: number }; restaurar: () => void } {
  const llamadas = { fillRect: 0 };
  const falso: CanvasRenderingContext2D = new Proxy({} as CanvasRenderingContext2D, {
    get(_destino, propiedad) {
      if (propiedad === 'fillRect') {
        return () => {
          llamadas.fillRect++;
        };
      }
      if (propiedad === 'measureText') return () => ({ width: 10 });
      return () => falso;
    },
    set: () => true,
  });
  const espia = vi
    .spyOn(HTMLCanvasElement.prototype, 'getContext')
    .mockImplementation((() => falso) as unknown as typeof HTMLCanvasElement.prototype.getContext);
  return { llamadas, restaurar: () => espia.mockRestore() };
}

const FABRICAS: ReadonlyArray<{
  nombre: string;
  fabrica: FabricaParada;
  x: number;
  escalaAncha: number;
}> = [
  { nombre: 'caja', fabrica: crearParadaCaja, x: -2.8, escalaAncha: 1.15 },
  { nombre: 'inventario', fabrica: crearParadaInventario, x: 3, escalaAncha: 1.15 },
  { nombre: 'probador', fabrica: crearParadaProbador, x: -2.8, escalaAncha: 1.4 },
];

describe('paradas de caja, inventario y probador', () => {
  // jsdom no trae canvas 2d: lo dejamos en null (sin el aviso de "Not implemented") salvo en las pruebas que lo simulan
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });
  afterEach(() => vi.restoreAllMocks());

  for (const { nombre, fabrica, x, escalaAncha } of FABRICAS) {
    describe(nombre, () => {
      it('deja el grupo en z y en la escena, con su posición y escalas', () => {
        const { parada, scene } = montar(fabrica, -72);
        expect(parada.grupo.position.z).toBe(-72);
        expect(parada.grupo.parent).toBe(scene);
        expect(parada.x).toBe(x);
        expect(parada.escalaAncha).toBe(escalaAncha);
        expect(parada.escalaAngosta).toBe(0.7);
        expect(parada.yAngosta).toBe(1.5);
        expect(parada.grupo.children.length).toBeGreaterThan(5);
      });

      it('no deja objetos sin padre', () => {
        const { parada } = montar(fabrica);
        parada.grupo.traverse((objeto) => {
          if (objeto !== parada.grupo) expect(objeto.parent, objeto.type).not.toBeNull();
        });
      });

      it('actualizar no lanza con distintos progresos y con o sin reducirMovimiento', () => {
        const { parada } = montar(fabrica);
        for (const reducirMovimiento of [false, true]) {
          for (const progreso of [0, 0.2, 1]) {
            expect(() => parada.actualizar(estado({ t: 3.3, progreso, reducirMovimiento }))).not.toThrow();
          }
        }
      });

      it('redibujar no lanza sin contexto 2d ni con él', () => {
        const { parada } = montar(fabrica);
        expect(() => parada.redibujar?.()).not.toThrow();
        const falso = simular2d();
        expect(() => parada.redibujar?.()).not.toThrow();
        falso.restaurar();
      });
    });
  }

  describe('caja', () => {
    it('dibuja el panel al inicio y en redibujar', () => {
      const falso = simular2d();
      const { parada } = montar(crearParadaCaja);
      // Al crear: la sombra y el brillo (una vez) y el panel
      const alInicio = falso.llamadas.fillRect;
      expect(alInicio).toBeGreaterThan(0);
      parada.redibujar?.();
      const panel = falso.llamadas.fillRect - alInicio;
      expect(panel).toBeGreaterThan(0);
      parada.redibujar?.();
      expect(falso.llamadas.fillRect).toBe(alInicio + panel * 2);
    });

    it('redibuja cada 0,1 s solo cuando el scroll está cerca de la parada', () => {
      const falso = simular2d();
      const { parada } = montar(crearParadaCaja);
      const alInicio = falso.llamadas.fillRect;

      parada.actualizar(estado({ t: 5, progreso: 0 }));
      parada.actualizar(estado({ t: 5.2, progreso: 1 }));
      expect(falso.llamadas.fillRect).toBe(alInicio);

      parada.actualizar(estado({ t: 6, progreso: 0.2 }));
      const dibujo = falso.llamadas.fillRect - alInicio;
      expect(dibujo).toBeGreaterThan(0);

      parada.actualizar(estado({ t: 6.05, progreso: 0.2 }));
      expect(falso.llamadas.fillRect).toBe(alInicio + dibujo);

      parada.actualizar(estado({ t: 6.2, progreso: 0.2 }));
      expect(falso.llamadas.fillRect).toBe(alInicio + dibujo * 2);

      // A 0,21 de distancia ya no cuenta como cerca
      parada.actualizar(estado({ t: 7, progreso: 0.41 }));
      expect(falso.llamadas.fillRect).toBe(alInicio + dibujo * 2);
    });
  });

  describe('inventario', () => {
    function pines(parada: Parada): THREE.Group[] {
      return parada.grupo.children.filter((o): o is THREE.Group => o instanceof THREE.Group);
    }

    it('tiene tres marcadores de sucursal, cada uno con cono y esfera', () => {
      const { parada } = montar(crearParadaInventario);
      const marcadores = pines(parada);
      expect(marcadores).toHaveLength(3);
      for (const pin of marcadores) {
        expect(pin.children.map((h) => (h as THREE.Mesh).geometry.type).sort()).toEqual([
          'ConeGeometry',
          'SphereGeometry',
        ]);
      }
    });

    it('los marcadores oscilan y giran con t, y quedan quietos con reducirMovimiento', () => {
      const { parada } = montar(crearParadaInventario);
      const [primero] = pines(parada);

      parada.actualizar(estado({ t: 0.5 }));
      const y1 = primero.position.y;
      const giro1 = primero.rotation.y;
      parada.actualizar(estado({ t: 1.5 }));
      expect(primero.position.y).not.toBeCloseTo(y1, 5);
      expect(primero.rotation.y).not.toBeCloseTo(giro1, 5);

      parada.actualizar(estado({ t: 0.5, reducirMovimiento: true }));
      const quietoY = primero.position.y;
      const quietoGiro = primero.rotation.y;
      parada.actualizar(estado({ t: 9.7, reducirMovimiento: true }));
      expect(primero.position.y).toBe(quietoY);
      expect(primero.rotation.y).toBe(quietoGiro);
    });

    it('usa el mismo azar repetible en cada carga', () => {
      const alturas = (): number[] => {
        const { parada } = montar(crearParadaInventario);
        const hojas: number[] = [];
        parada.grupo.traverse((o) => {
          if (o instanceof THREE.Mesh && o.geometry.type === 'ExtrudeGeometry') hojas.push(o.position.y);
        });
        return hojas;
      };
      expect(alturas()).toEqual(alturas());
    });

    it('los marcadores siguen al acento', () => {
      const { parada, ayudas } = montar(crearParadaInventario);
      ayudas.fijarAcento('#E27B55');
      ayudas.avanzarAcento(1);
      const [primero] = pines(parada);
      const cono = primero.children[0] as THREE.Mesh;
      expect((cono.material as THREE.MeshBasicMaterial).color.getHexString()).toBe('e27b55');
    });
  });

  describe('probador', () => {
    function buscar<T extends THREE.Object3D>(parada: Parada, tipo: abstract new (...a: never[]) => T, geo?: string): T {
      let hallado: T | undefined;
      parada.grupo.traverse((o) => {
        if (!hallado && o instanceof tipo && (!geo || (o as unknown as THREE.Mesh).geometry?.type === geo)) hallado = o;
      });
      expect(hallado, geo ?? tipo.name).toBeDefined();
      return hallado!;
    }

    it('el escaneo sube y baja con t y se detiene con reducirMovimiento', () => {
      const { parada } = montar(crearParadaProbador);
      const anillo = buscar(parada, THREE.Mesh, 'TorusGeometry');
      const disco = buscar(parada, THREE.Mesh, 'CircleGeometry');
      const brillo = buscar(parada, THREE.Sprite);

      parada.actualizar(estado({ t: 0.4 }));
      const y1 = anillo.position.y;
      parada.actualizar(estado({ t: 1.9 }));
      expect(anillo.position.y).not.toBeCloseTo(y1, 5);
      expect(disco.position.y).toBe(anillo.position.y);
      expect(brillo.position.y).toBe(anillo.position.y);
      expect(anillo.position.y).toBeGreaterThanOrEqual(-1.0);
      expect(anillo.position.y).toBeLessThanOrEqual(1.3);

      parada.actualizar(estado({ t: 0.4, reducirMovimiento: true }));
      const quieto = anillo.position.y;
      parada.actualizar(estado({ t: 8.8, reducirMovimiento: true }));
      expect(anillo.position.y).toBe(quieto);
    });

    it('la polera (a escala 0,42) gira suave y el teléfono flota', () => {
      const poleras: THREE.Group[] = [];
      const scene = new THREE.Scene();
      const ayudas = new Ayudas();
      const parada = crearParadaProbador({
        ayudas,
        scene,
        paleta: PALETA,
        crearPolera: () => {
          const g = new THREE.Group();
          poleras.push(g);
          return g;
        },
        z: -108,
        datos: { planes: [], tiendas: [] },
        alElegirTienda: () => undefined,
      });
      expect(poleras).toHaveLength(1);
      expect(poleras[0].scale.x).toBeCloseTo(0.42);
      expect(poleras[0].parent).toBe(parada.grupo);

      parada.actualizar(estado({ t: 1.2 }));
      const giro = poleras[0].rotation.y;
      expect(Math.abs(giro)).toBeLessThanOrEqual(0.6);
      parada.actualizar(estado({ t: 2.4 }));
      expect(poleras[0].rotation.y).not.toBeCloseTo(giro, 5);

      parada.actualizar(estado({ t: 3, reducirMovimiento: true }));
      expect(poleras[0].rotation.y).toBe(0);
    });

    it('el teléfono se dibuja con el acento vigente y se redibuja en redibujar', () => {
      const falso = simular2d();
      const { parada } = montar(crearParadaProbador);
      const alInicio = falso.llamadas.fillRect;
      expect(alInicio).toBeGreaterThan(0);
      parada.redibujar?.();
      const telefono = falso.llamadas.fillRect - alInicio;
      expect(telefono).toBeGreaterThan(0);
      parada.redibujar?.();
      expect(falso.llamadas.fillRect).toBe(alInicio + telefono * 2);
    });
  });
});
