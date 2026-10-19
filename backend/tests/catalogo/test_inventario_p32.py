from decimal import Decimal

import pytest


@pytest.fixture()
def variante_y_dos_sucursales(client, admin_headers):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas P32"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "L", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Rojo"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "INV-P32-1",
            "nombre": "Camisa P32",
            "categoria_id": cat["id"],
            "precio_base": "80.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]

    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "La Paz", "departamento": "La Paz"}, headers=admin_headers
    ).json()
    suc_a = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-P32-A", "nombre": "Sucursal A", "direccion": "Calle 1"},
        headers=admin_headers,
    ).json()
    suc_b = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-P32-B", "nombre": "Sucursal B", "direccion": "Calle 2"},
        headers=admin_headers,
    ).json()

    return variante["id"], suc_a["id"], suc_b["id"]


def _recibir(client, headers, variante_id, sucursal_id, cantidad, costo):
    return client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": cantidad,
            "costo_unitario": costo,
        },
        headers=headers,
    )


# ---- disponibilidad (público) --------------------------------------------------


def test_disponibilidad_sin_token_es_publica(client, variante_y_dos_sucursales):
    variante_id, _, _ = variante_y_dos_sucursales
    respuesta = client.get(f"/api/v1/inventario/disponibilidad?variante_id={variante_id}")
    assert respuesta.status_code == 200
    assert respuesta.json() == []


def test_disponibilidad_refleja_recepciones_por_sucursal(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, suc_b = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 10, "5.00")

    respuesta = client.get(f"/api/v1/inventario/disponibilidad?variante_id={variante_id}")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo) == 1
    assert cuerpo[0]["sucursal_id"] == suc_a
    assert cuerpo[0]["cantidad_disponible"] == 10

    filtrado = client.get(
        f"/api/v1/inventario/disponibilidad?variante_id={variante_id}&sucursal_id={suc_b}"
    ).json()
    assert filtrado == []


def test_disponibilidad_variante_inexistente_falla(client):
    respuesta = client.get("/api/v1/inventario/disponibilidad?variante_id=9999")
    assert respuesta.status_code == 404


# ---- sucursal/{id} ----------------------------------------------------------------


def test_listar_stock_por_sucursal(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, suc_b = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 10, "5.00")

    respuesta = client.get(f"/api/v1/inventario/sucursal/{suc_a}", headers=admin_headers)
    assert respuesta.status_code == 200
    assert len(respuesta.json()) == 1

    vacio = client.get(f"/api/v1/inventario/sucursal/{suc_b}", headers=admin_headers)
    assert vacio.status_code == 200
    assert vacio.json() == []


# ---- límites ------------------------------------------------------------------


def test_actualizar_limites_stock(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, _ = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 10, "5.00")
    stock = client.get(f"/api/v1/inventario/stock/{variante_id}/{suc_a}", headers=admin_headers).json()

    respuesta = client.put(
        f"/api/v1/inventario/stock/{stock['id']}/limites",
        json={"stock_minimo": 3, "stock_maximo": 50},
        headers=admin_headers,
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["stock_minimo"] == 3
    assert respuesta.json()["stock_maximo"] == 50


def test_limites_maximo_menor_que_minimo_falla(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, _ = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 10, "5.00")
    stock = client.get(f"/api/v1/inventario/stock/{variante_id}/{suc_a}", headers=admin_headers).json()

    respuesta = client.put(
        f"/api/v1/inventario/stock/{stock['id']}/limites",
        json={"stock_minimo": 20, "stock_maximo": 5},
        headers=admin_headers,
    )
    assert respuesta.status_code == 400


# ---- alertas --------------------------------------------------------------------


def test_alertas_disponible_bajo_minimo(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, _ = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 5, "5.00")
    stock = client.get(f"/api/v1/inventario/stock/{variante_id}/{suc_a}", headers=admin_headers).json()
    client.put(
        f"/api/v1/inventario/stock/{stock['id']}/limites", json={"stock_minimo": 10}, headers=admin_headers
    )

    respuesta = client.get("/api/v1/inventario/alertas", headers=admin_headers)
    assert respuesta.status_code == 200
    filas = [f for f in respuesta.json() if f["variante_id"] == variante_id]
    assert len(filas) == 1
    assert filas[0]["cantidad_disponible"] == 5
    assert filas[0]["stock_minimo"] == 10


def test_alertas_no_incluye_stock_por_encima_del_minimo(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, _ = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 100, "5.00")

    respuesta = client.get("/api/v1/inventario/alertas", headers=admin_headers)
    filas = [f for f in respuesta.json() if f["variante_id"] == variante_id]
    assert filas == []


# ---- consolidado / valuación -----------------------------------------------------


def test_consolidado_expone_columnas_de_la_vista(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, _ = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 10, "8.00")

    respuesta = client.get(
        f"/api/v1/inventario/consolidado?sucursal_id={suc_a}", headers=admin_headers
    )
    assert respuesta.status_code == 200
    filas = [f for f in respuesta.json() if f["variante_id"] == variante_id]
    assert len(filas) == 1
    fila = filas[0]
    assert fila["cantidad_fisica"] == 10
    assert Decimal(str(fila["costo_promedio"])) == Decimal("8.0000")
    assert Decimal(str(fila["valor_inventario"])) == Decimal("80.0000")


def test_valuacion_suma_valor_inventario_por_sucursal(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, _ = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 10, "8.00")

    respuesta = client.get(
        f"/api/v1/inventario/valuacion?sucursal_id={suc_a}", headers=admin_headers
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo) == 1
    assert Decimal(str(cuerpo[0]["valor_total"])) == Decimal("80.0000")


# ---- ajustes --------------------------------------------------------------------


def test_ajuste_positivo_incrementa_stock_sin_afectar_costo(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, _ = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 10, "8.00")

    respuesta = client.post(
        "/api/v1/inventario/ajustes",
        json={"variante_id": variante_id, "sucursal_id": suc_a, "cantidad": 3, "observacion": "sobrante en conteo"},
        headers=admin_headers,
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["cantidad"] == 3
    assert respuesta.json()["saldo_post"] == 13

    stock = client.get(f"/api/v1/inventario/stock/{variante_id}/{suc_a}", headers=admin_headers).json()
    assert Decimal(str(stock["costo_promedio"])) == Decimal("8.0000")  # el ajuste no afecta_costo


def test_ajuste_negativo_reduce_stock(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, _ = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 10, "8.00")

    respuesta = client.post(
        "/api/v1/inventario/ajustes",
        json={"variante_id": variante_id, "sucursal_id": suc_a, "cantidad": -4},
        headers=admin_headers,
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["cantidad"] == -4
    assert respuesta.json()["saldo_post"] == 6


def test_ajuste_cantidad_cero_rechazado(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, _ = variante_y_dos_sucursales
    respuesta = client.post(
        "/api/v1/inventario/ajustes",
        json={"variante_id": variante_id, "sucursal_id": suc_a, "cantidad": 0},
        headers=admin_headers,
    )
    assert respuesta.status_code == 422


# ---- transferencias ---------------------------------------------------------------


def _crear_transferencia(client, headers, codigo, variante_id, origen, destino, cantidad=5):
    return client.post(
        "/api/v1/transferencias",
        json={
            "codigo": codigo,
            "sucursal_origen_id": origen,
            "sucursal_destino_id": destino,
            "detalle": [{"variante_id": variante_id, "cantidad": cantidad}],
        },
        headers=headers,
    )


def test_transferencia_origen_igual_destino_falla(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, _ = variante_y_dos_sucursales
    respuesta = _crear_transferencia(client, admin_headers, "TR-1", variante_id, suc_a, suc_a)
    assert respuesta.status_code == 400


def test_flujo_completo_transferencia(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, suc_b = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 20, "12.00")

    creada = _crear_transferencia(client, admin_headers, "TR-2", variante_id, suc_a, suc_b, cantidad=8)
    assert creada.status_code == 201
    transferencia = creada.json()
    assert transferencia["estado"] == "pendiente"
    assert transferencia["fecha_envio"] is None

    # crear no mueve stock todavía
    stock_a = client.get(f"/api/v1/inventario/stock/{variante_id}/{suc_a}", headers=admin_headers).json()
    assert stock_a["cantidad_fisica"] == 20

    enviada = client.post(
        f"/api/v1/transferencias/{transferencia['id']}/enviar", headers=admin_headers
    )
    assert enviada.status_code == 200
    assert enviada.json()["estado"] == "en_transito"

    stock_a = client.get(f"/api/v1/inventario/stock/{variante_id}/{suc_a}", headers=admin_headers).json()
    assert stock_a["cantidad_fisica"] == 12  # 20 - 8

    recibida = client.post(
        f"/api/v1/transferencias/{transferencia['id']}/recibir", headers=admin_headers
    )
    assert recibida.status_code == 200
    assert recibida.json()["estado"] == "recibida"

    stock_b = client.get(f"/api/v1/inventario/stock/{variante_id}/{suc_b}", headers=admin_headers).json()
    assert stock_b["cantidad_fisica"] == 8
    # usa el costo promedio del origen (12.00)
    assert Decimal(str(stock_b["costo_promedio"])) == Decimal("12.0000")


def test_no_se_puede_enviar_transferencia_sin_stock_suficiente(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, suc_b = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 3, "10.00")

    creada = _crear_transferencia(client, admin_headers, "TR-3", variante_id, suc_a, suc_b, cantidad=8)
    transferencia_id = creada.json()["id"]

    respuesta = client.post(f"/api/v1/transferencias/{transferencia_id}/enviar", headers=admin_headers)
    assert respuesta.status_code == 409

    # el estado no cambió y el stock de origen no se tocó (atomicidad)
    detalle = client.get(f"/api/v1/transferencias/{transferencia_id}", headers=admin_headers).json()
    assert detalle["estado"] == "pendiente"
    stock_a = client.get(f"/api/v1/inventario/stock/{variante_id}/{suc_a}", headers=admin_headers).json()
    assert stock_a["cantidad_fisica"] == 3


def test_no_se_puede_recibir_transferencia_pendiente(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, suc_b = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 10, "10.00")
    creada = _crear_transferencia(client, admin_headers, "TR-4", variante_id, suc_a, suc_b)

    respuesta = client.post(f"/api/v1/transferencias/{creada.json()['id']}/recibir", headers=admin_headers)
    assert respuesta.status_code == 409


def test_anular_transferencia_pendiente(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, suc_b = variante_y_dos_sucursales
    creada = _crear_transferencia(client, admin_headers, "TR-5", variante_id, suc_a, suc_b)

    respuesta = client.delete(f"/api/v1/transferencias/{creada.json()['id']}", headers=admin_headers)
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "anulada"


def test_no_se_puede_anular_transferencia_en_transito(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, suc_b = variante_y_dos_sucursales
    _recibir(client, admin_headers, variante_id, suc_a, 10, "10.00")
    creada = _crear_transferencia(client, admin_headers, "TR-6", variante_id, suc_a, suc_b)
    client.post(f"/api/v1/transferencias/{creada.json()['id']}/enviar", headers=admin_headers)

    respuesta = client.delete(f"/api/v1/transferencias/{creada.json()['id']}", headers=admin_headers)
    assert respuesta.status_code == 409


def test_transferencia_codigo_duplicado_falla(client, admin_headers, variante_y_dos_sucursales):
    variante_id, suc_a, suc_b = variante_y_dos_sucursales
    _crear_transferencia(client, admin_headers, "TR-DUP", variante_id, suc_a, suc_b)
    duplicada = _crear_transferencia(client, admin_headers, "TR-DUP", variante_id, suc_a, suc_b)
    assert duplicada.status_code == 409


def test_transferencias_requiere_permiso_gestionar_para_escribir(client, cliente_headers, variante_y_dos_sucursales):
    variante_id, suc_a, suc_b = variante_y_dos_sucursales
    respuesta = _crear_transferencia(client, cliente_headers, "TR-7", variante_id, suc_a, suc_b)
    assert respuesta.status_code == 403
