import * as THREE from 'three';
import type { Ayudas } from '../ayudas';

type MaterialConColor = THREE.Material & { color: THREE.Color };
type MaterialConMapa = THREE.Material & { map?: THREE.Texture | null };

/**
 * Libera un contenido que la parada reconstruye cuando cambian sus datos: geometrías, materiales y
 * las texturas que la propia parada creó (`propias`; las compartidas de `Ayudas` no se tocan). Los
 * materiales dejan de seguir al acento. Después se quita de su padre.
 */
export function liberarContenido(raiz: THREE.Object3D, ayudas: Ayudas, propias: Set<THREE.Texture>): void {
  raiz.traverse((objeto) => {
    const malla = objeto as THREE.Mesh;
    // Los sprites comparten una sola geometría dentro de three: no es de la parada.
    if (malla.geometry && !(objeto as THREE.Sprite).isSprite) malla.geometry.dispose();
    const material = malla.material as THREE.Material | THREE.Material[] | undefined;
    if (!material) return;
    for (const m of Array.isArray(material) ? material : [material]) {
      ayudas.desacentuar(m as MaterialConColor);
      const mapa = (m as MaterialConMapa).map;
      if (mapa && propias.has(mapa)) {
        mapa.dispose();
        propias.delete(mapa);
      }
      m.dispose();
    }
  });
  raiz.removeFromParent();
}
