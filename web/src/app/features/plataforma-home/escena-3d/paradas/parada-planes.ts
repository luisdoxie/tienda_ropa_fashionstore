import * as THREE from 'three';
import type { DatosEscena, EstadoCuadro, FabricaParada, PlanEscena } from '../contrato';
import { liberarContenido } from './liberar-contenido';

/** Planes que dibuja la parada (de menor a mayor). */
export const MAX_PLANES_ESCENA = 5;
/** Un cubo por sucursal, hasta este tope por plataforma (la etiqueta dice siempre el número real). */
export const MAX_CUBOS_POR_PLATAFORMA = 12;

const HUESO = 0xd8d3c6;
const OSCURO = 0x26221c;
/** Borde de la plataforma más allá del radio de la tapa. */
const BORDE = 0.2;
/** Aire entre una plataforma y la siguiente. */
const SEPARACION = 1.2;
/** Aire alrededor del conjunto (etiquetas, halo) al calcular la escala. */
const MARGEN = 2;
/** Altura de la tapa de las plataformas. */
const Y_TAPA = -2.3;

function suave(a: number, b: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
}

/** El radio crece con las sucursales (2 → 1,9; 5 → 2,5; 10 → 3,1 aprox.), siempre entre 1,7 y 3,4. */
export function radioPlataforma(sucursales: number): number {
  const r = 1.45 + 0.65 * Math.log(Math.max(1, sucursales));
  return Math.min(3.4, Math.max(1.7, r));
}

/** De menor a mayor número de sucursales (estable) y a lo sumo cinco. */
function ordenar(planes: readonly PlanEscena[]): PlanEscena[] {
  return planes
    .map((plan, i) => ({ plan, i }))
    .sort((a, b) => a.plan.sucursales - b.plan.sucursales || a.i - b.i)
    .slice(0, MAX_PLANES_ESCENA)
    .map((e) => e.plan);
}

function textoSucursales(plan: PlanEscena): string {
  const n = Math.max(0, Math.floor(plan.sucursales));
  const base = `${n} ${n === 1 ? 'sucursal' : 'sucursales'}`;
  return n > MAX_CUBOS_POR_PLATAFORMA ? `${base} +${n - MAX_CUBOS_POR_PLATAFORMA}` : base;
}

interface Cubo {
  malla: THREE.Mesh;
  y: number;
  orden: number;
}

interface Mezcla {
  material: THREE.MeshStandardMaterial;
  /** 0 = acento puro, 1 = hueso puro. */
  hueso: number;
}

/**
 * Parada 4 · Planes: una plataforma por plan (de 1 a 5), con un cubo por sucursal. Se reconstruye
 * cada vez que cambian los planes (`fijarDatos`).
 */
export const crearParadaPlanes: FabricaParada = (ctx) => {
  const { ayudas, paleta } = ctx;
  const grupo = new THREE.Group();
  grupo.position.z = ctx.z;
  ctx.scene.add(grupo);

  const propias = new Set<THREE.Texture>();
  const colorHueso = new THREE.Color(HUESO);
  let datos: DatosEscena = ctx.datos;
  let contenido: THREE.Group | null = null;
  let cubos: Cubo[] = [];
  let mezclas: Mezcla[] = [];
  let pasoAparicion = 0.12;
  let anchoTotal = 0;
  let ultimo = { progreso: 0, reducirMovimiento: false };

  function aplicar(): void {
    for (const m of mezclas) m.material.color.copy(ayudas.acento).lerp(colorHueso, m.hueso);
    const aparece = ultimo.reducirMovimiento ? 1 : suave(0.6, 0.8, ultimo.progreso);
    for (const cubo of cubos) {
      let s = 1;
      if (!ultimo.reducirMovimiento) {
        s = Math.min(1, Math.max(0, aparece * 3.6 - cubo.orden * pasoAparicion));
        s = s * s * (3 - 2 * s);
      }
      cubo.malla.scale.setScalar(Math.max(0.001, s));
      cubo.malla.position.y = cubo.y - (1 - s) * 0.6;
    }
  }

  function reconstruir(): void {
    if (contenido) liberarContenido(contenido, ayudas, propias);
    cubos = [];
    mezclas = [];
    contenido = new THREE.Group();
    grupo.add(contenido);

    const planes = ordenar(datos.planes);
    const radios = planes.map((p) => radioPlataforma(p.sucursales));
    const anchos = radios.map((r) => 2 * (r + BORDE));
    const total = anchos.reduce((suma, a) => suma + a, 0) + SEPARACION * Math.max(0, planes.length - 1);
    anchoTotal = total + MARGEN;

    const oscuro = ayudas.liso(OSCURO);
    const totalCubos = planes.reduce((n, p) => n + cubosDe(p), 0);
    // Que el último cubo empiece a aparecer a tiempo aunque haya muchos.
    pasoAparicion = Math.min(0.12, 2.4 / Math.max(1, totalCubos - 1));

    let borde = -total / 2;
    let orden = 0;
    planes.forEach((plan, i) => {
      const r = radios[i];
      const x = borde + anchos[i] / 2;
      borde += anchos[i] + SEPARACION;

      const plataforma = new THREE.Group();
      plataforma.userData = { plataforma: true, codigo: plan.codigo, radio: r };
      plataforma.position.x = x;
      contenido!.add(plataforma);

      const base = new THREE.Mesh(new THREE.CylinderGeometry(r, r + BORDE, 0.3, 64), oscuro);
      base.position.y = -2.45;
      plataforma.add(base);
      const aro = new THREE.Mesh(
        new THREE.RingGeometry(r - 0.12, r - 0.06, 64),
        ayudas.basico({ side: THREE.DoubleSide }),
      );
      aro.rotation.x = -Math.PI / 2;
      aro.position.y = -2.29;
      plataforma.add(aro);
      ayudas.sombra(r * 2.6, r * 2.6, 0, 0, 0.8, plataforma);

      // Material: el plan más chico en hueso, el más grande en acento, los demás mezclados.
      let material: THREE.MeshStandardMaterial;
      if (i === planes.length - 1) material = ayudas.lisoAcento();
      else if (i === 0) material = ayudas.liso(HUESO);
      else {
        const hueso = 0.9 * (1 - i / (planes.length - 1));
        material = new THREE.MeshStandardMaterial({ color: ayudas.acento.clone(), roughness: 0.6, metalness: 0.12 });
        mezclas.push({ material, hueso });
      }

      const n = cubosDe(plan);
      const tam = n <= 3 ? 0.9 : 0.7;
      const paso = tam + 0.1;
      const columnas = n <= 6 ? Math.max(1, n) : Math.ceil(n / 2);
      const filas = Math.ceil(n / columnas);
      const y = Y_TAPA + 0.16 + tam / 2;
      for (let k = 0; k < n; k++) {
        const fila = Math.floor(k / columnas);
        const enFila = Math.min(columnas, n - fila * columnas);
        const cx = ((k % columnas) - (enFila - 1) / 2) * paso;
        const cz = (fila - (filas - 1) / 2) * paso;
        const malla = ayudas.cajaR(tam, tam, tam, tam * 0.145, material, cx, y, cz, plataforma);
        malla.userData = { cubo: true };
        cubos.push({ malla, y, orden: orden++ });
      }

      const etiqueta = ayudas.etiqueta(plan.nombre.toUpperCase(), textoSucursales(plan), paleta.tenue, paleta.texto);
      etiqueta.position.set(0, -0.45, 0);
      etiqueta.userData = { etiqueta: true, nombre: plan.nombre.toUpperCase(), texto: textoSucursales(plan) };
      if (etiqueta.material.map) propias.add(etiqueta.material.map);
      plataforma.add(etiqueta);
    });
    aplicar();
  }

  function cubosDe(plan: PlanEscena): number {
    return Math.min(MAX_CUBOS_POR_PLATAFORMA, Math.max(0, Math.floor(plan.sucursales)));
  }

  reconstruir();

  return {
    grupo,
    x: 0,
    get escalaAncha(): number {
      return Math.min(0.9, 15 / anchoTotal);
    },
    get escalaAngosta(): number {
      return Math.min(0.7, 9.3 / anchoTotal);
    },
    yAngosta: 0.4,
    actualizar(estado: EstadoCuadro): void {
      ultimo = { progreso: estado.progreso, reducirMovimiento: estado.reducirMovimiento };
      aplicar();
    },
    fijarDatos(nuevos: DatosEscena): void {
      datos = nuevos;
      reconstruir();
    },
    // Las etiquetas dependen de las fuentes: se vuelven a dibujar con el resto.
    redibujar: reconstruir,
  };
};
