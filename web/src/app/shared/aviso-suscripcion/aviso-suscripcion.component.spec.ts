import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { fechaLocalIso } from '../../core/date-utils';
import { MiSuscripcion } from '../../core/models/plan.models';
import { PlanService } from '../../core/plan.service';
import { AvisoSuscripcionComponent, formatearFecha } from './aviso-suscripcion.component';

function sumarDias(dias: number): string {
  const fecha = new Date();
  fecha.setDate(fecha.getDate() + dias);
  return fechaLocalIso(fecha);
}

function suscripcion(parcial: Partial<MiSuscripcion>): MiSuscripcion {
  return {
    plan_codigo: 'basico',
    plan_nombre: 'Básico',
    estado: 'activa',
    fecha_inicio: sumarDias(-30),
    fecha_vencimiento: sumarDias(30),
    max_sucursales: 2,
    sucursales_activas: 1,
    funcionalidades: [],
    ...parcial,
  };
}

describe('AvisoSuscripcionComponent', () => {
  let plan: PlanService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    plan = TestBed.inject(PlanService);
  });

  function texto(): string | null {
    const fixture = TestBed.createComponent(AvisoSuscripcionComponent);
    fixture.detectChanges();
    const franja = (fixture.nativeElement as HTMLElement).querySelector('.aviso-suscripcion');
    return franja ? (franja.textContent ?? '').replace(/\s+/g, ' ').trim() : null;
  }

  function clases(): string[] {
    const fixture = TestBed.createComponent(AvisoSuscripcionComponent);
    fixture.detectChanges();
    const franja = (fixture.nativeElement as HTMLElement).querySelector('.aviso-suscripcion');
    return franja ? Array.from(franja.classList) : [];
  }

  it('lleva un ícono del sistema de 28 px, no un pi-*', () => {
    plan.suscripcion.set(suscripcion({ estado: 'vencida' }));
    const fixture = TestBed.createComponent(AvisoSuscripcionComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    expect(el.querySelector('i.pi')).toBeNull();
    expect(el.querySelector('fs-icono svg')?.getAttribute('width')).toBe('28');
  });

  it('formatea la fecha como dd/mm/aaaa', () => {
    expect(formatearFecha('2026-10-12')).toBe('12/10/2026');
  });

  it('no muestra nada si no se conoce el plan', () => {
    expect(texto()).toBeNull();
  });

  it('no muestra nada con la suscripción activa y lejos de vencer', () => {
    plan.suscripcion.set(suscripcion({}));
    expect(texto()).toBeNull();
  });

  it('vencida: franja roja con la fecha y el bloqueo', () => {
    plan.suscripcion.set(suscripcion({ estado: 'vencida', fecha_vencimiento: '2026-10-12' }));

    expect(texto()).toBe(
      'Tu suscripción está vencida desde el 12/10/2026. Las operaciones de tu empresa están bloqueadas. Avisa al administrador de la plataforma.',
    );
    expect(clases()).toContain('aviso-suscripcion--bloqueada');
  });

  it('suspendida y cancelada también bloquean', () => {
    plan.suscripcion.set(suscripcion({ estado: 'suspendida' }));
    expect(texto()).toContain('Tu suscripción está suspendida.');
    expect(texto()).toContain('bloqueadas');

    plan.suscripcion.set(suscripcion({ estado: 'cancelada' }));
    expect(texto()).toContain('Tu suscripción está cancelada.');
  });

  it('bloqueada por un 403 sin conocer el plan, también avisa', () => {
    plan.marcarBloqueada('suspendida');
    expect(texto()).toContain('Tu suscripción está suspendida.');
  });

  it('activa que vence en 7 días o menos: franja ámbar', () => {
    plan.suscripcion.set(suscripcion({ fecha_vencimiento: sumarDias(5) }));
    expect(texto()).toBe('Tu suscripción vence en 5 días.');
    expect(clases()).not.toContain('aviso-suscripcion--bloqueada');

    plan.suscripcion.set(suscripcion({ fecha_vencimiento: sumarDias(7) }));
    expect(texto()).toBe('Tu suscripción vence en 7 días.');

    plan.suscripcion.set(suscripcion({ fecha_vencimiento: sumarDias(1) }));
    expect(texto()).toBe('Tu suscripción vence en 1 día.');

    plan.suscripcion.set(suscripcion({ fecha_vencimiento: sumarDias(0) }));
    expect(texto()).toBe('Tu suscripción vence hoy.');
  });

  it('a 8 días todavía no avisa', () => {
    plan.suscripcion.set(suscripcion({ fecha_vencimiento: sumarDias(8) }));
    expect(texto()).toBeNull();
  });
});
