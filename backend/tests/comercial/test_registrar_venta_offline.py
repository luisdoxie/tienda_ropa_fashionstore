"""E07, 4.1: los parámetros nuevos de `registrar_venta`, `cobrar_en_caja` y `crear_reserva`
que usa la sincronización offline (CU-25) y el `StockInsuficienteError`. Todo es opcional:
sin los parámetros nuevos el comportamiento no cambia (lo cubren test_ventas, test_pagos,
test_reservas y test_unidad_de_trabajo)."""

import datetime as dt
from decimal import Decimal

import pytest

from app.comercial.models import Pago, Reserva, ReservaHistorial, Venta, VentaDetalle
from app.comercial.politicas import cobrar_en_caja, crear_reserva, registrar_venta
from app.core.exceptions import ConflictoError, DomainError, StockInsuficienteError
from app.plataforma.models import Cliente
from sqlalchemy import select
from tests.comercial.test_unidad_de_trabajo import (  # noqa: F401  (reusa el escenario)
    _datos_reserva,
    _stock,
    contexto,
)

FECHA_REAL = dt.datetime(2026, 9, 1, 15, 30, 45)


def _vender(db, ctx, *, cantidad=1, **extra) -> Venta:
    return registrar_venta(
        db,
        canal="presencial",
        sucursal_id=ctx["sucursal_id"],
        lineas=[(ctx["variante_id"], cantidad)],
        cliente_id=None,
        cajero_id=ctx["cajero_id"],
        reserva_id=None,
        costo_envio=Decimal("0"),
        usuario_id=ctx["cajero_usuario_id"],
        commit=False,
        **extra,
    )


# ---- registrar_venta ----


def test_registrar_venta_con_fecha_deja_la_fecha_exacta(db_session, contexto):
    venta = _vender(db_session, contexto, fecha=FECHA_REAL)
    db_session.commit()
    db_session.refresh(venta)
    assert venta.fecha == FECHA_REAL


def test_registrar_venta_sin_fecha_usa_la_de_la_base(db_session, contexto):
    venta = _vender(db_session, contexto)
    db_session.commit()
    db_session.refresh(venta)
    assert venta.fecha is not None and venta.fecha.year >= 2026
    assert venta.fecha != FECHA_REAL


def test_precios_pactados_usa_el_precio_dado_aunque_el_actual_sea_otro(db_session, contexto):
    # El precio de lista es 100.00: la operación se hizo a 80.00 con 5.00 de descuento.
    venta = _vender(db_session, contexto, cantidad=2, precios_pactados=[(Decimal("80.00"), Decimal("5.00"))])
    detalle = db_session.scalars(select(VentaDetalle).where(VentaDetalle.venta_id == venta.id)).one()
    assert (detalle.precio_unitario, detalle.descuento_unitario, detalle.subtotal) == (
        Decimal("80.00"), Decimal("5.00"), Decimal("150.00"),
    )
    assert (venta.subtotal, venta.descuento, venta.total) == (Decimal("160.00"), Decimal("10.00"), Decimal("150.00"))


def test_sin_precios_pactados_se_calcula_el_precio_actual(db_session, contexto):
    venta = _vender(db_session, contexto, cantidad=2)
    assert venta.total == Decimal("200.00")


def test_precios_pactados_de_distinta_longitud_que_las_lineas_es_un_error(db_session, contexto):
    with pytest.raises(DomainError, match="un precio por cada línea"):
        _vender(db_session, contexto, precios_pactados=[(Decimal("1"), Decimal("0")), (Decimal("1"), Decimal("0"))])


def test_stock_insuficiente_es_un_conflicto_409_con_el_mismo_texto(db_session, contexto):
    with pytest.raises(StockInsuficienteError) as error:
        _vender(db_session, contexto, cantidad=11)
    assert isinstance(error.value, ConflictoError)
    assert error.value.status_code == 409
    assert str(error.value) == f"No hay stock disponible suficiente de la variante {contexto['variante_id']}"
    assert (error.value.variante_id, error.value.solicitado, error.value.disponible) == (contexto["variante_id"], 11, 10)


def test_el_endpoint_de_venta_sin_stock_sigue_respondiendo_409_con_el_mismo_texto(client, contexto):
    respuesta = client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": contexto["sucursal_id"], "detalle": [{"variante_id": contexto["variante_id"], "cantidad": 99}]},
        headers=contexto["cajero_headers"],
    )
    assert respuesta.status_code == 409
    assert respuesta.json() == {"detail": f"No hay stock disponible suficiente de la variante {contexto['variante_id']}"}


def test_dos_lineas_de_la_misma_variante_que_juntas_superan_el_stock_dan_stock_insuficiente(db_session, contexto):
    with pytest.raises(StockInsuficienteError) as error:
        registrar_venta(
            db_session,
            canal="presencial",
            sucursal_id=contexto["sucursal_id"],
            lineas=[(contexto["variante_id"], 6), (contexto["variante_id"], 6)],
            cliente_id=None,
            cajero_id=contexto["cajero_id"],
            reserva_id=None,
            costo_envio=Decimal("0"),
            usuario_id=contexto["cajero_usuario_id"],
            commit=False,
        )
    assert error.value.variante_id == contexto["variante_id"]
    db_session.rollback()
    assert _stock(db_session, contexto) == (10, 0)


# ---- cobrar_en_caja ----


def test_cobrar_en_caja_con_fecha_fija_la_fecha_del_pago(db_session, contexto):
    venta = _vender(db_session, contexto, fecha=FECHA_REAL)
    pago, _ = cobrar_en_caja(
        db_session, contexto["cajero_usuario_id"], venta.id, "efectivo", Decimal("100.00"), commit=False, fecha=FECHA_REAL
    )
    db_session.commit()
    db_session.refresh(pago)
    assert pago.fecha == FECHA_REAL


def test_cobrar_en_caja_sin_fecha_usa_la_de_la_base(db_session, contexto):
    venta = _vender(db_session, contexto)
    pago, _ = cobrar_en_caja(
        db_session, contexto["cajero_usuario_id"], venta.id, "efectivo", Decimal("100.00"), commit=False
    )
    db_session.commit()
    db_session.refresh(pago)
    assert pago.fecha is not None and pago.fecha != FECHA_REAL


# ---- crear_reserva ----


def test_crear_reserva_con_cliente_id_es_del_cliente_con_el_actor_en_el_historial(db_session, contexto):
    cliente = db_session.scalars(select(Cliente).where(Cliente.usuario_id == contexto["cliente_usuario_id"])).one()
    reserva = crear_reserva(
        db_session,
        contexto["cajero_usuario_id"],
        _datos_reserva(contexto),
        commit=False,
        cliente_id=cliente.id,
        creado_en=FECHA_REAL,
    )
    db_session.commit()
    db_session.refresh(reserva)

    assert reserva.cliente_id == cliente.id
    assert reserva.creado_en == FECHA_REAL
    historial = db_session.scalars(select(ReservaHistorial).where(ReservaHistorial.reserva_id == reserva.id)).one()
    assert historial.usuario_id == contexto["cajero_usuario_id"]
    assert historial.comentario == "Reserva registrada por el personal"
    assert _stock(db_session, contexto) == (10, 1)


def test_crear_reserva_con_un_cliente_inexistente_da_404(db_session, contexto):
    with pytest.raises(DomainError) as error:
        crear_reserva(db_session, contexto["cajero_usuario_id"], _datos_reserva(contexto), commit=False, cliente_id=999999)
    assert error.value.status_code == 404
    db_session.rollback()


def test_crear_reserva_sin_cliente_id_se_comporta_como_antes(db_session, contexto):
    reserva = crear_reserva(db_session, contexto["cliente_usuario_id"], _datos_reserva(contexto), commit=False)
    db_session.commit()
    db_session.refresh(reserva)

    cliente = db_session.scalars(select(Cliente).where(Cliente.usuario_id == contexto["cliente_usuario_id"])).one()
    assert reserva.cliente_id == cliente.id
    assert reserva.creado_en is not None and reserva.creado_en != FECHA_REAL
    historial = db_session.scalars(select(ReservaHistorial).where(ReservaHistorial.reserva_id == reserva.id)).one()
    assert historial.comentario == "Reserva creada"
