import 'fake-indexeddb/auto';
import { computed, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AuthService } from '../auth.service';
import type { UsuarioYo } from '../models/seguridad.models';
import { AlmacenOfflineService } from './almacen-offline.service';
import { BaseOffline } from './db-offline';
import { CLAVE_DISPOSITIVO, CLAVE_ULTIMA_EMPRESA, META_ULTIMA_DESCARGA, metaSucursalCaja } from './offline.config';
import type { AlcanceOffline } from './offline.models';
import { RepositorioLocal } from './repositorio-local';
import { SesionOfflineService } from './sesion-offline.service';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

let contadorBases = 0;

function usuarioYo(id: number, empresaId: number | null, roles: string[] = ['cajero']): UsuarioYo {
  return {
    id,
    nombre: `Nombre${id}`,
    apellido: 'Prueba',
    email: `u${id}@prueba.bo`,
    telefono: null,
    activo: true,
    roles,
    permisos: ['ventas.crear'],
    empresa_id: empresaId,
    empresa_codigo: empresaId === null ? null : `empresa-${empresaId}`,
    empresa_nombre: empresaId === null ? null : `Empresa ${empresaId}`,
  };
}

describe('SesionOfflineService', () => {
  let db: BaseOffline;
  let almacen: AlmacenOfflineService;
  let sesion: SesionOfflineService;
  const usuarioSesion = signal<UsuarioYo | null>(null);

  /** Solo lo que lee SesionOfflineService de AuthService (sin HTTP: aquí se prueba el almacenamiento, no el login). */
  const authFalso = {
    usuario: usuarioSesion.asReadonly(),
    empresaId: computed(() => usuarioSesion()?.empresa_id ?? null),
    esSuperadmin: computed(() => {
      const u = usuarioSesion();
      return u !== null && (u.roles.includes('superadministrador') || u.empresa_id === null);
    }),
  };

  function arrancar(): void {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: authFalso },
        { provide: AlmacenOfflineService, useValue: almacen },
      ],
    });
    sesion = TestBed.inject(SesionOfflineService);
  }

  function repo(empresaId: number, usuarioId: number) {
    return almacen.repositorio({ empresaId, usuarioId } satisfies AlcanceOffline);
  }

  async function sembrarProducto(empresaId: number, id: number): Promise<void> {
    await db.productos.put({
      empresa_id: empresaId,
      id,
      codigo: `P-${id}`,
      nombre: `Polera ${id}`,
      nombre_norm: `polera ${id}`,
      categoria_id: 1,
      genero: 'hombre',
      temporada_id: null,
      imagen_principal: null,
    });
  }

  async function sembrarCliente(empresaId: number, id: number): Promise<void> {
    await db.clientes_minimos.put({
      empresa_id: empresaId,
      id,
      nombre: 'Ana',
      apellido: `Paz${id}`,
      ci_nit: `${id}00`,
      nombre_norm: `ana paz${id}`,
    });
  }

  async function sembrarOperacion(empresaId: number, usuarioId: number, operacionId: string): Promise<void> {
    await db.operaciones_pendientes.put({
      empresa_id: empresaId,
      usuario_id: usuarioId,
      operacion_id: operacionId,
      tipo: 'venta_contado',
      estado: 'registrada',
      fecha_operacion: '2026-10-30T10:00:00-04:00',
    });
  }

  beforeEach(() => {
    localStorage.clear();
    usuarioSesion.set(null);
    db = new BaseOffline(`prueba-sesion-offline-${++contadorBases}`);
    almacen = new AlmacenOfflineService();
    (almacen as { base: BaseOffline }).base = db;
    arrancar();
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await db.delete();
    localStorage.clear();
  });

  describe('dispositivoId', () => {
    it('es un UUID y se guarda en localStorage', () => {
      const id = sesion.dispositivoId();
      expect(id).toMatch(UUID);
      expect(localStorage.getItem(CLAVE_DISPOSITIVO)).toBe(id);
    });

    it('es estable entre llamadas y entre instancias del servicio (otra apertura de la app)', () => {
      const primero = sesion.dispositivoId();
      expect(sesion.dispositivoId()).toBe(primero);
      arrancar();
      expect(sesion.dispositivoId()).toBe(primero);
    });

    it('respeta el identificador que ya había guardado el equipo', () => {
      localStorage.setItem(CLAVE_DISPOSITIVO, 'equipo-existente');
      expect(sesion.dispositivoId()).toBe('equipo-existente');
    });

    it('dos equipos distintos (localStorage vacío) reciben identificadores distintos', () => {
      const a = sesion.dispositivoId();
      localStorage.clear();
      arrancar();
      const b = sesion.dispositivoId();
      expect(b).toMatch(UUID);
      expect(b).not.toBe(a);
    });

    it('sin localStorage genera uno en memoria y lo mantiene mientras viva el servicio', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('sin almacenamiento');
      });
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('sin almacenamiento');
      });
      const id = sesion.dispositivoId();
      expect(id).toMatch(UUID);
      expect(sesion.dispositivoId()).toBe(id);
    });
  });

  describe('alIniciarSesion', () => {
    it('guarda el perfil del usuario (roles y permisos) en su empresa y recuerda la última empresa', async () => {
      const usuario = usuarioYo(5, 7);
      await sesion.alIniciarSesion(usuario);

      expect(await repo(7, 5).perfilGuardado()).toEqual(usuario);
      expect(await sesion.perfilGuardado(7, 5)).toEqual(usuario);
      expect(localStorage.getItem(CLAVE_ULTIMA_EMPRESA)).toBe('7');
    });

    it('el perfil de un usuario no se lee con otro usuario ni desde otra empresa', async () => {
      await sesion.alIniciarSesion(usuarioYo(5, 7));
      expect(await sesion.perfilGuardado(7, 6)).toBeUndefined();
      expect(await sesion.perfilGuardado(8, 5)).toBeUndefined();
    });

    it('perfilGuardado devuelve undefined si nunca se guardó', async () => {
      expect(await sesion.perfilGuardado(7, 5)).toBeUndefined();
    });

    it('volver a entrar en la MISMA empresa no vacía el catálogo', async () => {
      await sesion.alIniciarSesion(usuarioYo(5, 7));
      await sembrarProducto(7, 1);
      await sembrarCliente(7, 1);
      await repo(7, 5).guardarMeta(META_ULTIMA_DESCARGA, '2026-10-30T10:00:00Z');

      await sesion.alIniciarSesion(usuarioYo(6, 7));

      expect(await repo(7, 5).hayCatalogo()).toBe(true);
      expect(await repo(7, 5).ultimaDescarga()).toBe('2026-10-30T10:00:00Z');
      expect((await repo(7, 5).clientes()).length).toBe(1);
    });

    it('cambiar de empresa vacía el catálogo de la anterior pero NO sus operaciones', async () => {
      await sesion.alIniciarSesion(usuarioYo(5, 7));
      await sembrarProducto(7, 1);
      await sembrarCliente(7, 1);
      await repo(7, 5).guardarMeta(META_ULTIMA_DESCARGA, '2026-10-30T10:00:00Z');
      await sembrarOperacion(7, 5, 'op-empresa-7');
      // La otra empresa ya tenía su propio catálogo: no se toca (solo se vacía la anterior).
      await sembrarProducto(8, 90);

      await sesion.alIniciarSesion(usuarioYo(9, 8));

      expect(await repo(7, 5).hayCatalogo()).toBe(false);
      expect(await repo(7, 5).ultimaDescarga()).toBeUndefined();
      expect(await repo(7, 5).clientes()).toEqual([]);
      expect(await db.operaciones_pendientes.get([7, 'op-empresa-7'])).toBeDefined();
      expect(await repo(8, 9).hayCatalogo()).toBe(true);
      expect(await repo(8, 9).perfilGuardado()).toEqual(usuarioYo(9, 8));
      expect(localStorage.getItem(CLAVE_ULTIMA_EMPRESA)).toBe('8');
    });

    it('al volver a la empresa anterior, la de en medio es la que se vacía', async () => {
      await sesion.alIniciarSesion(usuarioYo(5, 7));
      await sesion.alIniciarSesion(usuarioYo(9, 8));
      await sembrarProducto(8, 1);
      await sesion.alIniciarSesion(usuarioYo(5, 7));
      expect(await repo(8, 9).hayCatalogo()).toBe(false);
      expect(localStorage.getItem(CLAVE_ULTIMA_EMPRESA)).toBe('7');
    });

    it('el superadministrador sin empresa no guarda nada', async () => {
      await sesion.alIniciarSesion(usuarioYo(1, null, ['superadministrador']));
      expect(await db.meta.count()).toBe(0);
      expect(localStorage.getItem(CLAVE_ULTIMA_EMPRESA)).toBeNull();
    });

    it('un superadministrador actuando sobre una empresa tampoco guarda nada', async () => {
      await sesion.alIniciarSesion(usuarioYo(1, 7, ['superadministrador']));
      expect(await db.meta.count()).toBe(0);
      expect(localStorage.getItem(CLAVE_ULTIMA_EMPRESA)).toBeNull();
    });

    it('un comprador de la tienda (solo rol cliente) no guarda su perfil ni vacía el catálogo de otra empresa', async () => {
      await sesion.alIniciarSesion(usuarioYo(5, 7));
      await sembrarProducto(7, 1);
      const metaAntes = await db.meta.count();

      await sesion.alIniciarSesion(usuarioYo(9, 8, ['cliente']));

      expect(await db.meta.count()).toBe(metaAntes);
      expect(await repo(7, 5).hayCatalogo()).toBe(true);
      expect(await sesion.perfilGuardado(8, 9)).toBeUndefined();
      expect(localStorage.getItem(CLAVE_ULTIMA_EMPRESA)).toBe('7');
    });

    it('un usuario sin empresa_id definido no guarda nada', async () => {
      const sinEmpresa = { ...usuarioYo(5, 7) } as Partial<UsuarioYo>;
      delete sinEmpresa.empresa_id;
      await sesion.alIniciarSesion(sinEmpresa as UsuarioYo);
      expect(await db.meta.count()).toBe(0);
    });

    it('si falla vaciar la empresa anterior, la última empresa NO se actualiza (se reintenta la próxima vez)', async () => {
      await sesion.alIniciarSesion(usuarioYo(5, 7));
      vi.spyOn(RepositorioLocal.prototype, 'vaciarReferencia').mockRejectedValueOnce(new Error('fallo de IndexedDB'));

      await expect(sesion.alIniciarSesion(usuarioYo(9, 8))).rejects.toThrow('fallo de IndexedDB');
      expect(localStorage.getItem(CLAVE_ULTIMA_EMPRESA)).toBe('7');
      expect(await sesion.perfilGuardado(8, 9)).toBeUndefined();
    });
  });

  describe('alCerrarSesion', () => {
    beforeEach(() => {
      usuarioSesion.set(usuarioYo(5, 7));
    });

    it('borra los clientes y el perfil de ESE usuario, y conserva catálogo, stock y operaciones', async () => {
      await sesion.alIniciarSesion(usuarioYo(5, 7));
      await sesion.alIniciarSesion(usuarioYo(6, 7)); // otro usuario de la misma empresa en el mismo equipo
      await sembrarProducto(7, 1);
      await db.stock_conocido.put({ empresa_id: 7, variante_id: 1, sucursal_id: 1, cantidad: 4, generado_en: '2026-10-30T10:00:00Z' });
      await sembrarCliente(7, 1);
      await sembrarCliente(8, 1); // de otra empresa
      await repo(7, 5).guardarMeta(META_ULTIMA_DESCARGA, '2026-10-30T10:00:00Z');
      await sembrarOperacion(7, 5, 'op-propia');
      await sembrarOperacion(7, 6, 'op-del-otro-usuario');

      await sesion.alCerrarSesion();

      expect(await repo(7, 5).clientes()).toEqual([]);
      expect(await sesion.perfilGuardado(7, 5)).toBeUndefined();
      // Lo que se conserva (D31).
      expect(await repo(7, 5).hayCatalogo()).toBe(true);
      expect(await repo(7, 5).ultimaDescarga()).toBe('2026-10-30T10:00:00Z');
      expect(await db.stock_conocido.count()).toBe(1);
      expect(await db.operaciones_pendientes.get([7, 'op-propia'])).toBeDefined();
      expect(await db.operaciones_pendientes.get([7, 'op-del-otro-usuario'])).toBeDefined();
      // Lo ajeno: el perfil del otro usuario y los clientes de otra empresa.
      expect(await sesion.perfilGuardado(7, 6)).toEqual(usuarioYo(6, 7));
      expect((await repo(8, 5).clientes()).length).toBe(1);
    });

    it('toma el alcance al invocarla: limpia aunque el usuario se borre justo después', async () => {
      await sesion.alIniciarSesion(usuarioYo(5, 7));
      await sembrarCliente(7, 1);

      const terminada = sesion.alCerrarSesion();
      usuarioSesion.set(null); // lo que hace AuthService.logout() a continuación
      await terminada;

      expect(await repo(7, 5).clientes()).toEqual([]);
      expect(await sesion.perfilGuardado(7, 5)).toBeUndefined();
    });

    it('sin sesión (sin alcance) no toca nada ni lanza', async () => {
      await sesion.alIniciarSesion(usuarioYo(5, 7));
      await sembrarCliente(7, 1);
      usuarioSesion.set(null);

      await expect(sesion.alCerrarSesion()).resolves.toBeUndefined();

      expect((await repo(7, 5).clientes()).length).toBe(1);
      expect(await sesion.perfilGuardado(7, 5)).toBeDefined();
    });

    it('el superadministrador no tiene alcance: no toca nada', async () => {
      await sembrarCliente(7, 1);
      usuarioSesion.set(usuarioYo(1, null, ['superadministrador']));

      await sesion.alCerrarSesion();

      expect((await repo(7, 5).clientes()).length).toBe(1);
    });
  });

  describe('sucursal de caja recordada (E14b: reabrir Caja sin red)', () => {
    it('la guarda y la lee para la sesión actual (solo el número, ningún dato personal)', async () => {
      usuarioSesion.set(usuarioYo(5, 7));

      await sesion.guardarSucursalDeCaja(10);

      expect(await sesion.sucursalDeCajaGuardada()).toBe(10);
      expect(await repo(7, 5).leerMeta(metaSucursalCaja(5))).toBe(10);
    });

    it('es de cada persona: otro usuario de la misma empresa no la ve', async () => {
      usuarioSesion.set(usuarioYo(5, 7));
      await sesion.guardarSucursalDeCaja(10);

      usuarioSesion.set(usuarioYo(6, 7));

      expect(await sesion.sucursalDeCajaGuardada()).toBeNull();
    });

    it('sin sesión o siendo superadministrador no guarda ni devuelve nada', async () => {
      usuarioSesion.set(null);
      await sesion.guardarSucursalDeCaja(10);
      expect(await sesion.sucursalDeCajaGuardada()).toBeNull();

      usuarioSesion.set(usuarioYo(1, null, ['superadministrador']));
      await sesion.guardarSucursalDeCaja(10);
      expect(await db.meta.count()).toBe(0);
    });
  });

  describe('alcance y repositorio (lo que ya existía)', () => {
    it('sin sesión no hay alcance ni repositorio', () => {
      expect(sesion.alcance()).toBeNull();
      expect(sesion.repositorio()).toBeNull();
    });

    it('con sesión de empresa, el alcance es empresa y usuario', () => {
      usuarioSesion.set(usuarioYo(5, 7));
      expect(sesion.alcance()).toEqual({ empresaId: 7, usuarioId: 5 });
      expect(sesion.repositorio()?.alcance).toEqual({ empresaId: 7, usuarioId: 5 });
    });

    it('el superadministrador no tiene alcance', () => {
      usuarioSesion.set(usuarioYo(1, null, ['superadministrador']));
      expect(sesion.alcance()).toBeNull();
    });
  });
});
