import { Injectable, inject } from '@angular/core';
import { aCentavos, centavosATexto, fechaConDesfase, subtotalEnCentavos } from './dinero-offline';
import type { FaltanteLocal, LineaOperacionLocal, OperacionOffline } from './offline.models';
import { SesionOfflineService } from './sesion-offline.service';
import { stockDisponibleLocal } from './stock-local';

/** Una prenda y cuántas unidades; el PRECIO sale de lo descargado, nunca de quien llama (D17). */
export interface EntradaLinea {
  varianteId: number;
  cantidad: number;
}

export interface EntradaVenta {
  sucursalId: number;
  lineas: EntradaLinea[];
  /** Con cuánto paga el cliente, en efectivo (texto o número). */
  montoRecibido: string | number;
  clienteId?: number | null;
  clienteNombre?: string | null;
  /** Si no se manda se crea uno. Reusa el MISMO al reintentar tras un aviso: así un doble clic no duplica la venta. */
  operacionId?: string;
  /** El usuario ya vio el aviso de "no hay stock local" y decidió seguir. */
  aceptarSinStock?: boolean;
}

export interface EntradaReserva {
  sucursalId: number;
  lineas: EntradaLinea[];
  clienteId: number;
  clienteNombre?: string | null;
  /** AAAA-MM-DD */
  fechaVisita: string;
  /** HH:MM */
  horaDesde: string;
  horaHasta: string;
  observacion?: string | null;
  operacionId?: string;
  aceptarSinStock?: boolean;
}

/** Lo que tienen en común una venta y una reserva al nacer (`Pick` explícito: `OperacionLocal` trae un índice abierto). */
type CamposBase = Pick<
  OperacionOffline,
  | 'empresa_id'
  | 'usuario_id'
  | 'operacion_id'
  | 'sucursal_id'
  | 'tipo'
  | 'estado'
  | 'fecha_operacion'
  | 'creada_en'
  | 'lineas'
  | 'total'
  | 'codigo_local'
  | 'dispositivo'
  | 'intentos'
  | 'ultimo_intento_en'
  | 'proximo_intento_en'
  | 'ultimo_error'
  | 'bloqueada'
  | 'motivo'
  | 'mensaje'
  | 'resultado'
>;

/** Un error pensado para mostrarse tal cual al usuario. */
export class ErrorOperacionOffline extends Error {
  constructor(mensaje: string) {
    super(mensaje);
    this.name = 'ErrorOperacionOffline';
  }
}

/** Según lo descargado no alcanza el stock: la pantalla pregunta si se registra de todos modos (decisión del usuario). */
export class StockLocalInsuficienteError extends ErrorOperacionOffline {
  constructor(readonly faltantes: FaltanteLocal[]) {
    super('Según tu información local no hay stock suficiente. La operación se registrará y puede quedar en conflicto.');
    this.name = 'StockLocalInsuficienteError';
  }
}

const RE_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const RE_FECHA = /^\d{4}-\d{2}-\d{2}$/;
const RE_HORA = /^([01]\d|2[0-3]):[0-5]\d$/;

/** UUID v4 en minúscula: con `crypto.randomUUID` si existe; si no, con `getRandomValues` o, como último recurso, `Math.random`. */
export function generarOperacionId(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID().toLowerCase();
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * Registra ventas de contado y reservas SIN conexión (E14b). Todo se guarda en IndexedDB en una sola transacción; la cola
 * de envío (`ColaSincronizacionService`) las manda cuando hay red. Reglas: solo efectivo (D18), precio y descuento de lo
 * descargado (D17), nunca se borra una operación y repetir el mismo `operacionId` no crea otra.
 */
@Injectable({ providedIn: 'root' })
export class OperacionesOfflineService {
  private readonly sesion = inject(SesionOfflineService);

  nuevoOperacionId(): string {
    return generarOperacionId();
  }

  private repositorio() {
    const repositorio = this.sesion.repositorio();
    if (repositorio === null) throw new ErrorOperacionOffline('Inicia sesión para trabajar sin conexión.');
    return repositorio;
  }

  /** Unidades que se pueden ofrecer ahora de esa prenda en esa sucursal (lo conocido menos lo ya registrado aquí); null = no se conoce. */
  async stockDisponible(varianteId: number, sucursalId: number): Promise<number | null> {
    const repositorio = this.repositorio();
    const conocido = await repositorio.stockConocido(varianteId, sucursalId);
    if (!conocido) return null;
    return stockDisponibleLocal(conocido.cantidad, conocido.generado_en, await repositorio.misOperaciones(), varianteId, sucursalId);
  }

  /** Qué prendas no alcanzan según el stock local (vacío = todo alcanza). Una prenda sin dato de stock cuenta como 0. */
  async verificarStock(sucursalId: number, lineas: EntradaLinea[]): Promise<FaltanteLocal[]> {
    const repositorio = this.repositorio();
    const solicitado = this.consolidar(lineas);
    const faltantes: FaltanteLocal[] = [];
    for (const [varianteId, cantidad] of solicitado) {
      const disponible = Math.max((await this.stockDisponible(varianteId, sucursalId)) ?? 0, 0);
      if (disponible >= cantidad) continue;
      const detalle = await repositorio.varianteDetalle(varianteId);
      faltantes.push({
        variante_id: varianteId,
        producto_nombre: detalle?.producto.nombre ?? `Prenda ${varianteId}`,
        talla: detalle?.variante.talla ?? null,
        color: detalle?.variante.color ?? null,
        solicitado: cantidad,
        disponible,
      });
    }
    return faltantes;
  }

  async registrarVenta(entrada: EntradaVenta): Promise<OperacionOffline> {
    const operacionId = this.validarId(entrada.operacionId);
    const lineas = await this.armarLineas(entrada.lineas);
    const totalCentavos = lineas.reduce((suma, l) => suma + aCentavos(l.subtotal), 0);
    const recibido = aCentavos(entrada.montoRecibido);
    if (!Number.isFinite(recibido) || recibido < totalCentavos) {
      throw new ErrorOperacionOffline('El monto recibido no alcanza para cubrir el total.');
    }
    await this.exigirStockOConfirmacion(entrada.sucursalId, entrada.lineas, entrada.aceptarSinStock);

    return this.guardar({
      ...this.base(operacionId, 'venta_contado', entrada.sucursalId, lineas, totalCentavos),
      cliente_id: entrada.clienteId ?? null,
      cliente_nombre: entrada.clienteNombre ?? null,
      pago: { metodo: 'efectivo', monto_recibido: centavosATexto(recibido), cambio: centavosATexto(recibido - totalCentavos) },
      reserva: null,
    });
  }

  async registrarReserva(entrada: EntradaReserva): Promise<OperacionOffline> {
    const operacionId = this.validarId(entrada.operacionId);
    if (!Number.isInteger(entrada.clienteId) || entrada.clienteId <= 0) {
      throw new ErrorOperacionOffline('Elige el cliente de la reserva.');
    }
    if (!RE_FECHA.test(entrada.fechaVisita)) throw new ErrorOperacionOffline('La fecha de la visita no es válida.');
    if (!RE_HORA.test(entrada.horaDesde) || !RE_HORA.test(entrada.horaHasta)) {
      throw new ErrorOperacionOffline('El horario de la visita no es válido.');
    }
    if (entrada.horaDesde >= entrada.horaHasta) {
      throw new ErrorOperacionOffline('La hora de inicio debe ser anterior a la hora de fin.');
    }
    const lineas = await this.armarLineas(entrada.lineas);
    const totalCentavos = lineas.reduce((suma, l) => suma + aCentavos(l.subtotal), 0);
    await this.exigirStockOConfirmacion(entrada.sucursalId, entrada.lineas, entrada.aceptarSinStock);

    return this.guardar({
      ...this.base(operacionId, 'reserva', entrada.sucursalId, lineas, totalCentavos),
      cliente_id: entrada.clienteId,
      cliente_nombre: entrada.clienteNombre ?? null,
      pago: null,
      reserva: {
        fecha_visita: entrada.fechaVisita,
        hora_visita_desde: entrada.horaDesde,
        hora_visita_hasta: entrada.horaHasta,
        observacion: entrada.observacion?.trim() ? entrada.observacion.trim().slice(0, 300) : null,
      },
    });
  }

  // ---- Interno -----------------------------------------------------------------------------------------------------------

  private validarId(operacionId: string | undefined): string {
    const id = (operacionId ?? this.nuevoOperacionId()).toLowerCase();
    if (!RE_UUID.test(id)) throw new ErrorOperacionOffline('El identificador de la operación no es válido.');
    return id;
  }

  /** Suma las líneas repetidas de una misma prenda y valida las cantidades. */
  private consolidar(lineas: EntradaLinea[]): Map<number, number> {
    if (!Array.isArray(lineas) || lineas.length === 0) throw new ErrorOperacionOffline('Agrega al menos una prenda.');
    const total = new Map<number, number>();
    for (const linea of lineas) {
      if (!Number.isInteger(linea.varianteId) || !Number.isInteger(linea.cantidad) || linea.cantidad <= 0) {
        throw new ErrorOperacionOffline('Las cantidades deben ser números enteros mayores que cero.');
      }
      total.set(linea.varianteId, (total.get(linea.varianteId) ?? 0) + linea.cantidad);
    }
    return total;
  }

  /** Arma las líneas con el precio y el descuento DESCARGADOS (D17), no con lo que mande la pantalla. */
  private async armarLineas(entrada: EntradaLinea[]): Promise<LineaOperacionLocal[]> {
    const repositorio = this.repositorio();
    const lineas: LineaOperacionLocal[] = [];
    for (const [varianteId, cantidad] of this.consolidar(entrada)) {
      const detalle = await repositorio.varianteDetalle(varianteId);
      if (!detalle) throw new ErrorOperacionOffline('Una de las prendas no está en los datos descargados en este equipo.');
      const { variante, producto } = detalle;
      const precio = aCentavos(variante.precio);
      const descuento = aCentavos(variante.descuento_unitario);
      if (!Number.isFinite(precio) || precio < 0 || !Number.isFinite(descuento) || descuento < 0 || descuento > precio) {
        throw new ErrorOperacionOffline(`La prenda ${producto.nombre} no tiene un precio válido en los datos descargados.`);
      }
      lineas.push({
        variante_id: varianteId,
        producto_nombre: producto.nombre,
        sku: variante.sku,
        talla: variante.talla,
        color: variante.color,
        cantidad,
        precio_unitario: centavosATexto(precio),
        descuento_unitario: centavosATexto(descuento),
        subtotal: centavosATexto(subtotalEnCentavos(cantidad, variante.precio, variante.descuento_unitario)),
      });
    }
    return lineas;
  }

  private async exigirStockOConfirmacion(sucursalId: number, lineas: EntradaLinea[], aceptado: boolean | undefined): Promise<void> {
    if (aceptado) return;
    const faltantes = await this.verificarStock(sucursalId, lineas);
    if (faltantes.length > 0) throw new StockLocalInsuficienteError(faltantes);
  }

  private base(
    operacionId: string,
    tipo: 'venta_contado' | 'reserva',
    sucursalId: number,
    lineas: LineaOperacionLocal[],
    totalCentavos: number,
  ): CamposBase {
    const alcance = this.sesion.alcance();
    if (alcance === null) throw new ErrorOperacionOffline('Inicia sesión para trabajar sin conexión.');
    if (!Number.isInteger(sucursalId) || sucursalId <= 0) throw new ErrorOperacionOffline('Elige la sucursal.');
    const ahora = fechaConDesfase();
    return {
      empresa_id: alcance.empresaId,
      usuario_id: alcance.usuarioId,
      operacion_id: operacionId,
      sucursal_id: sucursalId,
      tipo,
      estado: 'registrada',
      fecha_operacion: ahora,
      creada_en: ahora,
      lineas,
      total: centavosATexto(totalCentavos),
      codigo_local: `OFF-${operacionId.slice(0, 6).toUpperCase()}`,
      dispositivo: this.sesion.dispositivoId(),
      intentos: 0,
      ultimo_intento_en: null,
      proximo_intento_en: null,
      ultimo_error: null,
      bloqueada: false,
      motivo: null,
      mensaje: null,
      resultado: null,
    };
  }

  /** Guarda en una transacción. Si no hay espacio o falla la escritura, la operación NO queda registrada y se dice claro. */
  private async guardar(operacion: OperacionOffline): Promise<OperacionOffline> {
    try {
      return await this.repositorio().registrarOperacion(operacion);
    } catch (error) {
      const nombre = (error as { name?: string } | null)?.name;
      if (nombre === 'QuotaExceededError') {
        throw new ErrorOperacionOffline('No hay espacio en este equipo. La operación NO se registró: libera espacio e inténtalo de nuevo.');
      }
      throw new ErrorOperacionOffline('No se pudo guardar la operación en este equipo. NO se registró: inténtalo de nuevo.');
    }
  }
}
