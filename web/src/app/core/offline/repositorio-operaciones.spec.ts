import 'fake-indexeddb/auto';
import { BaseOffline } from './db-offline';
import type { OperacionOffline } from './offline.models';
import { RepositorioLocal } from './repositorio-local';

let contador = 0;

function operacion(id: string, extra: Partial<OperacionOffline> = {}): OperacionOffline {
  return {
    empresa_id: 1,
    usuario_id: 7,
    operacion_id: id,
    sucursal_id: 10,
    tipo: 'venta_contado',
    estado: 'registrada',
    fecha_operacion: '2026-10-30T10:00:00-04:00',
    creada_en: '2026-10-30T10:00:00-04:00',
    cliente_id: null,
    cliente_nombre: null,
    lineas: [],
    total: '100.00',
    pago: { metodo: 'efectivo', monto_recibido: '100.00', cambio: '0.00' },
    reserva: null,
    codigo_local: `OFF-${id.slice(0, 6).toUpperCase()}`,
    dispositivo: 'd1',
    intentos: 0,
    ultimo_intento_en: null,
    proximo_intento_en: null,
    ultimo_error: null,
    bloqueada: false,
    motivo: null,
    mensaje: null,
    resultado: null,
    ...extra,
  };
}

describe('RepositorioLocal: operaciones sin conexión', () => {
  let db: BaseOffline;
  let yo: RepositorioLocal;

  beforeEach(() => {
    db = new BaseOffline(`prueba_repo_operaciones_${++contador}_${Date.now()}`);
    yo = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
  });
  afterEach(() => db.close());

  it('registra una operación y repetir el mismo id devuelve la que ya estaba', async () => {
    const primera = await yo.registrarOperacion(operacion('aaaaaa-1'));
    const repetida = await yo.registrarOperacion(operacion('aaaaaa-1', { total: '999.00' }));

    expect(repetida.total).toBe(primera.total);
    expect(await db.operaciones_pendientes.count()).toBe(1);
  });

  it('rechaza guardar una operación de otra empresa o de otro usuario', async () => {
    await expect(yo.registrarOperacion(operacion('b-1', { empresa_id: 2 }))).rejects.toThrow();
    await expect(yo.registrarOperacion(operacion('b-2', { usuario_id: 8 }))).rejects.toThrow();
    expect(await db.operaciones_pendientes.count()).toBe(0);
  });

  it('NO MEZCLA usuarios ni empresas: cada uno ve solo lo suyo', async () => {
    const otroUsuario = new RepositorioLocal(db, { empresaId: 1, usuarioId: 8 });
    const otraEmpresa = new RepositorioLocal(db, { empresaId: 2, usuarioId: 7 });
    await yo.registrarOperacion(operacion('mia-1'));
    await otroUsuario.registrarOperacion(operacion('suya-1', { usuario_id: 8 }));

    expect((await yo.misOperaciones()).map((o) => o.operacion_id)).toEqual(['mia-1']);
    expect((await otroUsuario.misOperaciones()).map((o) => o.operacion_id)).toEqual(['suya-1']);
    expect(await otraEmpresa.misOperaciones()).toEqual([]);
    expect(await yo.operacion('suya-1')).toBeUndefined();
    expect(await otraEmpresa.operacion('mia-1')).toBeUndefined();
    expect(await yo.pendientesDeOtrosUsuarios()).toBe(1);
    expect(await otroUsuario.pendientesDeOtrosUsuarios()).toBe(1);
  });

  it('filtra por estado, tipo, sucursal, fechas y texto, y ordena de la más nueva a la más vieja', async () => {
    await yo.registrarOperacion(operacion('v-1', { fecha_operacion: '2026-10-28T09:00:00-04:00', codigo_local: 'OFF-AAA111' }));
    await yo.registrarOperacion(
      operacion('r-1', { tipo: 'reserva', estado: 'en_conflicto', sucursal_id: 11, fecha_operacion: '2026-10-30T09:00:00-04:00', cliente_nombre: 'María Pérez' }),
    );
    await yo.registrarOperacion(operacion('v-2', { estado: 'confirmada', fecha_operacion: '2026-10-29T09:00:00-04:00' }));

    expect((await yo.misOperaciones()).map((o) => o.operacion_id)).toEqual(['r-1', 'v-2', 'v-1']);
    expect((await yo.misOperaciones({ estado: 'confirmada' })).map((o) => o.operacion_id)).toEqual(['v-2']);
    expect((await yo.misOperaciones({ tipo: 'reserva' })).map((o) => o.operacion_id)).toEqual(['r-1']);
    expect((await yo.misOperaciones({ sucursalId: 11 })).map((o) => o.operacion_id)).toEqual(['r-1']);
    expect((await yo.misOperaciones({ desde: '2026-10-29', hasta: '2026-10-29' })).map((o) => o.operacion_id)).toEqual(['v-2']);
    expect((await yo.misOperaciones({ texto: 'maria' })).map((o) => o.operacion_id)).toEqual(['r-1']);
    expect((await yo.misOperaciones({ texto: 'aaa111' })).map((o) => o.operacion_id)).toEqual(['v-1']);
  });

  it('cuenta las operaciones por estado', async () => {
    await yo.registrarOperacion(operacion('a-1'));
    await yo.registrarOperacion(operacion('a-2', { estado: 'confirmada' }));
    await yo.registrarOperacion(operacion('a-3', { estado: 'en_conflicto' }));

    expect(await yo.contarPorEstado()).toEqual({ registrada: 1, enviada: 0, confirmada: 1, rechazada: 0, en_conflicto: 1 });
  });

  it('elige para enviar las registradas más antiguas primero, respetando la espera, el bloqueo y el máximo', async () => {
    const ahora = '2026-10-30T12:00:00Z';
    await yo.registrarOperacion(operacion('p-3', { fecha_operacion: '2026-10-30T09:00:00Z' }));
    await yo.registrarOperacion(operacion('p-1', { fecha_operacion: '2026-10-30T07:00:00Z' }));
    await yo.registrarOperacion(operacion('p-2', { fecha_operacion: '2026-10-30T08:00:00Z', proximo_intento_en: '2026-10-30T12:05:00Z' }));
    await yo.registrarOperacion(operacion('p-b', { fecha_operacion: '2026-10-30T06:00:00Z', bloqueada: true }));
    await yo.registrarOperacion(operacion('p-c', { fecha_operacion: '2026-10-30T05:00:00Z', estado: 'confirmada' }));
    const base = { max: 10, ahora, huerfanasMs: 120_000 };

    expect((await yo.operacionesParaEnviar(base)).map((o) => o.operacion_id)).toEqual(['p-1', 'p-3']);
    // El envío manual ignora la espera: entra p-2, y siguen por orden de fecha (D14).
    expect((await yo.operacionesParaEnviar({ ...base, ignorarEspera: true })).map((o) => o.operacion_id)).toEqual(['p-1', 'p-2', 'p-3']);
    expect((await yo.operacionesParaEnviar({ ...base, max: 1 })).map((o) => o.operacion_id)).toEqual(['p-1']);
  });

  it('recupera las `enviada` huérfanas (cierre brusco) solo cuando pasó el tiempo de espera', async () => {
    await yo.registrarOperacion(operacion('h-1', { estado: 'enviada', ultimo_intento_en: '2026-10-30T11:59:00Z' }));
    await yo.registrarOperacion(operacion('h-2', { estado: 'enviada', ultimo_intento_en: '2026-10-30T11:50:00Z' }));
    const opciones = { max: 10, ahora: '2026-10-30T12:00:00Z', huerfanasMs: 120_000 };

    expect((await yo.operacionesParaEnviar(opciones)).map((o) => o.operacion_id)).toEqual(['h-2']);
  });

  it('marca como enviadas, suma el intento y anota la hora', async () => {
    await yo.registrarOperacion(operacion('e-1'));
    await yo.marcarEnviadas(['e-1', 'no-existe'], '2026-10-30T12:00:00Z');

    expect(await yo.operacion('e-1')).toMatchObject({ estado: 'enviada', intentos: 1, ultimo_intento_en: '2026-10-30T12:00:00Z' });
  });

  it('actualiza solo los campos permitidos y una operación final no cambia de estado', async () => {
    await yo.registrarOperacion(operacion('u-1'));
    const cambiada = await yo.actualizarOperacion('u-1', {
      estado: 'confirmada',
      motivo: null,
      mensaje: 'ok',
      // @ts-expect-error: un campo que NO se puede cambiar (el total) se ignora
      total: '0.00',
    });
    expect(cambiada.estado).toBe('confirmada');
    expect((await yo.operacion('u-1'))!.total).toBe('100.00');

    await expect(yo.actualizarOperacion('u-1', { estado: 'registrada' })).rejects.toThrow(/ya no puede cambiar/);
    await expect(yo.actualizarOperacion('u-1', { estado: 'confirmada', mensaje: 'otra vez' })).resolves.toBeDefined();
    await expect(yo.actualizarOperacion('no-existe', { estado: 'rechazada' })).rejects.toThrow();
  });

  it('una operación en conflicto sí puede pasar a confirmada o rechazada (la resuelve el encargado)', async () => {
    await yo.registrarOperacion(operacion('c-1', { estado: 'en_conflicto' }));
    await expect(yo.actualizarOperacion('c-1', { estado: 'confirmada' })).resolves.toMatchObject({ estado: 'confirmada' });
  });

  it('guarda el historial de intentos de cada operación', async () => {
    await yo.registrarOperacion(operacion('i-1'));
    await yo.registrarIntento({ operacion_id: 'i-1', fecha: '2026-10-30T12:00:00Z', http_status: 503, motivo: 'servidor', respuesta: null });
    await yo.registrarIntento({ operacion_id: 'i-1', fecha: '2026-10-30T12:01:00Z', http_status: 200, motivo: null, respuesta: { estado: 'confirmada' } });
    await yo.registrarIntento({ operacion_id: 'otra', fecha: '2026-10-30T12:02:00Z', http_status: 200, motivo: null, respuesta: null });

    expect((await yo.intentosDe('i-1')).map((i) => i.http_status)).toEqual([503, 200]);
  });

  it('NO existe ningún método para borrar operaciones (D13)', () => {
    const metodos = Object.getOwnPropertyNames(RepositorioLocal.prototype);
    expect(metodos.filter((m) => /borrar|eliminar|remove|delete|vaciar/i.test(m) && /operacion|intento|resultado/i.test(m))).toEqual([]);
    // Los únicos que borran son de los datos de referencia, el perfil y la meta: nunca de operaciones.
    expect(metodos.filter((m) => /borrar|eliminar|remove|delete/i.test(m) && !/perfil|meta|referencia/i.test(m))).toEqual([]);
  });

  it('vaciar la referencia o los clientes no toca las operaciones', async () => {
    await yo.registrarOperacion(operacion('k-1'));
    await yo.vaciarReferencia();
    await yo.vaciarClientes();

    expect(await db.operaciones_pendientes.count()).toBe(1);
  });
});
