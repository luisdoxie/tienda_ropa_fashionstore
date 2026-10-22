import { HttpErrorResponse } from '@angular/common/http';
import { codigoFuncional } from './errores-funcionales';

function http(status: number, error: unknown): HttpErrorResponse {
  return new HttpErrorResponse({ status, error });
}

describe('codigoFuncional', () => {
  it('lee el campo codigo del cuerpo', () => {
    expect(codigoFuncional(http(403, { detail: 'x', codigo: 'limite_plan_excedido', mensaje: 'm' }))).toBe(
      'limite_plan_excedido',
    );
  });

  it('lee detail como string con formato de código', () => {
    expect(codigoFuncional(http(403, { detail: 'suscripcion_no_activa' }))).toBe('suscripcion_no_activa');
  });

  it('lee detail como objeto con codigo', () => {
    expect(codigoFuncional(http(403, { detail: { codigo: 'suscripcion_no_activa' } }))).toBe('suscripcion_no_activa');
  });

  it('el campo codigo tiene prioridad sobre detail', () => {
    expect(codigoFuncional(http(403, { codigo: 'a_b', detail: 'c_d' }))).toBe('a_b');
  });

  it('devuelve null si no hay código', () => {
    expect(codigoFuncional(http(500, { detail: 'Ocurrió un error inesperado.' }))).toBeNull();
    expect(codigoFuncional(http(500, { detail: 'Credenciales inválidas' }))).toBeNull();
    expect(codigoFuncional(http(500, { detail: { otro: 1 } }))).toBeNull();
    expect(codigoFuncional(http(500, {}))).toBeNull();
    expect(codigoFuncional(http(500, { codigo: '' }))).toBeNull();
    expect(codigoFuncional(http(500, null))).toBeNull();
    expect(codigoFuncional(http(500, 'texto plano'))).toBeNull();
  });

  it('devuelve null para errores que no son HTTP', () => {
    expect(codigoFuncional(new Error('boom'))).toBeNull();
    expect(codigoFuncional(null)).toBeNull();
    expect(codigoFuncional(undefined)).toBeNull();
    expect(codigoFuncional({ error: { codigo: 'x' } })).toBeNull();
  });
});
