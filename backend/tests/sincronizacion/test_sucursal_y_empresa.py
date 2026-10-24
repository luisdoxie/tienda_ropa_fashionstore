"""E07: sucursal y empresa de cada operación. La empresa sale SIEMPRE del token; una sucursal, un
cliente o una variante de otra empresa se ven igual que si no existieran; el personal limitado a
una sucursal no puede enviar operaciones de otra, y quien tiene alcance global sí.

Dos empresas independientes (A = Profesional, B = Básico) con una sesión nueva por petición."""

import uuid

import pytest

from app.catalogo.politicas import obtener_stock
from app.core.tenant import en_empresa
from tests.sincronizacion.ayudas import (
    API,
    STOCK_V1,
    armar_reserva,
    armar_venta,
    construir_escenario,
    enviar,
    nuevo_uuid,
)


@pytest.fixture()
def a(client_por_peticion, dos_empresas, db_session):
    return construir_escenario(
        client_por_peticion, dos_empresas.a.headers, db_session, sufijo="-a", codigo_empresa="tienda-a"
    )


@pytest.fixture()
def b(client_por_peticion, dos_empresas, db_session):
    return construir_escenario(
        client_por_peticion, dos_empresas.b.headers, db_session, sufijo="-b", codigo_empresa="tienda-b"
    )


def _una(respuesta) -> dict:
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["resultados"][0]


def _stock(db, empresa_id: int, variante_id: int, sucursal_id: int) -> tuple[int, int]:
    db.expire_all()
    with en_empresa(db, empresa_id):
        stock = obtener_stock(db, variante_id, sucursal_id)
        return stock.cantidad_fisica, stock.cantidad_reservada


def _segunda_sucursal(client, headers: dict, sufijo: str) -> int:
    """Otra sucursal de la MISMA empresa (por la API), abierta todos los días."""
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": f"Potosi{sufijo}", "departamento": "Potosi"}, headers=headers
    )
    assert ciudad.status_code in (200, 201), ciudad.text
    sucursal = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad.json()["id"], "codigo": f"SUC-B{sufijo}", "nombre": f"Sucursal B{sufijo}", "direccion": "Av. 2"},
        headers=headers,
    )
    assert sucursal.status_code in (200, 201), sucursal.text
    return sucursal.json()["id"]


# ---- Sucursales de la misma empresa -----------------------------------------------------------------


def test_un_cajero_no_puede_enviar_una_operacion_de_otra_sucursal_de_su_empresa(
    client_por_peticion, dos_empresas, a
):
    client = client_por_peticion
    otra = _segunda_sucursal(client, dos_empresas.a.headers, "-a")

    operacion = armar_venta(a, sucursal_id=otra)
    resultado = _una(enviar(client, a.cajero, [operacion]))

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "sucursal_no_autorizada"
    assert resultado["recurso"] is None
    detalle = client.get(f"{API}/operaciones/{operacion['operacion_id']}", headers=a.cajero).json()
    assert detalle["estado"] == "rechazada" and detalle["sucursal_id"] == otra  # la sucursal existe: se guarda


def test_el_administrador_con_alcance_global_si_puede_enviar_para_cualquier_sucursal(
    client_por_peticion, dos_empresas, db_session, a
):
    client, admin = client_por_peticion, dos_empresas.a.headers
    otra = _segunda_sucursal(client, admin, "-a")
    movimiento = client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": a.v1, "sucursal_id": otra, "tipo_movimiento_codigo": "recepcion",
            "cantidad": 5, "costo_unitario": "40.00",
        },
        headers=admin,
    )
    assert movimiento.status_code in (200, 201), movimiento.text
    # El administrador es empleado (de la sucursal A); su alcance global le permite vender en la B.
    ficha = client.post(
        "/api/v1/empleados",
        json={"usuario_id": dos_empresas.a.admin_id, "sucursal_id": a.sucursal_id, "cargo": "Administrador"},
        headers=admin,
    )
    assert ficha.status_code == 201, ficha.text

    en_otra = _una(enviar(client, admin, [armar_venta(a, sucursal_id=otra)]))
    en_la_propia = _una(enviar(client, admin, [armar_venta(a)]))

    assert en_otra["estado"] == "confirmada", en_otra
    assert en_la_propia["estado"] == "confirmada", en_la_propia
    assert _stock(db_session, dos_empresas.a.id, a.v1, otra) == (5 - 2, 0)
    assert _stock(db_session, dos_empresas.a.id, a.v1, a.sucursal_id) == (STOCK_V1 - 2, 0)


# ---- Datos de otra empresa --------------------------------------------------------------------------


def test_una_sucursal_de_otra_empresa_se_rechaza_como_inexistente_y_se_guarda_sin_sucursal(
    client_por_peticion, a, b
):
    client = client_por_peticion

    operacion = armar_venta(a, sucursal_id=b.sucursal_id)
    resultado = _una(enviar(client, a.cajero, [operacion]))

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "sucursal_inexistente"
    detalle = client.get(f"{API}/operaciones/{operacion['operacion_id']}", headers=a.cajero).json()
    assert detalle["sucursal_id"] is None  # la FK no apunta a la sucursal de otra empresa
    # La empresa B no se enteró de nada.
    assert client.get(f"{API}/operaciones", headers=b.cajero).json()["total"] == 0


def test_un_cliente_de_otra_empresa_se_rechaza_como_inexistente(client_por_peticion, a, b):
    resultado = _una(enviar(client_por_peticion, a.cajero, [armar_venta(a, cliente_id=b.cliente_id)]))
    reserva = _una(enviar(client_por_peticion, a.cajero, [armar_reserva(a, cliente_id=b.cliente_id)]))

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "cliente_inexistente"
    assert reserva["estado"] == "rechazada" and reserva["motivo"] == "cliente_inexistente"


def test_una_variante_de_otra_empresa_se_rechaza_como_inexistente_y_no_toca_su_stock(
    client_por_peticion, db_session, dos_empresas, a, b
):
    lineas = [{"variante_id": b.v1, "cantidad": 1, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]

    resultado = _una(enviar(client_por_peticion, a.cajero, [armar_venta(a, lineas=lineas, monto_recibido="100.00")]))

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "variante_inexistente"
    assert _stock(db_session, dos_empresas.b.id, b.v1, b.sucursal_id) == (STOCK_V1, 0)


def test_una_empresa_id_distinto_en_el_cuerpo_rechaza_todo_el_lote_con_403(
    client_por_peticion, dos_empresas, a
):
    client = client_por_peticion

    ajena = enviar(client, a.cajero, [armar_venta(a)], empresa_id=dos_empresas.b.id)
    assert ajena.status_code == 403, ajena.text
    assert client.get(f"{API}/operaciones", headers=a.cajero).json()["total"] == 0  # no se guardó nada

    # La misma petición con la empresa del token sí funciona (la empresa real es la del token).
    propia = enviar(client, a.cajero, [armar_venta(a)], empresa_id=dos_empresas.a.id)
    assert propia.status_code == 200 and propia.json()["resumen"]["confirmadas"] == 1


# ---- Aislamiento de las consultas ----------------------------------------------------------------


def test_un_usuario_de_otra_empresa_no_ve_ni_abre_las_operaciones_ajenas(client_por_peticion, dos_empresas, a, b):
    client = client_por_peticion
    operacion = armar_venta(a)
    assert _una(enviar(client, a.cajero, [operacion]))["estado"] == "confirmada"

    # Ni siquiera con el permiso de supervisar: el administrador de B tampoco la ve.
    for headers in (b.cajero, b.encargado, dos_empresas.b.headers):
        lista = client.get(f"{API}/operaciones", headers=headers)
        assert lista.status_code == 200 and lista.json()["total"] == 0 and lista.json()["items"] == []
        ajena = client.get(f"{API}/operaciones/{operacion['operacion_id']}", headers=headers)
        inexistente = client.get(f"{API}/operaciones/{uuid.uuid4()}", headers=headers)
        assert ajena.status_code == inexistente.status_code == 404
        assert ajena.json() == inexistente.json()  # mismo cuerpo: no revela que existe
        assert operacion["operacion_id"] not in ajena.text

    # Y el dueño sí la abre (la misma petición con sus datos funciona).
    assert client.get(f"{API}/operaciones/{operacion['operacion_id']}", headers=a.cajero).status_code == 200


def test_el_mismo_operacion_id_en_dos_empresas_no_choca_y_cada_una_ve_solo_la_suya(client_por_peticion, a, b):
    client = client_por_peticion
    compartido = nuevo_uuid()

    de_a = _una(enviar(client, a.cajero, [armar_venta(a, operacion_id=compartido)]))
    de_b = _una(enviar(client, b.cajero, [armar_venta(b, operacion_id=compartido)]))

    for resultado in (de_a, de_b):
        assert resultado["estado"] == "confirmada" and resultado["duplicada"] is False
    for headers, escenario in ((a.cajero, a), (b.cajero, b)):
        lista = client.get(f"{API}/operaciones", headers=headers).json()
        assert lista["total"] == 1 and lista["items"][0]["operacion_id"] == compartido
        assert lista["items"][0]["intentos"] == 1
        assert lista["items"][0]["sucursal_id"] == escenario.sucursal_id
        detalle = client.get(f"{API}/operaciones/{compartido}", headers=headers).json()
        assert detalle["sucursal_id"] == escenario.sucursal_id
