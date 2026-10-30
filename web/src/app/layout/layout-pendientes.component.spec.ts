import 'fake-indexeddb/auto';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../environments/environment';
import { AuthService } from '../core/auth.service';
import { ConectividadService, EstadoConexion } from '../core/conectividad.service';
import { MiSuscripcion } from '../core/models/plan.models';
import { ColaSincronizacionService } from '../core/offline/cola-sincronizacion.service';
import { BaseOffline } from '../core/offline/db-offline';
import type { OperacionOffline } from '../core/offline/offline.models';
import { RepositorioLocal } from '../core/offline/repositorio-local';
import { SesionOfflineService } from '../core/offline/sesion-offline.service';
import { PlanService } from '../core/plan.service';
import { LayoutComponent } from './layout.component';

/**
 * "Pendientes de envío" en el menú, [Salir] con operaciones sin enviar y el aviso de operaciones de otra persona (E14b,
 * plan 4.9 y 4.10). Usa un doble de la cola de envío y una base local propia por prueba.
 */
const API = environment.apiUrl;
const PERMISOS_VENTA = ['ventas.presencial', 'reservas.gestionar_sucursal'];
let contador = 0;

function suscripcion(funcionalidades: string[]): MiSuscripcion {
  return {
    plan_codigo: 'x',
    plan_nombre: 'Básico',
    estado: 'activa',
    fecha_inicio: '2026-01-01',
    fecha_vencimiento: '2099-01-01',
    max_sucursales: 2,
    sucursales_activas: 1,
    funcionalidades,
  };
}

function operacionDe(usuarioId: number, id: string, estado: OperacionOffline['estado'] = 'registrada'): OperacionOffline {
  return {
    empresa_id: 7,
    usuario_id: usuarioId,
    operacion_id: `${id}-0000-4000-8000-000000000000`,
    tipo: 'venta_contado',
    estado,
    fecha_operacion: '2026-10-30T10:00:00-04:00',
  } as unknown as OperacionOffline;
}

describe('LayoutComponent: pendientes de envío', () => {
  let http: HttpTestingController;
  let auth: AuthService;
  let fixture: ComponentFixture<LayoutComponent>;
  let el: HTMLElement;
  let db: BaseOffline;
  let repositorio: RepositorioLocal | null;
  let cerrarSesion: ReturnType<typeof vi.spyOn>;
  const conexion = signal<EstadoConexion>('en_linea');
  const cola = {
    estadoCola: signal('inactiva'),
    pendientes: signal(0),
    enConflicto: signal(0),
    rechazadas: signal(0),
    confirmadas: signal(0),
    proximoIntentoEn: signal<string | null>(null),
    motivoPausa: signal<string | null>(null),
    refrescarConteos: vi.fn(async () => undefined),
    notificarNuevaOperacion: vi.fn(),
    enviarAhora: vi.fn(async () => undefined),
  };

  beforeEach(() => {
    localStorage.clear();
    db = new BaseOffline(`prueba_layout_pendientes_${++contador}_${Date.now()}`);
    repositorio = null;
    conexion.set('en_linea');
    cola.pendientes.set(0);
    cola.enviarAhora.mockReset();
    cola.enviarAhora.mockResolvedValue(undefined);
    TestBed.configureTestingModule({
      imports: [LayoutComponent],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        { provide: ColaSincronizacionService, useValue: cola },
        {
          provide: ConectividadService,
          useValue: { estado: conexion, enLinea: () => conexion() === 'en_linea', volvioConexion$: { pipe: () => ({ subscribe: () => undefined }) } },
        },
        {
          provide: SesionOfflineService,
          useValue: {
            alcance: () => null,
            repositorio: () => repositorio,
            dispositivoId: () => 'dispositivo-prueba',
            alCerrarSesion: async () => undefined,
            alIniciarSesion: async () => undefined,
          },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
    cerrarSesion = vi.spyOn(auth, 'logout').mockImplementation(() => undefined);
  });

  afterEach(() => {
    fixture?.destroy();
    http.match(() => true);
    localStorage.clear();
    db.close();
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

  function crear(): void {
    fixture = TestBed.createComponent(LayoutComponent);
    fixture.detectChanges();
    el = fixture.nativeElement as HTMLElement;
  }

  const enlace = (texto: string) =>
    Array.from(el.querySelectorAll('nav a.layout__enlace')).find((a) => (a.textContent ?? '').includes(texto)) as HTMLElement | undefined;
  const contadores = () => Array.from(el.querySelectorAll('[data-contador-pendientes]'));
  const botonSalir = () => el.querySelector('.layout__barra-acciones button.fs-btn') as HTMLButtonElement;
  const salida = (cual: string) => document.body.querySelector(`[data-salida="${cual}"]`) as HTMLButtonElement | null;
  const dialogoSalida = () => document.body.querySelector('p-confirmdialog, .p-confirmdialog');

  describe('el ítem del menú', () => {
    it('va al FINAL de Ventas, después de "Catálogo local", y enlaza a /operaciones-pendientes', () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      crear();
      const ventas = Array.from(el.querySelectorAll('#menu-seccion-comercial a.layout__enlace')).map((a) => a.textContent?.replace(/\s+/g, ' ').trim());

      expect(ventas.slice(-2)).toEqual(['Catálogo local', 'Pendientes de envío']);
      expect(enlace('Pendientes de envío')?.getAttribute('href')).toBe('/operaciones-pendientes');
      expect(enlace('Pendientes de envío')?.classList).not.toContain('layout__enlace--deshabilitado');
    });

    it('lo ve quien tiene CUALQUIERA de los dos permisos', () => {
      iniciarSesion(['encargado'], ['reservas.gestionar_sucursal']);
      crear();
      expect(enlace('Pendientes de envío')).toBeDefined();
    });

    it('sin ninguno de los dos permisos no aparece', () => {
      iniciarSesion(['encargado'], ['inventario.ver', 'reportes.ver', 'ventas.gestionar']);
      crear();
      expect(enlace('Pendientes de envío')).toBeUndefined();
    });

    it('con un plan sin operación sin conexión sigue en su lugar, deshabilitado y con candado', () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      TestBed.inject(PlanService).suscripcion.set(suscripcion([]));
      crear();
      fixture.detectChanges();

      const item = enlace('Pendientes de envío')!;
      expect(item.classList).toContain('layout__enlace--deshabilitado');
      expect(item.querySelector('.layout__candado')).not.toBeNull();
    });
  });

  describe('el globito contador', () => {
    it('no aparece con cero pendientes', () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      crear();

      expect(contadores()).toEqual([]);
    });

    it('muestra cuántas operaciones esperan y se actualiza solo', () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      cola.pendientes.set(3);
      crear();

      expect(contadores().length).toBe(1);
      expect(enlace('Pendientes de envío')!.querySelector('[data-contador-pendientes]')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
        '3 operaciones sin enviar',
      );
      expect(enlace('Catálogo local')!.querySelector('[data-contador-pendientes]')).toBeNull();

      cola.pendientes.set(1);
      fixture.detectChanges();
      expect(contadores()[0].textContent?.replace(/\s+/g, ' ').trim()).toBe('1 operación sin enviar');

      cola.pendientes.set(0);
      fixture.detectChanges();
      expect(contadores()).toEqual([]);
    });
  });

  describe('[Salir]', () => {
    it('sin operaciones pendientes sale directo, como siempre', () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      crear();

      botonSalir().click();
      fixture.detectChanges();

      expect(cerrarSesion).toHaveBeenCalledTimes(1);
      expect(salida('cancelar')).toBeNull();
    });

    it('con pendientes NO sale: pregunta con el texto acordado y ofrece tres opciones', () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      cola.pendientes.set(3);
      crear();

      botonSalir().click();
      fixture.detectChanges();

      expect(cerrarSesion).not.toHaveBeenCalled();
      expect(document.body.textContent).toContain(
        'Tienes 3 operaciones sin enviar. Si sales ahora quedan guardadas en este equipo y se enviarán cuando vuelvas a entrar con tu usuario.',
      );
      expect(salida('enviar-y-salir')?.textContent).toContain('Enviar ahora y salir');
      expect(salida('salir-igual')?.textContent).toContain('Salir igual');
      expect(salida('cancelar')?.textContent).toContain('Cancelar');
      expect(dialogoSalida()).not.toBeNull();
    });

    it('con una sola operación usa el singular', () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      cola.pendientes.set(1);
      crear();

      botonSalir().click();
      fixture.detectChanges();

      expect(document.body.textContent).toContain('Tienes 1 operación sin enviar.');
    });

    it('[Cancelar] cierra la pregunta y no sale ni envía', () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      cola.pendientes.set(2);
      crear();
      botonSalir().click();
      fixture.detectChanges();

      salida('cancelar')!.click();
      fixture.detectChanges();

      expect(cerrarSesion).not.toHaveBeenCalled();
      expect(cola.enviarAhora).not.toHaveBeenCalled();
      expect(salida('cancelar')).toBeNull();
    });

    it('[Salir igual] sale sin intentar enviar nada', () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      cola.pendientes.set(2);
      crear();
      botonSalir().click();
      fixture.detectChanges();

      salida('salir-igual')!.click();
      fixture.detectChanges();

      expect(cerrarSesion).toHaveBeenCalledTimes(1);
      expect(cola.enviarAhora).not.toHaveBeenCalled();
    });

    it('[Enviar ahora y salir] ESPERA a la cola y recién entonces sale', async () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      cola.pendientes.set(2);
      let terminarEnvio: () => void = () => undefined;
      cola.enviarAhora.mockImplementation(() => new Promise<undefined>((resolver) => (terminarEnvio = () => resolver(undefined))));
      crear();
      botonSalir().click();
      fixture.detectChanges();

      salida('enviar-y-salir')!.click();
      fixture.detectChanges();
      await Promise.resolve();

      expect(cola.enviarAhora).toHaveBeenCalledTimes(1);
      expect(cerrarSesion).not.toHaveBeenCalled();
      expect(salida('enviar-y-salir')?.disabled).toBe(true);
      expect(salida('enviar-y-salir')?.textContent).toContain('Enviando…');

      terminarEnvio();
      await vi.waitFor(() => expect(cerrarSesion).toHaveBeenCalledTimes(1));
    });

    it('sin red [Enviar ahora y salir] queda deshabilitado y lo explica; las otras dos siguen disponibles', () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      cola.pendientes.set(2);
      conexion.set('sin_conexion');
      crear();
      botonSalir().click();
      fixture.detectChanges();

      expect(salida('enviar-y-salir')?.disabled).toBe(true);
      expect(salida('enviar-y-salir')?.getAttribute('title')).toContain('Conéctate a Internet');
      expect(salida('salir-igual')?.disabled).toBe(false);
      expect(salida('cancelar')?.disabled).toBe(false);
    });

    it('el botón Salir sigue donde estaba: último de la barra, después de la campana', () => {
      iniciarSesion(['administrador'], PERMISOS_VENTA);
      crear();

      const hijos = Array.from((el.querySelector('.layout__barra-acciones') as HTMLElement).children).map((h) => h.tagName.toLowerCase());
      expect(hijos).toEqual(['app-indicador-conexion', 'button', 'button']);
      expect(botonSalir().textContent).toContain('Salir');
    });
  });

  describe('operaciones de otra persona en este equipo', () => {
    async function sembrar(usuarios: number[]): Promise<void> {
      repositorio = new RepositorioLocal(db, { empresaId: 7, usuarioId: 1 });
      let n = 0;
      for (const usuarioId of usuarios) {
        await new RepositorioLocal(db, { empresaId: 7, usuarioId }).registrarOperacion(operacionDe(usuarioId, `0000000${++n}`));
      }
    }

    it('avisa cuántas dejó otro usuario y que se enviarán cuando esa persona vuelva a entrar', async () => {
      iniciarSesion(['cajero'], PERMISOS_VENTA);
      await sembrar([2, 2, 3]);
      crear();

      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(el.querySelector('[data-aviso="pendientes-de-otros"]')).not.toBeNull();
      });
      expect(el.querySelector('[data-aviso="pendientes-de-otros"]')?.textContent?.replace(/\s+/g, ' ').trim()).toContain(
        'Hay 3 operaciones de otro usuario en este equipo; se enviarán cuando esa persona vuelva a entrar.',
      );
    });

    it('no cuenta las mías ni las ya enviadas de otros', async () => {
      iniciarSesion(['cajero'], PERMISOS_VENTA);
      await sembrar([1, 1]);
      await new RepositorioLocal(db, { empresaId: 7, usuarioId: 2 }).registrarOperacion(operacionDe(2, '00000009', 'confirmada'));
      crear();
      await vi.waitFor(() => expect(repositorio).not.toBeNull());
      await new Promise((r) => setTimeout(r, 50));
      fixture.detectChanges();

      expect(el.querySelector('[data-aviso="pendientes-de-otros"]')).toBeNull();
    });

    it('con una sola operación usa el singular y el aviso se puede cerrar', async () => {
      iniciarSesion(['cajero'], PERMISOS_VENTA);
      await sembrar([2]);
      crear();
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(el.querySelector('[data-aviso="pendientes-de-otros"]')).not.toBeNull();
      });
      expect(el.querySelector('[data-aviso="pendientes-de-otros"]')?.textContent).toContain('Hay 1 operación de otro usuario');

      (el.querySelector('[data-aviso="pendientes-de-otros"] button') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(el.querySelector('[data-aviso="pendientes-de-otros"]')).toBeNull();
    });

    it('sin nada de otros no hay aviso, y el aviso va dentro del contenido sin mover la barra ni el panel', async () => {
      iniciarSesion(['cajero'], PERMISOS_VENTA);
      repositorio = new RepositorioLocal(db, { empresaId: 7, usuarioId: 1 });
      crear();
      await new Promise((r) => setTimeout(r, 50));
      fixture.detectChanges();

      expect(el.querySelector('[data-aviso="pendientes-de-otros"]')).toBeNull();
      const hijos = Array.from((el.querySelector('.layout__contenido') as HTMLElement).children).map((h) => h.tagName.toLowerCase());
      expect(hijos[0]).toBe('header');
      expect(hijos[hijos.length - 1]).toBe('main');
    });
  });
});
