"""E07: la operación `venta_contado` del lote. Qué deja una venta confirmada (venta pagada, pago
en efectivo, stock, kardex, costo congelado, fechas reales) y cada motivo de rechazo o de
conflicto. Todo por HTTP contra POST /sincronizacion/lote."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.catalogo.models import MovimientoInventario, TipoMovimiento
from app.comercial.models import EstadoPago, MetodoPago, Pago, Venta, VentaDetalle
from app.comercial.politicas import mapa_codigos_estado_venta
from app.sincronizacion.models import OperacionSync
from tests.sincronizacion.ayudas import (
    STOCK_V1,
    STOCK_V2,
    armar_venta,
    en_utc_naive,
    enviar,
    hace,
    stock_de,
)


def _linea(variante_id: int, cantidad: int = 1, precio: str = "100.00", descuento: str = "0.00") -> dict:
    return {"variante_id": variante_id, "cantidad": cantidad, "precio_unitario": precio, "descuento_unitario": descuento}


def _enviar_una(client, headers, operacion) -> dict:
    respuesta = enviar(client, headers, [operacion])
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["resultados"][0]


def _contar(db, modelo) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(modelo))


def _guardada(db, operacion: dict) -> OperacionSync:
    db.expire_all()
    return db.scalars(select(OperacionSync).where(OperacionSync.operacion_id == uuid.UUID(operacion["operacion_id"]))).one()


def _venta_de(db, resultado: dict) -> Venta:
    db.expire_all()
    return db.scalars(select(Venta).where(Venta.codigo == resultado["recurso"]["codigo"])).one()


def _sin_efectos(db, escenario) -> None:
    """Ni venta, ni pago, ni movimiento de venta, ni stock tocado de las dos variantes."""
    assert _contar(db, Venta) == 0 and _contar(db, Pago) == 0 and _contar(db, VentaDetalle) == 0
    assert stock_de(db, escenario, escenario.v1) == (STOCK_V1, 0)
    assert stock_de(db, escenario, escenario.v2) == (STOCK_V2, 0)


def _rechazada(client, db, escenario, operacion, motivo: str, headers=None) -> dict:
    resultado = _enviar_una(client, headers or escenario.cajero, operacion)
    assert resultado["estado"] == "rechazada" and resultado["motivo"] == motivo, resultado
    assert resultado["recurso"] is None and resultado["mensaje"]
    fila = _guardada(db, operacion)
    assert (fila.estado, fila.motivo) == ("rechazada", motivo)
    return resultado


# ---- Camino feliz ----------------------------------------------------------------------


def test_confirmada_deja_la_venta_pagada_con_su_cambio_y_su_costo_congelado(client, db_session, escenario):
    operacion = armar_venta(escenario, lineas=[_linea(escenario.v1, 2)], monto_recibido="250.00")
    resultado = _enviar_una(client, escenario.cajero, operacion)

    assert resultado["estado"] == "confirmada" and resultado["motivo"] is None
    assert resultado["recurso"]["tipo"] == "venta" and resultado["recurso"]["codigo"].startswith("VTA-")
    assert Decimal(resultado["recurso"]["total"]) == Decimal("200.00")
    assert Decimal(resultado["cambio"]) == Decimal("50.00")
    assert resultado["avisos"] == [] and resultado["faltantes"] == []

    venta = _venta_de(db_session, resultado)
    assert venta.id == resultado["recurso"]["id"]
    assert mapa_codigos_estado_venta(db_session)[venta.estado_id] == "pagada"
    assert venta.canal == "presencial" and venta.cliente_id == escenario.cliente_id
    assert venta.sucursal_id == escenario.sucursal_id
    assert (venta.subtotal, venta.descuento, venta.total) == (Decimal("200.00"), Decimal("0.00"), Decimal("200.00"))

    (linea,) = venta.detalle
    assert (linea.variante_id, linea.cantidad) == (escenario.v1, 2)
    assert linea.precio_unitario == Decimal("100.00") and linea.subtotal == Decimal("200.00")
    # El costo se congela al cobrar: el de la recepción del escenario (40.00).
    assert linea.costo_unitario == Decimal("40.0000")


def test_confirmada_registra_un_pago_en_efectivo_aprobado_por_el_total(client, db_session, escenario):
    resultado = _enviar_una(client, escenario.cajero, armar_venta(escenario, monto_recibido="250.00"))

    venta = _venta_de(db_session, resultado)
    pago = db_session.scalars(select(Pago).where(Pago.venta_id == venta.id)).one()
    metodo = db_session.get(MetodoPago, pago.metodo_pago_id)
    estado = db_session.get(EstadoPago, pago.estado_id)
    assert (metodo.codigo, estado.codigo) == ("efectivo", "aprobado")
    # El pago es por el total de la venta, no por lo que entregó el cliente (el resto es el cambio).
    assert pago.monto == venta.total == Decimal("200.00")


def test_confirmada_baja_el_stock_fisico_y_deja_el_movimiento_de_venta_en_el_kardex(client, db_session, escenario):
    resultado = _enviar_una(client, escenario.cajero, armar_venta(escenario, lineas=[_linea(escenario.v1, 3)], monto_recibido="300.00"))

    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 3, 0)
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2, 0)
    movimiento = db_session.execute(
        select(MovimientoInventario, TipoMovimiento.codigo)
        .join(TipoMovimiento, TipoMovimiento.id == MovimientoInventario.tipo_movimiento_id)
        .where(MovimientoInventario.referencia_tipo == "venta", MovimientoInventario.referencia_id == resultado["recurso"]["id"])
    ).one()
    fila, codigo = movimiento
    assert codigo == "venta"
    assert (fila.variante_id, fila.sucursal_id) == (escenario.v1, escenario.sucursal_id)
    assert fila.cantidad == -3 and fila.saldo_post == STOCK_V1 - 3
    assert fila.usuario_id == escenario.cajero_usuario_id


def test_la_venta_y_el_pago_llevan_la_fecha_real_de_la_operacion(client, db_session, escenario):
    # Una venta hecha hace 3 horas sin conexión: la fecha del registro NO es la de la sincronización.
    fecha = hace(180)
    resultado = _enviar_una(client, escenario.cajero, armar_venta(escenario, fecha_operacion=fecha))

    venta = _venta_de(db_session, resultado)
    pago = db_session.scalars(select(Pago).where(Pago.venta_id == venta.id)).one()
    assert venta.fecha == en_utc_naive(fecha)
    assert pago.fecha == en_utc_naive(fecha)
    db_session.expire_all()
    assert db_session.scalars(select(OperacionSync)).one().fecha_operacion == en_utc_naive(fecha)


def test_venta_anonima_sin_cliente_se_confirma(client, db_session, escenario):
    resultado = _enviar_una(client, escenario.cajero, armar_venta(escenario, cliente_id=None))

    assert resultado["estado"] == "confirmada"
    assert _venta_de(db_session, resultado).cliente_id is None


# ---- Precio de la operación (D17) ---------------------------------------------------


def test_precio_distinto_del_actual_se_acepta_y_sale_el_aviso(client, db_session, escenario):
    # El catálogo dice 100.00; la caja vendió a 90.00 antes de perder la conexión.
    operacion = armar_venta(escenario, lineas=[_linea(escenario.v1, 2, precio="90.00")], monto_recibido="200.00")
    resultado = _enviar_una(client, escenario.cajero, operacion)

    assert resultado["estado"] == "confirmada"
    assert Decimal(resultado["recurso"]["total"]) == Decimal("180.00")
    assert Decimal(resultado["cambio"]) == Decimal("20.00")
    (aviso,) = resultado["avisos"]
    assert aviso["codigo"] == "precio_distinto" and aviso["variante_id"] == escenario.v1
    assert Decimal(aviso["precio_operacion"]) == Decimal("90.00")
    assert Decimal(aviso["precio_actual"]) == Decimal("100.00")

    venta = _venta_de(db_session, resultado)
    (linea,) = venta.detalle
    assert linea.precio_unitario == Decimal("90.00") and venta.total == Decimal("180.00")
    # El aviso queda guardado con la operación, para consultarlo después.
    assert _guardada(db_session, operacion).resultado["avisos"][0]["codigo"] == "precio_distinto"


# ---- Rechazos ------------------------------------------------------------------------


def test_total_que_no_es_la_suma_de_las_lineas_se_rechaza_como_inconsistente(client, db_session, escenario):
    operacion = armar_venta(escenario, lineas=[_linea(escenario.v1, 2)], total="150.00", monto_recibido="250.00")
    _rechazada(client, db_session, escenario, operacion, "total_inconsistente")
    _sin_efectos(db_session, escenario)


def test_total_cero_con_lineas_en_cero_se_rechaza_como_invalido(client, db_session, escenario):
    operacion = armar_venta(
        escenario, lineas=[_linea(escenario.v1, 1, precio="0.00")], total="0.00", monto_recibido="0.00"
    )
    _rechazada(client, db_session, escenario, operacion, "total_invalido")
    _sin_efectos(db_session, escenario)


def test_un_metodo_de_pago_que_no_es_efectivo_se_rechaza(client, db_session, escenario):
    operacion = armar_venta(escenario, metodo="tarjeta")
    _rechazada(client, db_session, escenario, operacion, "metodo_pago_no_permitido")
    _sin_efectos(db_session, escenario)


def test_monto_recibido_menor_al_total_se_rechaza(client, db_session, escenario):
    operacion = armar_venta(escenario, lineas=[_linea(escenario.v1, 2)], monto_recibido="199.99")
    _rechazada(client, db_session, escenario, operacion, "monto_insuficiente")
    _sin_efectos(db_session, escenario)


def test_variante_inexistente_se_rechaza(client, db_session, escenario):
    operacion = armar_venta(escenario, lineas=[_linea(999999)], monto_recibido="100.00")
    _rechazada(client, db_session, escenario, operacion, "variante_inexistente")
    _sin_efectos(db_session, escenario)


def test_variante_dada_de_baja_se_rechaza_como_inactiva(client, db_session, escenario):
    baja = client.delete(f"/api/v1/variantes/{escenario.v1}", headers=escenario.admin)
    assert baja.status_code == 204, baja.text

    operacion = armar_venta(escenario, lineas=[_linea(escenario.v1, 1)], monto_recibido="100.00")
    _rechazada(client, db_session, escenario, operacion, "variante_inactiva")
    assert _contar(db_session, Venta) == 0 and _contar(db_session, Pago) == 0
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 0)


def test_cliente_inexistente_se_rechaza(client, db_session, escenario):
    operacion = armar_venta(escenario, cliente_id=999999)
    _rechazada(client, db_session, escenario, operacion, "cliente_inexistente")
    _sin_efectos(db_session, escenario)


def test_descuento_mayor_al_precio_y_payload_sin_lineas_se_rechazan_como_payload_invalido(client, db_session, escenario):
    con_descuento_excesivo = armar_venta(
        escenario, lineas=[_linea(escenario.v1, 1, precio="100.00", descuento="150.00")], total="0.00", monto_recibido="0.00"
    )
    _rechazada(client, db_session, escenario, con_descuento_excesivo, "payload_invalido")

    sin_lineas = armar_venta(escenario)
    sin_lineas["payload"]["lineas"] = []
    _rechazada(client, db_session, escenario, sin_lineas, "payload_invalido")
    _sin_efectos(db_session, escenario)


def test_fecha_en_el_futuro_se_rechaza(client, db_session, escenario):
    operacion = armar_venta(escenario, fecha_operacion=hace(-120))  # dentro de 2 horas
    _rechazada(client, db_session, escenario, operacion, "fecha_futura")
    _sin_efectos(db_session, escenario)


def test_un_usuario_sin_ventas_presencial_recibe_permiso_denegado(client, db_session, escenario):
    # El encargado puede sincronizar (sincronizacion.operar) y es empleado de la sucursal, pero su
    # rol no incluye ventas.presencial: la venta de contado no es suya.
    operacion = armar_venta(escenario)
    _rechazada(client, db_session, escenario, operacion, "permiso_denegado", headers=escenario.encargado)
    _sin_efectos(db_session, escenario)


def test_un_usuario_sin_ficha_de_empleado_recibe_usuario_no_es_empleado(client, db_session, escenario):
    # El administrador tiene el permiso de sincronizar pero no es empleado de ninguna sucursal.
    operacion = armar_venta(escenario)
    _rechazada(client, db_session, escenario, operacion, "usuario_no_es_empleado", headers=escenario.admin)
    _sin_efectos(db_session, escenario)


# ---- Conflicto por stock -------------------------------------------------------------


def test_dos_lineas_de_la_misma_variante_que_juntas_superan_el_stock_quedan_en_conflicto(client, db_session, escenario):
    # v2 tiene 3: cada línea (2) cabe sola, las dos juntas (4) no.
    operacion = armar_venta(
        escenario, lineas=[_linea(escenario.v2, 2), _linea(escenario.v2, 2)], monto_recibido="400.00"
    )
    resultado = _enviar_una(client, escenario.cajero, operacion)

    assert resultado["estado"] == "en_conflicto" and resultado["motivo"] == "stock_insuficiente"
    assert resultado["recurso"] is None
    assert resultado["faltantes"] == [{"variante_id": escenario.v2, "solicitado": 4, "disponible": STOCK_V2}]
    _sin_efectos(db_session, escenario)
    fila = _guardada(db_session, operacion)
    assert (fila.estado, fila.motivo) == ("en_conflicto", "stock_insuficiente")
