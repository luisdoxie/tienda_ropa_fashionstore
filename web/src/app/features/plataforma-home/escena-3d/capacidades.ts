/** Lo que la escena 3D necesita saber del navegador; inyectable para probar sin navegador. */
export interface Entorno {
  /** El navegador puede crear un contexto WebGL (2 o 1). */
  tieneWebGL: boolean;
  /** `prefers-reduced-motion: reduce`. */
  reducirMovimiento: boolean;
  /** `navigator.connection.saveData`. */
  ahorroDeDatos: boolean;
  /** `navigator.deviceMemory` en GB (undefined si el navegador no lo expone). */
  memoriaGb?: number;
  /** `navigator.hardwareConcurrency` (undefined si el navegador no lo expone). */
  nucleos?: number;
  /** `window.devicePixelRatio`. */
  densidadPixeles?: number;
}

export interface PerfilRendimiento {
  /** Tope de `devicePixelRatio` que usa el renderer. */
  pixelRatioMax: 2 | 1.5 | 1;
  /** Cantidad de partículas de polvo. */
  particulas: 520 | 260;
}

export const PERFIL_ALTO: PerfilRendimiento = { pixelRatioMax: 2, particulas: 520 };

/** Lee el entorno del navegador actual. */
export function entornoReal(): Entorno {
  const nav = typeof navigator !== 'undefined' ? navigator : undefined;
  const info = nav as (Navigator & { deviceMemory?: number; connection?: { saveData?: boolean } }) | undefined;
  return {
    tieneWebGL: hayWebGL(),
    reducirMovimiento: coincide('(prefers-reduced-motion: reduce)'),
    ahorroDeDatos: info?.connection?.saveData === true,
    memoriaGb: info?.deviceMemory,
    nucleos: info?.hardwareConcurrency,
    densidadPixeles: typeof window !== 'undefined' ? window.devicePixelRatio : undefined,
  };
}

function coincide(consulta: string): boolean {
  try {
    return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(consulta).matches;
  } catch {
    return false;
  }
}

function hayWebGL(): boolean {
  try {
    if (typeof document === 'undefined') return false;
    const lienzo = document.createElement('canvas');
    const gl = (lienzo.getContext('webgl2') ?? lienzo.getContext('webgl')) as WebGLRenderingContext | null;
    if (!gl) return false;
    // El contexto de la prueba no se usa: se suelta para no gastar uno de los pocos que admite el navegador.
    gl.getExtension?.('WEBGL_lose_context')?.loseContext();
    return true;
  } catch {
    return false;
  }
}

/**
 * ¿Vale la pena montar la escena 3D? Falso sin WebGL, con "reducir movimiento", con ahorro de datos
 * o en equipos modestos (menos de 4 GB de memoria o de 4 núcleos, cuando el navegador lo informa).
 */
export function puedeUsarEscena3D(entorno: Entorno = entornoReal()): boolean {
  if (!entorno.tieneWebGL) return false;
  if (entorno.reducirMovimiento) return false;
  if (entorno.ahorroDeDatos) return false;
  if (entorno.memoriaGb !== undefined && entorno.memoriaGb < 4) return false;
  if (entorno.nucleos !== undefined && entorno.nucleos < 4) return false;
  return true;
}

/** Calidad según la potencia: gama media o baja baja la densidad de píxeles y las partículas. */
export function perfilRendimiento(entorno: Entorno = entornoReal()): PerfilRendimiento {
  const memoria = entorno.memoriaGb;
  const nucleos = entorno.nucleos;
  const baja = (memoria !== undefined && memoria < 4) || (nucleos !== undefined && nucleos < 4);
  const media = (memoria !== undefined && memoria < 8) || (nucleos !== undefined && nucleos < 8);
  if (baja) return { pixelRatioMax: 1, particulas: 260 };
  if (media) return { pixelRatioMax: 1.5, particulas: 260 };
  return { ...PERFIL_ALTO };
}
