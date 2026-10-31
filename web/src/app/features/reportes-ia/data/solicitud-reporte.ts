import { FechaParcial, PeriodoSolicitado, SolicitudReporte, SolicitudResuelta } from '../../../core/models/reportes-ia.models';

/**
 * Del "entendí esto" a una solicitud que se puede reenviar sin pasar por la IA. El servidor devuelve la solicitud ya
 * resuelta (fechas calculadas, ids), pero `/ejecutar` solo acepta `SolicitudReporte`: periodo relativo o `rango_fechas`
 * y NOMBRES (nunca ids). Así, editar un filtro y pulsar "Actualizar reporte" no consume una llamada a la IA.
 */

/** `2026-09-30` → `{dia: 30, mes: 9, anio: 2026}`. */
export function fechaParcialDesdeIso(iso: string): FechaParcial {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) throw new Error(`Fecha inválida: ${iso}`);
  return { dia: Number(m[3]), mes: Number(m[2]), anio: Number(m[1]) };
}

/** Un rango de fechas (aaaa-mm-dd, ambos incluidos) como periodo de la solicitud. */
export function periodoDeRango(desdeIso: string, hastaIso: string): PeriodoSolicitado {
  return { tipo: 'rango_fechas', desde: fechaParcialDesdeIso(desdeIso), hasta: fechaParcialDesdeIso(hastaIso) };
}

/** Lo que el servidor entendió, convertido a una solicitud reenviable. Los filtros sin valor no se mandan. */
export function solicitudDesdeResuelta(r: SolicitudResuelta): SolicitudReporte {
  const solicitud: SolicitudReporte = { tipo_reporte: r.tipo_reporte };
  if (r.periodo) solicitud.periodo = periodoDeRango(r.periodo.desde, r.periodo.hasta);
  if (r.sucursales.length > 0) solicitud.sucursales = r.sucursales.map((s) => s.nombre);
  if (r.categorias.length > 0) solicitud.categorias = r.categorias.map((c) => c.nombre);
  if (r.productos.length > 0) solicitud.productos = r.productos.map((p) => p.nombre);
  if (r.canal) solicitud.canal = r.canal;
  if (r.agrupacion) solicitud.agrupacion = r.agrupacion;
  if (r.orden) solicitud.orden = r.orden;
  if (r.limite != null) solicitud.limite = r.limite;
  if (r.horizonte_semanas != null) solicitud.horizonte_semanas = r.horizonte_semanas;
  return solicitud;
}
