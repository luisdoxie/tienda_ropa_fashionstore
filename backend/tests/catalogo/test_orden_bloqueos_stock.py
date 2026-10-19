"""Orden de los bloqueos de stock (T3 del análisis): toda operación que recorre
varias líneas toca las filas de `stock` en orden ascendente por
(variante_id, sucursal_id), sea cual sea el orden de las líneas, para que dos
lotes concurrentes con las mismas variantes no se interbloqueen.

SQLite no aplica FOR UPDATE: no se puede demostrar el bloqueo, solo el orden en
que se piden (fixture `espia_bloqueos`) y que el resultado funcional (respuestas,
orden del detalle, stock final) no cambia.
"""

import pytest

from app.catalogo import politicas as catalogo_politicas
from app.catalogo.repository import TransferenciaRepository

INV = "/api/v1/inventario/movimientos"


@pytest.fixture()
def lote(client, admin_headers):
    """Tres variantes (ids ascendentes), dos sucursales y un proveedor, con 50
    unidades de cada variante en ambas sucursales (las filas de stock ya existen)."""
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas Orden"}, headers=admin_headers).json()
    tallas = [
        client.post("/api/v1/tallas", json={"codigo": codigo, "orden": i}, headers=admin_headers).json()
        for i, codigo in enumerate(("S", "M", "L"), start=1)
    ]
    color = client.post("/api/v1/colores", json={"nombre": "Gris Orden"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "ORD-1",
            "nombre": "Camisa orden",
            "categoria_id": cat["id"],
            "precio_base": "50.00",
            "tallas_ids": [t["id"] for t in tallas],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variantes = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()
    variante_ids = sorted(v["id"] for v in variantes)
    assert len(variante_ids) == 3

    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Sucre Orden", "departamento": "Chuquisaca"}, headers=admin_headers
    ).json()
    sucursales = [
        client.post(
            "/api/v1/sucursales",
            json={"ciudad_id": ciudad["id"], "codigo": f"SUC-ORD-{n}", "nombre": f"Orden {n}", "direccion": "Av. 1"},
            headers=admin_headers,
        ).json()["id"]
        for n in ("A", "B")
    ]
    proveedor = client.post(
        "/api/v1/proveedores", json={"nombre": "Textiles Orden", "nit": "ORD-NIT"}, headers=admin_headers
    ).json()

    for variante_id in variante_ids:
        for sucursal_id in sucursales:
            respuesta = client.post(
                INV,
                json={
                    "variante_id": variante_id,
                    "sucursal_id": sucursal_id,
                    "tipo_movimiento_codigo": "recepcion",
                    "cantidad": 50,
                    "costo_unitario": "10.00",
                },
                headers=admin_headers,
            )
            assert respuesta.status_code == 201, respuesta.text

    return {
        "variantes": variante_ids,  # ascendentes
        "origen": sucursales[0],
        "destino": sucursales[1],
        "proveedor_id": proveedor["id"],
    }


def _stock(client, headers, variante_id, sucursal_id) -> dict:
    return client.get(f"/api/v1/inventario/stock/{variante_id}/{sucursal_id}", headers=headers).json()


# ---- el helper ---------------------------------------------------------------------------


def test_bloquear_stock_en_orden_pide_las_claves_ascendentes_y_sin_repetir(db_session, espia_bloqueos):
    catalogo_politicas.bloquear_stock_en_orden(db_session, [(3, 2), (1, 2), (3, 1), (1, 2), (2, 9)])

    assert espia_bloqueos.lotes() == [[(1, 2), (2, 9), (3, 1), (3, 2)]]


def test_bloquear_stock_en_orden_sin_claves_no_consulta(db_session, espia_bloqueos):
    catalogo_politicas.bloquear_stock_en_orden(db_session, [])

    assert espia_bloqueos.eventos == []


def test_bloquear_existentes_ignora_las_filas_que_no_existen(client, db_session, admin_headers, lote):
    from app.catalogo.politicas import stock_repo

    v1, _, v3 = lote["variantes"]
    filas = stock_repo.bloquear_existentes(
        db_session, sorted([(v3, lote["origen"]), (v1, lote["origen"]), (999_999, lote["origen"])])
    )

    assert [(f.variante_id, f.sucursal_id) for f in filas] == [(v1, lote["origen"]), (v3, lote["origen"])]


# ---- recepción (CU-08) -------------------------------------------------------------------


def test_recepcion_bloquea_en_orden_y_conserva_el_orden_de_las_lineas(client, admin_headers, lote, espia_bloqueos):
    v1, v2, v3 = lote["variantes"]
    desordenadas = [v3, v1, v2]
    espia_bloqueos.eventos.clear()

    respuesta = client.post(
        "/api/v1/recepciones",
        json={
            "codigo": "REC-ORD-1",
            "proveedor_id": lote["proveedor_id"],
            "sucursal_id": lote["origen"],
            "detalle": [{"variante_id": v, "cantidad": 5, "costo_unitario": "10.00"} for v in desordenadas],
        },
        headers=admin_headers,
    )

    assert respuesta.status_code == 201, respuesta.text
    # Orden de adquisición: ascendente, aunque las líneas llegaron v3, v1, v2.
    assert espia_bloqueos.lotes() == [[(v1, lote["origen"]), (v2, lote["origen"]), (v3, lote["origen"])]]
    assert espia_bloqueos.orden_de_adquisicion() == [(v, lote["origen"]) for v in (v1, v2, v3)]
    # Lo persistido / respondido sigue en el orden recibido.
    assert [linea["variante_id"] for linea in respuesta.json()["detalle"]] == desordenadas
    for v in (v1, v2, v3):
        assert _stock(client, admin_headers, v, lote["origen"])["cantidad_fisica"] == 55


# ---- transferencia (CU-09) ---------------------------------------------------------------


def _crear_transferencia(client, headers, lote, codigo, variantes) -> dict:
    respuesta = client.post(
        "/api/v1/transferencias",
        json={
            "codigo": codigo,
            "sucursal_origen_id": lote["origen"],
            "sucursal_destino_id": lote["destino"],
            "detalle": [{"variante_id": v, "cantidad": 4} for v in variantes],
        },
        headers=headers,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def test_enviar_y_recibir_transferencia_bloquean_en_orden(client, admin_headers, lote, espia_bloqueos):
    v1, v2, v3 = lote["variantes"]
    desordenadas = [v3, v1, v2]
    transferencia = _crear_transferencia(client, admin_headers, lote, "TR-ORD-1", desordenadas)
    espia_bloqueos.eventos.clear()

    enviada = client.post(f"/api/v1/transferencias/{transferencia['id']}/enviar", headers=admin_headers)

    assert enviada.status_code == 200, enviada.text
    assert espia_bloqueos.orden_de_adquisicion() == [(v, lote["origen"]) for v in (v1, v2, v3)]
    assert [linea["variante_id"] for linea in enviada.json()["detalle"]] == desordenadas
    assert enviada.json()["estado"] == "en_transito"

    espia_bloqueos.eventos.clear()
    recibida = client.post(f"/api/v1/transferencias/{transferencia['id']}/recibir", headers=admin_headers)

    assert recibida.status_code == 200, recibida.text
    assert espia_bloqueos.orden_de_adquisicion() == [(v, lote["destino"]) for v in (v1, v2, v3)]
    assert [linea["variante_id"] for linea in recibida.json()["detalle"]] == desordenadas
    assert recibida.json()["estado"] == "recibida"
    for v in (v1, v2, v3):
        assert _stock(client, admin_headers, v, lote["origen"])["cantidad_fisica"] == 46
        assert _stock(client, admin_headers, v, lote["destino"])["cantidad_fisica"] == 54


def test_enviar_dos_veces_la_misma_transferencia_la_segunda_es_409(client, admin_headers, lote):
    transferencia = _crear_transferencia(client, admin_headers, lote, "TR-ORD-2", lote["variantes"])
    url = f"/api/v1/transferencias/{transferencia['id']}/enviar"

    assert client.post(url, headers=admin_headers).status_code == 200
    segunda = client.post(url, headers=admin_headers)

    assert segunda.status_code == 409
    assert _stock(client, admin_headers, lote["variantes"][0], lote["origen"])["cantidad_fisica"] == 46


def test_enviar_recibir_y_anular_toman_la_fila_de_la_transferencia_bloqueada_antes_de_validar(
    client, admin_headers, lote, monkeypatch
):
    """La fila se pide con obtener_bloqueado (FOR UPDATE en Postgres) y no con
    obtener, y antes de que se valide el estado."""
    llamadas: list[str] = []
    original = TransferenciaRepository.obtener_bloqueado

    def espiar(self, db, transferencia_id):
        llamadas.append("bloqueado")
        return original(self, db, transferencia_id)

    def prohibir(self, db, transferencia_id):
        raise AssertionError("enviar/recibir/anular no deben leer la transferencia sin bloquearla")

    monkeypatch.setattr(TransferenciaRepository, "obtener_bloqueado", espiar)
    primera = _crear_transferencia(client, admin_headers, lote, "TR-ORD-3", lote["variantes"])
    segunda = _crear_transferencia(client, admin_headers, lote, "TR-ORD-4", lote["variantes"])
    monkeypatch.setattr(TransferenciaRepository, "obtener", prohibir)

    assert client.post(f"/api/v1/transferencias/{primera['id']}/enviar", headers=admin_headers).status_code == 200
    assert client.post(f"/api/v1/transferencias/{primera['id']}/recibir", headers=admin_headers).status_code == 200
    anulada = client.delete(f"/api/v1/transferencias/{segunda['id']}", headers=admin_headers)

    assert llamadas == ["bloqueado"] * 3
    assert anulada.status_code == 200, anulada.text
    assert anulada.json()["estado"] == "anulada"
