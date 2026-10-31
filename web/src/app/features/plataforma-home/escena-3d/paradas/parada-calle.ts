import * as THREE from 'three';
import type { DatosEscena, EstadoCuadro, FabricaParada, Interactivo, TiendaEscena } from '../contrato';
import { liberarContenido } from './liberar-contenido';

/** Locales que dibuja la calle. */
export const MAX_LOCALES = 5;

/** Separación entre los ejes de dos locales. */
const SEPARACION = 2.6;
/** Cuánto se levanta el local bajo el mouse. */
const ALZA = 0.14;

interface Local {
  grupo: THREE.Group;
  codigo: string;
  resplandor: THREE.Sprite;
  /** 0 = en el suelo, 1 = levantado y encendido. */
  alza: number;
  dibujar: () => void;
}

/**
 * Parada 5 · Calle de tiendas: un local por tienda (hasta cinco), cada uno con el nombre y el color de
 * su empresa. Se reconstruye cuando cambian las tiendas (`fijarDatos`). Sin tiendas, solo la acera.
 */
export const crearParadaCalle: FabricaParada = (ctx) => {
  const { ayudas, paleta } = ctx;
  const grupo = new THREE.Group();
  grupo.position.z = ctx.z;
  ctx.scene.add(grupo);

  const propias = new Set<THREE.Texture>();
  let datos: DatosEscena = ctx.datos;
  let contenido: THREE.Group | null = null;
  let locales: Local[] = [];
  let objetos: THREE.Object3D[] = [];
  let bajoElMouse: Local | null = null;

  // Colores de la escena derivados de los tokens (cuerpos apenas distintos entre sí).
  const colorCuerpo = (i: number): THREE.Color =>
    new THREE.Color(paleta.panel).lerp(new THREE.Color(paleta.borde), [0, 0.25, 0.1, 0.2, 0.05][i % 5]);

  function textura(lienzo: HTMLCanvasElement): THREE.CanvasTexture {
    const t = new THREE.CanvasTexture(lienzo);
    propias.add(t);
    return t;
  }

  function crearLocal(tienda: TiendaEscena, i: number, cantidad: number, padre: THREE.Object3D): Local {
    const acento = tienda.acento ?? paleta.acento;
    const nombre = tienda.nombre.toUpperCase();
    const s = new THREE.Group();
    s.position.set((i - (cantidad - 1) / 2) * SEPARACION, 0, 0);
    s.userData = { local: true, codigo: tienda.codigo };
    padre.add(s);

    ayudas.cajaR(2.3, 3.0, 2.2, 0.14, ayudas.liso(colorCuerpo(i)), 0, -1.1, -0.3, s);
    ayudas.cajaR(2.44, 0.2, 2.34, 0.07, ayudas.liso(paleta.borde), 0, 0.45, -0.3, s);

    // Letrero: siglas sobre el color de la tienda + nombre.
    const lLetrero = ayudas.lienzo(512, 128);
    const tLetrero = textura(lLetrero);
    const letrero = new THREE.Mesh(new THREE.PlaneGeometry(2.0, 0.5), new THREE.MeshBasicMaterial({ map: tLetrero }));
    letrero.position.set(0, 0.08, 0.82);
    s.add(letrero);

    // Escaparate con una polera del color de la tienda.
    const lVitrina = ayudas.lienzo(256, 340);
    const tVitrina = textura(lVitrina);
    const vitrina = new THREE.Mesh(new THREE.PlaneGeometry(1.2, 1.6), new THREE.MeshBasicMaterial({ map: tVitrina }));
    vitrina.position.set(-0.5, -1.55, 0.82);
    s.add(vitrina);

    // Puerta y tirador.
    ayudas.cajaR(0.62, 1.7, 0.08, 0.04, ayudas.liso(paleta.profundo), 0.62, -1.7, 0.84, s);
    const tirador = new THREE.Mesh(new THREE.SphereGeometry(0.04, 10, 8), new THREE.MeshBasicMaterial({ color: acento }));
    tirador.position.set(0.8, -1.7, 0.9);
    tirador.userData = { tirador: true };
    s.add(tirador);

    // Toldo a rayas.
    const lToldo = ayudas.lienzo(256, 64);
    const tToldo = textura(lToldo);
    const toldo = new THREE.Mesh(new THREE.BoxGeometry(2.3, 0.07, 0.95), new THREE.MeshLambertMaterial({ map: tToldo }));
    toldo.position.set(0, -0.45, 1.25);
    toldo.rotation.x = 0.32;
    s.add(toldo);

    // Resplandor del color de la tienda: no sigue al acento de la demo.
    const resplandor = ayudas.brillo(0, -1.2, 1.7, 3.6, 0, s);
    ayudas.desacentuar(resplandor.material);
    resplandor.material.color.set(acento);
    ayudas.sombra(2.9, 3.0, 0, 0.7, 0.8, s);

    const dibujar = (): void => {
      const g = lLetrero.getContext('2d');
      if (g) {
        g.fillStyle = paleta.profundo;
        g.fillRect(0, 0, 512, 128);
        g.strokeStyle = acento;
        g.lineWidth = 6;
        g.strokeRect(3, 3, 506, 122);
        g.fillStyle = acento;
        g.fillRect(22, 22, 84, 84);
        g.fillStyle = paleta.sobreAcento;
        g.textAlign = 'center';
        g.textBaseline = 'middle';
        g.font = '800 40px Archivo, Arial, sans-serif';
        g.fillText(ayudas.siglas(tienda.nombre), 64, 66);
        g.fillStyle = paleta.texto;
        g.textAlign = 'left';
        ayudas.ajustarTexto(g, nombre, '800 {t}px Archivo, Arial, sans-serif', 370, 40);
        g.fillText(nombre, 124, 66);
        tLetrero.needsUpdate = true;
      }

      const v = lVitrina.getContext('2d');
      if (v) {
        const degradado = v.createLinearGradient(0, 0, 0, 340);
        degradado.addColorStop(0, paleta.borde);
        degradado.addColorStop(1, paleta.carbon);
        v.fillStyle = degradado;
        v.fillRect(0, 0, 256, 340);
        v.fillStyle = 'rgba(255,255,255,.05)';
        v.beginPath();
        v.moveTo(0, 0);
        v.lineTo(110, 0);
        v.lineTo(0, 200);
        v.closePath();
        v.fill();
        v.fillStyle = acento;
        v.beginPath();
        v.moveTo(98, 100);
        v.lineTo(64, 116);
        v.lineTo(44, 168);
        v.lineTo(66, 178);
        v.lineTo(84, 166);
        v.lineTo(84, 270);
        v.lineTo(172, 270);
        v.lineTo(172, 166);
        v.lineTo(190, 178);
        v.lineTo(212, 168);
        v.lineTo(192, 116);
        v.lineTo(158, 100);
        v.quadraticCurveTo(128, 126, 98, 100);
        v.closePath();
        v.fill();
        v.strokeStyle = paleta.borde;
        v.lineWidth = 6;
        v.strokeRect(3, 3, 250, 334);
        tVitrina.needsUpdate = true;
      }

      const w = lToldo.getContext('2d');
      if (w) {
        for (let k = 0; k < 8; k++) {
          w.fillStyle = k % 2 ? paleta.texto : acento;
          w.fillRect(k * 32, 0, 32, 64);
        }
        tToldo.needsUpdate = true;
      }
    };
    dibujar();
    return { grupo: s, codigo: tienda.codigo, resplandor, alza: 0, dibujar };
  }

  function reconstruir(): void {
    if (contenido) liberarContenido(contenido, ayudas, propias);
    bajoElMouse = null;
    contenido = new THREE.Group();
    grupo.add(contenido);

    // Acera con borde de acento.
    ayudas.cajaR(15.4, 0.14, 6.4, 0.05, ayudas.liso(new THREE.Color(paleta.panel).multiplyScalar(0.85)), 0, -2.53, 0.7, contenido);
    ayudas.cajaR(15.4, 0.05, 0.07, 0.02, ayudas.basico(), 0, -2.44, 3.8, contenido);

    const tiendas = datos.tiendas.slice(0, MAX_LOCALES);
    locales = tiendas.map((t, i) => crearLocal(t, i, tiendas.length, contenido!));
    objetos = locales.map((l) => l.grupo);
  }

  /** El local al que pertenece `objeto` (el mismo grupo o uno de sus hijos). */
  function localDe(objeto: THREE.Object3D | null): Local | null {
    for (let o = objeto; o; o = o.parent) {
      const encontrado = locales.find((l) => l.grupo === o);
      if (encontrado) return encontrado;
    }
    return null;
  }

  reconstruir();

  const interactivo: Interactivo = {
    get objetos(): readonly THREE.Object3D[] {
      return objetos;
    },
    desdeProgreso: 0.85,
    alPasar(objeto) {
      bajoElMouse = localDe(objeto);
    },
    alClic(objeto) {
      const local = localDe(objeto);
      if (local) ctx.alElegirTienda(local.codigo);
    },
  };

  return {
    grupo,
    x: 2.6,
    escalaAncha: 0.8,
    escalaAngosta: 0.34,
    yAngosta: 0.2,
    interactivo,
    actualizar(estado: EstadoCuadro): void {
      // Fuera de la calle el mouse no cuenta (el motor deja de evaluar el rayo).
      if (estado.progreso <= interactivo.desdeProgreso) bajoElMouse = null;
      const k = estado.reducirMovimiento ? 1 : Math.min(1, estado.dt * 8);
      for (const local of locales) {
        const meta = local === bajoElMouse ? 1 : 0;
        local.alza += (meta - local.alza) * k;
        local.grupo.position.y = local.alza * ALZA;
        local.resplandor.material.opacity = local.alza * 0.55;
      }
    },
    fijarDatos(nuevos: DatosEscena): void {
      datos = nuevos;
      reconstruir();
    },
    // Los letreros dependen de las fuentes: se dibujan otra vez cuando cargan.
    redibujar(): void {
      for (const local of locales) local.dibujar();
    },
  };
};
