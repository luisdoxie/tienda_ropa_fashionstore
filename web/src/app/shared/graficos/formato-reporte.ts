import { TipoColumna, ValorCelda } from '../../core/models/reportes-ia.models';

/** Cómo se muestran las cifras de un reporte: es-BO, 2 decimales en dinero, 1 en porcentajes (el servidor manda 0 a 100). */

/** Un número a partir de la celda: acepta números y textos ("12.5" o "12,5"); null si no es un número. */
export function aNumero(valor: ValorCelda | undefined): number | null {
  if (typeof valor === 'number') return Number.isFinite(valor) ? valor : null;
  if (typeof valor !== 'string') return null;
  const limpio = valor.replace(/[%\s]|Bs/g, '');
  if (limpio === '') return null;
  const normalizado = limpio.includes(',') && !limpio.includes('.') ? limpio.replace(',', '.') : limpio;
  const n = Number(normalizado);
  return Number.isFinite(n) ? n : null;
}

function numero(n: number, decimales: number): string {
  return n.toLocaleString('es-BO', { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
}

export function formatearMoneda(n: number): string {
  return `Bs ${numero(n, 2)}`;
}

export function formatearEntero(n: number): string {
  return numero(Math.round(n), 0);
}

export function formatearPorcentaje(n: number): string {
  return `${numero(n, 1)} %`;
}

/** `2026-10-20` o `2026-10-20T14:05:00Z` → `20/10/2026` (sin pasar por la zona horaria: la fecha es la del servidor). */
export function formatearFechaIso(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

/** El texto de una celda según el tipo de su columna. Un valor vacío se muestra como "—". */
export function formatearCelda(valor: ValorCelda | undefined, tipo: TipoColumna): string {
  if (valor === null || valor === undefined || valor === '') return '—';
  switch (tipo) {
    case 'moneda': {
      const n = aNumero(valor);
      return n === null ? String(valor) : formatearMoneda(n);
    }
    case 'entero': {
      const n = aNumero(valor);
      return n === null ? String(valor) : formatearEntero(n);
    }
    case 'porcentaje': {
      const n = aNumero(valor);
      return n === null ? String(valor) : formatearPorcentaje(n);
    }
    case 'fecha':
      return typeof valor === 'string' ? formatearFechaIso(valor) : String(valor);
    case 'booleano':
      return valor === true || valor === 'true' ? 'Sí' : 'No';
    default:
      return String(valor);
  }
}

/** El formateador de números para los tooltips y los ejes de un gráfico cuya métrica es de este tipo. */
export function formateadorDe(tipo: TipoColumna): (n: number) => string {
  switch (tipo) {
    case 'moneda':
      return formatearMoneda;
    case 'porcentaje':
      return formatearPorcentaje;
    case 'entero':
      return formatearEntero;
    default:
      return (n) => numero(n, Number.isInteger(n) ? 0 : 2);
  }
}
