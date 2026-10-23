import { severidadEstadoSuscripcion } from '../../../core/models/plataforma.models';

/** Clases del chip (`.fs-chip`) de un estado de suscripción: activa verde, vencida roja, suspendida ámbar, cancelada gris. */
export function claseChipEstado(estado: string | null | undefined): string {
  switch (severidadEstadoSuscripcion(estado)) {
    case 'success':
      return 'fs-chip fs-chip--exito';
    case 'danger':
      return 'fs-chip fs-chip--error';
    case 'warn':
      return 'fs-chip fs-chip--advertencia';
    default:
      return 'fs-chip';
  }
}
