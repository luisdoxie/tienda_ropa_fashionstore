import { aCentavos } from '../../core/offline/dinero-offline';
import type { EstadoOperacion, OperacionOffline, ResultadoSync, TipoOperacion } from '../../core/offline/offline.models';
import type { EstadoCola } from '../../core/offline/cola-sincronizacion.service';
import type { NombreIcono } from '../../shared/icono/iconos';

/** Cómo se ve cada estado de una operación: texto, ícono y severidad del `p-tag` (nunca solo color). */
export interface VistaEstado {
  texto: string;
  icono: NombreIcono;
  severidad: 'secondary' | 'info' | 'success' | 'danger' | 'warn';
}

export const VISTA_ESTADO: Record<EstadoOperacion, VistaEstado> = {
  registrada: { texto: 'Pendiente de enviar', icono: 'reloj', severidad: 'secondary' },
  enviada: { texto: 'Enviando…', icono: 'enviar', severidad: 'info' },
  confirmada: { texto: 'Sincronizada', icono: 'check', severidad: 'success' },
  rechazada: { texto: 'Rechazada', icono: 'cerrar', severidad: 'danger' },
  en_conflicto: { texto: 'En conflicto: espera la revisión del encargado', icono: 'advertencia', severidad: 'warn' },
};

export const ETIQUETA_TIPO: Record<TipoOperacion, string> = {
  venta_contado: 'Venta',
  reserva: 'Reserva',
};

/**
 * Textos fijos para los motivos que devuelve el servidor (`backend/app/sincronizacion/politicas.py`). Sin jerga: dicen
 * qué pasó y, cuando se puede, qué hacer.
 */
export const TEXTO_MOTIVO: Record<string, string> = {
  stock_insuficiente: 'No había stock suficiente en la sucursal cuando se envió.',
  variante_inactiva: 'Una de las prendas ya no está disponible: se dio de baja.',
  variante_inexistente: 'Una de las prendas ya no existe en el catálogo.',
  cliente_inexistente: 'El cliente ya no existe en el sistema.',
  sucursal_no_autorizada: 'No tienes autorizada esa sucursal.',
  sucursal_inexistente: 'La sucursal ya no existe en el sistema.',
  usuario_no_es_empleado: 'Tu usuario no está registrado como empleado de la empresa.',
  permiso_denegado: 'Tu usuario no tiene permiso para registrar este tipo de operación.',
  operador_inactivo: 'Tu usuario ya no está activo, por eso no se pudo confirmar la operación.',
  suscripcion_no_activa: 'La suscripción de tu empresa no está activa.',
  plan_sin_operacion_offline: 'El plan de tu empresa no incluye operar sin conexión.',
  metodo_pago_no_permitido: 'Sin conexión solo se acepta efectivo.',
  monto_insuficiente: 'El monto recibido no cubría el total de la venta.',
  total_inconsistente: 'El total no coincide con las prendas. Avisa a soporte.',
  total_invalido: 'El total de la operación no es válido. Avisa a soporte.',
  payload_invalido: 'La operación tiene un error de formato. Avisa a soporte.',
  tipo_no_soportado: 'El servidor no reconoce este tipo de operación. Avisa a soporte.',
  fecha_futura: 'La fecha de la operación está en el futuro: revisa la hora de este equipo.',
  reserva_fuera_de_horario: 'La visita quedó fuera del horario de la sucursal.',
  reserva_vencida: 'La fecha de la visita ya pasó.',
  regla_de_negocio: 'El servidor no aceptó la operación por una regla del negocio.',
  rechazada_por_encargado: 'Un encargado rechazó esta operación.',
};

const TEXTO_CONFLICTO_STOCK =
  'No había stock suficiente para esta operación. Un encargado la revisará y la aceptará o la rechazará.';
const TEXTO_BLOQUEADA = 'No se pudo enviar por un error de formato. Avisa a soporte.';
const TEXTO_SIN_RESPUESTA = 'El servidor no respondió. Se reintentará.';
const TEXTO_ERROR_ENVIO = 'No se pudo enviar. Se reintentará.';
const TEXTO_RECHAZO_GENERICO = 'El servidor no aceptó la operación.';

/** "Bs 1.234,50": miles con punto, centavos con coma y siempre dos decimales. */
export function formatoBs(monto: string | number | null | undefined): string {
  const centavos = aCentavos(monto);
  if (!Number.isFinite(centavos)) return '—';
  const absoluto = Math.abs(centavos);
  const entero = String(Math.floor(absoluto / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return `${centavos < 0 ? '-' : ''}Bs ${entero},${String(absoluto % 100).padStart(2, '0')}`;
}

/** El motivo de una operación en lenguaje claro, o `null` si no hay nada que explicar (pendiente sin problemas). */
export function motivoClaro(operacion: OperacionOffline): string | null {
  const { estado, motivo } = operacion;
  if (estado === 'rechazada' || estado === 'en_conflicto') {
    if (estado === 'en_conflicto' && (motivo === 'stock_insuficiente' || motivo === null)) return TEXTO_CONFLICTO_STOCK;
    const fijo = motivo ? TEXTO_MOTIVO[motivo] : undefined;
    if (fijo) return fijo;
    return operacion.mensaje?.trim() || TEXTO_RECHAZO_GENERICO;
  }
  if (estado === 'registrada') {
    if (operacion.bloqueada) return TEXTO_BLOQUEADA;
    if (operacion.ultimo_error === 'sin_respuesta') return TEXTO_SIN_RESPUESTA;
    if (operacion.ultimo_error) return TEXTO_ERROR_ENVIO;
  }
  return null;
}

/** Lo que se muestra en la columna "Último resultado": el motivo, o el código del servidor si ya se sincronizó. */
export function ultimoResultado(operacion: OperacionOffline): string {
  const motivo = motivoClaro(operacion);
  if (motivo) return motivo;
  if (operacion.estado === 'confirmada') {
    const codigo = operacion.resultado?.recurso?.codigo;
    const tipo = operacion.tipo === 'reserva' ? 'Reserva' : 'Venta';
    return codigo ? `${tipo} ${codigo} en el servidor.` : 'Recibida por el servidor.';
  }
  if (operacion.estado === 'enviada') return 'Esperando la respuesta del servidor.';
  return 'Aún no se envió.';
}

/** El resultado de un intento de envío, sin códigos técnicos. */
export function textoIntento(intento: ResultadoSync): string {
  const estado = intento.http_status;
  if (estado === null || estado === 0) return 'Sin respuesta: no había conexión o el servidor no contestó.';
  if (estado === 401) return 'Tu sesión había vencido.';
  if (estado === 403) return 'No se permitió enviar (permiso, plan o suscripción).';
  if (estado === 429) return 'El servidor estaba ocupado.';
  if (estado === 400 || estado === 422) return 'El servidor no entendió el formato.';
  if (estado >= 500) return 'El servidor tuvo un problema.';
  if (estado >= 200 && estado < 300) {
    const motivo = intento.motivo ? (TEXTO_MOTIVO[intento.motivo] ?? 'El servidor no aceptó la operación.') : null;
    return motivo ?? 'El servidor la recibió.';
  }
  return 'El servidor respondió con un error.';
}

export function textoEstadoCola(estado: EstadoCola, pendientes: number, segundosParaReintento: number | null): string {
  switch (estado) {
    case 'sincronizando':
      return 'Sincronizando…';
    case 'esperando_reintento':
      if (segundosParaReintento === null || segundosParaReintento <= 0) return 'Reintentando en un momento';
      return segundosParaReintento < 60
        ? `Reintento en ${segundosParaReintento} s`
        : `Reintento en ${Math.ceil(segundosParaReintento / 60)} min`;
    case 'pausada_sesion':
      return 'Pausada: inicia sesión';
    case 'pausada_plan':
      return 'Pausada: revisa el plan o la suscripción de tu empresa';
    case 'detenida_por_fallos':
      return 'Detenida: reintenta manualmente';
    case 'sin_conexion':
      return 'Sin conexión';
    default:
      return pendientes > 0 ? 'Listo para enviar' : 'Todo al día';
  }
}

export function iconoEstadoCola(estado: EstadoCola): NombreIcono {
  switch (estado) {
    case 'sincronizando':
      return 'refrescar';
    case 'esperando_reintento':
      return 'reloj';
    case 'pausada_sesion':
    case 'pausada_plan':
      return 'advertencia';
    case 'detenida_por_fallos':
      return 'alerta';
    case 'sin_conexion':
      return 'enlace-roto';
    default:
      return 'check';
  }
}

export function plural(cantidad: number, singular: string, plural: string): string {
  return `${cantidad} ${cantidad === 1 ? singular : plural}`;
}

function escapar(texto: unknown): string {
  return String(texto ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

/**
 * El comprobante de una venta hecha sin conexión, como página lista para imprimir (blanco y negro). Todo el texto se
 * escapa: el nombre del cliente y de las prendas vienen de datos de la empresa.
 */
export function htmlComprobante(operacion: OperacionOffline, sucursal: string, empresa: string, fecha: string): string {
  const lineas = operacion.lineas
    .map((l) => {
      const detalle = [l.talla, l.color].filter(Boolean).join(' · ');
      return `<tr><td>${escapar(l.producto_nombre)}${detalle ? ` <small>(${escapar(detalle)})</small>` : ''}</td><td class="n">${escapar(l.cantidad)}</td><td class="n">${escapar(formatoBs(l.subtotal))}</td></tr>`;
    })
    .join('');
  const pago = operacion.pago
    ? `<p>Recibido: ${escapar(formatoBs(operacion.pago.monto_recibido))}<br>Cambio: ${escapar(formatoBs(operacion.pago.cambio))}</p>`
    : '';
  const sincronizada = operacion.estado === 'confirmada';
  return (
    `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Comprobante ${escapar(operacion.codigo_local)}</title>` +
    `<style>body{font-family:sans-serif;font-size:13px;margin:16px;max-width:360px}h1{font-size:16px;margin:0 0 4px}` +
    `table{width:100%;border-collapse:collapse}td{padding:3px 0;border-bottom:1px solid black}.n{text-align:right}` +
    `.aviso{margin-top:12px;font-weight:bold}</style></head><body>` +
    `<h1>${escapar(empresa)}</h1><p>Sucursal: ${escapar(sucursal)}<br>Comprobante: ${escapar(operacion.codigo_local)}<br>Fecha: ${escapar(fecha)}` +
    `${operacion.cliente_nombre ? `<br>Cliente: ${escapar(operacion.cliente_nombre)}` : ''}</p>` +
    `<table><tbody>${lineas}</tbody></table><p><strong>Total: ${escapar(formatoBs(operacion.total))}</strong></p>${pago}` +
    `<p class="aviso">${sincronizada ? 'Venta sincronizada con el servidor.' : 'Venta registrada sin conexión: pendiente de enviar.'}</p></body></html>`
  );
}
