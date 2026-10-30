import Dexie, { type Table } from 'dexie';
import type { BaseOffline } from './db-offline';
import {
  META_EMPRESA,
  META_REGLAS,
  META_SUCURSALES_STOCK,
  META_ULTIMA_DESCARGA,
  META_UMBRAL_HORAS,
  LIMITE_BUSQUEDA_LOCAL,
  metaPerfil,
} from './offline.config';
import type {
  AlcanceOffline,
  EstadoOperacion,
  FilaCategoria,
  FilaCliente,
  FilaColor,
  FilaProducto,
  FilaStock,
  FilaSucursal,
  FilaTalla,
  FilaVariante,
  FiltroOperaciones,
  OperacionOffline,
  PaqueteLocal,
  ProductoLocal,
  ResultadoSync,
  VarianteLocal,
} from './offline.models';
import { normalizarTexto } from './normalizar';

/** Los únicos campos de una operación que se pueden cambiar después de registrarla. */
export type CambiosOperacion = Partial<
  Pick<
    OperacionOffline,
    'estado' | 'motivo' | 'mensaje' | 'resultado' | 'ultimo_error' | 'proximo_intento_en' | 'bloqueada' | 'intentos' | 'ultimo_intento_en'
  >
>;

/**
 * Todas las filas de una empresa en una tabla cuya clave (o índice) empieza por `empresa_id`, sea de 2 o de 3 partes.
 * El rango va de `[empresa]` (un prefijo ordena antes que cualquier clave más larga) a `[empresa, maxKey]`: así no se
 * depende de centinelas en cada parte de la clave (con 3 partes algunas implementaciones de IndexedDB lo rechazan).
 */
function deLaEmpresa<T>(tabla: Table<T, any>, indice: string, empresaId: number, _partes?: number): ReturnType<Table<T>['where']> {
  return tabla.where(indice).between([empresaId], [empresaId, Dexie.maxKey], true, true) as ReturnType<Table<T>['where']>;
}

/**
 * La ÚNICA clase que toca las tablas de IndexedDB. Se construye con un alcance obligatorio (empresa y usuario) y todas
 * sus consultas lo aplican: ni un componente ni un servicio recibe nunca una tabla ni una consulta sin empresa.
 *
 * Las operaciones locales (ventas y reservas, E14b) se registran y cambian de estado, pero NO existe un método para
 * borrarlas (D13, "una operación no desaparece por intentar enviarla").
 */
export class RepositorioLocal {
  constructor(
    private readonly db: BaseOffline,
    readonly alcance: AlcanceOffline,
  ) {
    if (!Number.isInteger(alcance?.empresaId) || !Number.isInteger(alcance?.usuarioId)) {
      throw new Error('No se puede usar el almacenamiento local sin empresa y usuario.');
    }
  }

  private get empresaId(): number {
    return this.alcance.empresaId;
  }

  // ---- Meta ----------------------------------------------------------------------------------------------------------------

  async leerMeta<T = unknown>(clave: string): Promise<T | undefined> {
    const fila = await this.db.meta.get([this.empresaId, clave]);
    return fila?.valor as T | undefined;
  }

  async guardarMeta(clave: string, valor: unknown): Promise<void> {
    await this.db.meta.put({ empresa_id: this.empresaId, clave, valor });
  }

  async borrarMeta(clave: string): Promise<void> {
    await this.db.meta.delete([this.empresaId, clave]);
  }

  // ---- Perfil del usuario (para reabrir la app sin red) --------------------------------------------------------------------

  async guardarPerfil<T>(perfil: T): Promise<void> {
    await this.guardarMeta(metaPerfil(this.alcance.usuarioId), perfil);
  }

  async perfilGuardado<T>(): Promise<T | undefined> {
    return this.leerMeta<T>(metaPerfil(this.alcance.usuarioId));
  }

  async borrarPerfil(): Promise<void> {
    await this.borrarMeta(metaPerfil(this.alcance.usuarioId));
  }

  // ---- Reemplazo y borrado de lo que viene del servidor ---------------------------------------------------------------------

  /**
   * Deja los datos de referencia de la empresa EXACTAMENTE como dice el paquete, en UNA transacción: si algo falla a la
   * mitad (cuota llena, error de escritura), IndexedDB deshace todo y queda el paquete anterior intacto.
   */
  async reemplazarReferencia(paquete: PaqueteLocal): Promise<void> {
    const e = this.empresaId;
    const filasProducto: FilaProducto[] = paquete.productos.map((p) => ({
      empresa_id: e,
      id: p.id,
      codigo: p.codigo,
      nombre: p.nombre,
      nombre_norm: normalizarTexto(p.nombre),
      categoria_id: p.categoria_id,
      genero: p.genero,
      temporada_id: p.temporada_id,
      imagen_principal: p.imagen_principal,
    }));
    const filasVariante: FilaVariante[] = paquete.productos.flatMap((p) =>
      p.variantes.map((v) => ({
        empresa_id: e,
        id: v.id,
        producto_id: p.id,
        talla_id: v.talla_id,
        color_id: v.color_id,
        sku: v.sku,
        codigo_barras: v.codigo_barras,
        precio: v.precio,
        descuento_unitario: v.descuento_unitario,
      })),
    );
    const filasStock: FilaStock[] = paquete.stock.flatMap((s) =>
      s.items.map((i) => ({
        empresa_id: e,
        variante_id: i.variante_id,
        sucursal_id: s.sucursalId,
        cantidad: i.cantidad_disponible,
        generado_en: s.generadoEn,
      })),
    );
    const filasCliente: FilaCliente[] = paquete.clientes.map((c) => ({
      empresa_id: e,
      id: c.id,
      nombre: c.nombre,
      apellido: c.apellido,
      ci_nit: c.ci_nit,
      nombre_norm: normalizarTexto(`${c.nombre} ${c.apellido}`),
    }));

    const db = this.db;
    await db.transaction(
      'rw',
      [db.meta, db.sucursales, db.categorias, db.tallas, db.colores, db.productos, db.variantes, db.stock_conocido, db.clientes_minimos],
      async () => {
        await this.borrarReferenciaEnTransaccion();
        await db.sucursales.bulkPut(paquete.sucursales.map((s) => ({ ...s, empresa_id: e })));
        await db.categorias.bulkPut(paquete.categorias.map((c) => ({ ...c, empresa_id: e })));
        await db.tallas.bulkPut(paquete.tallas.map((t) => ({ ...t, empresa_id: e })));
        await db.colores.bulkPut(paquete.colores.map((c) => ({ ...c, empresa_id: e })));
        await db.productos.bulkPut(filasProducto);
        await db.variantes.bulkPut(filasVariante);
        await db.stock_conocido.bulkPut(filasStock);
        await db.clientes_minimos.bulkPut(filasCliente);
        await db.meta.bulkPut([
          { empresa_id: e, clave: META_ULTIMA_DESCARGA, valor: paquete.generadoEn },
          { empresa_id: e, clave: META_EMPRESA, valor: paquete.empresa },
          { empresa_id: e, clave: META_UMBRAL_HORAS, valor: paquete.avisoDesactualizadoHoras },
          { empresa_id: e, clave: META_REGLAS, valor: paquete.reglas },
          { empresa_id: e, clave: META_SUCURSALES_STOCK, valor: paquete.stock.map((s) => s.sucursalId) },
        ]);
      },
    );
  }

  private async borrarReferenciaEnTransaccion(): Promise<void> {
    const e = this.empresaId;
    const db = this.db;
    await deLaEmpresa(db.sucursales, '[empresa_id+id]', e, 2).delete();
    await deLaEmpresa(db.categorias, '[empresa_id+id]', e, 2).delete();
    await deLaEmpresa(db.tallas, '[empresa_id+id]', e, 2).delete();
    await deLaEmpresa(db.colores, '[empresa_id+id]', e, 2).delete();
    await deLaEmpresa(db.productos, '[empresa_id+id]', e, 2).delete();
    await deLaEmpresa(db.variantes, '[empresa_id+id]', e, 2).delete();
    await deLaEmpresa(db.stock_conocido, '[empresa_id+variante_id+sucursal_id]', e, 3).delete();
    await deLaEmpresa(db.clientes_minimos, '[empresa_id+id]', e, 2).delete();
  }

  /** Borra el catálogo, el stock y los clientes de la empresa y su meta de descarga. NO toca las operaciones. */
  async vaciarReferencia(): Promise<void> {
    const db = this.db;
    await db.transaction(
      'rw',
      [db.meta, db.sucursales, db.categorias, db.tallas, db.colores, db.productos, db.variantes, db.stock_conocido, db.clientes_minimos],
      async () => {
        await this.borrarReferenciaEnTransaccion();
        for (const clave of [META_ULTIMA_DESCARGA, META_EMPRESA, META_UMBRAL_HORAS, META_REGLAS, META_SUCURSALES_STOCK]) {
          await db.meta.delete([this.empresaId, clave]);
        }
      },
    );
  }

  /** Borra solo los clientes (datos personales): se hace al cerrar sesión. */
  async vaciarClientes(): Promise<void> {
    await deLaEmpresa(this.db.clientes_minimos, '[empresa_id+id]', this.empresaId, 2).delete();
  }

  // ---- Consultas ---------------------------------------------------------------------------------------------------------

  async hayCatalogo(): Promise<boolean> {
    return (await deLaEmpresa(this.db.productos, '[empresa_id+id]', this.empresaId, 2).count()) > 0;
  }

  /** Cuándo (ISO, hora del servidor) se descargó por última vez el paquete de esta empresa. */
  async ultimaDescarga(): Promise<string | undefined> {
    return this.leerMeta<string>(META_ULTIMA_DESCARGA);
  }

  async umbralHoras(): Promise<number | undefined> {
    return this.leerMeta<number>(META_UMBRAL_HORAS);
  }

  sucursales(): Promise<FilaSucursal[]> {
    return deLaEmpresa(this.db.sucursales, '[empresa_id+id]', this.empresaId, 2).toArray();
  }

  categorias(): Promise<FilaCategoria[]> {
    return deLaEmpresa(this.db.categorias, '[empresa_id+id]', this.empresaId, 2).toArray();
  }

  tallas(): Promise<FilaTalla[]> {
    return deLaEmpresa(this.db.tallas, '[empresa_id+id]', this.empresaId, 2).toArray();
  }

  colores(): Promise<FilaColor[]> {
    return deLaEmpresa(this.db.colores, '[empresa_id+id]', this.empresaId, 2).toArray();
  }

  /**
   * Productos que coinciden con el texto (nombre, código, SKU o código de barras de alguna variante) y la categoría,
   * con sus variantes, tallas, colores y el stock conocido por sucursal. Sin texto, todos. Ordenados por nombre.
   */
  async buscarProductos(texto = '', categoriaId?: number | null, limite: number = LIMITE_BUSQUEDA_LOCAL): Promise<ProductoLocal[]> {
    const e = this.empresaId;
    const busqueda = normalizarTexto(texto);
    const [productos, variantes, categorias, tallas, colores, stock] = await Promise.all([
      deLaEmpresa(this.db.productos, '[empresa_id+id]', e, 2).toArray(),
      deLaEmpresa(this.db.variantes, '[empresa_id+id]', e, 2).toArray(),
      this.categorias(),
      this.tallas(),
      this.colores(),
      deLaEmpresa(this.db.stock_conocido, '[empresa_id+variante_id+sucursal_id]', e, 3).toArray(),
    ]);
    const categoriaPorId = new Map(categorias.map((c) => [c.id, c.nombre]));
    const tallaPorId = new Map(tallas.map((t) => [t.id, t.codigo]));
    const colorPorId = new Map(colores.map((c) => [c.id, c]));
    const stockPorVariante = new Map<number, Record<number, number>>();
    for (const s of stock) {
      const porSucursal = stockPorVariante.get(s.variante_id) ?? {};
      porSucursal[s.sucursal_id] = s.cantidad;
      stockPorVariante.set(s.variante_id, porSucursal);
    }
    const variantesPorProducto = new Map<number, VarianteLocal[]>();
    for (const v of variantes) {
      const color = colorPorId.get(v.color_id);
      const local: VarianteLocal = {
        ...v,
        talla: tallaPorId.get(v.talla_id) ?? null,
        color: color?.nombre ?? null,
        color_hex: color?.codigo_hex ?? null,
        stock: stockPorVariante.get(v.id) ?? {},
      };
      const lista = variantesPorProducto.get(v.producto_id) ?? [];
      lista.push(local);
      variantesPorProducto.set(v.producto_id, lista);
    }

    const resultado: ProductoLocal[] = [];
    for (const p of productos) {
      if (categoriaId != null && p.categoria_id !== categoriaId) continue;
      const suyas = variantesPorProducto.get(p.id) ?? [];
      if (busqueda) {
        const coincide =
          p.nombre_norm.includes(busqueda) ||
          normalizarTexto(p.codigo).includes(busqueda) ||
          suyas.some((v) => normalizarTexto(v.sku).includes(busqueda) || (v.codigo_barras ?? '').includes(texto.trim()));
        if (!coincide) continue;
      }
      resultado.push({ ...p, categoria: categoriaPorId.get(p.categoria_id) ?? null, variantes: suyas });
    }
    resultado.sort((a, b) => a.nombre_norm.localeCompare(b.nombre_norm));
    return resultado.slice(0, limite);
  }

  /** Un producto por id (con variantes y stock), o undefined si no está en el paquete. */
  async producto(id: number): Promise<ProductoLocal | undefined> {
    const todos = await this.buscarProductos('', null, Number.MAX_SAFE_INTEGER);
    return todos.find((p) => p.id === id);
  }

  /** Stock conocido de una variante por sucursal (`sucursal_id` -> unidades). */
  async stockDeVariante(varianteId: number): Promise<Record<number, number>> {
    const filas = await this.db.stock_conocido
      .where('[empresa_id+variante_id+sucursal_id]')
      .between([this.empresaId, varianteId], [this.empresaId, varianteId, Dexie.maxKey], true, true)
      .toArray();
    return Object.fromEntries(filas.map((f) => [f.sucursal_id, f.cantidad]));
  }

  /** Una variante con su producto, talla y color, y el stock conocido por sucursal (para armar una línea de venta). */
  async varianteDetalle(varianteId: number): Promise<{ variante: VarianteLocal; producto: FilaProducto } | undefined> {
    const e = this.empresaId;
    const variante = await this.db.variantes.get([e, varianteId]);
    if (!variante) return undefined;
    const [producto, talla, color, stock] = await Promise.all([
      this.db.productos.get([e, variante.producto_id]),
      this.db.tallas.get([e, variante.talla_id]),
      this.db.colores.get([e, variante.color_id]),
      this.stockDeVariante(varianteId),
    ]);
    if (!producto) return undefined;
    return {
      producto,
      variante: { ...variante, talla: talla?.codigo ?? null, color: color?.nombre ?? null, color_hex: color?.codigo_hex ?? null, stock },
    };
  }

  /** El stock conocido de UNA variante en UNA sucursal y cuándo lo leyó el servidor (no hay fila = no se conoce). */
  stockConocido(varianteId: number, sucursalId: number): Promise<FilaStock | undefined> {
    return this.db.stock_conocido.get([this.empresaId, varianteId, sucursalId]);
  }

  // ---- Operaciones hechas sin conexión (E14b) ---------------------------------------------------------------------------
  // Aquí NO hay (ni habrá) un método para borrar: una operación solo cambia de estado (D13). Las consultas son SIEMPRE de
  // la empresa y del usuario del alcance: nadie ve ni envía las de otro usuario del mismo equipo.

  private operacionesDeMiUsuario(): Promise<OperacionOffline[]> {
    const { empresaId: e, usuarioId: u } = this.alcance;
    return this.db.operaciones_pendientes
      .where('[empresa_id+usuario_id+fecha_operacion]')
      .between([e, u], [e, u, Dexie.maxKey], true, true)
      .toArray() as unknown as Promise<OperacionOffline[]>;
  }

  /**
   * Guarda una operación NUEVA. Si ya existe una con el mismo `operacion_id` (doble clic, reintento), devuelve la que
   * ya estaba y NO crea otra (idempotencia local). Es una sola transacción: si falla, no queda nada a medias.
   */
  async registrarOperacion(operacion: OperacionOffline): Promise<OperacionOffline> {
    if (operacion.empresa_id !== this.empresaId || operacion.usuario_id !== this.alcance.usuarioId) {
      throw new Error('La operación no corresponde a la empresa y el usuario de esta sesión.');
    }
    return this.db.transaction('rw', this.db.operaciones_pendientes, async () => {
      const existente = await this.db.operaciones_pendientes.get([this.empresaId, operacion.operacion_id]);
      if (existente) return existente as OperacionOffline;
      await this.db.operaciones_pendientes.add(operacion);
      return operacion;
    });
  }

  /** Una operación de MI usuario por id (las de otro usuario o de otra empresa no se ven). */
  async operacion(operacionId: string): Promise<OperacionOffline | undefined> {
    const fila = (await this.db.operaciones_pendientes.get([this.empresaId, operacionId])) as OperacionOffline | undefined;
    return fila && fila.usuario_id === this.alcance.usuarioId ? fila : undefined;
  }

  /** Mis operaciones, de la más nueva a la más vieja, con los filtros de la pantalla de pendientes. */
  async misOperaciones(filtro: FiltroOperaciones = {}): Promise<OperacionOffline[]> {
    const texto = normalizarTexto(filtro.texto);
    const todas = await this.operacionesDeMiUsuario();
    return todas
      .filter((o) => {
        if (filtro.estado && o.estado !== filtro.estado) return false;
        if (filtro.tipo && o.tipo !== filtro.tipo) return false;
        if (filtro.sucursalId != null && o.sucursal_id !== filtro.sucursalId) return false;
        const dia = o.fecha_operacion.slice(0, 10);
        if (filtro.desde && dia < filtro.desde) return false;
        if (filtro.hasta && dia > filtro.hasta) return false;
        if (texto && !normalizarTexto(`${o.codigo_local} ${o.cliente_nombre ?? ''}`).includes(texto)) return false;
        return true;
      })
      .sort((a, b) => Date.parse(b.fecha_operacion) - Date.parse(a.fecha_operacion));
  }

  /** Cuántas operaciones mías hay en cada estado. */
  async contarPorEstado(): Promise<Record<EstadoOperacion, number>> {
    const conteo: Record<EstadoOperacion, number> = { registrada: 0, enviada: 0, confirmada: 0, rechazada: 0, en_conflicto: 0 };
    for (const operacion of await this.operacionesDeMiUsuario()) conteo[operacion.estado] += 1;
    return conteo;
  }

  /** Cuántas operaciones sin enviar tienen OTROS usuarios de la misma empresa en este equipo (no se envían desde esta sesión). */
  async pendientesDeOtrosUsuarios(): Promise<number> {
    const todas = await deLaEmpresa(this.db.operaciones_pendientes, '[empresa_id+operacion_id]', this.empresaId, 2).toArray();
    return todas.filter((o) => o.usuario_id !== this.alcance.usuarioId && (o.estado === 'registrada' || o.estado === 'enviada')).length;
  }

  /**
   * Lo que toca enviar ahora: mis operaciones `registrada` no bloqueadas cuya espera ya pasó (o todas, si el envío es
   * manual) y las `enviada` que llevan más de `huerfanasMs` (un cierre brusco las dejó a medias). Las más antiguas
   * primero (D14), hasta `max`.
   */
  async operacionesParaEnviar(opciones: { max: number; ahora: string; ignorarEspera?: boolean; huerfanasMs: number }): Promise<OperacionOffline[]> {
    const ahora = Date.parse(opciones.ahora);
    const elegibles = (await this.operacionesDeMiUsuario()).filter((o) => {
      if (o.estado === 'registrada') {
        if (o.bloqueada) return false;
        if (opciones.ignorarEspera || !o.proximo_intento_en) return true;
        return Date.parse(o.proximo_intento_en) <= ahora;
      }
      if (o.estado === 'enviada') {
        return !o.ultimo_intento_en || ahora - Date.parse(o.ultimo_intento_en) > opciones.huerfanasMs;
      }
      return false;
    });
    return elegibles.sort((a, b) => Date.parse(a.fecha_operacion) - Date.parse(b.fecha_operacion)).slice(0, opciones.max);
  }

  /** Antes de enviar: pasa las operaciones a `enviada`, suma un intento y anota la hora (una sola transacción). */
  async marcarEnviadas(operacionIds: string[], ahora: string): Promise<void> {
    await this.db.transaction('rw', this.db.operaciones_pendientes, async () => {
      for (const id of operacionIds) {
        const actual = await this.operacion(id);
        if (!actual || (actual.estado !== 'registrada' && actual.estado !== 'enviada')) continue;
        await this.db.operaciones_pendientes.update([this.empresaId, id], {
          estado: 'enviada',
          intentos: actual.intentos + 1,
          ultimo_intento_en: ahora,
        });
      }
    });
  }

  /**
   * Cambia SOLO los campos permitidos de una operación mía. `confirmada` y `rechazada` son finales: intentar cambiarles
   * el estado es un error (la misma respuesta repetida no cambia nada). Ningún camino la borra.
   */
  async actualizarOperacion(operacionId: string, cambios: CambiosOperacion): Promise<OperacionOffline> {
    const permitidos: (keyof CambiosOperacion)[] = [
      'estado', 'motivo', 'mensaje', 'resultado', 'ultimo_error', 'proximo_intento_en', 'bloqueada', 'intentos', 'ultimo_intento_en',
    ];
    const limpios: Record<string, unknown> = {};
    for (const clave of permitidos) {
      if (clave in cambios) limpios[clave] = cambios[clave];
    }
    return this.db.transaction('rw', this.db.operaciones_pendientes, async () => {
      const actual = await this.operacion(operacionId);
      if (!actual) throw new Error('No existe esa operación en este equipo.');
      const nuevo = limpios['estado'] as EstadoOperacion | undefined;
      if (nuevo && nuevo !== actual.estado && (actual.estado === 'confirmada' || actual.estado === 'rechazada')) {
        throw new Error(`Una operación ${actual.estado} ya no puede cambiar de estado.`);
      }
      await this.db.operaciones_pendientes.update([this.empresaId, operacionId], limpios);
      return { ...actual, ...limpios } as OperacionOffline;
    });
  }

  /** Anota un intento de envío (fecha, respuesta del servidor y motivo) para diagnóstico. */
  async registrarIntento(intento: Omit<ResultadoSync, 'id' | 'empresa_id'>): Promise<void> {
    await this.db.resultados_sync.add({ ...intento, empresa_id: this.empresaId });
  }

  /** Los intentos de envío de una operación, del más viejo al más nuevo. */
  async intentosDe(operacionId: string): Promise<ResultadoSync[]> {
    const filas = await this.db.resultados_sync.where('[empresa_id+operacion_id]').equals([this.empresaId, operacionId]).toArray();
    return filas.sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
  }

  /** Clientes por nombre, apellido o CI/NIT (sin texto, los primeros). */
  async clientes(texto = '', limite: number = LIMITE_BUSQUEDA_LOCAL): Promise<FilaCliente[]> {
    const busqueda = normalizarTexto(texto);
    const todos = await deLaEmpresa(this.db.clientes_minimos, '[empresa_id+id]', this.empresaId, 2).toArray();
    const filtrados = busqueda
      ? todos.filter((c) => c.nombre_norm.includes(busqueda) || (c.ci_nit ?? '').toLowerCase().includes(busqueda))
      : todos;
    return filtrados.sort((a, b) => a.nombre_norm.localeCompare(b.nombre_norm)).slice(0, limite);
  }
}
