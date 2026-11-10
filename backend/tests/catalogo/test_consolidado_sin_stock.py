"""Inventario > Consolidado con `incluir_sin_stock`: la vista `vw_inventario_consolidado` parte de `stock`, así que
una variante que nunca tuvo un movimiento en una sucursal no aparecía y no había cómo darle su primer stock. Con el
parámetro salen también las variantes activas sin fila (en cero y con `sin_registro`), y un ajuste positivo les crea
la fila."""

from app.catalogo.models import ProductoVariante, Talla
from app.core.tenant import empresa_de, fijar_empresa
from tests.catalogo.test_consolidado_empresa import sembrar_negocio

CONSOLIDADO = "/api/v1/inventario/consolidado"


def _agregar_variante_sin_stock(db, datos: dict, codigo_talla: str, sku: str, activa: bool = True) -> int:
    """Una variante más del mismo producto y color que `sembrar_negocio`, SIN fila de stock."""
    original = empresa_de(db)
    fijar_empresa(db, datos["empresa_id"])
    base = db.get(ProductoVariante, datos["variante_id"])
    talla = Talla(codigo=codigo_talla)
    db.add(talla)
    db.flush()
    variante = ProductoVariante(
        producto_id=base.producto_id, talla_id=talla.id, color_id=base.color_id, sku=sku, activo=activa
    )
    db.add(variante)
    db.commit()
    variante_id = variante.id
    fijar_empresa(db, original)
    return variante_id


def test_sin_el_parametro_el_consolidado_sigue_igual(client_por_peticion, dos_empresas, db_session):
    a = sembrar_negocio(db_session, dos_empresas.a.id, "A")
    _agregar_variante_sin_stock(db_session, a, "XL", "SKU-A-XL")

    respuesta = client_por_peticion.get(CONSOLIDADO, headers=dos_empresas.a.headers)

    assert respuesta.status_code == 200, respuesta.text
    assert [fila["sku"] for fila in respuesta.json()] == ["SKU-A"]
    assert respuesta.json()[0]["sin_registro"] is False


def test_incluir_sin_stock_suma_la_variante_sin_fila_en_cero(client_por_peticion, dos_empresas, db_session):
    a = sembrar_negocio(db_session, dos_empresas.a.id, "A", fisica=10)
    sembrar_negocio(db_session, dos_empresas.b.id, "B")
    nueva = _agregar_variante_sin_stock(db_session, a, "XL", "SKU-A-XL")

    respuesta = client_por_peticion.get(CONSOLIDADO, params={"incluir_sin_stock": True}, headers=dos_empresas.a.headers)

    assert respuesta.status_code == 200, respuesta.text
    filas = {fila["sku"]: fila for fila in respuesta.json()}
    # Solo lo de la empresa A: nada de B.
    assert set(filas) == {"SKU-A", "SKU-A-XL"}
    assert filas["SKU-A"]["sin_registro"] is False
    assert filas["SKU-A"]["cantidad_fisica"] == 10
    sin_stock = filas["SKU-A-XL"]
    assert sin_stock["sin_registro"] is True
    assert sin_stock["variante_id"] == nueva
    assert sin_stock["sucursal_id"] == a["sucursal_id"]
    assert sin_stock["sucursal"] == a["sucursal"]
    assert sin_stock["talla"] == "XL"
    assert (sin_stock["cantidad_fisica"], sin_stock["cantidad_reservada"], sin_stock["cantidad_disponible"]) == (0, 0, 0)
    assert float(sin_stock["valor_inventario"]) == 0


def test_una_variante_dada_de_baja_no_sale_sin_stock(client_por_peticion, dos_empresas, db_session):
    a = sembrar_negocio(db_session, dos_empresas.a.id, "A")
    _agregar_variante_sin_stock(db_session, a, "XL", "SKU-A-XL", activa=False)

    respuesta = client_por_peticion.get(CONSOLIDADO, params={"incluir_sin_stock": True}, headers=dos_empresas.a.headers)

    assert [fila["sku"] for fila in respuesta.json()] == ["SKU-A"]


def test_el_filtro_por_producto_tambien_acota_las_filas_sin_stock(client_por_peticion, dos_empresas, db_session):
    a = sembrar_negocio(db_session, dos_empresas.a.id, "A")
    _agregar_variante_sin_stock(db_session, a, "XL", "SKU-A-XL")

    con_su_producto = client_por_peticion.get(
        CONSOLIDADO,
        params={"incluir_sin_stock": True, "producto_id": a["producto_id"]},
        headers=dos_empresas.a.headers,
    )
    con_otro_producto = client_por_peticion.get(
        CONSOLIDADO,
        params={"incluir_sin_stock": True, "producto_id": a["producto_id"] + 999},
        headers=dos_empresas.a.headers,
    )

    assert {fila["sku"] for fila in con_su_producto.json()} == {"SKU-A", "SKU-A-XL"}
    assert con_otro_producto.json() == []


def test_un_ajuste_positivo_le_crea_la_fila_y_deja_de_ser_sin_registro(client_por_peticion, dos_empresas, db_session):
    a = sembrar_negocio(db_session, dos_empresas.a.id, "A")
    nueva = _agregar_variante_sin_stock(db_session, a, "XL", "SKU-A-XL")

    ajuste = client_por_peticion.post(
        "/api/v1/inventario/ajustes",
        json={"variante_id": nueva, "sucursal_id": a["sucursal_id"], "cantidad": 5, "observacion": "Alta inicial"},
        headers=dos_empresas.a.headers,
    )
    assert ajuste.status_code in (200, 201), ajuste.text

    respuesta = client_por_peticion.get(CONSOLIDADO, params={"incluir_sin_stock": True}, headers=dos_empresas.a.headers)
    fila = next(fila for fila in respuesta.json() if fila["sku"] == "SKU-A-XL")
    assert fila["sin_registro"] is False
    assert fila["cantidad_fisica"] == 5
    assert fila["cantidad_disponible"] == 5
    # Una sola fila por variante y sucursal: no queda también la "sin registro".
    assert [f["sku"] for f in respuesta.json()].count("SKU-A-XL") == 1
