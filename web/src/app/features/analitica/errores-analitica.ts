import { HttpErrorResponse } from '@angular/common/http';
import { codigoFuncional } from '../../core/errores-funcionales';

/**
 * Qué le pasó a una consulta de analítica, en las categorías que la pantalla sabe explicar. Cada bloque pide lo suyo y
 * explica su propio fallo (por eso las llamadas van sin el toast global).
 */
export type ClaseErrorAnalitica =
  | 'plan' // 403 plan_no_incluye_funcionalidad
  | 'alcance' // 403: la analítica es de toda la empresa (el usuario tiene sucursal) o falta el permiso
  | 'sin_modelo' // 409 modelo_no_entrenado
  | 'obsoleto' // 409 modelo_obsoleto
  | 'en_curso' // 409 entrenamiento_en_curso
  | 'limite' // 429
  | 'sin_conexion' // status 0
  | 'otro';

export interface ErrorAnalitica {
  clase: ClaseErrorAnalitica;
  status: number;
  codigo: string | null;
  /** Mensaje legible del servidor, o uno genérico en español. */
  mensaje: string;
}

export const MENSAJE_GENERICO = 'No se pudo completar la operación. Inténtalo de nuevo.';
export const MENSAJE_EN_CURSO = 'Otra persona ya está entrenando; vuelve a intentarlo en un momento.';
export const MENSAJE_LIMITE_ENTRENAR = 'Puedes entrenar hasta 3 veces por minuto. Espera un momento e inténtalo de nuevo.';
export const MENSAJE_LIMITE_CONSULTAS = 'Hiciste muchas consultas seguidas. Espera un momento e inténtalo de nuevo.';

const FORMATO_CODIGO = /^[a-z][a-z0-9_]*$/;

function texto(valor: unknown): string | null {
  return typeof valor === 'string' && valor.trim() !== '' ? valor.trim() : null;
}

/** El mensaje que el servidor mandó (`mensaje`, o un `detail` que no sea un código), o null. */
function mensajeDelServidor(cuerpo: unknown): string | null {
  if (cuerpo === null || typeof cuerpo !== 'object') return null;
  const c = cuerpo as Record<string, unknown>;
  const mensaje = texto(c['mensaje']);
  if (mensaje !== null) return mensaje;
  const detalle = texto(c['detail']);
  if (detalle !== null && !FORMATO_CODIGO.test(detalle)) return detalle;
  return null;
}

/** Clasifica cualquier error de una consulta de `/analitica`. Síncrona y sin efectos: el cuerpo ya viene como objeto. */
export function clasificarError(error: unknown): ErrorAnalitica {
  const status = error instanceof HttpErrorResponse ? error.status : 0;
  const cuerpo: unknown = error instanceof HttpErrorResponse ? error.error : null;
  const codigo = codigoFuncional(error);
  const mensaje = mensajeDelServidor(cuerpo);

  const resultado = (clase: ClaseErrorAnalitica, texto: string): ErrorAnalitica => ({ clase, status, codigo, mensaje: texto });

  if (status === 0) return resultado('sin_conexion', 'No se pudo conectar con el servidor. Revisa tu conexión.');
  if (status === 429) return resultado('limite', MENSAJE_LIMITE_CONSULTAS);
  if (status === 403) {
    if (codigo === 'plan_no_incluye_funcionalidad') return resultado('plan', mensaje ?? 'Tu plan no incluye la analítica.');
    if (codigo === 'suscripcion_no_activa') return resultado('otro', mensaje ?? 'Tu suscripción no está activa.');
    return resultado('alcance', mensaje ?? 'La analítica es de toda la empresa.');
  }
  if (status === 409) {
    if (codigo === 'modelo_no_entrenado') return resultado('sin_modelo', mensaje ?? 'Aún no hay un modelo entrenado.');
    if (codigo === 'modelo_obsoleto') return resultado('obsoleto', mensaje ?? 'El modelo quedó obsoleto: vuelve a entrenarlo.');
    if (codigo === 'entrenamiento_en_curso') return resultado('en_curso', MENSAJE_EN_CURSO);
  }
  return resultado('otro', mensaje ?? MENSAJE_GENERICO);
}
