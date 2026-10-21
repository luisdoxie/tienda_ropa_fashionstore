"""E02 (multitenant): los reportes (CU-22) y el reporte por voz (CU-23) de cada
empresa muestran SOLO sus cifras. Las consultas de ventas e inventario son SQL
en texto sobre vistas (`condicion_empresa`); las de reservas, probador y
nombres de sucursal pasan por el filtro del ORM. Por HTTP con una sesión nueva
por petición (como en producción) y dos empresas:

  A: 2 unidades vendidas (200.00), 2 reservas, stock 10 (mínimo 2).
  B: 3 unidades vendidas (300.00), 1 reserva,  stock 3  (mínimo 5, en alerta).
"""

import datetime as dt

import pytest
from sqlalchemy import text

from app.comercial.repository import VW_VENTAS_DETALLE_V2_SQL
from app.core.rate_limit import limiter
from app.inteligencia.schemas import FiltrosReporteVoz
from tests.catalogo.test_consolidado_empresa import sembrar_negocio
from tests.inteligencia.test_reporte_voz import dictar, sumas_decimales  # noqa: F401  (fixtures)

RUTA_VOZ = "/api/v1/ia/reporte-voz"
RUTA = "/api/v1/reportes"
HOY = dt.date.today()
PERIODO = {"desde": str(HOY - dt.timedelta(days=2)), "hasta": str(HOY + dt.timedelta(days=1))}


@pytest.fixture()
def mundo(db_session, dos_empresas, sumas_decimales):  # noqa: F811
    """Las dos empresas con sus datos de negocio y la vista de ventas creada
    (conftest solo crea la de inventario)."""
    db_session.execute(text(VW_VENTAS_DETALLE_V2_SQL))
    db_session.commit()
    a = sembrar_negocio(
        db_session, dos_empresas.a.id, "A", fisica=10, minimo=2, costo="10.0000", venta_cantidad=2, reservas=2
    )
    b = sembrar_negocio(
        db_session, dos_empresas.b.id, "B", fisica=3, minimo=5, costo="20.0000", venta_cantidad=3, reservas=1
    )
    return a, b


def _cada_empresa(dos_empresas, mundo):
    a, b = mundo
    return ((dos_empresas.a, a, b), (dos_empresas.b, b, a))


def test_reporte_de_ventas_cada_empresa_ve_solo_sus_cifras(client_por_peticion, dos_empresas, mundo):
    for empresa, propia, ajena in _cada_empresa(dos_empresas, mundo):
        respuesta = client_por_peticion.get(f"{RUTA}/ventas", params=PERIODO, headers=empresa.headers)
        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        unidades = 2 if propia["venta"] == "V-A" else 3

        assert cuerpo["resumen"]["transacciones"] == 1
        assert float(cuerpo["resumen"]["total_ventas"]) == 100.0 * unidades
        assert [fila["producto"] for fila in cuerpo["top_productos"]] == [propia["producto"]]
        assert [fila["cantidad_vendida"] for fila in cuerpo["top_productos"]] == [unidades]
        assert [fila["sucursal"] for fila in cuerpo["por_sucursal"]] == [propia["sucursal"]]
        assert [fila["producto"] for fila in cuerpo["detalle"]] == [propia["producto"]]
        assert ajena["producto"] not in respuesta.text and ajena["sucursal"] not in respuesta.text


def test_reporte_de_inventario_cada_empresa_ve_solo_el_suyo(client_por_peticion, dos_empresas, mundo):
    for empresa, propia, ajena in _cada_empresa(dos_empresas, mundo):
        respuesta = client_por_peticion.get(f"{RUTA}/inventario", headers=empresa.headers)
        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        assert [fila["sucursal"] for fila in cuerpo["consolidado"]] == [propia["sucursal"]]
        assert [fila["sucursal"] for fila in cuerpo["valuacion"]] == [propia["sucursal"]]
        assert ajena["sucursal"] not in respuesta.text
    # Solo B tiene el stock por debajo del mínimo.
    alertas_a = client_por_peticion.get(f"{RUTA}/inventario", headers=dos_empresas.a.headers).json()["alertas"]
    alertas_b = client_por_peticion.get(f"{RUTA}/inventario", headers=dos_empresas.b.headers).json()["alertas"]
    assert alertas_a == []
    assert [fila["sucursal"] for fila in alertas_b] == ["Sucursal B"]


def test_reporte_de_reservas_cada_empresa_cuenta_solo_las_suyas(client_por_peticion, dos_empresas, mundo):
    esperado = {dos_empresas.a.id: 2, dos_empresas.b.id: 1}
    for empresa, _propia, _ajena in _cada_empresa(dos_empresas, mundo):
        respuesta = client_por_peticion.get(f"{RUTA}/reservas", params=PERIODO, headers=empresa.headers)
        assert respuesta.status_code == 200, respuesta.text
        por_estado = {fila["codigo"]: fila["cantidad"] for fila in respuesta.json()["por_estado"]}
        assert por_estado == {"pendiente": esperado[empresa.id]}


def test_dashboard_cada_empresa_ve_solo_sus_indicadores(client_por_peticion, dos_empresas, mundo):
    for empresa, propia, ajena in _cada_empresa(dos_empresas, mundo):
        respuesta = client_por_peticion.get(f"{RUTA}/dashboard", params=PERIODO, headers=empresa.headers)
        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        unidades = 2 if propia["venta"] == "V-A" else 3

        assert cuerpo["transacciones"] == 1
        assert float(cuerpo["ventas_del_periodo"]) == 100.0 * unidades
        assert [fila["producto"] for fila in cuerpo["top_productos"]] == [propia["producto"]]
        assert [fila["sucursal"] for fila in cuerpo["ventas_por_sucursal"]] == [propia["sucursal"]]
        assert ajena["producto"] not in respuesta.text and ajena["sucursal"] not in respuesta.text


def test_reporte_por_voz_cada_empresa_oye_sus_cifras_y_no_resuelve_sucursales_ajenas(
    client_por_peticion, dos_empresas, mundo, dictar  # noqa: F811
):
    a, b = mundo
    # El administrador de A dicta el nombre de una sucursal de B: no se resuelve
    # (queda sin filtro de sucursal) y el reporte es el de A, nunca el de B.
    dictar(FiltrosReporteVoz(tipo_reporte="ventas", sucursal=b["sucursal"], **{"desde": HOY - dt.timedelta(days=2)}))
    ajeno = client_por_peticion.post(RUTA_VOZ, json={"texto": "ventas de la sucursal B"}, headers=dos_empresas.a.headers)
    assert ajeno.status_code == 200, ajeno.text
    cuerpo = ajeno.json()
    assert cuerpo["filtros_aplicados"]["sucursal_id"] is None
    assert b["sucursal"] not in cuerpo["respuesta"]
    assert float(cuerpo["resultado"]["resumen"]["total_ventas"]) == 200.0

    # Dictando la propia, sí se resuelve y se aplica.
    dictar(FiltrosReporteVoz(tipo_reporte="ventas", sucursal=a["sucursal"], **{"desde": HOY - dt.timedelta(days=2)}))
    propio = client_por_peticion.post(RUTA_VOZ, json={"texto": "ventas de la sucursal A"}, headers=dos_empresas.a.headers)
    assert propio.json()["filtros_aplicados"]["sucursal_id"] == a["sucursal_id"]

    # Y B oye sus cifras, no las de A.
    dictar(FiltrosReporteVoz(tipo_reporte="ventas", desde=HOY - dt.timedelta(days=2)))
    de_b = client_por_peticion.post(RUTA_VOZ, json={"texto": "como van las ventas"}, headers=dos_empresas.b.headers)
    assert float(de_b.json()["resultado"]["resumen"]["total_ventas"]) == 300.0
    assert a["sucursal"] not in de_b.text


@pytest.mark.parametrize(
    "ruta", ["ventas", "inventario", "reservas", "dashboard"]
)
def test_un_sucursal_id_de_otra_empresa_responde_404(client_por_peticion, dos_empresas, mundo, ruta):
    _a, b = mundo
    respuesta = client_por_peticion.get(
        f"{RUTA}/{ruta}", params={"sucursal_id": b["sucursal_id"]}, headers=dos_empresas.a.headers
    )
    assert respuesta.status_code == 404, respuesta.text
    # El mismo id en la empresa dueña sí existe.
    assert client_por_peticion.get(
        f"{RUTA}/{ruta}", params={"sucursal_id": b["sucursal_id"]}, headers=dos_empresas.b.headers
    ).status_code == 200


def test_los_nombres_dictados_solo_se_resuelven_dentro_de_la_empresa(db_session, dos_empresas, mundo):
    """PASO 3.3: sucursal y categoría dictadas por nombre (`func.lower() ==
    texto`) quedan acotadas por el filtro: el nombre de otra empresa no se
    resuelve, el propio sí."""
    from app.catalogo import politicas as catalogo_politicas
    from app.core.tenant import fijar_empresa
    from app.plataforma import politicas as plataforma_politicas

    a, b = mundo
    fijar_empresa(db_session, dos_empresas.a.id)
    assert plataforma_politicas.resolver_sucursal_por_nombre(db_session, a["sucursal"].upper()) == a["sucursal_id"]
    assert plataforma_politicas.resolver_sucursal_por_nombre(db_session, b["sucursal"]) is None
    assert catalogo_politicas.resolver_categoria_por_nombre(db_session, "Categoria A") == a["categoria_id"]
    assert catalogo_politicas.resolver_categoria_por_nombre(db_session, "Categoria B") is None

    fijar_empresa(db_session, dos_empresas.b.id)
    assert plataforma_politicas.resolver_sucursal_por_nombre(db_session, a["sucursal"]) is None
    assert plataforma_politicas.resolver_sucursal_por_nombre(db_session, b["sucursal"]) == b["sucursal_id"]
