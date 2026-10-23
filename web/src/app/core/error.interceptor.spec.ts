import { HttpClient, HttpContext, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { errorInterceptor, reiniciarAvisosFuncionales } from './error.interceptor';
import { SIN_TOAST_ERROR } from './http-contexts';
import { PlanService } from './plan.service';

describe('errorInterceptor', () => {
  let http: HttpClient;
  let controller: HttpTestingController;
  let mensajes: MessageService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([errorInterceptor])), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
    mensajes = TestBed.inject(MessageService);
  });

  afterEach(() => controller.verify());

  it('sin el context muestra el toast en un 404', () => {
    const add = vi.spyOn(mensajes, 'add');
    let fallo: unknown = null;
    http.get('/api/x').subscribe({ error: (e) => (fallo = e) });
    controller.expectOne('/api/x').flush({ detail: 'No existe' }, { status: 404, statusText: 'Not Found' });
    expect(add).toHaveBeenCalledTimes(1);
    expect(add.mock.calls[0][0]).toMatchObject({ severity: 'error', detail: 'No existe' });
    expect(fallo).not.toBeNull();
  });

  it('con SIN_TOAST_ERROR no muestra el toast pero propaga el error', () => {
    const add = vi.spyOn(mensajes, 'add');
    let fallo: any = null;
    const context = new HttpContext().set(SIN_TOAST_ERROR, true);
    http.get('/api/x', { context }).subscribe({ error: (e) => (fallo = e) });
    controller.expectOne('/api/x').flush({ detail: 'No existe' }, { status: 404, statusText: 'Not Found' });
    expect(add).not.toHaveBeenCalled();
    expect(fallo?.status).toBe(404);
  });

  it('no muestra toast en un 401', () => {
    const add = vi.spyOn(mensajes, 'add');
    http.get('/api/x').subscribe({ error: () => undefined });
    controller.expectOne('/api/x').flush({}, { status: 401, statusText: 'Unauthorized' });
    expect(add).not.toHaveBeenCalled();
  });

  describe('errores del plan y la suscripción', () => {
    beforeEach(() => reiniciarAvisosFuncionales());
    afterEach(() => vi.restoreAllMocks());

    function fallar(cuerpo: object, status: number, url = '/api/x'): void {
      http.get(url).subscribe({ error: () => undefined });
      controller.expectOne(url).flush(cuerpo, { status, statusText: 'Error' });
    }

    it('plan_no_incluye_funcionalidad (cuerpo del backend) dice qué hacer, sin "Error 403"', () => {
      const add = vi.spyOn(mensajes, 'add');
      fallar(
        {
          detail: 'plan_no_incluye_funcionalidad',
          codigo: 'plan_no_incluye_funcionalidad',
          mensaje: 'Su plan no incluye esta funcionalidad',
          funcionalidad: 'reportes_ia',
          plan: 'basico',
        },
        403,
      );
      expect(add).toHaveBeenCalledTimes(1);
      const toast = add.mock.calls[0][0];
      expect(toast.severity).toBe('warn');
      expect(toast.summary).toBe('Función no incluida en tu plan');
      expect(toast.detail).toBe(
        'Tu plan Básico no incluye esta funcionalidad. Mira qué incluye cada plan en Mi empresa.',
      );
      expect(JSON.stringify(toast)).not.toContain('Error 403');
      expect(JSON.stringify(toast)).not.toContain('plan_no_incluye_funcionalidad');
    });

    it('suscripcion_no_activa nombra el estado y marca la suscripción como bloqueada', () => {
      const add = vi.spyOn(mensajes, 'add');
      const plan = TestBed.inject(PlanService);
      fallar({ detail: 'suscripcion_no_activa', codigo: 'suscripcion_no_activa', mensaje: 'x', estado: 'suspendida' }, 403);

      expect(add.mock.calls[0][0].summary).toBe('Suscripción no activa');
      expect(add.mock.calls[0][0].detail).toBe(
        'La suscripción de tu empresa está suspendida. Mientras tanto no se pueden registrar operaciones. Avisa al administrador de la plataforma.',
      );
      expect(plan.estado()).toBe('suspendida');
      expect(plan.estadoActivo()).toBe(false);
    });

    it('limite_plan_excedido muestra el uso y el máximo', () => {
      const add = vi.spyOn(mensajes, 'add');
      fallar(
        {
          detail: 'limite_plan_excedido',
          codigo: 'limite_plan_excedido',
          mensaje: 'x',
          recurso: 'sucursales',
          limite: 2,
          actual: 2,
          plan: 'basico',
        },
        409,
      );
      expect(add.mock.calls[0][0].summary).toBe('Límite del plan alcanzado');
      expect(add.mock.calls[0][0].detail).toBe(
        'Llegaste al máximo de tu plan (2 de 2 sucursales). Para agregar más, pedí el cambio de plan.',
      );
    });

    it('también entiende el código dentro de detail (texto y objeto)', () => {
      const add = vi.spyOn(mensajes, 'add');
      fallar({ detail: 'plan_no_incluye_funcionalidad' }, 403);
      expect(add.mock.calls[0][0].summary).toBe('Función no incluida en tu plan');

      reiniciarAvisosFuncionales();
      fallar({ detail: { codigo: 'limite_plan_excedido', mensaje: 'x', actual: 3, limite: 3, recurso: 'sucursales' } }, 409);
      expect(add.mock.calls[1][0].summary).toBe('Límite del plan alcanzado');
    });

    it('no repite el mismo aviso antes de 10 segundos, pero sí después', () => {
      const add = vi.spyOn(mensajes, 'add');
      let ahora = 1_000_000;
      vi.spyOn(Date, 'now').mockImplementation(() => ahora);
      const cuerpo = { detail: 'suscripcion_no_activa', codigo: 'suscripcion_no_activa', mensaje: 'x', estado: 'vencida' };

      fallar(cuerpo, 403);
      ahora += 9_000;
      fallar(cuerpo, 403);
      expect(add).toHaveBeenCalledTimes(1);

      ahora += 2_000;
      fallar(cuerpo, 403);
      expect(add).toHaveBeenCalledTimes(2);
    });

    it('avisos de códigos distintos no se silencian entre sí', () => {
      const add = vi.spyOn(mensajes, 'add');
      fallar({ detail: 'suscripcion_no_activa', codigo: 'suscripcion_no_activa', estado: 'vencida' }, 403);
      fallar({ detail: 'plan_no_incluye_funcionalidad', codigo: 'plan_no_incluye_funcionalidad', plan: 'basico' }, 403);
      expect(add).toHaveBeenCalledTimes(2);
    });

    it('con SIN_TOAST_ERROR no hay toast, pero el aviso persistente sí se activa', () => {
      const add = vi.spyOn(mensajes, 'add');
      const plan = TestBed.inject(PlanService);
      const context = new HttpContext().set(SIN_TOAST_ERROR, true);
      http.get('/api/x', { context }).subscribe({ error: () => undefined });
      controller
        .expectOne('/api/x')
        .flush({ detail: 'suscripcion_no_activa', codigo: 'suscripcion_no_activa', estado: 'vencida' }, { status: 403, statusText: 'Forbidden' });

      expect(add).not.toHaveBeenCalled();
      expect(plan.estado()).toBe('vencida');
    });

    it('un error común no cambia: "Error 403" con el detalle del backend', () => {
      const add = vi.spyOn(mensajes, 'add');
      fallar({ detail: 'No tenés permiso para esto' }, 403);
      expect(add.mock.calls[0][0]).toMatchObject({
        severity: 'error',
        summary: 'Error 403',
        detail: 'No tenés permiso para esto',
      });
    });

    it('un código desconocido se muestra como un error común', () => {
      const add = vi.spyOn(mensajes, 'add');
      fallar({ detail: 'otra_cosa', codigo: 'otra_cosa', mensaje: 'Algo pasó' }, 400);
      expect(add.mock.calls[0][0]).toMatchObject({ severity: 'error', summary: 'Error 400', detail: 'otra_cosa' });
    });
  });
});
