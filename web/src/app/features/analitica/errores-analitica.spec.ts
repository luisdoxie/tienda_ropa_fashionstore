import { HttpErrorResponse } from '@angular/common/http';
import { MENSAJE_EN_CURSO, MENSAJE_GENERICO, clasificarError } from './errores-analitica';

function error(status: number, cuerpo: unknown): HttpErrorResponse {
  return new HttpErrorResponse({ status, error: cuerpo, statusText: 'x' });
}

describe('clasificarError', () => {
  it('403 plan_no_incluye_funcionalidad es de plan', () => {
    const e = clasificarError(
      error(403, { detail: 'plan_no_incluye_funcionalidad', codigo: 'plan_no_incluye_funcionalidad', mensaje: 'Tu plan no incluye esto.' }),
    );
    expect(e.clase).toBe('plan');
    expect(e.mensaje).toBe('Tu plan no incluye esto.');
  });

  it('403 con "La analítica es de toda la empresa" es de alcance (el usuario tiene sucursal)', () => {
    const e = clasificarError(error(403, { detail: 'La analítica es de toda la empresa' }));
    expect(e.clase).toBe('alcance');
    expect(e.mensaje).toBe('La analítica es de toda la empresa');
  });

  it('403 con suscripción vencida NO se confunde con el rol', () => {
    expect(clasificarError(error(403, { codigo: 'suscripcion_no_activa', detail: 'suscripcion_no_activa' })).clase).toBe('otro');
  });

  it.each([
    ['modelo_no_entrenado', 'sin_modelo'],
    ['modelo_obsoleto', 'obsoleto'],
    ['entrenamiento_en_curso', 'en_curso'],
  ])('409 %s es %s', (codigo, clase) => {
    expect(clasificarError(error(409, { detail: codigo, codigo, mensaje: 'texto' })).clase).toBe(clase);
  });

  it('409 entrenamiento_en_curso usa el mensaje de la pantalla', () => {
    expect(clasificarError(error(409, { codigo: 'entrenamiento_en_curso' })).mensaje).toBe(MENSAJE_EN_CURSO);
  });

  it('429 es de límite, 0 es sin conexión y lo demás es "otro" con un mensaje legible', () => {
    expect(clasificarError(error(429, {})).clase).toBe('limite');
    expect(clasificarError(error(0, null)).clase).toBe('sin_conexion');
    const otro = clasificarError(error(500, null));
    expect(otro.clase).toBe('otro');
    expect(otro.mensaje).toBe(MENSAJE_GENERICO);
    expect(clasificarError(new Error('x')).clase).toBe('sin_conexion');
  });
});
