import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../environments/environment';
import { fechaLocalIso } from './date-utils';
import { AuthService } from './auth.service';
import { MiSuscripcion } from './models/plan.models';
import { PlanService } from './plan.service';

const API = environment.apiUrl;

function sumarDias(dias: number): string {
  const fecha = new Date();
  fecha.setDate(fecha.getDate() + dias);
  return fechaLocalIso(fecha);
}

function suscripcion(parcial: Partial<MiSuscripcion> = {}): MiSuscripcion {
  return {
    plan_codigo: 'basico',
    plan_nombre: 'Básico',
    estado: 'activa',
    fecha_inicio: sumarDias(-10),
    fecha_vencimiento: sumarDias(20),
    max_sucursales: 2,
    sucursales_activas: 1,
    funcionalidades: ['gestion_productos', 'gestion_ventas', 'reservas', 'reportes_convencionales', 'operacion_offline'],
    ...parcial,
  };
}

describe('PlanService', () => {
  let plan: PlanService;
  let auth: AuthService;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    plan = TestBed.inject(PlanService);
    auth = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    localStorage.clear();
    http.verify();
  });

  function iniciarSesion(roles: string[], permisos: string[], empresaId: number | null = 7): void {
    auth.guardarTokens({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
    auth.cargarUsuarioActual().subscribe();
    http.expectOne(`${API}/auth/yo`).flush({
      id: 1,
      nombre: 'Ana',
      apellido: 'Paz',
      email: 'a@b.com',
      telefono: null,
      activo: true,
      roles,
      permisos,
      empresa_id: empresaId,
    });
  }

  describe('sin datos del plan', () => {
    it('incluye todo, el estado es activo y no hay aviso', () => {
      expect(plan.incluye('reportes_ia')).toBe(true);
      expect(plan.estado()).toBeNull();
      expect(plan.estadoActivo()).toBe(true);
      expect(plan.diasParaVencer()).toBeNull();
    });
  });

  describe('incluye()', () => {
    it('responde según las funcionalidades del plan', () => {
      plan.suscripcion.set(suscripcion());

      expect(plan.incluye('gestion_ventas')).toBe(true);
      expect(plan.incluye('reportes_ia')).toBe(false);
      expect(plan.incluye('analitica_ml')).toBe(false);
      expect(plan.incluye('copias_seguridad')).toBe(false);
    });

    it('un plan Profesional incluye todo lo que declara', () => {
      plan.suscripcion.set(suscripcion({ plan_nombre: 'Profesional', funcionalidades: ['reportes_ia', 'analitica_ml'] }));

      expect(plan.incluye('reportes_ia')).toBe(true);
      expect(plan.incluye('analitica_ml')).toBe(true);
    });
  });

  describe('estadoActivo', () => {
    it('es verdadero solo con la suscripción activa', () => {
      plan.suscripcion.set(suscripcion({ estado: 'activa' }));
      expect(plan.estadoActivo()).toBe(true);

      for (const estado of ['vencida', 'suspendida', 'cancelada', 'sin_suscripcion']) {
        plan.suscripcion.set(suscripcion({ estado }));
        expect(plan.estadoActivo()).toBe(false);
      }
    });

    it('un 403 suscripcion_no_activa lo vuelve falso aunque no se conozca el plan', () => {
      plan.marcarBloqueada('suspendida');

      expect(plan.estado()).toBe('suspendida');
      expect(plan.estadoActivo()).toBe(false);
    });

    it('si el backend no informa el estado, queda como vencida (nunca como activa)', () => {
      plan.marcarBloqueada(undefined);
      expect(plan.estado()).toBe('vencida');
    });
  });

  describe('diasParaVencer', () => {
    it('cuenta los días que faltan', () => {
      plan.suscripcion.set(suscripcion({ fecha_vencimiento: sumarDias(5) }));
      expect(plan.diasParaVencer()).toBe(5);
    });

    it('vence hoy = 0 y vencida = negativo', () => {
      plan.suscripcion.set(suscripcion({ fecha_vencimiento: sumarDias(0) }));
      expect(plan.diasParaVencer()).toBe(0);

      plan.suscripcion.set(suscripcion({ fecha_vencimiento: sumarDias(-3) }));
      expect(plan.diasParaVencer()).toBe(-3);
    });
  });

  describe('cargar() y refrescar()', () => {
    it('el administrador de la empresa carga su plan una sola vez', () => {
      iniciarSesion(['administrador'], ['empresa.gestionar']);

      plan.cargar();
      http.expectOne(`${API}/mi-empresa/suscripcion`).flush(suscripcion());
      expect(plan.nombrePlan()).toBe('Básico');
      expect(plan.cargando()).toBe(false);

      plan.cargar();
      http.expectNone(`${API}/mi-empresa/suscripcion`);
    });

    it('refrescar() vuelve a pedirlo', () => {
      iniciarSesion(['administrador'], ['empresa.gestionar']);
      plan.suscripcion.set(suscripcion());

      plan.refrescar();
      http.expectOne(`${API}/mi-empresa/suscripcion`).flush(suscripcion({ plan_nombre: 'Profesional' }));
      expect(plan.nombrePlan()).toBe('Profesional');
    });

    it('quien no tiene empresa.gestionar no lo pide (el backend respondería 403)', () => {
      iniciarSesion(['cajero'], ['ventas.presencial']);

      plan.cargar();
      plan.refrescar();
      http.expectNone(`${API}/mi-empresa/suscripcion`);
      expect(plan.incluye('reportes_ia')).toBe(true);
    });

    it('el superadministrador no tiene plan', () => {
      iniciarSesion(['superadministrador'], ['plataforma.gestionar', 'empresa.gestionar'], null);

      plan.cargar();
      http.expectNone(`${API}/mi-empresa/suscripcion`);
    });

    it('un fallo deja el error a la vista y no inventa un plan', () => {
      iniciarSesion(['administrador'], ['empresa.gestionar']);

      plan.cargar();
      http.expectOne(`${API}/mi-empresa/suscripcion`).flush({}, { status: 500, statusText: 'Error' });
      expect(plan.error()).toBe(true);
      expect(plan.suscripcion()).toBeNull();
    });

    it('un 403 suscripcion_no_activa pide el plan para mostrar el detalle', () => {
      iniciarSesion(['administrador'], ['empresa.gestionar']);

      plan.marcarBloqueada('vencida');
      http
        .expectOne(`${API}/mi-empresa/suscripcion`)
        .flush(suscripcion({ estado: 'vencida', fecha_vencimiento: sumarDias(-2) }));
      expect(plan.estado()).toBe('vencida');
      expect(plan.diasParaVencer()).toBe(-2);
    });

    it('al cerrar sesión se olvida del plan', () => {
      iniciarSesion(['administrador'], ['empresa.gestionar']);
      TestBed.tick();
      plan.suscripcion.set(suscripcion());

      auth.limpiarSesion();
      TestBed.tick();

      expect(plan.suscripcion()).toBeNull();
      expect(plan.estadoActivo()).toBe(true);
    });
  });
});
