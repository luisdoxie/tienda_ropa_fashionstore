import { esErrorFuncionalConocido, mensajeFuncional, nombreDePlan } from './mensajes-error-funcional';

describe('mensajes-error-funcional', () => {
  it('conoce los tres códigos', () => {
    expect(esErrorFuncionalConocido('plan_no_incluye_funcionalidad')).toBe(true);
    expect(esErrorFuncionalConocido('suscripcion_no_activa')).toBe(true);
    expect(esErrorFuncionalConocido('limite_plan_excedido')).toBe(true);
    expect(esErrorFuncionalConocido('otro')).toBe(false);
    expect(esErrorFuncionalConocido(null)).toBe(false);
    expect(esErrorFuncionalConocido('constructor')).toBe(false);
  });

  it('nombra el plan: el conocido por el servicio manda sobre el código', () => {
    expect(mensajeFuncional('plan_no_incluye_funcionalidad', { plan: 'basico' })?.detalle).toContain('Tu plan Básico');
    expect(mensajeFuncional('plan_no_incluye_funcionalidad', { plan: 'basico' }, 'Plan Pro')?.detalle).toContain(
      'Tu plan Plan Pro',
    );
    expect(nombreDePlan('profesional')).toBe('Profesional');
    expect(nombreDePlan('gold')).toBe('Gold');
    expect(nombreDePlan(undefined)).toBe('actual');
  });

  it('cada estado de suscripción se dice en lenguaje claro', () => {
    for (const estado of ['vencida', 'suspendida', 'cancelada']) {
      expect(mensajeFuncional('suscripcion_no_activa', { estado })?.detalle).toContain(`está ${estado}.`);
    }
    expect(mensajeFuncional('suscripcion_no_activa', { estado: 'sin_suscripcion' })?.detalle).toContain(
      'está sin registrar.',
    );
  });

  it('sin datos no deja llaves sin reemplazar', () => {
    for (const codigo of ['plan_no_incluye_funcionalidad', 'suscripcion_no_activa', 'limite_plan_excedido']) {
      const mensaje = mensajeFuncional(codigo, null);
      expect(mensaje).not.toBeNull();
      expect(mensaje?.detalle).not.toMatch(/[{}]/);
    }
  });

  it('un código desconocido no tiene mensaje', () => {
    expect(mensajeFuncional('otra_cosa', {})).toBeNull();
  });
});
