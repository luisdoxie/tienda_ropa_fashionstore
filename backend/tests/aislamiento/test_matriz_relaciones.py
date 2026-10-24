"""E05, 4.4: relaciones entre recursos. Un recurso de A que lleva en su interior un id de B.

Son los escenarios que el informe cita por nombre (la mayoría se repiten, campo por campo, en
`test_matriz_fk_en_cuerpo.py`; aquí se leen como frases). Cada uno exige 404 y que ni A ni B
cambien. Las rutas PROPIAS con un id de variante en el path (carrito y favoritos) se prueban aquí
porque no son rutas "por id" de la matriz.
"""

import datetime as dt

import pytest

from .universo import crear

API = "/api/v1"


def _sin_cambios(mundo, accion):
    """Ejecuta `accion()` y devuelve (respuesta, cambios en A, cambios en B)."""
    antes_a, antes_b = mundo.instantanea(mundo.a.id), mundo.instantanea(mundo.b.id)
    respuesta = accion()
    return (
        respuesta,
        mundo.cambios(antes_a, mundo.instantanea(mundo.a.id)),
        mundo.cambios(antes_b, mundo.instantanea(mundo.b.id)),
    )


def _exigir_404_sin_efecto(mundo, accion):
    respuesta, cambios_a, cambios_b = _sin_cambios(mundo, accion)
    assert respuesta.status_code == 404, f"{respuesta.status_code} {respuesta.text[:300]}"
    assert mundo.b.m("") not in respuesta.text
    assert cambios_a == [] and cambios_b == [], f"A: {cambios_a} / B: {cambios_b}"


def _pedir(mundo, metodo, ruta, cuerpo=None, token="admin"):
    return lambda: mundo.client.request(metodo, f"{API}{ruta}", json=cuerpo, headers=mundo.a.headers[token])


def test_crear_producto_de_a_con_tallas_de_b(mundo):
    a, b = mundo.a, mundo.b
    cuerpo = {
        "codigo": "REL-001",
        "nombre": "Producto REL",
        "categoria_id": a.ids["categoria"],
        "precio_base": "10.00",
        "tallas_ids": [b.ids["talla"]],
        "colores_ids": [a.ids["color"]],
    }
    _exigir_404_sin_efecto(mundo, _pedir(mundo, "POST", "/productos", cuerpo))


def test_crear_variante_de_a_con_color_de_b(mundo):
    a, b = mundo.a, mundo.b
    cuerpo = {"tallas_ids": [a.nuevo("talla")], "colores_ids": [b.ids["color"]]}
    _exigir_404_sin_efecto(mundo, _pedir(mundo, "POST", f"/productos/{a.ids['producto']}/variantes", cuerpo))


def test_vender_en_a_una_variante_de_b(mundo):
    a, b = mundo.a, mundo.b
    cuerpo = {"sucursal_id": a.ids["sucursal"], "detalle": [{"variante_id": b.ids["variante"], "cantidad": 1}]}
    _exigir_404_sin_efecto(mundo, _pedir(mundo, "POST", "/ventas/presencial", cuerpo))


def test_reservar_en_a_en_una_sucursal_de_b(mundo):
    a, b = mundo.a, mundo.b
    manana = dt.date.today() + dt.timedelta(days=3)
    cuerpo = {
        "sucursal_id": b.ids["sucursal"],
        "fecha_visita": manana.isoformat(),
        "hora_visita_desde": "10:00:00",
        "hora_visita_hasta": "11:00:00",
        "detalle": [{"variante_id": a.ids["variante"], "cantidad": 1}],
    }
    _exigir_404_sin_efecto(mundo, _pedir(mundo, "POST", "/reservas", cuerpo, token="cliente"))


def test_devolver_una_venta_de_b_desde_a(mundo):
    a, b = mundo.a, mundo.b
    cuerpo = {"venta_id": b.ids["venta"], "detalle": [{"venta_detalle_id": b.ids["venta_detalle"], "cantidad": 1}]}
    _exigir_404_sin_efecto(mundo, _pedir(mundo, "POST", "/devoluciones", cuerpo))


def test_cobrar_una_venta_de_b_desde_a(mundo):
    a, b = mundo.a, mundo.b
    cuerpo = {"venta_id": b.ids["venta_pendiente"], "metodo_pago": "efectivo", "monto_recibido": "99999"}
    _exigir_404_sin_efecto(mundo, _pedir(mundo, "POST", "/pagos/caja", cuerpo))


def test_recibir_en_a_una_orden_de_compra_de_b(mundo):
    a, b = mundo.a, mundo.b
    crear(mundo.client, f"/ordenes-compra/{b.ids['orden_compra']}/enviar", None, b.admin)
    cuerpo = {
        "codigo": "REL-REC",
        "orden_compra_id": b.ids["orden_compra"],
        "proveedor_id": a.ids["proveedor"],
        "sucursal_id": a.ids["sucursal"],
        "detalle": [{"variante_id": a.ids["variante"], "cantidad": 1, "costo_unitario": "1.00"}],
    }
    _exigir_404_sin_efecto(mundo, _pedir(mundo, "POST", "/recepciones", cuerpo))


def test_transferir_de_una_sucursal_de_a_a_una_de_b(mundo):
    a, b = mundo.a, mundo.b
    cuerpo = {
        "codigo": "REL-TRF",
        "sucursal_origen_id": a.ids["sucursal"],
        "sucursal_destino_id": b.ids["sucursal"],
        "detalle": [{"variante_id": a.ids["variante"], "cantidad": 1}],
    }
    _exigir_404_sin_efecto(mundo, _pedir(mundo, "POST", "/transferencias", cuerpo))


def test_listar_las_variantes_de_un_producto_de_b(mundo):
    b = mundo.b
    _exigir_404_sin_efecto(mundo, _pedir(mundo, "GET", f"/productos/{b.ids['producto']}/variantes"))


@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo"),
    [
        ("DELETE", "/carrito/{variante}", None),
        ("PUT", "/carrito/{variante}", {"cantidad": 2}),
        ("DELETE", "/favoritos/{variante}", None),
    ],
    ids=["DELETE carrito", "PUT carrito", "DELETE favoritos"],
)
def test_las_rutas_propias_con_una_variante_de_b_dan_404(mundo, metodo, ruta, cuerpo):
    b = mundo.b
    # B sí tiene esa variante en su carrito y en sus favoritos: A no puede tocarla.
    ruta = ruta.format(variante=b.ids["variante"])
    _exigir_404_sin_efecto(mundo, _pedir(mundo, metodo, ruta, cuerpo, token="cliente"))
    carrito_b = mundo.client.get(f"{API}/carrito", headers=b.headers["cliente"]).json()
    assert len(carrito_b["detalle"]) >= 1, "el carrito de B perdió su prenda"
