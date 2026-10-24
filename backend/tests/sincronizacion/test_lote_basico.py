"""E07: el camino principal del lote, de punta a punta por HTTP (venta confirmada, reenvío,
conflicto por stock, rechazo y reserva). Los casos finos están en los otros archivos."""

from decimal import Decimal

from sqlalchemy import func, select

from app.comercial.models import Pago, Reserva, Venta
from app.sincronizacion.models import OperacionSync
from tests.sincronizacion.ayudas import (
    API,
    STOCK_V1,
    armar_reserva,
    armar_venta,
    enviar,
    stock_de,
)


def _contar(db, modelo) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(modelo))


def test_una_venta_de_contado_se_confirma_y_descuenta_el_stock(client, db_session, escenario):
    operacion = armar_venta(escenario)
    respuesta = enviar(client, escenario.cajero, [operacion])

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["version_contrato"] == "1.0"
    assert cuerpo["resumen"] == {
        "total": 1, "confirmadas": 1, "rechazadas": 0, "en_conflicto": 0, "errores_temporales": 0, "duplicadas": 0,
    }
    resultado = cuerpo["resultados"][0]
    assert resultado["estado"] == "confirmada" and resultado["motivo"] is None and resultado["duplicada"] is False
    assert resultado["recurso"]["tipo"] == "venta" and resultado["recurso"]["total"] == "200.00"
    assert resultado["cambio"] == "50.00"
    assert resultado["procesada_en"].endswith("Z")
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)


def test_reenviar_la_misma_operacion_devuelve_lo_guardado_y_no_repite(client, db_session, escenario):
    operacion = armar_venta(escenario)
    primera = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]
    ventas = _contar(db_session, Venta)

    segunda = enviar(client, escenario.cajero, [operacion])
    resultado = segunda.json()["resultados"][0]

    assert segunda.json()["resumen"]["duplicadas"] == 1
    assert resultado["duplicada"] is True and resultado["estado"] == "confirmada"
    assert resultado["recurso"] == primera["recurso"]
    assert _contar(db_session, Venta) == ventas
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)
    assert db_session.scalars(select(OperacionSync)).one().intentos == 2


def test_sin_stock_suficiente_queda_en_conflicto_sin_tocar_el_inventario(client, db_session, escenario):
    lineas = [{"variante_id": escenario.v2, "cantidad": 5, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    respuesta = enviar(client, escenario.cajero, [armar_venta(escenario, lineas=lineas, monto_recibido="500.00")])

    resultado = respuesta.json()["resultados"][0]
    assert resultado["estado"] == "en_conflicto" and resultado["motivo"] == "stock_insuficiente"
    assert resultado["faltantes"] == [{"variante_id": escenario.v2, "solicitado": 5, "disponible": 3}]
    assert resultado["recurso"] is None
    assert stock_de(db_session, escenario, escenario.v2) == (3, 0)
    assert _contar(db_session, Venta) == 0 and _contar(db_session, Pago) == 0


def test_una_variante_inexistente_se_rechaza_con_su_motivo_y_queda_guardada(client, db_session, escenario):
    lineas = [{"variante_id": 999999, "cantidad": 1, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    operacion = armar_venta(escenario, lineas=lineas, monto_recibido="100.00")
    resultado = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "variante_inexistente"
    guardada = db_session.scalars(select(OperacionSync)).one()
    assert (guardada.estado, guardada.motivo) == ("rechazada", "variante_inexistente")


def test_una_reserva_se_confirma_a_nombre_del_cliente_y_aparta_el_stock(client, db_session, escenario):
    respuesta = enviar(client, escenario.cajero, [armar_reserva(escenario)])

    resultado = respuesta.json()["resultados"][0]
    assert resultado["estado"] == "confirmada", resultado
    assert resultado["recurso"]["tipo"] == "reserva" and resultado["recurso"]["codigo"].startswith("RES-")
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 1)
    reserva = db_session.scalars(select(Reserva)).one()
    assert reserva.cliente_id == escenario.cliente_id


def test_las_consultas_listan_lo_enviado(client, escenario):
    venta = armar_venta(escenario)
    enviar(client, escenario.cajero, [venta])

    lista = client.get(f"{API}/operaciones", headers=escenario.cajero)
    assert lista.status_code == 200
    assert [i["operacion_id"] for i in lista.json()["items"]] == [venta["operacion_id"]]
    assert "payload" not in lista.json()["items"][0]

    detalle = client.get(f"{API}/operaciones/{venta['operacion_id']}", headers=escenario.cajero)
    assert detalle.status_code == 200 and detalle.json()["estado"] == "confirmada"
    assert Decimal(detalle.json()["recurso"]["total"]) == Decimal("200.00")
