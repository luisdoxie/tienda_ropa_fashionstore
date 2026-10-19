"""Orden de los bloqueos de stock en `comercial` (T3 del análisis): registrar,
confirmar y anular venta, y crear, cancelar y expirar reserva toman las filas de
`stock` en orden ascendente por (variante_id, sucursal_id) aunque las líneas
lleguen desordenadas (ver tests/catalogo/test_orden_bloqueos_stock.py).

SQLite no aplica FOR UPDATE: se verifica el ORDEN en que se piden los
bloqueos (fixture `espia_bloqueos`) y que lo respondido y persistido no cambia.
"""

import datetime as dt

import pytest

from app.comercial.models import Reserva
from app.comercial.politicas import anular_venta, expirar_reservas_vencidas
from tests.conftest import crear_cajero


def _proxima_fecha_con_dia_semana(dia_semana: int) -> dt.date:
    base = dt.date.today() + dt.timedelta(days=7)
    return base + dt.timedelta(days=(dia_semana - base.isoweekday()) % 7)


@pytest.fixture()
def contexto(client, admin_headers, db_session):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas Orden Com"}, headers=admin_headers).json()
    tallas = [
        client.post("/api/v1/tallas", json={"codigo": codigo, "orden": i}, headers=admin_headers).json()
        for i, codigo in enumerate(("S", "M", "L"), start=1)
    ]
    color = client.post("/api/v1/colores", json={"nombre": "Gris Orden Com"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "ORDC-1",
            "nombre": "Camisa orden comercial",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [t["id"] for t in tallas],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variantes = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()
    variante_ids = sorted(v["id"] for v in variantes)

    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Tarija Orden", "departamento": "Tarija"}, headers=admin_headers
    ).json()
    sucursal_id = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-ORDC", "nombre": "Sucursal Orden", "direccion": "Av. 1"},
        headers=admin_headers,
    ).json()["id"]

    fecha_visita = _proxima_fecha_con_dia_semana(3)  # miércoles
    client.post(
        f"/api/v1/sucursales/{sucursal_id}/horarios",
        json={"dia_semana": 3, "hora_apertura": "08:00:00", "hora_cierre": "20:00:00"},
        headers=admin_headers,
    )

    for variante_id in variante_ids:
        client.post(
            "/api/v1/inventario/movimientos",
            json={
                "variante_id": variante_id,
                "sucursal_id": sucursal_id,
                "tipo_movimiento_codigo": "recepcion",
                "cantidad": 10,
                "costo_unitario": "10.00",
            },
            headers=admin_headers,
        )

    return {
        "variantes": variante_ids,  # ascendentes
        "sucursal_id": sucursal_id,
        "fecha_visita": fecha_visita.isoformat(),
        "cajero_headers": crear_cajero(client, admin_headers, db_session, sucursal_id=sucursal_id),
    }


def _claves_ascendentes(ctx) -> list[tuple[int, int]]:
    return [(v, ctx["sucursal_id"]) for v in ctx["variantes"]]


def _desordenadas(ctx) -> list[int]:
    v1, v2, v3 = ctx["variantes"]
    return [v3, v1, v2]


def _registrar_venta(client, ctx):
    return client.post(
        "/api/v1/ventas/presencial",
        json={
            "sucursal_id": ctx["sucursal_id"],
            "detalle": [{"variante_id": v, "cantidad": 2} for v in _desordenadas(ctx)],
        },
        headers=ctx["cajero_headers"],
    )


def _stock(client, headers, variante_id, sucursal_id) -> dict:
    return client.get(f"/api/v1/inventario/stock/{variante_id}/{sucursal_id}", headers=headers).json()


# ---- ventas ------------------------------------------------------------------------------


def test_registrar_venta_bloquea_en_orden_y_conserva_el_orden_del_detalle(client, contexto, espia_bloqueos):
    espia_bloqueos.eventos.clear()

    respuesta = _registrar_venta(client, contexto)

    assert respuesta.status_code == 201, respuesta.text
    assert espia_bloqueos.lotes()[0] == _claves_ascendentes(contexto)
    assert espia_bloqueos.orden_de_adquisicion() == _claves_ascendentes(contexto)
    # El detalle de la venta sigue en el orden en que llegaron las líneas.
    assert [linea["variante_id"] for linea in respuesta.json()["detalle"]] == _desordenadas(contexto)
    assert respuesta.json()["total"] == "600.00"
    for v in contexto["variantes"]:
        assert _stock(client, contexto["cajero_headers"], v, contexto["sucursal_id"])["cantidad_reservada"] == 2


def test_confirmar_venta_al_pagar_bloquea_en_orden(client, admin_headers, contexto, espia_bloqueos):
    venta = _registrar_venta(client, contexto).json()
    espia_bloqueos.eventos.clear()

    pago = client.post(
        "/api/v1/pagos/caja",
        json={"venta_id": venta["id"], "metodo_pago": "qr"},
        headers=contexto["cajero_headers"],
    )

    assert pago.status_code == 201, pago.text
    assert espia_bloqueos.lotes() == [_claves_ascendentes(contexto)]
    assert espia_bloqueos.orden_de_adquisicion() == _claves_ascendentes(contexto)
    comprobante = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=admin_headers).json()
    assert comprobante["estado"] == "pagada"
    assert [linea["variante_id"] for linea in comprobante["detalle"]] == _desordenadas(contexto)
    for v in contexto["variantes"]:
        stock = _stock(client, admin_headers, v, contexto["sucursal_id"])
        assert (stock["cantidad_fisica"], stock["cantidad_reservada"]) == (8, 0)


def test_anular_venta_pendiente_bloquea_en_orden_y_libera_la_reserva(
    client, admin_headers, db_session, contexto, espia_bloqueos
):
    venta = _registrar_venta(client, contexto).json()
    espia_bloqueos.eventos.clear()

    anular_venta(db_session, venta["id"])

    assert espia_bloqueos.lotes() == [_claves_ascendentes(contexto)]
    assert espia_bloqueos.orden_de_adquisicion() == _claves_ascendentes(contexto)
    comprobante = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=admin_headers).json()
    assert comprobante["estado"] == "anulada"
    for v in contexto["variantes"]:
        stock = _stock(client, admin_headers, v, contexto["sucursal_id"])
        assert (stock["cantidad_fisica"], stock["cantidad_reservada"]) == (10, 0)


def test_anular_venta_pagada_bloquea_en_orden_y_reingresa_el_stock(
    client, admin_headers, db_session, contexto, espia_bloqueos
):
    venta = _registrar_venta(client, contexto).json()
    client.post(
        "/api/v1/pagos/caja",
        json={"venta_id": venta["id"], "metodo_pago": "qr"},
        headers=contexto["cajero_headers"],
    )
    espia_bloqueos.eventos.clear()

    anular_venta(db_session, venta["id"])

    assert espia_bloqueos.lotes() == [_claves_ascendentes(contexto)]
    assert espia_bloqueos.orden_de_adquisicion() == _claves_ascendentes(contexto)
    for v in contexto["variantes"]:
        assert _stock(client, admin_headers, v, contexto["sucursal_id"])["cantidad_fisica"] == 10


# ---- reservas ----------------------------------------------------------------------------


def _crear_reserva(client, cliente_headers, ctx):
    return client.post(
        "/api/v1/reservas",
        json={
            "sucursal_id": ctx["sucursal_id"],
            "fecha_visita": ctx["fecha_visita"],
            "hora_visita_desde": "10:00:00",
            "hora_visita_hasta": "11:00:00",
            "detalle": [{"variante_id": v, "cantidad": 1} for v in _desordenadas(ctx)],
        },
        headers=cliente_headers,
    )


def test_crear_y_cancelar_reserva_bloquean_en_orden(client, admin_headers, cliente_headers, contexto, espia_bloqueos):
    espia_bloqueos.eventos.clear()
    reserva = _crear_reserva(client, cliente_headers, contexto)

    assert reserva.status_code == 201, reserva.text
    assert espia_bloqueos.lotes() == [_claves_ascendentes(contexto)]
    assert espia_bloqueos.orden_de_adquisicion() == _claves_ascendentes(contexto)
    assert [linea["variante_id"] for linea in reserva.json()["detalle"]] == _desordenadas(contexto)

    espia_bloqueos.eventos.clear()
    cancelada = client.delete(f"/api/v1/reservas/{reserva.json()['id']}", headers=cliente_headers)

    assert cancelada.status_code == 200, cancelada.text
    assert cancelada.json()["estado"] == "cancelada"
    assert espia_bloqueos.lotes() == [_claves_ascendentes(contexto)]
    assert espia_bloqueos.orden_de_adquisicion() == _claves_ascendentes(contexto)
    for v in contexto["variantes"]:
        assert _stock(client, admin_headers, v, contexto["sucursal_id"])["cantidad_reservada"] == 0


def test_expirar_reservas_bloquea_en_orden_por_reserva(
    client, admin_headers, cliente_headers, db_session, contexto, espia_bloqueos
):
    reserva = _crear_reserva(client, cliente_headers, contexto).json()
    db_session.get(Reserva, reserva["id"]).fecha_expiracion = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    db_session.commit()
    espia_bloqueos.eventos.clear()

    assert expirar_reservas_vencidas(db_session) == 1

    assert espia_bloqueos.lotes() == [_claves_ascendentes(contexto)]
    assert espia_bloqueos.orden_de_adquisicion() == _claves_ascendentes(contexto)
    assert client.get(f"/api/v1/reservas/{reserva['id']}", headers=cliente_headers).json()["estado"] == "expirada"
    for v in contexto["variantes"]:
        assert _stock(client, admin_headers, v, contexto["sucursal_id"])["cantidad_reservada"] == 0
