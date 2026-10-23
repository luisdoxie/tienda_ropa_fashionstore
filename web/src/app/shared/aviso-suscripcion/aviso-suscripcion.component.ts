import { Component, computed, inject } from '@angular/core';
import { fechaDesdeIso } from '../../core/date-utils';
import { DIAS_AVISO_VENCIMIENTO, PlanService } from '../../core/plan.service';
import { IconoComponent } from '../icono/icono.component';
import { NombreIcono } from '../icono/iconos';

type Gravedad = 'bloqueada' | 'por-vencer';

/** 2026-10-12 -> 12/10/2026 */
export function formatearFecha(iso: string): string {
  const fecha = fechaDesdeIso(iso);
  const dia = String(fecha.getDate()).padStart(2, '0');
  const mes = String(fecha.getMonth() + 1).padStart(2, '0');
  return `${dia}/${mes}/${fecha.getFullYear()}`;
}

/**
 * Franja de aviso arriba del contenido del back office de una empresa:
 * - suscripción vencida, suspendida o cancelada: operaciones bloqueadas (roja);
 * - activa que vence en 7 días o menos: aviso (ámbar).
 * No se muestra al superadministrador (el layout no la incluye).
 */
@Component({
  selector: 'app-aviso-suscripcion',
  standalone: true,
  imports: [IconoComponent],
  templateUrl: './aviso-suscripcion.component.html',
  styleUrl: './aviso-suscripcion.component.scss',
})
export class AvisoSuscripcionComponent {
  private readonly plan = inject(PlanService);

  protected readonly aviso = computed<{ gravedad: Gravedad; icono: NombreIcono; texto: string } | null>(() => {
    const estado = this.plan.estado();
    const vencimiento = this.plan.fechaVencimiento();

    if (estado !== null && estado !== 'activa') {
      const desde =
        estado === 'vencida' && vencimiento ? ` desde el ${formatearFecha(vencimiento)}` : '';
      const nombre = estado === 'sin_suscripcion' ? 'no está registrada' : `está ${estado}${desde}`;
      return {
        gravedad: 'bloqueada',
        icono: 'candado',
        texto: `Tu suscripción ${nombre}. Las operaciones de tu empresa están bloqueadas. Avisa al administrador de la plataforma.`,
      };
    }

    const dias = this.plan.diasParaVencer();
    if (estado === 'activa' && dias !== null && dias >= 0 && dias <= DIAS_AVISO_VENCIMIENTO) {
      const cuando = dias === 0 ? 'vence hoy' : dias === 1 ? 'vence en 1 día' : `vence en ${dias} días`;
      return { gravedad: 'por-vencer', icono: 'reloj', texto: `Tu suscripción ${cuando}.` };
    }
    return null;
  });
}
