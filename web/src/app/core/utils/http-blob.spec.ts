import { HttpErrorResponse } from '@angular/common/http';
import { leerErrorBlob, leerTextoBlob } from './http-blob';

const blobJson = (cuerpo: unknown) => new Blob([JSON.stringify(cuerpo)], { type: 'application/json' });
const error = (status: number, cuerpo: unknown) => new HttpErrorResponse({ status, error: cuerpo });

describe('leerErrorBlob', () => {
  it('lee el mensaje, el código y las sugerencias de un Blob JSON (reporte_no_exportable)', async () => {
    const leido = await leerErrorBlob(
      error(422, blobJson({ detail: 'reporte_no_exportable', codigo: 'reporte_no_exportable', mensaje: 'Falta el periodo.', estado: 'incompleta', sugerencias: ['ventas del mes'] })),
    );
    expect(leido).toEqual({
      status: 422,
      codigo: 'reporte_no_exportable',
      mensaje: 'Falta el periodo.',
      sugerencias: ['ventas del mes'],
      estado: 'incompleta',
    });
  });

  it('un detail de texto legible es el mensaje', async () => {
    const leido = await leerErrorBlob(error(409, blobJson({ detail: 'Ya existe.' })));
    expect(leido.mensaje).toBe('Ya existe.');
    expect(leido.codigo).toBeNull();
  });

  it('un detail que es solo un código no se muestra como mensaje', async () => {
    const leido = await leerErrorBlob(error(403, blobJson({ detail: 'plan_no_incluye_funcionalidad' })));
    expect(leido.codigo).toBe('plan_no_incluye_funcionalidad');
    expect(leido.mensaje).toBe('Tu plan o tu rol no permiten esta operación.');
  });

  it('errores de validación de FastAPI (422) se unen', async () => {
    const leido = await leerErrorBlob(error(422, blobJson({ detail: [{ msg: 'a' }, { msg: 'b' }] })));
    expect(leido.mensaje).toBe('a · b');
  });

  it('un Blob que no es JSON da el mensaje genérico de su estado', async () => {
    const leido = await leerErrorBlob(error(429, new Blob(['<html>demasiadas</html>'], { type: 'text/html' })));
    expect(leido.mensaje).toMatch(/demasiadas consultas/);
    expect(leido.codigo).toBeNull();
  });

  it('sin red (estado 0) explica que no hay conexión', async () => {
    const leido = await leerErrorBlob(error(0, null));
    expect(leido.mensaje).toMatch(/conectar con el servidor/);
  });

  it('también lee un cuerpo ya convertido a objeto', async () => {
    const leido = await leerErrorBlob(error(422, { mensaje: 'Listo.', codigo: 'x_y' }));
    expect(leido).toMatchObject({ mensaje: 'Listo.', codigo: 'x_y' });
  });

  it('un valor que no es un error HTTP tampoco lanza', async () => {
    const leido = await leerErrorBlob(new Error('x'));
    expect(leido.status).toBe(0);
    expect(typeof leido.mensaje).toBe('string');
  });
});

describe('leerTextoBlob', () => {
  it('devuelve el texto del Blob', async () => {
    expect(await leerTextoBlob(new Blob(['hola']))).toBe('hola');
  });
});
