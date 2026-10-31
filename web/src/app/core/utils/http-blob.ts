import { HttpErrorResponse } from '@angular/common/http';

/**
 * Un error HTTP ya legible. Las descargas (`responseType: 'blob'`) devuelven el cuerpo de un 4xx como `Blob`, y el
 * interceptor global no sabe leerlo (mostraría "Ocurrió un error inesperado"): por eso las pantallas que descargan lo
 * piden con `SIN_TOAST_ERROR` y explican el fallo con esto.
 */
export interface ErrorLeido {
  status: number;
  /** Código funcional (`reporte_no_exportable`, `plan_no_incluye_funcionalidad`...) o null. */
  codigo: string | null;
  mensaje: string;
  sugerencias: string[];
  /** Estado del reporte cuando el servidor rechaza exportar uno que no está `ok`. */
  estado: string | null;
}

const FORMATO_CODIGO = /^[a-z][a-z0-9_]*$/;

const MENSAJE_GENERICO = 'No se pudo completar la operación. Inténtalo de nuevo.';

const MENSAJES_POR_ESTADO: Record<number, string> = {
  0: 'No se pudo conectar con el servidor. Revisa tu conexión.',
  403: 'Tu plan o tu rol no permiten esta operación.',
  429: 'Hiciste demasiadas consultas seguidas. Espera un momento e inténtalo de nuevo.',
};

/** Lee el texto de un Blob. jsdom no implementa `Blob.text()`, de modo que se cae a `FileReader`. */
export function leerTextoBlob(blob: Blob): Promise<string> {
  if (typeof blob.text === 'function') return blob.text();
  return new Promise((resolver, rechazar) => {
    const lector = new FileReader();
    lector.onload = () => resolver(String(lector.result ?? ''));
    lector.onerror = () => rechazar(lector.error);
    lector.readAsText(blob);
  });
}

function texto(valor: unknown): string | null {
  return typeof valor === 'string' && valor.trim() !== '' ? valor : null;
}

function listaDeTextos(valor: unknown): string[] {
  return Array.isArray(valor) ? valor.filter((x): x is string => typeof x === 'string') : [];
}

/** Extrae lo útil de un cuerpo de error ya convertido a objeto (formato `ErrorFuncional` o `detail` clásico). */
function interpretarCuerpo(status: number, cuerpo: unknown): ErrorLeido {
  const base: ErrorLeido = {
    status,
    codigo: null,
    mensaje: MENSAJES_POR_ESTADO[status] ?? MENSAJE_GENERICO,
    sugerencias: [],
    estado: null,
  };
  if (cuerpo === null || typeof cuerpo !== 'object') return base;

  const c = cuerpo as Record<string, unknown>;
  const detalle = c['detail'];
  const detalleTexto = texto(detalle);

  const codigo =
    texto(c['codigo']) ??
    (detalleTexto !== null && FORMATO_CODIGO.test(detalleTexto) ? detalleTexto : null) ??
    (detalle !== null && typeof detalle === 'object' ? texto((detalle as Record<string, unknown>)['codigo']) : null);

  let mensaje = texto(c['mensaje']);
  if (mensaje === null && detalleTexto !== null && !FORMATO_CODIGO.test(detalleTexto)) mensaje = detalleTexto;
  if (mensaje === null && Array.isArray(detalle)) {
    // Validación de FastAPI (422): [{msg}, ...]
    const msgs = detalle.map((d) => texto((d as Record<string, unknown> | null)?.['msg'])).filter((m): m is string => m !== null);
    if (msgs.length > 0) mensaje = msgs.join(' · ');
  }
  if (mensaje === null && detalle !== null && typeof detalle === 'object' && !Array.isArray(detalle)) {
    mensaje = texto((detalle as Record<string, unknown>)['mensaje']);
  }

  return {
    status,
    codigo,
    mensaje: mensaje ?? base.mensaje,
    sugerencias: listaDeTextos(c['sugerencias']),
    estado: texto(c['estado']),
  };
}

/**
 * Convierte cualquier fallo de una petición (cuerpo `Blob`, JSON ya leído o sin cuerpo) en un `ErrorLeido`. Nunca lanza:
 * un cuerpo que no es JSON da el mensaje genérico de su estado HTTP.
 */
export async function leerErrorBlob(error: unknown): Promise<ErrorLeido> {
  const status = error instanceof HttpErrorResponse ? error.status : 0;
  const cuerpo: unknown = error instanceof HttpErrorResponse ? error.error : error;

  if (cuerpo instanceof Blob) {
    try {
      return interpretarCuerpo(status, JSON.parse(await leerTextoBlob(cuerpo)));
    } catch {
      return interpretarCuerpo(status, null);
    }
  }
  return interpretarCuerpo(status, cuerpo);
}
