/** Cuerpo de un error funcional del backend: `{detail, codigo, mensaje, ...contexto}`. */
export type CuerpoErrorFuncional = Record<string, unknown>;

export interface MensajeFuncional {
  resumen: string;
  detalle: string;
  severidad: 'warn' | 'error' | 'info';
}

/**
 * Textos para el usuario de los errores del plan y la suscripción. Los códigos
 * técnicos nunca se muestran. `{plan}`, `{estado}`, `{uso}`, `{maximo}` y
 * `{recurso}` salen del contexto que manda el backend.
 */
const MENSAJES: Readonly<Record<string, MensajeFuncional>> = {
  plan_no_incluye_funcionalidad: {
    resumen: 'Función no incluida en tu plan',
    detalle: 'Tu plan {plan} no incluye esta funcionalidad. Mira qué incluye cada plan en Mi empresa.',
    severidad: 'warn',
  },
  suscripcion_no_activa: {
    resumen: 'Suscripción no activa',
    detalle:
      'La suscripción de tu empresa está {estado}. Mientras tanto no se pueden registrar operaciones. Avisa al administrador de la plataforma.',
    severidad: 'warn',
  },
  limite_plan_excedido: {
    resumen: 'Límite del plan alcanzado',
    detalle: 'Llegaste al máximo de tu plan ({uso} de {maximo} {recurso}). Para agregar más, pedí el cambio de plan.',
    severidad: 'warn',
  },
};

const ESTADOS: Readonly<Record<string, string>> = {
  activa: 'activa',
  suspendida: 'suspendida',
  vencida: 'vencida',
  cancelada: 'cancelada',
  sin_suscripcion: 'sin registrar',
};

export function esErrorFuncionalConocido(codigo: string | null): codigo is string {
  return codigo !== null && Object.hasOwn(MENSAJES, codigo);
}

// Planes sembrados: el nombre real lo sabe PlanService; esto es solo para quien no puede consultarlo.
const NOMBRES_DE_PLAN: Readonly<Record<string, string>> = { basico: 'Básico', profesional: 'Profesional' };

/** Nombre del plan a partir de su código. */
export function nombreDePlan(codigo: unknown): string {
  if (typeof codigo !== 'string' || codigo === '') return 'actual';
  return NOMBRES_DE_PLAN[codigo] ?? codigo.charAt(0).toLocaleUpperCase('es') + codigo.slice(1);
}

function textoDe(valor: unknown, porDefecto: string): string {
  return typeof valor === 'string' || typeof valor === 'number' ? String(valor) : porDefecto;
}

/** El mensaje del código, con los datos del error puestos, o null si el código no es conocido. */
export function mensajeFuncional(
  codigo: string | null,
  cuerpo: CuerpoErrorFuncional | null | undefined,
  nombrePlanConocido?: string | null,
): MensajeFuncional | null {
  if (!esErrorFuncionalConocido(codigo)) return null;
  const base = MENSAJES[codigo];
  const datos = cuerpo ?? {};
  const estado = typeof datos['estado'] === 'string' ? (datos['estado'] as string) : '';
  const valores: Record<string, string> = {
    plan: nombrePlanConocido ?? nombreDePlan(datos['plan']),
    estado: ESTADOS[estado] ?? 'inactiva',
    uso: textoDe(datos['actual'], '?'),
    maximo: textoDe(datos['limite'], '?'),
    recurso: textoDe(datos['recurso'], 'recursos'),
  };
  const detalle = base.detalle.replace(/\{(\w+)\}/g, (_texto, clave: string) => valores[clave] ?? '');
  return { ...base, detalle };
}
