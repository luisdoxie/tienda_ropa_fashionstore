import * as THREE from 'three';
import { Ayudas } from '../ayudas';
import type { ContextoParada, Paleta, TiendaEscena } from '../contrato';
import { MAX_LOCALES, crearParadaCalle } from './parada-calle';

const PALETA: Paleta = {
  carbon: '#1b1916',
  profundo: '#121110',
  panel: '#232019',
  borde: '#2f2c27',
  texto: '#f2f2f0',
  tenue: '#b5b2aa',
  acento: '#8fae5b',
  sobreAcento: '#121110',
};

const TIENDAS: TiendaEscena[] = [
  { codigo: 'fashionstore', nombre: 'FashionStore', acento: '#8fae5b' },
  { codigo: 'boutique-andina', nombre: 'Boutique Andina', acento: '#e27b55' },
  { codigo: 'urbano-sur', nombre: 'Urbano Sur', acento: null },
  { codigo: 'casa-lino', nombre: 'Casa Lino', acento: '#e5b94f' },
  { codigo: 'altiplano-wear', nombre: 'Altiplano Wear', acento: '#e0607a' },
  { codigo: 'nube-moda', nombre: 'Nube Moda', acento: '#b9a6e8' },
];

function crear(tiendas: readonly TiendaEscena[]) {
  const scene = new THREE.Scene();
  const ayudas = new Ayudas();
  const alElegirTienda = vi.fn();
  const ctx: ContextoParada = {
    ayudas,
    scene,
    paleta: PALETA,
    crearPolera: () => new THREE.Group(),
    z: -180,
    datos: { planes: [], tiendas },
    alElegirTienda,
  };
  const parada = crearParadaCalle(ctx);
  return { parada, ayudas, scene, alElegirTienda };
}

function locales(raiz: THREE.Object3D): THREE.Object3D[] {
  const lista: THREE.Object3D[] = [];
  raiz.traverse((o) => {
    if (o.userData['local']) lista.push(o);
  });
  return lista;
}

function contar(raiz: THREE.Object3D): number {
  let n = 0;
  raiz.traverse(() => n++);
  return n;
}

function colorTirador(local: THREE.Object3D): string {
  let hex = '';
  local.traverse((o) => {
    if (o.userData['tirador']) hex = ((o as THREE.Mesh).material as THREE.MeshBasicMaterial).color.getHexString();
  });
  return hex;
}

describe('crearParadaCalle', () => {
  beforeEach(() => {
    // jsdom no dibuja en canvas: getContext('2d') devuelve null (y avisa por consola).
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });

  afterEach(() => vi.restoreAllMocks());

  it('se ubica en la z de la parada, en x = 2,6 y a escala 0,8', () => {
    const { parada, scene } = crear(TIENDAS.slice(0, 2));
    expect(parada.grupo.position.z).toBe(-180);
    expect(parada.x).toBe(2.6);
    expect(parada.escalaAncha).toBe(0.8);
    expect(scene.children).toContain(parada.grupo);
  });

  it('sin tiendas muestra solo la acera', () => {
    const { parada } = crear([]);
    expect(locales(parada.grupo).length).toBe(0);
    expect(parada.interactivo?.objetos.length).toBe(0);
    // La acera y su borde siguen ahí.
    expect(contar(parada.grupo)).toBeGreaterThan(2);
    expect(() => parada.actualizar({ t: 0, dt: 0.016, progreso: 1, reducirMovimiento: false })).not.toThrow();
  });

  it('con dos tiendas dibuja dos locales centrados', () => {
    const { parada } = crear(TIENDAS.slice(0, 2));
    const lista = locales(parada.grupo);
    expect(lista.length).toBe(2);
    expect(lista[0].position.x + lista[1].position.x).toBeCloseTo(0, 5);
    expect(lista[1].position.x - lista[0].position.x).toBeCloseTo(2.6, 5);
  });

  it('con cinco o más tiendas dibuja solo cinco locales', () => {
    const cinco = crear(TIENDAS.slice(0, 5));
    expect(locales(cinco.parada.grupo).length).toBe(5);
    const seis = crear(TIENDAS);
    expect(locales(seis.parada.grupo).length).toBe(MAX_LOCALES);
    expect(seis.parada.interactivo?.objetos.length).toBe(MAX_LOCALES);
  });

  it('cada local usa el color de su tienda y, si no tiene, el acento de la paleta', () => {
    const { parada } = crear(TIENDAS.slice(0, 3));
    const lista = locales(parada.grupo);
    expect(colorTirador(lista[0])).toBe('8fae5b');
    expect(colorTirador(lista[1])).toBe('e27b55');
    expect(colorTirador(lista[2])).toBe('8fae5b');
  });

  it('el clic en un local avisa el código de su tienda (también si cae en un hijo)', () => {
    const { parada, alElegirTienda } = crear(TIENDAS.slice(0, 3));
    const objetos = parada.interactivo!.objetos;
    parada.interactivo!.alClic(objetos[1]);
    expect(alElegirTienda).toHaveBeenLastCalledWith('boutique-andina');

    parada.interactivo!.alClic(objetos[2].children[0]);
    expect(alElegirTienda).toHaveBeenLastCalledWith('urbano-sur');
    expect(alElegirTienda).toHaveBeenCalledTimes(2);
  });

  it('el clic fuera de un local no hace nada', () => {
    const { parada, alElegirTienda } = crear(TIENDAS.slice(0, 2));
    parada.interactivo!.alClic(new THREE.Object3D());
    expect(alElegirTienda).not.toHaveBeenCalled();
  });

  it('el local bajo el mouse se levanta y se enciende; al salir vuelve', () => {
    const { parada } = crear(TIENDAS.slice(0, 3));
    const objetos = parada.interactivo!.objetos;
    parada.interactivo!.alPasar(objetos[1]);
    parada.actualizar({ t: 1, dt: 0.5, progreso: 1, reducirMovimiento: false });
    expect(objetos[1].position.y).toBeCloseTo(0.14, 5);
    expect(objetos[0].position.y).toBe(0);

    parada.interactivo!.alPasar(null);
    parada.actualizar({ t: 2, dt: 0.5, progreso: 1, reducirMovimiento: false });
    expect(objetos[1].position.y).toBeCloseTo(0, 5);
  });

  it('el motor solo evalúa el rayo desde 0,85 y por debajo el hover se apaga', () => {
    const { parada } = crear(TIENDAS.slice(0, 2));
    expect(parada.interactivo!.desdeProgreso).toBe(0.85);
    const objetos = parada.interactivo!.objetos;
    parada.interactivo!.alPasar(objetos[0]);
    parada.actualizar({ t: 1, dt: 0.5, progreso: 0.5, reducirMovimiento: false });
    expect(objetos[0].position.y).toBe(0);
  });

  it('actualizar no lanza con ningún progreso, con y sin reducirMovimiento', () => {
    const { parada } = crear(TIENDAS.slice(0, 5));
    parada.interactivo!.alPasar(parada.interactivo!.objetos[0]);
    for (const reducirMovimiento of [false, true]) {
      for (let p = 0; p <= 1.0001; p += 0.05) {
        expect(() => parada.actualizar({ t: p, dt: 0.016, progreso: Math.min(1, p), reducirMovimiento })).not.toThrow();
      }
    }
    // Con menos movimiento el cambio es inmediato.
    parada.interactivo!.alPasar(parada.interactivo!.objetos[0]);
    parada.actualizar({ t: 3, dt: 0.001, progreso: 1, reducirMovimiento: true });
    expect(parada.interactivo!.objetos[0].position.y).toBeCloseTo(0.14, 5);
  });

  it('fijarDatos repetido no acumula objetos y reconstruye con los datos nuevos', () => {
    const { parada, scene } = crear(TIENDAS.slice(0, 4));
    const inicial = contar(parada.grupo);
    const hijosEscena = scene.children.length;

    for (let i = 0; i < 4; i++) parada.fijarDatos?.({ planes: [], tiendas: TIENDAS.slice(0, 4) });
    expect(contar(parada.grupo)).toBe(inicial);
    expect(scene.children.length).toBe(hijosEscena);

    parada.fijarDatos?.({ planes: [], tiendas: TIENDAS.slice(0, 1) });
    expect(locales(parada.grupo).length).toBe(1);
    expect(parada.interactivo!.objetos.length).toBe(1);

    parada.fijarDatos?.({ planes: [], tiendas: [] });
    expect(locales(parada.grupo).length).toBe(0);
    expect(parada.interactivo!.objetos.length).toBe(0);
  });

  it('un clic después de fijarDatos usa las tiendas nuevas', () => {
    const { parada, alElegirTienda } = crear(TIENDAS.slice(0, 2));
    parada.fijarDatos?.({ planes: [], tiendas: [TIENDAS[5]] });
    parada.interactivo!.alClic(parada.interactivo!.objetos[0]);
    expect(alElegirTienda).toHaveBeenCalledWith('nube-moda');
  });

  it('redibujar no acumula objetos ni lanza (sin contexto 2D)', () => {
    const { parada } = crear(TIENDAS.slice(0, 3));
    const inicial = contar(parada.grupo);
    expect(() => parada.redibujar?.()).not.toThrow();
    expect(contar(parada.grupo)).toBe(inicial);
  });
});
