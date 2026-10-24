"""E05, PASO 3: el propio universo. Cada recurso existe en A y en B, con su marca, y los
datos solapados (mismo código, SKU, correo) conviven."""

import pytest

from app.main import app

API = "/api/v1"

RECURSOS_ESPERADOS = [
    "ciudad", "sucursal", "sucursal_destino", "horario", "usuario", "usuario_extra", "empleado", "cliente",
    "direccion", "categoria_padre", "categoria", "talla", "color", "material", "temporada", "coleccion",
    "producto", "variante", "medida", "imagen", "activo_probador", "generacion", "stock", "movimiento",
    "transferencia", "proveedor", "orden_compra", "recepcion", "zona_envio", "regla_tarifa", "promocion",
    "reserva", "venta", "venta_detalle", "pago", "devolucion", "venta_pendiente", "pago_pasarela",
    "transaccion", "envio", "consulta_voz", "historial", "recomendacion", "notificacion",
]


@pytest.mark.parametrize("recurso", RECURSOS_ESPERADOS)
def test_cada_recurso_existe_en_a_y_en_b(mundo, recurso):
    assert recurso in mundo.a.ids and recurso in mundo.b.ids
    assert mundo.a.ids[recurso] and mundo.b.ids[recurso]


def test_las_dos_empresas_tienen_la_misma_estructura_y_ids_distintos(mundo):
    assert set(mundo.a.ids) == set(mundo.b.ids)
    assert mundo.a.id != mundo.b.id
    # Los ids de una tabla compartida nunca se repiten entre empresas.
    for recurso in ("producto", "variante", "venta", "sucursal", "usuario", "pago"):
        assert mundo.a.ids[recurso] != mundo.b.ids[recurso], recurso


def test_los_datos_solapados_conviven(mundo):
    a, b = mundo.a, mundo.b
    assert a.ids["sku"] == b.ids["sku"]  # el mismo SKU en las dos empresas
    producto_a = mundo.client.get(f"{API}/productos/{a.ids['producto']}", headers=a.admin).json()
    producto_b = mundo.client.get(f"{API}/productos/{b.ids['producto']}", headers=b.admin).json()
    assert producto_a["codigo"] == producto_b["codigo"] == "CAM-001"
    sucursales_a = {s["codigo"] for s in mundo.client.get(f"{API}/sucursales", headers=a.admin).json()}
    sucursales_b = {s["codigo"] for s in mundo.client.get(f"{API}/sucursales", headers=b.admin).json()}
    assert {"SUC-1", "SUC-2"} <= sucursales_a & sucursales_b  # otras pruebas pueden haber agregado más
    correos_a = {u["email"] for u in mundo.client.get(f"{API}/usuarios", headers=a.admin).json()}
    correos_b = {u["email"] for u in mundo.client.get(f"{API}/usuarios", headers=b.admin).json()}
    assert {"caja@tienda.bo", "admin@tienda.bo"} <= correos_a & correos_b


def test_cada_empresa_solo_ve_sus_marcas(mundo):
    for propia, ajena in ((mundo.a, mundo.b), (mundo.b, mundo.a)):
        for ruta in ("/productos", "/sucursales", "/categorias", "/proveedores", "/promociones", "/ciudades"):
            texto = mundo.client.get(f"{API}{ruta}", headers=propia.admin).text
            assert propia.m("") in texto, ruta
            assert ajena.m("") not in texto, ruta


def test_los_totales_de_ventas_son_distintos(mundo):
    from tests.aislamiento.universo import TOTAL_VENDIDO

    assert TOTAL_VENDIDO["A"] != TOTAL_VENDIDO["B"]
    # Cada universo tiene como mínimo sus ventas pagadas (A: 3, B: 5) más la pendiente; la
    # prueba espejo de otros módulos puede haber agregado ventas desechables.
    ventas_a = mundo.client.get(f"{API}/ventas/sucursal/{mundo.a.ids['sucursal']}", headers=mundo.a.admin).json()
    ventas_b = mundo.client.get(f"{API}/ventas/sucursal/{mundo.b.ids['sucursal']}", headers=mundo.b.admin).json()
    assert len(ventas_a) >= 3 + 1 and len(ventas_b) >= 5 + 1
    assert mundo.a.ids["venta"] in {v["id"] for v in ventas_a}
    assert mundo.b.ids["venta"] in {v["id"] for v in ventas_b}


def test_la_instantanea_es_estable_si_no_se_toca_nada(mundo):
    antes = mundo.instantanea(mundo.b.id)
    mundo.client.get(f"{API}/productos", headers=mundo.a.admin)
    assert mundo.cambios(antes, mundo.instantanea(mundo.b.id)) == []
    assert len(antes) >= 48  # las tablas propias de empresa
