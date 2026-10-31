import { HttpErrorResponse } from '@angular/common/http';
import { ErrorLeido } from '../../core/utils/http-blob';
import {
  checksumCorto,
  clasificarErrorCopia,
  copiarAlPortapapeles,
  fechaDeUtc,
  formatearTamano,
  limiteBytesDeError,
  nombreLegible,
  textoMotivoFallo,
  vistaEstadoCopia,
} from './vistas-copias';

function leido(status: number, codigo: string | null = null, mensaje = 'mensaje del servidor'): ErrorLeido {
  return { status, codigo, mensaje, sugerencias: [], estado: null };
}

describe('vistas-copias', () => {
  describe('formatearTamano', () => {
    it('elige B, KB, MB o GB y usa coma decimal', () => {
      expect(formatearTamano(512)).toBe('512 B');
      expect(formatearTamano(1536)).toMatch(/^1[,.]5 KB$/);
      expect(formatearTamano(1_572_864)).toMatch(/^1[,.]5 MB$/);
      expect(formatearTamano(3 * 1024 ** 3)).toMatch(/^3[,.]0 GB$/);
    });

    it('sin dato o dato inválido da una raya', () => {
      expect(formatearTamano(null)).toBe('—');
      expect(formatearTamano(undefined)).toBe('—');
      expect(formatearTamano(-1)).toBe('—');
      expect(formatearTamano(Number.NaN)).toBe('—');
    });
  });

  describe('fechaDeUtc', () => {
    it('lee como UTC una fecha sin zona', () => {
      expect(fechaDeUtc('2026-10-30T14:05:00').toISOString()).toBe('2026-10-30T14:05:00.000Z');
    });

    it('respeta la zona cuando viene', () => {
      expect(fechaDeUtc('2026-10-30T14:05:00Z').toISOString()).toBe('2026-10-30T14:05:00.000Z');
      expect(fechaDeUtc('2026-10-30T10:05:00-04:00').toISOString()).toBe('2026-10-30T14:05:00.000Z');
    });
  });

  it('checksumCorto deja los primeros 12 caracteres', () => {
    expect(checksumCorto('0123456789abcdef0123')).toBe('0123456789ab');
    expect(checksumCorto(null)).toBe('—');
  });

  it('nombreLegible quita los guiones bajos y pone mayúscula inicial', () => {
    expect(nombreLegible('orden_compra')).toBe('Orden compra');
    expect(nombreLegible('venta')).toBe('Venta');
  });

  it('vistaEstadoCopia: completada es éxito, fallida es error y en_proceso dice "En curso"', () => {
    expect(vistaEstadoCopia('completada')).toMatchObject({ texto: 'Completada', clase: 'fs-chip--exito' });
    expect(vistaEstadoCopia('fallida')).toMatchObject({ texto: 'Fallida', clase: 'fs-chip--error' });
    expect(vistaEstadoCopia('en_proceso')).toMatchObject({ texto: 'En curso' });
    expect(vistaEstadoCopia('rara')).toMatchObject({ texto: 'rara', clase: '' });
  });

  it('textoMotivoFallo nunca muestra el código crudo', () => {
    expect(textoMotivoFallo('abandonada')).toBe('Se interrumpió antes de terminar.');
    expect(textoMotivoFallo('inventado')).toBe('No se pudo completar la copia.');
    expect(textoMotivoFallo(null)).toBe('No se pudo completar la copia.');
  });

  describe('clasificarErrorCopia', () => {
    it('separa los 403 por código: plan, suscripción o rol', () => {
      expect(clasificarErrorCopia(leido(403, 'plan_no_incluye_funcionalidad')).clase).toBe('plan');
      expect(clasificarErrorCopia(leido(403, 'suscripcion_no_activa'), null, 'vencida')).toMatchObject({
        clase: 'suscripcion',
        estadoSuscripcion: 'vencida',
      });
      expect(clasificarErrorCopia(leido(403)).clase).toBe('rol');
    });

    it('409 copia_en_curso, 413, 429, 503, 504, 500 y estado 0', () => {
      expect(clasificarErrorCopia(leido(409, 'copia_en_curso')).clase).toBe('en_curso');
      expect(clasificarErrorCopia(leido(413, 'copia_demasiado_grande'), 5_242_880).mensaje).toContain('5,0 MB');
      expect(clasificarErrorCopia(leido(429)).clase).toBe('limite');
      expect(clasificarErrorCopia(leido(503)).clase).toBe('ocupado');
      expect(clasificarErrorCopia(leido(504)).clase).toBe('tiempo');
      expect(clasificarErrorCopia(leido(500)).clase).toBe('fallida');
      expect(clasificarErrorCopia(leido(0)).clase).toBe('sin_conexion');
    });

    it('otro error usa el mensaje del servidor y es reintentable; en_curso y límite no', () => {
      const otro = clasificarErrorCopia(leido(422, null, 'Dato inválido'));
      expect(otro).toMatchObject({ clase: 'otro', mensaje: 'Dato inválido', reintentable: true });
      expect(clasificarErrorCopia(leido(409, 'copia_en_curso')).reintentable).toBe(false);
      expect(clasificarErrorCopia(leido(429)).reintentable).toBe(false);
    });
  });

  describe('limiteBytesDeError', () => {
    it('lee limite_bytes de un cuerpo Blob', async () => {
      const error = new HttpErrorResponse({ status: 413, error: new Blob([JSON.stringify({ limite_bytes: 1000 })]) });
      expect(await limiteBytesDeError(error)).toBe(1000);
    });

    it('devuelve null si no viene, no es número o el cuerpo no es JSON', async () => {
      expect(await limiteBytesDeError(new HttpErrorResponse({ status: 413, error: new Blob(['{}']) }))).toBeNull();
      expect(await limiteBytesDeError(new HttpErrorResponse({ status: 413, error: new Blob(['no json']) }))).toBeNull();
      expect(await limiteBytesDeError(new HttpErrorResponse({ status: 413, error: { limite_bytes: 'x' } }))).toBeNull();
      expect(await limiteBytesDeError(new HttpErrorResponse({ status: 413, error: { limite_bytes: 2048 } }))).toBe(2048);
    });
  });

  describe('copiarAlPortapapeles', () => {
    afterEach(() => {
      delete (navigator as { clipboard?: unknown }).clipboard;
      delete (document as { execCommand?: unknown }).execCommand;
    });

    it('usa navigator.clipboard cuando existe', async () => {
      const escribir = vi.fn(() => Promise.resolve());
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: escribir } });
      expect(await copiarAlPortapapeles('abc')).toBe(true);
      expect(escribir).toHaveBeenCalledWith('abc');
    });

    it('si el portapapeles rechaza, cae al respaldo con execCommand y no deja el campo temporal', async () => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText: vi.fn(() => Promise.reject(new Error('denegado'))) },
      });
      const exec = vi.fn(() => true);
      (document as { execCommand?: unknown }).execCommand = exec;
      expect(await copiarAlPortapapeles('abc')).toBe(true);
      expect(exec).toHaveBeenCalledWith('copy');
      expect(document.querySelector('textarea')).toBeNull();
    });

    it('sin ninguna de las dos formas devuelve false sin lanzar', async () => {
      expect(await copiarAlPortapapeles('abc')).toBe(false);
    });
  });
});
