import type * as THREE from 'three';
import type { Ayudas } from './ayudas';

/**
 * Contrato de la escena 3D de la portada pública ("/"): lo que el motor (`escena-tienda.ts`) y cada
 * parada del recorrido se prometen entre sí. Las paradas NO se conocen entre ellas: solo conocen
 * este archivo y `ayudas.ts`.
 */

/** Un plan, tal como lo necesita la escena (sale de GET /public/planes). */
export interface PlanEscena {
  codigo: string;
  nombre: string;
  /** Sucursales activas permitidas: un cubo por sucursal (la parada limita cuántos dibuja). */
  sucursales: number;
}

/** Una tienda activa (sale de GET /public/tiendas). */
export interface TiendaEscena {
  codigo: string;
  nombre: string;
  /** "#rrggbb" ya resuelto para superficies oscuras, o null si la empresa no definió acento. */
  acento: string | null;
}

export interface DatosEscena {
  planes: readonly PlanEscena[];
  tiendas: readonly TiendaEscena[];
}

/** Colores base leídos de los tokens `--fs-*` (nunca hex sueltos en las paradas). */
export interface Paleta {
  /** --fs-carbon */
  carbon: string;
  /** --fs-carbon-2 */
  profundo: string;
  /** --fs-carbon-panel */
  panel: string;
  /** --fs-carbon-borde */
  borde: string;
  /** --fs-claro */
  texto: string;
  /** --fs-claro-tenue */
  tenue: string;
  /** --fs-acento-oscuro */
  acento: string;
  /** --fs-sobre-acento-oscuro */
  sobreAcento: string;
}

/** Lo que el motor le pasa a cada parada en cada cuadro. */
export interface EstadoCuadro {
  /** Segundos desde que arrancó la escena. */
  t: number;
  /** Segundos desde el cuadro anterior (acotado a 0,05). */
  dt: number;
  /** 0 (inicio) a 1 (calle de tiendas): posición del scroll en el recorrido. */
  progreso: number;
  /** El usuario pidió menos movimiento: las paradas no deben animar nada continuo. */
  reducirMovimiento: boolean;
}

/** Objetos de una parada que reaccionan al mouse (solo la calle de tiendas lo usa). */
export interface Interactivo {
  /** Raíces sobre las que el motor lanza el rayo (recursivo). */
  objetos: readonly THREE.Object3D[];
  /** El rayo cae sobre `objeto` (una de las raíces de arriba) o sobre nada (null). */
  alPasar(objeto: THREE.Object3D | null): void;
  /** Clic sobre `objeto` (una de las raíces). */
  alClic(objeto: THREE.Object3D): void;
  /** Solo se evalúa cuando `progreso` supera este valor. */
  desdeProgreso: number;
}

/** Una parada del recorrido: un grupo ubicado en el mundo, con su propia animación. */
export interface Parada {
  /** Ya ubicado en `z` (lo pone la parada) y agregado a la escena. */
  readonly grupo: THREE.Group;
  /** Posición x del grupo en pantalla ancha (la y la calcula el motor con `escalaAncha`). */
  readonly x: number;
  /** Escala del grupo en pantalla ancha. El suelo está en y = -2,6: el motor sube el grupo 2,6*(escala-1). */
  readonly escalaAncha: number;
  /** Escala del grupo en pantalla angosta (x = 0, y = `yAngosta`). */
  readonly escalaAngosta: number;
  readonly yAngosta: number;
  actualizar(estado: EstadoCuadro): void;
  /** Llegan o cambian los planes y las tiendas. Se llama una vez al crear y cada vez que cambian. */
  fijarDatos?(datos: DatosEscena): void;
  /** Redibuja lo que dependa del acento o de las fuentes (el motor avisa cuando cambian). */
  redibujar?(): void;
  readonly interactivo?: Interactivo;
}

/** La marca que el visitante prueba en la demo del inicio (no se guarda en ningún lado). */
export interface MarcaDemo {
  /** Nombre de la tienda de ejemplo (la polera lo lleva estampado). */
  nombre: string;
  /** "#rrggbb" de la tela de la polera. */
  tela: string;
  /** "#rrggbb" de acento sobre superficies oscuras (ya resuelto, con buen contraste). */
  acento: string;
}

/** Lo que recibe cada fábrica de parada. */
export interface ContextoParada {
  ayudas: Ayudas;
  scene: THREE.Scene;
  paleta: Paleta;
  /**
   * Crea una polera 3D nueva con la marca vigente. Todas comparten geometría, materiales y estampas
   * con la del inicio, así que cambian solas cuando el visitante cambia de color o de nombre.
   * Mide unos 4 x 3,9 unidades (sin escala); el que la usa la escala y la ubica.
   */
  crearPolera(): THREE.Group;
  /** Coordenada z donde va el grupo de la parada. */
  z: number;
  datos: DatosEscena;
  /** La calle avisa cuál tienda eligió el usuario (el motor lo reenvía al componente). */
  alElegirTienda(codigo: string): void;
}

export type FabricaParada = (ctx: ContextoParada) => Parada;

/** z de cada parada: 0 hero, 1 caja, 2 inventario, 3 probador, 4 planes, 5 calle. */
export const Z_PARADAS: readonly number[] = [0, -36, -72, -108, -144, -180];

/** Altura del suelo del mundo. */
export const Y_SUELO = -2.6;
