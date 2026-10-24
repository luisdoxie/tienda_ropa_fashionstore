"""E07: consulta del estado de lo enviado (GET /operaciones y /operaciones/{operacion_id}).

Sin el permiso `sincronizacion.supervisar` cada usuario ve SOLO lo suyo (la ajena es 404). Con él
(administrador, encargado de sucursal) ve su alcance: el administrador toda la empresa, el encargado
solo su sucursal. El listado nunca trae el payload; el detalle de un supervisor sí."""

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.tiempo import hoy_utc
from app.plataforma.models import Usuario
from tests.sincronizacion.ayudas import (
    API,
    armar_reserva,
    armar_venta,
    enviar,
)


def _ids(respuesta) -> list[str]:
    assert respuesta.status_code == 200, respuesta.text
    return [item["operacion_id"] for item in respuesta.json()["items"]]


def _enviar_una(client, headers, operacion, estado: str) -> str:
    resultado = enviar(client, headers, [operacion]).json()["resultados"][0]
    assert resultado["estado"] == estado, resultado
    return operacion["operacion_id"]


@pytest.fixture()
def mundo(client, db_session, escenario):
    """Seis operaciones, enviadas en este orden (la primera es la más antigua):
    cajero: venta (confirmada), reserva (confirmada), venta con variante inexistente (rechazada) y
    venta sin stock (en_conflicto); encargado: reserva (confirmada; el encargado no tiene el permiso de vender en caja); administrador: venta en una
    SEGUNDA sucursal (confirmada)."""
    admin = escenario.admin
    ciudad = client.post("/api/v1/ciudades", json={"nombre": "Potosi sync", "departamento": "Potosi"}, headers=admin)
    otra = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad.json()["id"], "codigo": "SUC-SYNC-B", "nombre": "Sucursal sync B", "direccion": "Av. 2"},
        headers=admin,
    ).json()["id"]
    client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": escenario.v1, "sucursal_id": otra, "tipo_movimiento_codigo": "recepcion",
            "cantidad": 5, "costo_unitario": "40.00",
        },
        headers=admin,
    )
    admin_id = db_session.scalar(select(Usuario.id).where(Usuario.email == "admin@example.com"))
    ficha = client.post(
        "/api/v1/empleados",
        json={"usuario_id": admin_id, "sucursal_id": escenario.sucursal_id, "cargo": "Administrador"},
        headers=admin,
    )
    assert ficha.status_code == 201, ficha.text

    sin_variante = [{"variante_id": 999999, "cantidad": 1, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    sin_stock = [{"variante_id": escenario.v2, "cantidad": 5, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    ops = SimpleNamespace(
        otra_sucursal=otra,
        admin_id=admin_id,
        venta_cajero=_enviar_una(client, escenario.cajero, armar_venta(escenario), "confirmada"),
        reserva_cajero=_enviar_una(client, escenario.cajero, armar_reserva(escenario), "confirmada"),
        rechazada_cajero=_enviar_una(
            client, escenario.cajero, armar_venta(escenario, lineas=sin_variante, monto_recibido="100.00"), "rechazada"
        ),
        conflicto_cajero=_enviar_una(
            client, escenario.cajero, armar_venta(escenario, lineas=sin_stock, monto_recibido="500.00"), "en_conflicto"
        ),
        reserva_encargado=_enviar_una(client, escenario.encargado, armar_reserva(escenario), "confirmada"),
        venta_admin_otra=_enviar_una(client, admin, armar_venta(escenario, sucursal_id=otra), "confirmada"),
    )
    ops.orden_de_envio = [
        ops.venta_cajero, ops.reserva_cajero, ops.rechazada_cajero, ops.conflicto_cajero,
        ops.reserva_encargado, ops.venta_admin_otra,
    ]  # fmt: skip
    ops.del_cajero = set(ops.orden_de_envio[:4])
    return ops


# ---- Quién ve qué -----------------------------------------------------------------------------------


def test_cada_usuario_sin_permiso_de_supervisar_ve_solo_sus_operaciones(client, escenario, mundo):
    del_cajero = client.get(f"{API}/operaciones", headers=escenario.cajero)

    assert set(_ids(del_cajero)) == mundo.del_cajero
    assert del_cajero.json()["total"] == 4
    assert mundo.reserva_encargado not in _ids(del_cajero)
    assert all(i["usuario_id"] == escenario.cajero_usuario_id for i in del_cajero.json()["items"])


def test_el_encargado_supervisa_las_de_su_sucursal_y_no_las_de_otra(client, escenario, mundo):
    del_encargado = client.get(f"{API}/operaciones", headers=escenario.encargado)

    assert set(_ids(del_encargado)) == mundo.del_cajero | {mundo.reserva_encargado}
    assert mundo.venta_admin_otra not in _ids(del_encargado)
    assert {i["sucursal_id"] for i in del_encargado.json()["items"]} == {escenario.sucursal_id}


def test_el_administrador_ve_toda_la_empresa(client, escenario, mundo):
    del_admin = client.get(f"{API}/operaciones", headers=escenario.admin)

    assert set(_ids(del_admin)) == set(mundo.orden_de_envio)
    assert del_admin.json()["total"] == 6


# ---- Filtros -----------------------------------------------------------------------------------------


def test_los_filtros_de_estado_y_tipo(client, escenario, mundo):
    def consulta(**parametros):
        return set(_ids(client.get(f"{API}/operaciones", params=parametros, headers=escenario.admin)))

    assert consulta(estado="confirmada") == {
        mundo.venta_cajero, mundo.reserva_cajero, mundo.reserva_encargado, mundo.venta_admin_otra,
    }  # fmt: skip
    assert consulta(estado="rechazada") == {mundo.rechazada_cajero}
    assert consulta(estado="en_conflicto") == {mundo.conflicto_cajero}
    reservas = {mundo.reserva_cajero, mundo.reserva_encargado}
    assert consulta(tipo="reserva") == reservas
    assert consulta(tipo="venta_contado") == set(mundo.orden_de_envio) - reservas
    assert consulta(tipo="venta_contado", estado="confirmada") == {mundo.venta_cajero, mundo.venta_admin_otra}
    assert client.get(f"{API}/operaciones", params={"estado": "inventada"}, headers=escenario.admin).status_code == 422
    assert client.get(f"{API}/operaciones", params={"tipo": "inventado"}, headers=escenario.admin).status_code == 422


def test_los_filtros_de_fecha_son_por_recibida_en_con_hasta_inclusivo(client, escenario, mundo):
    hoy = hoy_utc()
    ayer, manana = hoy - dt.timedelta(days=1), hoy + dt.timedelta(days=1)

    def total(**parametros):
        respuesta = client.get(f"{API}/operaciones", params=parametros, headers=escenario.admin)
        assert respuesta.status_code == 200, respuesta.text
        return respuesta.json()["total"]

    assert total(desde=hoy.isoformat(), hasta=hoy.isoformat()) == 6  # hoy entra completo
    assert total(desde=ayer.isoformat()) == 6
    assert total(hasta=manana.isoformat()) == 6
    assert total(desde=manana.isoformat()) == 0
    assert total(hasta=ayer.isoformat()) == 0
    assert total(desde=ayer.isoformat(), hasta=ayer.isoformat()) == 0
    assert client.get(f"{API}/operaciones", params={"desde": "no-es-fecha"}, headers=escenario.admin).status_code == 422


def test_los_filtros_de_sucursal_y_usuario(client, escenario, mundo):
    def ids(headers, **parametros):
        return set(_ids(client.get(f"{API}/operaciones", params=parametros, headers=headers)))

    # El administrador (alcance global) elige la sucursal.
    assert ids(escenario.admin, sucursal_id=mundo.otra_sucursal) == {mundo.venta_admin_otra}
    assert ids(escenario.admin, sucursal_id=escenario.sucursal_id) == set(mundo.orden_de_envio) - {mundo.venta_admin_otra}
    # Un supervisor puede filtrar por usuario.
    assert ids(escenario.admin, usuario_id=escenario.cajero_usuario_id) == mundo.del_cajero
    assert ids(escenario.encargado, usuario_id=escenario.cajero_usuario_id) == mundo.del_cajero
    assert ids(escenario.admin, usuario_id=mundo.admin_id) == {mundo.venta_admin_otra}
    # El encargado está limitado a su sucursal: pedir otra es 403 y pedir la propia no cambia nada.
    ajena = client.get(f"{API}/operaciones", params={"sucursal_id": mundo.otra_sucursal}, headers=escenario.encargado)
    assert ajena.status_code == 403, ajena.text
    assert len(ids(escenario.encargado, sucursal_id=escenario.sucursal_id)) == 5


def test_quien_no_supervisa_no_puede_ver_lo_ajeno_aunque_mande_usuario_id_o_sucursal(client, escenario, mundo):
    con_usuario_ajeno = client.get(
        f"{API}/operaciones", params={"usuario_id": escenario.encargado_usuario_id}, headers=escenario.cajero
    )
    con_admin = client.get(f"{API}/operaciones", params={"usuario_id": mundo.admin_id}, headers=escenario.cajero)
    con_sucursal_ajena = client.get(
        f"{API}/operaciones", params={"sucursal_id": mundo.otra_sucursal}, headers=escenario.cajero
    )

    assert set(_ids(con_usuario_ajeno)) == mundo.del_cajero  # ignora el filtro: sigue viendo solo lo suyo
    assert set(_ids(con_admin)) == mundo.del_cajero
    assert _ids(con_sucursal_ajena) == []  # lo suyo, filtrado por esa sucursal: nada


# ---- Paginación y orden ----------------------------------------------------------------------------


def test_la_paginacion_y_el_orden_son_de_la_mas_reciente_a_la_mas_antigua(client, escenario, mundo):
    esperado = list(reversed(mundo.orden_de_envio))

    completa = client.get(f"{API}/operaciones", headers=escenario.admin)
    assert _ids(completa) == esperado
    assert completa.json()["pagina"] == 1 and completa.json()["tamanio"] == 20

    paginas = []
    for pagina in (1, 2, 3):
        respuesta = client.get(f"{API}/operaciones", params={"pagina": pagina, "tamanio": 2}, headers=escenario.admin)
        assert respuesta.json()["total"] == 6 and respuesta.json()["pagina"] == pagina and respuesta.json()["tamanio"] == 2
        paginas.append(_ids(respuesta))
    assert paginas == [esperado[0:2], esperado[2:4], esperado[4:6]]
    assert _ids(client.get(f"{API}/operaciones", params={"pagina": 4, "tamanio": 2}, headers=escenario.admin)) == []

    for parametros in ({"tamanio": 101}, {"tamanio": 0}, {"pagina": 0}):
        assert client.get(f"{API}/operaciones", params=parametros, headers=escenario.admin).status_code == 422
    assert client.get(f"{API}/operaciones", params={"tamanio": 100}, headers=escenario.admin).status_code == 200


# ---- Payload y detalle ----------------------------------------------------------------------------


def test_el_listado_nunca_trae_el_payload_y_el_detalle_solo_para_quien_supervisa(client, escenario, mundo):
    for headers in (escenario.cajero, escenario.encargado, escenario.admin):
        for item in client.get(f"{API}/operaciones", headers=headers).json()["items"]:
            assert "payload" not in item

    ruta = f"{API}/operaciones/{mundo.venta_cajero}"
    propio = client.get(ruta, headers=escenario.cajero)  # el dueño, sin supervisar
    assert propio.status_code == 200 and propio.json()["estado"] == "confirmada"
    assert propio.json().get("payload") is None

    for supervisor in (escenario.encargado, escenario.admin):
        detalle = client.get(ruta, headers=supervisor)
        assert detalle.status_code == 200, detalle.text
        payload = detalle.json()["payload"]
        assert payload["cliente_id"] == escenario.cliente_id and payload["total"] == "200.00"
        assert payload["pago"] == {"metodo": "efectivo", "monto_recibido": "250.00"}
        assert detalle.json()["operacion_id"] == mundo.venta_cajero and detalle.json()["intentos"] == 1


def test_el_detalle_de_una_ajena_sin_permiso_o_fuera_de_alcance_es_404_igual_que_una_inexistente(
    client, escenario, mundo
):
    inexistente = client.get(f"{API}/operaciones/{uuid.uuid4()}", headers=escenario.cajero)
    assert inexistente.status_code == 404

    del_encargado = client.get(f"{API}/operaciones/{mundo.reserva_encargado}", headers=escenario.cajero)
    del_admin = client.get(f"{API}/operaciones/{mundo.venta_admin_otra}", headers=escenario.cajero)
    de_otra_sucursal = client.get(f"{API}/operaciones/{mundo.venta_admin_otra}", headers=escenario.encargado)
    for respuesta in (del_encargado, del_admin, de_otra_sucursal):
        assert respuesta.status_code == 404, respuesta.text
        assert respuesta.json() == inexistente.json()
    # Con su alcance completo, el administrador abre cualquiera (la misma petición con permiso funciona).
    assert client.get(f"{API}/operaciones/{mundo.venta_admin_otra}", headers=escenario.admin).status_code == 200
    assert client.get(f"{API}/operaciones/{mundo.reserva_encargado}", headers=escenario.encargado).status_code == 200


def test_un_operacion_id_que_no_es_uuid_responde_422(client, escenario, mundo):
    for texto in ("no-es-un-uuid", "123", "0d6b6c1e-xxxx-4000-8000-000000000000"):
        respuesta = client.get(f"{API}/operaciones/{texto}", headers=escenario.admin)
        assert respuesta.status_code == 422, f"{texto}: {respuesta.text}"
