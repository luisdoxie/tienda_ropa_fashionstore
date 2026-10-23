import { EstadoReserva } from '../../../core/models/reservas.models';

export const ETIQUETAS_ESTADO_RESERVA: Record<EstadoReserva, string> = {
  pendiente: 'Pendiente',
  preparada: 'Preparada',
  en_prueba: 'En prueba',
  completada: 'Completada',
  cancelada: 'Cancelada',
  expirada: 'Expirada',
};

/** Variante del chip de estado (ver .fs-chip en styles.scss). */
export const CLASES_ESTADO_RESERVA: Record<EstadoReserva, string> = {
  pendiente: 'fs-chip--advertencia',
  preparada: 'fs-chip--exito',
  en_prueba: 'fs-chip--advertencia',
  completada: 'fs-chip--exito',
  cancelada: 'fs-chip--error',
  expirada: 'fs-chip--error',
};
