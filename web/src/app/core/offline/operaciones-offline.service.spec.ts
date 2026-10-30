import 'fake-indexeddb/auto';
import { TestBed } from '@angular/core/testing';
import { aCentavos, centavosATexto, fechaConDesfase, subtotalEnCentavos } from './dinero-offline';
import { BaseOffline } from './db-offline';
import type { OperacionOffline, PaqueteLocal } from './offline.models';
import {
  ErrorOperacionOffline,
  generarOperacionId,
  OperacionesOfflineService,
  StockLocalInsuficienteError,
} from './operaciones-offline.service';
import { RepositorioLocal } from './repositorio-local';
import { SesionOfflineService } from './sesion-offline.service';
import { stockDisponibleLocal } from './stock-local';

let contador = 0;
const GENERADO = '2026-10-30T10:00:00Z';

function paquete(): PaqueteLocal {
  return {
    empresa: { id: 1, codigo: 'alfa', nombre: 'Alfa' },
    generadoEn: GENERADO,
    avisoDesactualizadoHoras: 12,
    sucursales: [{ id: 10, codigo: 'SC-CENTRO', nombre: 'Centro', direccion: 'Calle 1', es_deposito: false, horarios: [] }],
    categorias: [{ id: 1, nombre: 'Poleras', categoria_padre_id: null }],
    tallas: [{ id: 1, codigo: 'M', orden: 1 }],
    colores: [{ id: 1, nombre: 'Negro', codigo_hex: '#000000' }],
    productos: [
      {
        id: 100,
        codigo: 'FS-1',
        nombre: 'Polera Estampada',
        categoria_id: 1,
        genero: 'hombre',
        temporada_id: null,
        imagen_principal: null,
        variantes: [
          { id: 1000, talla_id: 1, color_id: 1, sku: 'POL-M', codigo_barras: null, precio: '149.00', descuento_unitario: '14.90' },
          { id: 1001, talla_id: 1, color_id: 1, sku: 'POL-L', codigo_barras: null, precio: '99.90', descuento_unitario: '0.00' },
        ],
      },
    ],
    stock: [
      {
        sucursalId: 10,
        generadoEn: GENERADO,
        items: [
          { variante_id: 1000, cantidad_disponible: 5, actualizado_en: GENERADO },
          { variante_id: 1001, cantidad_disponible: 0, actualizado_en: GENERADO },
        ],
      },
    ],
    clientes: [{ id: 1, nombre: 'María', apellido: 'Pérez', ci_nit: '123' }],
    reglas: { metodos_pago_offline: ['efectivo'], max_operaciones_por_lote: 50, plazo_cambio_horas: 24, cambios_y_devoluciones: 'solo_en_linea', reservas_offline: 'permitidas' },
  };
}

describe('dinero-offline', () => {
  it('convierte a centavos y de vuelta sin errores de coma flotante', () => {
    expect(aCentavos('149.00')).toBe(14900);
    expect(aCentavos('0.1')).toBe(10);
    expect(aCentavos(99.9)).toBe(9990);
    expect(aCentavos('1,5')).toBe(150);
    expect(Number.isNaN(aCentavos('abc'))).toBe(true);
    expect(Number.isNaN(aCentavos(null))).toBe(true);
    expect(centavosATexto(14900)).toBe('149.00');
    expect(centavosATexto(5)).toBe('0.05');
    expect(centavosATexto(-250)).toBe('-2.50');
    // 3 x (99.90 - 0.10) sería 299.40 con el error de coma flotante habitual; en centavos es exacto.
    expect(centavosATexto(subtotalEnCentavos(3, '99.90', '0.10'))).toBe('299.40');
  });

  it('la fecha lleva el desfase local de la zona horaria', () => {
    expect(fechaConDesfase(new Date(2026, 9, 30, 14, 5, 7))).toMatch(/^2026-10-30T14:05:07[+-]\d{2}:\d{2}$/);
  });

  it('el identificador de la operación es un UUID v4 en minúscula', () => {
    expect(generarOperacionId()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(generarOperacionId()).not.toBe(generarOperacionId());
  });
});

describe('stockDisponibleLocal', () => {
  const op = (estado: OperacionOffline['estado'], fecha: string, cantidad: number, sucursal = 10): OperacionOffline =>
    ({ estado, fecha_operacion: fecha, sucursal_id: sucursal, lineas: [{ variante_id: 1000, cantidad }] }) as unknown as OperacionOffline;

  it('descuenta solo lo registrado DESPUÉS de la descarga', () => {
    const ops = [op('registrada', '2026-10-30T11:00:00Z', 2), op('confirmada', '2026-10-30T09:00:00Z', 4)];
    expect(stockDisponibleLocal(5, GENERADO, ops, 1000, 10)).toBe(3);
  });

  it('una operación rechazada devuelve sus unidades y una en conflicto las sigue ocupando', () => {
    expect(stockDisponibleLocal(5, GENERADO, [op('rechazada', '2026-10-30T11:00:00Z', 3)], 1000, 10)).toBe(5);
    expect(stockDisponibleLocal(5, GENERADO, [op('en_conflicto', '2026-10-30T11:00:00Z', 3)], 1000, 10)).toBe(2);
  });

  it('no mezcla sucursales ni prendas y puede dar negativo', () => {
    expect(stockDisponibleLocal(5, GENERADO, [op('registrada', '2026-10-30T11:00:00Z', 2, 11)], 1000, 10)).toBe(5);
    expect(stockDisponibleLocal(5, GENERADO, [op('registrada', '2026-10-30T11:00:00Z', 2)], 1001, 10)).toBe(5);
    expect(stockDisponibleLocal(1, GENERADO, [op('registrada', '2026-10-30T11:00:00Z', 3)], 1000, 10)).toBe(-2);
  });

  it('una descarga más nueva deja de descontar lo anterior', () => {
    const ops = [op('confirmada', '2026-10-30T11:00:00Z', 2)];
    expect(stockDisponibleLocal(5, '2026-10-30T12:00:00Z', ops, 1000, 10)).toBe(5);
  });
});

describe('OperacionesOfflineService', () => {
  let db: BaseOffline;
  let repo: RepositorioLocal;
  let servicio: OperacionesOfflineService;
  let hayAlcance: boolean;

  beforeEach(async () => {
    db = new BaseOffline(`prueba_operaciones_${++contador}_${Date.now()}`);
    repo = new RepositorioLocal(db, { empresaId: 1, usuarioId: 7 });
    await repo.reemplazarReferencia(paquete());
    hayAlcance = true;
    TestBed.configureTestingModule({
      providers: [
        {
          provide: SesionOfflineService,
          useValue: {
            alcance: () => (hayAlcance ? { empresaId: 1, usuarioId: 7 } : null),
            repositorio: () => (hayAlcance ? repo : null),
            dispositivoId: () => 'dispositivo-prueba',
          },
        },
      ],
    });
    servicio = TestBed.inject(OperacionesOfflineService);
  });

  afterEach(() => db.close());

  it('registra una venta con el precio y el descuento DESCARGADOS, el total exacto y el cambio', async () => {
    const venta = await servicio.registrarVenta({ sucursalId: 10, lineas: [{ varianteId: 1000, cantidad: 2 }], montoRecibido: '300' });

    expect(venta.estado).toBe('registrada');
    expect(venta.tipo).toBe('venta_contado');
    expect(venta.lineas[0]).toMatchObject({ precio_unitario: '149.00', descuento_unitario: '14.90', subtotal: '268.20', talla: 'M', color: 'Negro' });
    expect(venta.total).toBe('268.20');
    expect(venta.pago).toEqual({ metodo: 'efectivo', monto_recibido: '300.00', cambio: '31.80' });
    expect(venta.codigo_local).toBe(`OFF-${venta.operacion_id.slice(0, 6).toUpperCase()}`);
    expect(venta.fecha_operacion).toMatch(/[+-]\d{2}:\d{2}$/);
    expect(venta.dispositivo).toBe('dispositivo-prueba');
    expect(venta).toMatchObject({ empresa_id: 1, usuario_id: 7, intentos: 0, bloqueada: false, resultado: null });
    expect((await repo.misOperaciones()).length).toBe(1);
  });

  it('repetir el mismo operacionId (doble clic) NO crea una segunda venta', async () => {
    const operacionId = servicio.nuevoOperacionId();
    const entrada = { sucursalId: 10, lineas: [{ varianteId: 1000, cantidad: 1 }], montoRecibido: 200, operacionId };

    const primera = await servicio.registrarVenta(entrada);
    const segunda = await servicio.registrarVenta(entrada);

    expect(segunda.operacion_id).toBe(primera.operacion_id);
    expect(await db.operaciones_pendientes.count()).toBe(1);
  });

  it('no registra si el monto recibido no alcanza', async () => {
    await expect(
      servicio.registrarVenta({ sucursalId: 10, lineas: [{ varianteId: 1000, cantidad: 1 }], montoRecibido: '100' }),
    ).rejects.toThrow(/monto recibido/i);
    expect(await db.operaciones_pendientes.count()).toBe(0);
  });

  it('con stock local insuficiente avisa y NO registra hasta que el usuario acepta', async () => {
    const entrada = { sucursalId: 10, lineas: [{ varianteId: 1000, cantidad: 6 }], montoRecibido: 1000, operacionId: servicio.nuevoOperacionId() };

    const error = await servicio.registrarVenta(entrada).catch((e) => e);
    expect(error).toBeInstanceOf(StockLocalInsuficienteError);
    expect(error.faltantes).toEqual([
      { variante_id: 1000, producto_nombre: 'Polera Estampada', talla: 'M', color: 'Negro', solicitado: 6, disponible: 5 },
    ]);
    expect(await db.operaciones_pendientes.count()).toBe(0);

    const venta = await servicio.registrarVenta({ ...entrada, aceptarSinStock: true });
    expect(venta.estado).toBe('registrada');
    expect(await db.operaciones_pendientes.count()).toBe(1);
  });

  it('una prenda con stock local 0 también pide confirmación', async () => {
    const error = await servicio.registrarVenta({ sucursalId: 10, lineas: [{ varianteId: 1001, cantidad: 1 }], montoRecibido: 200 }).catch((e) => e);
    expect(error).toBeInstanceOf(StockLocalInsuficienteError);
    expect(error.faltantes[0]).toMatchObject({ variante_id: 1001, solicitado: 1, disponible: 0 });
  });

  it('lo ya vendido en este equipo baja el stock que se puede ofrecer', async () => {
    await servicio.registrarVenta({ sucursalId: 10, lineas: [{ varianteId: 1000, cantidad: 5 }], montoRecibido: 1000 });

    expect(await servicio.stockDisponible(1000, 10)).toBe(0);
    await expect(
      servicio.registrarVenta({ sucursalId: 10, lineas: [{ varianteId: 1000, cantidad: 1 }], montoRecibido: 200 }),
    ).rejects.toBeInstanceOf(StockLocalInsuficienteError);
  });

  it('si la operación se rechaza sus unidades vuelven al stock local', async () => {
    const venta = await servicio.registrarVenta({ sucursalId: 10, lineas: [{ varianteId: 1000, cantidad: 5 }], montoRecibido: 1000 });
    await repo.actualizarOperacion(venta.operacion_id, { estado: 'rechazada', motivo: 'variante_inactiva' });

    expect(await servicio.stockDisponible(1000, 10)).toBe(5);
  });

  it('suma las líneas repetidas de una misma prenda y valida las cantidades', async () => {
    const venta = await servicio.registrarVenta({
      sucursalId: 10,
      lineas: [{ varianteId: 1000, cantidad: 1 }, { varianteId: 1000, cantidad: 2 }],
      montoRecibido: 1000,
    });
    expect(venta.lineas).toHaveLength(1);
    expect(venta.lineas[0].cantidad).toBe(3);

    for (const cantidad of [0, -1, 1.5]) {
      await expect(
        servicio.registrarVenta({ sucursalId: 10, lineas: [{ varianteId: 1000, cantidad }], montoRecibido: 1000 }),
      ).rejects.toThrow(ErrorOperacionOffline);
    }
    await expect(servicio.registrarVenta({ sucursalId: 10, lineas: [], montoRecibido: 1000 })).rejects.toThrow(/al menos una prenda/i);
  });

  it('rechaza una prenda que no está en los datos descargados', async () => {
    await expect(
      servicio.registrarVenta({ sucursalId: 10, lineas: [{ varianteId: 9999, cantidad: 1 }], montoRecibido: 1000 }),
    ).rejects.toThrow(/no está en los datos descargados/i);
  });

  it('sin sesión no registra nada y lo dice claro', async () => {
    hayAlcance = false;
    await expect(
      servicio.registrarVenta({ sucursalId: 10, lineas: [{ varianteId: 1000, cantidad: 1 }], montoRecibido: 1000 }),
    ).rejects.toThrow(/inicia sesión/i);
  });

  it('un error de escritura (p. ej. sin espacio) NO deja la venta a medias y avisa que no se registró', async () => {
    vi.spyOn(repo, 'registrarOperacion').mockRejectedValue(Object.assign(new Error('lleno'), { name: 'QuotaExceededError' }));

    await expect(
      servicio.registrarVenta({ sucursalId: 10, lineas: [{ varianteId: 1000, cantidad: 1 }], montoRecibido: 1000 }),
    ).rejects.toThrow(/NO se registró/);
  });

  it('registra una reserva con su horario, observación y valor referencial', async () => {
    const reserva = await servicio.registrarReserva({
      sucursalId: 10,
      clienteId: 1,
      clienteNombre: 'María Pérez',
      fechaVisita: '2026-11-02',
      horaDesde: '10:00',
      horaHasta: '11:30',
      observacion: '  Pasa por la tarde  ',
      lineas: [{ varianteId: 1000, cantidad: 1 }],
    });

    expect(reserva.tipo).toBe('reserva');
    expect(reserva.pago).toBeNull();
    expect(reserva.cliente_id).toBe(1);
    expect(reserva.reserva).toEqual({ fecha_visita: '2026-11-02', hora_visita_desde: '10:00', hora_visita_hasta: '11:30', observacion: 'Pasa por la tarde' });
    expect(reserva.total).toBe('134.10');
  });

  it('valida el cliente, la fecha y el horario de una reserva', async () => {
    const base = { sucursalId: 10, clienteId: 1, fechaVisita: '2026-11-02', horaDesde: '10:00', horaHasta: '11:00', lineas: [{ varianteId: 1000, cantidad: 1 }] };

    await expect(servicio.registrarReserva({ ...base, clienteId: 0 })).rejects.toThrow(/cliente/i);
    await expect(servicio.registrarReserva({ ...base, fechaVisita: '02/11/2026' })).rejects.toThrow(/fecha/i);
    await expect(servicio.registrarReserva({ ...base, horaDesde: '25:00' })).rejects.toThrow(/horario/i);
    await expect(servicio.registrarReserva({ ...base, horaDesde: '12:00', horaHasta: '11:00' })).rejects.toThrow(/anterior/i);
    expect(await db.operaciones_pendientes.count()).toBe(0);
  });
});
