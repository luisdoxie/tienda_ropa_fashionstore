"""E05, 4.4: matriz de listados. Cada listado de A trae SOLO datos de A (y el de B solo de B);
los filtros de consulta con ids de B no devuelven nada de B; la paginación no se sale."""

import pytest

from .introspeccion import parametros_de_consulta, ruta_por_clave
from .plantillas import token_de_ruta
from .rutas_esperadas import LISTADO, MATRIZ, RUTAS

LISTADOS = sorted(clave for clave, ruta in RUTAS.items() if ruta.clase == LISTADO and ruta.cobertura == MATRIZ)

# Consulta mínima para que la ruta responda 200 (parámetros obligatorios). Función(universo).
CONSULTA_BASE = {
    ("GET", "/api/v1/catalogo/variantes/buscar"): lambda u: {"q": u.ids["sku"]},
    ("GET", "/api/v1/catalogo/variantes/detalle"): lambda u: {"variante_ids": str(u.ids["variante"])},
    ("GET", "/api/v1/inventario/disponibilidad"): lambda u: {"variante_id": u.ids["variante"]},
    ("GET", "/api/v1/inventario/stock"): lambda u: {"variante_id": u.ids["variante"]},
    ("GET", "/api/v1/inventario/movimientos"): lambda u: {"variante_id": u.ids["variante"], "sucursal_id": u.ids["sucursal"]},
    ("GET", "/api/v1/probador/assets"): lambda u: {"variante_id": u.ids["variante"]},
    ("GET", "/api/v1/sincronizacion/paquete/stock"): lambda u: {"sucursal_id": u.ids["sucursal"]},
}

# Listados que leen una vista que solo existe en PostgreSQL: los cubre el perfil PostgreSQL.
SOLO_POSTGRESQL = {
    ("GET", "/api/v1/reportes/ventas"): "lee vw_ventas_detalle (vista solo de PostgreSQL)",
    ("GET", "/api/v1/reportes/dashboard"): "lee vw_ventas_detalle (vista solo de PostgreSQL)",
}

# Listados cuya respuesta no incluye ningún texto libre al que ponerle marca (ids, cifras,
# códigos globales). La ausencia de datos de B se comprueba por ids (ver `fuga_por_ids`).
SIN_MARCA = {
    ("GET", "/api/v1/inventario/alertas"): "solo cifras y ids de variante y sucursal",
    ("GET", "/api/v1/inventario/disponibilidad"): "solo cifras y ids",
    ("GET", "/api/v1/inventario/stock"): "solo cifras y ids",
    ("GET", "/api/v1/inventario/tipos-movimiento"): "catálogo global del sistema",
    ("GET", "/api/v1/permisos"): "catálogo global del sistema",
    ("GET", "/api/v1/roles"): "catálogo global del sistema",
    ("GET", "/api/v1/ordenes-compra"): "solo códigos, ids y cifras",
    ("GET", "/api/v1/recepciones"): "solo códigos, ids y cifras",
    ("GET", "/api/v1/transferencias"): "solo códigos, ids y cifras",
    ("GET", "/api/v1/reportes/inventario"): "solo cifras",
    ("GET", "/api/v1/reportes/reservas"): "solo cifras",
    ("GET", "/api/v1/inventario/valuacion"): "solo cifras",
    ("GET", "/api/v1/inventario/consolidado"): "nombre del producto sin marca en la vista",
    ("GET", "/api/v1/sincronizacion/paquete/stock"): "solo ids y cifras de stock",
    ("GET", "/api/v1/sincronizacion/paquete/clientes"): "nombre y apellido del cliente del universo sin marca; el aislamiento se prueba en tests/sincronizacion/test_paquete_seguridad.py",
}

# Claves de una respuesta que son ids de un recurso con id único entre empresas.
CLAVE_A_RECURSO = {
    "sucursal_id": "sucursal",
    "sucursal_origen_id": "sucursal",
    "sucursal_destino_id": "sucursal",
    "variante_id": "variante",
    "producto_id": "producto",
    "cliente_id": "cliente",
    "venta_id": "venta",
    "proveedor_id": "proveedor",
    "categoria_id": "categoria",
    "ciudad_id": "ciudad",
    "zona_envio_id": "zona_envio",
}

# Parámetro de consulta -> recurso del universo, para las pruebas de filtro con ids de B.
FILTRO_A_RECURSO = {
    "sucursal_id": "sucursal",
    "categoria_id": "categoria",
    "talla_id": "talla",
    "color_id": "color",
    "material_id": "material",
    "temporada_id": "temporada",
    "coleccion_id": "coleccion",
    "producto_id": "producto",
    "variante_id": "variante",
    "cliente_id": "cliente",
    "proveedor_id": "proveedor",
}


def _recorrer(valor):
    if isinstance(valor, dict):
        for clave, hijo in valor.items():
            yield clave, hijo
            yield from _recorrer(hijo)
    elif isinstance(valor, list):
        for hijo in valor:
            yield from _recorrer(hijo)


def fuga_por_ids(cuerpo, ajena) -> list[str]:
    """Claves de la respuesta cuyo valor es un id de un recurso de la otra empresa."""
    fugas = []
    for clave, valor in _recorrer(cuerpo):
        recurso = CLAVE_A_RECURSO.get(clave)
        if recurso and valor is not None and valor == ajena.ids[recurso]:
            fugas.append(f"{clave}={valor}")
    return fugas


def _consulta(metodo, ruta, universo) -> dict:
    return CONSULTA_BASE.get((metodo, ruta), lambda u: {})(universo)


def _pedir(mundo, metodo, ruta, quien, params):
    return mundo.client.request(metodo, ruta, params=params, headers=quien.headers[token_de_ruta(metodo, ruta)])


def _ids(clave):
    return f"{clave[0]} {clave[1].removeprefix('/api/v1')}"


@pytest.mark.parametrize("clave", LISTADOS, ids=[_ids(c) for c in LISTADOS])
@pytest.mark.parametrize("lado", ["A", "B"])
def test_el_listado_trae_solo_datos_de_la_empresa(mundo, clave, lado):
    metodo, ruta = clave
    if clave in SOLO_POSTGRESQL:
        pytest.skip(SOLO_POSTGRESQL[clave])
    propia, ajena = (mundo.a, mundo.b) if lado == "A" else (mundo.b, mundo.a)
    respuesta = _pedir(mundo, metodo, ruta, propia, _consulta(metodo, ruta, propia))
    assert respuesta.status_code == 200, f"{metodo} {ruta}: {respuesta.status_code} {respuesta.text[:300]}"
    assert ajena.m("") not in respuesta.text, f"{metodo} {ruta}: marca de la otra empresa en la respuesta"
    assert fuga_por_ids(respuesta.json(), ajena) == [], f"{metodo} {ruta}: ids de la otra empresa"
    if clave not in SIN_MARCA:
        assert propia.m("") in respuesta.text, f"{metodo} {ruta}: no trae datos de la propia empresa (¿prueba mal armada?)"


def _filtros_de(clave) -> list[str]:
    metodo, ruta = clave
    return sorted(p for p in parametros_de_consulta(ruta_por_clave(metodo, ruta)) if p in FILTRO_A_RECURSO)


CASOS_FILTRO = [(clave, filtro) for clave in LISTADOS if clave not in SOLO_POSTGRESQL for filtro in _filtros_de(clave)]


@pytest.mark.parametrize("caso", CASOS_FILTRO, ids=[f"{_ids(c)} ?{f}" for c, f in CASOS_FILTRO])
def test_un_filtro_con_id_de_b_no_devuelve_datos_de_b(mundo, caso):
    (metodo, ruta), filtro = caso
    a, b = mundo.a, mundo.b
    consulta = {**_consulta(metodo, ruta, a), filtro: b.ids[FILTRO_A_RECURSO[filtro]]}
    respuesta = _pedir(mundo, metodo, ruta, a, consulta)
    assert respuesta.status_code in (200, 404), f"{metodo} {ruta}?{filtro}: {respuesta.status_code} {respuesta.text[:300]}"
    assert b.m("") not in respuesta.text
    if respuesta.status_code == 200:
        assert fuga_por_ids(respuesta.json(), b) == [], f"{metodo} {ruta}?{filtro}: ids de B en la respuesta"


CON_PAGINA = [c for c in LISTADOS if c not in SOLO_POSTGRESQL and "pagina" in parametros_de_consulta(ruta_por_clave(*c))]


@pytest.mark.parametrize("clave", CON_PAGINA, ids=[_ids(c) for c in CON_PAGINA])
def test_la_segunda_pagina_no_trae_datos_de_b(mundo, clave):
    metodo, ruta = clave
    a, b = mundo.a, mundo.b
    for pagina in (1, 2, 3):
        consulta = {**_consulta(metodo, ruta, a), "pagina": pagina, "tamanio": 1}
        respuesta = _pedir(mundo, metodo, ruta, a, consulta)
        assert respuesta.status_code == 200, f"{metodo} {ruta} pagina {pagina}: {respuesta.status_code} {respuesta.text[:200]}"
        assert b.m("") not in respuesta.text
