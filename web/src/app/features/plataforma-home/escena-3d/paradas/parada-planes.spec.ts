import * as THREE from 'three';
import { Ayudas } from '../ayudas';
import type { ContextoParada, DatosEscena, Paleta, PlanEscena } from '../contrato';
import { MAX_CUBOS_POR_PLATAFORMA, crearParadaPlanes, radioPlataforma } from './parada-planes';

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

const BASICO: PlanEscena = { codigo: 'basico', nombre: 'Básico', sucursales: 2 };
const ESTANDAR: PlanEscena = { codigo: 'estandar', nombre: 'Estándar', sucursales: 5 };
const PROFESIONAL: PlanEscena = { codigo: 'profesional', nombre: 'Profesional', sucursales: 10 };

function crear(planes: readonly PlanEscena[]) {
  const scene = new THREE.Scene();
  const ayudas = new Ayudas();
  const datos: DatosEscena = { planes, tiendas: [] };
  const ctx: ContextoParada = {
    ayudas,
    scene,
    paleta: PALETA,
    crearPolera: () => new THREE.Group(),
    z: -144,
    datos,
    alElegirTienda: vi.fn(),
  };
  const parada = crearParadaPlanes(ctx);
  return { parada, ayudas, scene, ctx };
}

function plataformas(grupo: THREE.Object3D): THREE.Object3D[] {
  const lista: THREE.Object3D[] = [];
  grupo.traverse((o) => {
    if (o.userData['plataforma']) lista.push(o);
  });
  return lista;
}

function cubosDe(raiz: THREE.Object3D): THREE.Mesh[] {
  const lista: THREE.Mesh[] = [];
  raiz.traverse((o) => {
    if (o.userData['cubo']) lista.push(o as THREE.Mesh);
  });
  return lista;
}

function contar(raiz: THREE.Object3D): number {
  let n = 0;
  raiz.traverse(() => n++);
  return n;
}

function etiquetaDe(plataforma: THREE.Object3D): { nombre: string; texto: string } {
  const e = plataforma.children.find((c) => c.userData['etiqueta']);
  return e?.userData as { nombre: string; texto: string };
}

describe('crearParadaPlanes', () => {
  beforeEach(() => {
    // jsdom no dibuja en canvas: getContext('2d') devuelve null (y avisa por consola).
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });

  afterEach(() => vi.restoreAllMocks());

  it('se ubica en la z de la parada y en x = 0', () => {
    const { parada, scene } = crear([BASICO]);
    expect(parada.grupo.position.z).toBe(-144);
    expect(parada.x).toBe(0);
    expect(scene.children).toContain(parada.grupo);
  });

  it('con un plan dibuja una plataforma y un cubo por sucursal', () => {
    const { parada } = crear([{ codigo: 'unico', nombre: 'Único', sucursales: 4 }]);
    const lista = plataformas(parada.grupo);
    expect(lista.length).toBe(1);
    expect(cubosDe(lista[0]).length).toBe(4);
    expect(etiquetaDe(lista[0])).toMatchObject({ nombre: 'ÚNICO', texto: '4 sucursales' });
    expect(parada.escalaAncha).toBeCloseTo(0.9);
  });

  it('con tres planes los reparte centrados, del menor al mayor, y crece el radio', () => {
    const { parada } = crear([PROFESIONAL, BASICO, ESTANDAR]);
    const lista = plataformas(parada.grupo);
    expect(lista.map((p) => p.userData['codigo'])).toEqual(['basico', 'estandar', 'profesional']);
    expect(lista.map((p) => cubosDe(p).length)).toEqual([2, 5, 10]);
    const radios = lista.map((p) => p.userData['radio'] as number);
    expect(radios[0]).toBeLessThan(radios[1]);
    expect(radios[1]).toBeLessThan(radios[2]);
    // Centradas: el borde izquierdo y el derecho del conjunto están a la misma distancia del centro.
    const izquierdo = lista[0].position.x - (radios[0] + 0.2);
    const derecho = lista[2].position.x + radios[2] + 0.2;
    expect(izquierdo + derecho).toBeCloseTo(0, 5);
    expect(parada.escalaAncha).toBeCloseTo(0.72, 1);
    expect(parada.escalaAngosta).toBeCloseTo(0.45, 1);
    expect(etiquetaDe(lista[1]).texto).toBe('5 sucursales');
  });

  it('con cinco planes caben en pantalla (escala menor) y con más de cinco dibuja solo cinco', () => {
    const cinco = Array.from({ length: 5 }, (_, i) => ({ codigo: `p${i}`, nombre: `Plan ${i}`, sucursales: i + 1 }));
    const a = crear(cinco);
    expect(plataformas(a.parada.grupo).length).toBe(5);
    const tres = crear([BASICO, ESTANDAR, PROFESIONAL]);
    expect(a.parada.escalaAncha).toBeLessThan(tres.parada.escalaAncha);

    const seis = crear([...cinco, { codigo: 'p5', nombre: 'Plan 5', sucursales: 6 }]);
    expect(plataformas(seis.parada.grupo).length).toBe(5);
  });

  it('con más de 12 sucursales limita los cubos y la etiqueta dice el número real', () => {
    const { parada } = crear([BASICO, { codigo: 'grande', nombre: 'Grande', sucursales: 20 }]);
    const lista = plataformas(parada.grupo);
    expect(cubosDe(lista[1]).length).toBe(MAX_CUBOS_POR_PLATAFORMA);
    expect(etiquetaDe(lista[1]).texto).toBe('20 sucursales +8');
    expect(etiquetaDe(lista[0]).texto).toBe('2 sucursales');
  });

  it('el plan más chico va en hueso, el más grande en acento y el del medio mezclado', () => {
    const { parada, ayudas } = crear([BASICO, ESTANDAR, PROFESIONAL]);
    const [a, b, c] = plataformas(parada.grupo).map((p) => (cubosDe(p)[0].material as THREE.MeshStandardMaterial));
    expect(a.color.getHex()).toBe(0xd8d3c6);
    expect(c.color.getHex()).toBe(ayudas.acento.getHex());
    expect(b.color.getHex()).not.toBe(a.color.getHex());
    expect(b.color.getHex()).not.toBe(c.color.getHex());
  });

  it('la mezcla del plan intermedio sigue al acento en actualizar', () => {
    const { parada, ayudas } = crear([BASICO, ESTANDAR, PROFESIONAL]);
    const medio = cubosDe(plataformas(parada.grupo)[1])[0].material as THREE.MeshStandardMaterial;
    const antes = medio.color.getHex();

    ayudas.fijarAcento('#e27b55');
    ayudas.avanzarAcento(1);
    parada.actualizar({ t: 1, dt: 0.016, progreso: 0.9, reducirMovimiento: false });

    expect(medio.color.getHex()).not.toBe(antes);
    const esperado = ayudas.acento.clone().lerp(new THREE.Color(0xd8d3c6), 0.45);
    expect(medio.color.getHex()).toBe(esperado.getHex());
  });

  it('los cubos aparecen uno a uno con el scroll', () => {
    const { parada } = crear([BASICO, ESTANDAR, PROFESIONAL]);
    const todos = cubosDe(parada.grupo);
    parada.actualizar({ t: 0, dt: 0.016, progreso: 0, reducirMovimiento: false });
    expect(todos.every((c) => c.scale.x < 0.01)).toBe(true);

    parada.actualizar({ t: 1, dt: 0.016, progreso: 0.67, reducirMovimiento: false });
    const visibles = todos.filter((c) => c.scale.x > 0.5).length;
    expect(visibles).toBeGreaterThan(0);
    expect(visibles).toBeLessThan(todos.length);

    parada.actualizar({ t: 2, dt: 0.016, progreso: 1, reducirMovimiento: false });
    expect(todos.every((c) => c.scale.x === 1)).toBe(true);
  });

  it('con muchos cubos todos terminan visibles al final de la aparición', () => {
    const cinco = Array.from({ length: 5 }, (_, i) => ({ codigo: `p${i}`, nombre: `Plan ${i}`, sucursales: 20 + i }));
    const { parada } = crear(cinco);
    parada.actualizar({ t: 2, dt: 0.016, progreso: 0.85, reducirMovimiento: false });
    const todos = cubosDe(parada.grupo);
    expect(todos.length).toBe(60);
    expect(todos.every((c) => c.scale.x > 0.99)).toBe(true);
  });

  it('con reducirMovimiento los cubos aparecen de golpe', () => {
    const { parada } = crear([BASICO, ESTANDAR, PROFESIONAL]);
    parada.actualizar({ t: 0, dt: 0.016, progreso: 0, reducirMovimiento: true });
    expect(cubosDe(parada.grupo).every((c) => c.scale.x === 1)).toBe(true);
  });

  it('actualizar no lanza con ningún progreso', () => {
    const { parada } = crear([BASICO, ESTANDAR, PROFESIONAL]);
    for (const reducirMovimiento of [false, true]) {
      for (let p = 0; p <= 1.0001; p += 0.05) {
        expect(() => parada.actualizar({ t: p, dt: 0.016, progreso: Math.min(1, p), reducirMovimiento })).not.toThrow();
      }
    }
  });

  it('fijarDatos repetido no acumula objetos y refleja los datos nuevos', () => {
    const { parada, scene } = crear([BASICO, ESTANDAR, PROFESIONAL]);
    const inicial = contar(parada.grupo);
    const hijosEscena = scene.children.length;

    for (let i = 0; i < 4; i++) parada.fijarDatos?.({ planes: [BASICO, ESTANDAR, PROFESIONAL], tiendas: [] });
    expect(contar(parada.grupo)).toBe(inicial);
    expect(scene.children.length).toBe(hijosEscena);

    parada.fijarDatos?.({ planes: [BASICO], tiendas: [] });
    expect(plataformas(parada.grupo).length).toBe(1);
    expect(contar(parada.grupo)).toBeLessThan(inicial);

    parada.fijarDatos?.({ planes: [], tiendas: [] });
    expect(plataformas(parada.grupo).length).toBe(0);
    expect(() => parada.actualizar({ t: 0, dt: 0.016, progreso: 1, reducirMovimiento: false })).not.toThrow();
    expect(parada.escalaAncha).toBeGreaterThan(0);
  });

  it('redibujar reconstruye sin acumular objetos', () => {
    const { parada } = crear([BASICO, ESTANDAR]);
    const inicial = contar(parada.grupo);
    parada.redibujar?.();
    expect(contar(parada.grupo)).toBe(inicial);
  });

  it('el radio de la plataforma crece con las sucursales dentro de límites', () => {
    expect(radioPlataforma(1)).toBeGreaterThanOrEqual(1.7);
    expect(radioPlataforma(2)).toBeLessThan(radioPlataforma(10));
    expect(radioPlataforma(10_000)).toBeLessThanOrEqual(3.4);
  });
});
