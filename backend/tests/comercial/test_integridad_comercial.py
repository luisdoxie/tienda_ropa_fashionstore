"""Integridad de `comercial` (grupo G3 del análisis, 2.3 puntos 3, 8 y 9):
anular una venta pagada con devoluciones previas, bloqueo de la venta en
devoluciones y en el cobro en caja, venta desde una reserva cuyo apartado ya
se liberó, y el helper único de cierre de transacción.

SQLite no aplica FOR UPDATE: el bloqueo se verifica con espías que registran
qué método del repositorio se pide y en qué orden (mismo criterio que
tests/comercial/test_orden_bloqueos_stock.py).
"""

import datetime as dt
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from app.comercial.models import Pago
from app.comercial.politicas import _cerrar_tx, anular_venta, cobrar_en_caja, registrar_venta
from app.comercial.repository import DevolucionRepository, VentaRepository
from app.core.exceptions import ConflictoError, DomainError
from tests.conftest import crear_cajero


def _proxima_fecha_con_dia_semana(dia_semana: int) -> dt.date:
    base = dt.date.today() + dt.timedelta(days=7)
    return base + dt.timedelta(days=(dia_semana - base.isoweekday()) % 7)


@pytest.fixture()
def contexto(client, admin_headers, db_session):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas Integridad"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Verde Integridad"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "INT-1",
            "nombre": "Camisa integridad",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante_id = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]["id"]

    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Sucre Integridad", "departamento": "Chuquisaca"}, headers=admin_headers
    ).json()
    sucursal_id = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-INT", "nombre": "Sucursal Integridad", "direccion": "Av. 1"},
        headers=admin_headers,
    ).json()["id"]
    client.post(
        f"/api/v1/sucursales/{sucursal_id}/horarios",
        json={"dia_semana": 3, "hora_apertura": "08:00:00", "hora_cierre": "20:00:00"},
        headers=admin_headers,
    )
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
        "variante_id": variante_id,
        "sucursal_id": sucursal_id,
        "cajero_headers": crear_cajero(client, admin_headers, db_session, sucursal_id=sucursal_id),
    }


def _stock(client, headers, ctx) -> dict:
    return client.get(
        f"/api/v1/inventario/stock/{ctx['variante_id']}/{ctx['sucursal_id']}", headers=headers
    ).json()


def _vender_y_pagar(client, ctx, cantidad):
    venta = client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": ctx["sucursal_id"], "detalle": [{"variante_id": ctx["variante_id"], "cantidad": cantidad}]},
        headers=ctx["cajero_headers"],
    ).json()
    pago = client.post(
        "/api/v1/pagos/caja", json={"venta_id": venta["id"], "metodo_pago": "qr"}, headers=ctx["cajero_headers"]
    )
    assert pago.status_code == 201, pago.text
    return venta


def _devolver(client, ctx, venta, cantidad):
    return client.post(
        "/api/v1/devoluciones",
        json={
            "venta_id": venta["id"],
            "motivo": "Prueba",
            "detalle": [{"venta_detalle_id": venta["detalle"][0]["id"], "cantidad": cantidad}],
        },
        headers=ctx["cajero_headers"],
    )


# ---- punto 1: anular una venta pagada con devoluciones previas -----------------------------


def test_anular_venta_pagada_con_devolucion_previa_no_infla_el_stock(client, admin_headers, contexto, db_session):
    venta = _vender_y_pagar(client, contexto, cantidad=4)
    assert _stock(client, admin_headers, contexto)["cantidad_fisica"] == 6
    assert _devolver(client, contexto, venta, 1).status_code == 201
    assert _stock(client, admin_headers, contexto)["cantidad_fisica"] == 7

    anular_venta(db_session, venta["id"])

    # Las 4 unidades vendidas vuelven al estante UNA sola vez: 1 por la
    # devolución y 3 por la anulación (antes volvían 4 y quedaban 11).
    assert _stock(client, admin_headers, contexto)["cantidad_fisica"] == 10


def test_anular_venta_pagada_con_todo_devuelto_no_reingresa_nada_mas(client, admin_headers, contexto, db_session):
    venta = _vender_y_pagar(client, contexto, cantidad=2)
    assert _devolver(client, contexto, venta, 2).status_code == 201
    assert _stock(client, admin_headers, contexto)["cantidad_fisica"] == 10

    anular_venta(db_session, venta["id"])

    stock = _stock(client, admin_headers, contexto)
    assert stock["cantidad_fisica"] == 10
    comprobante = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=admin_headers).json()
    assert comprobante["estado"] == "anulada"


def test_anular_venta_pagada_sin_devoluciones_reingresa_todo(client, admin_headers, contexto, db_session):
    venta = _vender_y_pagar(client, contexto, cantidad=3)

    anular_venta(db_session, venta["id"])

    assert _stock(client, admin_headers, contexto)["cantidad_fisica"] == 10


# ---- punto 2: devoluciones concurrentes ----------------------------------------------------


class _EspiaOrden:
    def __init__(self) -> None:
        self.eventos: list[str] = []


@pytest.fixture()
def espia_devolucion(monkeypatch):
    espia = _EspiaOrden()
    original_obtener = VentaRepository.obtener
    original_bloqueado = VentaRepository.obtener_bloqueado
    original_devuelta = DevolucionRepository.cantidad_devuelta

    def obtener(self, db, venta_id):
        espia.eventos.append("venta.obtener")
        return original_obtener(self, db, venta_id)

    def bloqueado(self, db, venta_id):
        espia.eventos.append("venta.obtener_bloqueado")
        return original_bloqueado(self, db, venta_id)

    def devuelta(self, db, venta_detalle_id):
        espia.eventos.append("cantidad_devuelta")
        return original_devuelta(self, db, venta_detalle_id)

    monkeypatch.setattr(VentaRepository, "obtener", obtener)
    monkeypatch.setattr(VentaRepository, "obtener_bloqueado", bloqueado)
    monkeypatch.setattr(DevolucionRepository, "cantidad_devuelta", devuelta)
    return espia


def test_devolucion_bloquea_la_venta_antes_de_validar_las_cantidades(client, contexto, espia_devolucion):
    venta = _vender_y_pagar(client, contexto, cantidad=4)
    espia_devolucion.eventos.clear()

    assert _devolver(client, contexto, venta, 1).status_code == 201

    eventos = espia_devolucion.eventos
    assert "venta.obtener_bloqueado" in eventos
    assert "venta.obtener" not in eventos  # la fila nunca se lee sin bloqueo
    assert eventos.index("venta.obtener_bloqueado") < eventos.index("cantidad_devuelta")


def test_dos_devoluciones_no_pueden_superar_lo_vendido(client, admin_headers, contexto):
    venta = _vender_y_pagar(client, contexto, cantidad=4)

    assert _devolver(client, contexto, venta, 3).status_code == 201
    segunda = _devolver(client, contexto, venta, 2)

    assert segunda.status_code == 400
    assert "No se puede devolver más de lo vendido" in segunda.json()["detail"]
    # Solo la primera devolución reingresó stock.
    assert _stock(client, admin_headers, contexto)["cantidad_fisica"] == 9


# ---- punto 3: cobro en caja con la venta bloqueada -----------------------------------------


@pytest.fixture()
def espia_venta(monkeypatch):
    espia = _EspiaOrden()
    original_obtener = VentaRepository.obtener
    original_bloqueado = VentaRepository.obtener_bloqueado

    def obtener(self, db, venta_id):
        espia.eventos.append("venta.obtener")
        return original_obtener(self, db, venta_id)

    def bloqueado(self, db, venta_id):
        espia.eventos.append("venta.obtener_bloqueado")
        return original_bloqueado(self, db, venta_id)

    monkeypatch.setattr(VentaRepository, "obtener", obtener)
    monkeypatch.setattr(VentaRepository, "obtener_bloqueado", bloqueado)
    return espia


def test_cobrar_en_caja_lee_la_venta_con_bloqueo(client, contexto, espia_venta):
    venta = client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": contexto["sucursal_id"], "detalle": [{"variante_id": contexto["variante_id"], "cantidad": 1}]},
        headers=contexto["cajero_headers"],
    ).json()
    espia_venta.eventos.clear()

    pago = client.post(
        "/api/v1/pagos/caja", json={"venta_id": venta["id"], "metodo_pago": "qr"}, headers=contexto["cajero_headers"]
    )

    assert pago.status_code == 201, pago.text
    # La primera lectura de la venta es la bloqueada (antes de validar nada).
    assert espia_venta.eventos[0] == "venta.obtener_bloqueado"


def test_cobrar_en_caja_una_venta_ya_pagada_se_rechaza_sin_crear_otro_pago(client, contexto, db_session):
    venta = _vender_y_pagar(client, contexto, cantidad=1)
    pagos_antes = db_session.scalar(select(func.count()).select_from(Pago))

    segundo = client.post(
        "/api/v1/pagos/caja", json={"venta_id": venta["id"], "metodo_pago": "qr"}, headers=contexto["cajero_headers"]
    )

    assert segundo.status_code == 400
    assert "pagada" in segundo.json()["detail"]
    assert db_session.scalar(select(func.count()).select_from(Pago)) == pagos_antes


def test_cobrar_en_caja_valida_el_estado_antes_de_crear_el_pago(client, contexto, db_session, admin_headers):
    """Con commit=False (sincronización offline) el error no deja un pago
    huérfano en flush: se rechaza antes de crearlo."""
    venta = _vender_y_pagar(client, contexto, cantidad=1)
    usuario_id = client.get("/api/v1/auth/yo", headers=contexto["cajero_headers"]).json()["id"]
    pagos_antes = db_session.scalar(select(func.count()).select_from(Pago))

    with pytest.raises(DomainError):
        cobrar_en_caja(db_session, usuario_id, venta["id"], "qr", commit=False)

    assert not any(isinstance(obj, Pago) for obj in db_session.new)
    assert db_session.scalar(select(func.count()).select_from(Pago)) == pagos_antes


# ---- punto 4: venta desde una reserva ------------------------------------------------------


def _reserva_completada(client, admin_headers, cliente_headers, ctx, cantidad):
    reserva = client.post(
        "/api/v1/reservas",
        json={
            "sucursal_id": ctx["sucursal_id"],
            "fecha_visita": _proxima_fecha_con_dia_semana(3).isoformat(),
            "hora_visita_desde": "10:00:00",
            "hora_visita_hasta": "11:00:00",
            "detalle": [{"variante_id": ctx["variante_id"], "cantidad": cantidad}],
        },
        headers=cliente_headers,
    ).json()
    client.put(f"/api/v1/reservas/{reserva['id']}/preparar", headers=admin_headers)
    client.put(f"/api/v1/reservas/{reserva['id']}/confirmar-llegada", headers=admin_headers)
    seleccion = client.put(
        f"/api/v1/reservas/{reserva['id']}/seleccion",
        json={"lineas": [{"variante_id": ctx["variante_id"], "seleccionada": True}]},
        headers=admin_headers,
    ).json()
    assert seleccion["estado"] == "completada"
    return reserva


def _facturar_reserva(client, ctx, reserva):
    return client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": ctx["sucursal_id"], "reserva_id": reserva["id"]},
        headers=ctx["cajero_headers"],
    )


def _venta_ajena(client, ctx, cantidad):
    """Otra venta pendiente de pago: su stock apartado es de ella, no de la reserva."""
    respuesta = client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": ctx["sucursal_id"], "detalle": [{"variante_id": ctx["variante_id"], "cantidad": cantidad}]},
        headers=ctx["cajero_headers"],
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def test_venta_desde_reserva_no_puede_pedir_mas_que_las_unidades_de_la_reserva(
    client, admin_headers, cliente_headers, contexto, db_session
):
    """La reserva aparta 2 unidades y hay otras 3 apartadas por una venta
    ajena (cantidad_reservada = 5). Pedir 5 en nombre de la reserva se tragaba
    las 3 ajenas porque se comparaba con el agregado de la variante."""
    reserva = _reserva_completada(client, admin_headers, cliente_headers, contexto, cantidad=2)
    _venta_ajena(client, contexto, 3)
    assert _stock(client, admin_headers, contexto)["cantidad_reservada"] == 5

    with pytest.raises(ConflictoError, match="reserva"):
        registrar_venta(
            db_session,
            canal="presencial",
            sucursal_id=contexto["sucursal_id"],
            lineas=[(contexto["variante_id"], 5)],
            cliente_id=None,
            cajero_id=None,
            reserva_id=reserva["id"],
            costo_envio=0,
            usuario_id=None,
        )


def test_documenta_el_comportamiento_actual_al_anular_una_venta_hecha_desde_reserva(
    client, admin_headers, cliente_headers, contexto, db_session
):
    """DOCUMENTA EL COMPORTAMIENTO ACTUAL (decisión de negocio pendiente, no
    se cambió): anular una venta 'pendiente_pago' hecha desde una reserva
    libera el stock apartado, pero la reserva sigue 'completada'."""
    reserva = _reserva_completada(client, admin_headers, cliente_headers, contexto, cantidad=2)
    venta = _facturar_reserva(client, contexto, reserva).json()
    assert _stock(client, admin_headers, contexto)["cantidad_reservada"] == 2

    anular_venta(db_session, venta["id"])

    assert _stock(client, admin_headers, contexto)["cantidad_reservada"] == 0  # se liberó el apartado
    estado_reserva = client.get(f"/api/v1/reservas/{reserva['id']}", headers=admin_headers).json()["estado"]
    assert estado_reserva == "completada"  # la reserva no se entera


def test_reserva_ya_liberada_por_una_anulacion_no_se_refactura_sobre_unidades_ajenas(
    client, admin_headers, cliente_headers, contexto, db_session
):
    """Tras anular la primera venta de la reserva (que liberó su apartado),
    otra venta aparta 3 unidades. Refacturar la reserva (2 unidades) pasaba el
    chequeo porque 3 >= 2, y al cobrarla liberaba unidades de la otra venta.
    Ahora se rechaza: la reserva ya no tiene stock apartado."""
    reserva = _reserva_completada(client, admin_headers, cliente_headers, contexto, cantidad=2)
    primera = _facturar_reserva(client, contexto, reserva).json()
    anular_venta(db_session, primera["id"])
    _venta_ajena(client, contexto, 3)

    segunda = _facturar_reserva(client, contexto, reserva)

    assert segunda.status_code == 409, segunda.text
    assert "ya no tiene stock apartado" in segunda.json()["detail"]
    # El apartado de la venta ajena queda intacto.
    assert _stock(client, admin_headers, contexto)["cantidad_reservada"] == 3


# ---- punto 5: helper único de cierre de transacción ----------------------------------------


def test_cerrar_tx_con_commit_confirma_y_refresca():
    db, entidad = MagicMock(), object()

    _cerrar_tx(db, entidad, True)

    db.commit.assert_called_once_with()
    db.refresh.assert_called_once_with(entidad)
    db.flush.assert_not_called()


def test_cerrar_tx_sin_commit_solo_hace_flush():
    db, entidad = MagicMock(), object()

    _cerrar_tx(db, entidad, False)

    db.flush.assert_called_once_with()
    db.commit.assert_not_called()
    db.refresh.assert_not_called()
