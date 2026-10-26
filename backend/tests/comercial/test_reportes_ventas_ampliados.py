"""E09, paso 2: las consultas de ventas ampliadas para los reportes generativos (filtros en lista,
top de productos ascendente) y las nuevas (serie diaria, ventas por categoría). Datos reales: ver
`ayudas_reportes_ia` (4 ventas efectivas en el período, más una pendiente, una anulada y dos fuera
de fecha que NO deben contar). Las cifras de cada prueba están calculadas a mano."""

import datetime as dt
from decimal import Decimal

import pytest

from app.comercial import politicas as comercial
from app.core.deps import ParametrosPeriodo
from app.core.exceptions import DomainError
from app.core.tenant import EmpresaNoDefinidaError, fijar_empresa
from tests.comercial.ayudas_reportes_ia import PERIODO, mundo_reportes  # noqa: F401  (fixture)

D14, D15, D20 = dt.date(2026, 9, 14), dt.date(2026, 9, 15), dt.date(2026, 9, 20)


def dinero(valor) -> Decimal:
    return Decimal(str(valor))


@pytest.fixture()
def a(db_session, mundo_reportes):  # noqa: F811
    """La empresa A (m=1) fijada en la sesión."""
    fijar_empresa(db_session, mundo_reportes[0]["empresa_id"])
    return mundo_reportes[0]


# ---- Ventas efectivas y compatibilidad de los parámetros singulares ---------------------------


def test_solo_cuentan_pagadas_y_entregadas_dentro_del_periodo(db_session, a):
    resumen = comercial.reporte_ventas_resumen(db_session, PERIODO)
    assert resumen["transacciones"] == 4
    assert dinero(resumen["total_ventas"]) == Decimal("740")
    assert dinero(resumen["margen_bruto"]) == Decimal("290")
    # 6 líneas: V1 (2), V2 (1), V3 (2), V4 (1). La pendiente, la anulada y las de fuera, no.
    assert len(comercial.reporte_ventas_detalle(db_session, PERIODO)) == 6


def test_los_parametros_singulares_siguen_funcionando_igual(db_session, a):
    centro, poleras = a["sucursales"]["centro"], a["categorias"]["poleras"]
    por_sucursal = comercial.reporte_ventas_por_sucursal(db_session, PERIODO)
    assert [(f["sucursal"], f["transacciones"], dinero(f["total_ventas"])) for f in por_sucursal] == [
        ("Centro", 2, Decimal("350")),
        ("Norte", 2, Decimal("390")),
    ]
    solo_centro = comercial.reporte_ventas_por_sucursal(db_session, PERIODO, sucursal_id=centro)
    assert [f["sucursal"] for f in solo_centro] == ["Centro"]
    resumen = comercial.reporte_ventas_resumen(db_session, PERIODO, categoria_id=poleras)
    assert (resumen["transacciones"], dinero(resumen["total_ventas"])) == (2, Decimal("200"))
    canales = {f["canal"]: (f["transacciones"], dinero(f["total_ventas"])) for f in comercial.reporte_ventas_por_canal(db_session, PERIODO)}
    assert canales == {"presencial": (3, Decimal("640")), "digital": (1, Decimal("100"))}


# ---- Filtros en lista ---------------------------------------------------------------------------


def test_filtro_por_lista_de_sucursales(db_session, a):
    centro, norte = a["sucursales"]["centro"], a["sucursales"]["norte"]
    ambas = comercial.reporte_ventas_resumen(db_session, PERIODO, sucursal_ids=[centro, norte])
    assert dinero(ambas["total_ventas"]) == Decimal("740")
    solo_norte = comercial.reporte_ventas_resumen(db_session, PERIODO, sucursal_ids=[norte])
    assert (solo_norte["transacciones"], dinero(solo_norte["total_ventas"])) == (2, Decimal("390"))
    filas = comercial.reporte_ventas_por_sucursal(db_session, PERIODO, sucursal_ids=[centro, norte])
    assert [f["sucursal"] for f in filas] == ["Centro", "Norte"]


def test_filtro_por_lista_de_categorias(db_session, a):
    camisas, poleras = a["categorias"]["camisas"], a["categorias"]["poleras"]
    assert dinero(comercial.reporte_ventas_resumen(db_session, PERIODO, categoria_ids=[camisas])["total_ventas"]) == Decimal("540")
    ambas = comercial.reporte_ventas_resumen(db_session, PERIODO, categoria_ids=[camisas, poleras])
    assert dinero(ambas["total_ventas"]) == Decimal("740")


def test_una_lista_vacia_no_coincide_con_nada(db_session, a):
    resumen = comercial.reporte_ventas_resumen(db_session, PERIODO, sucursal_ids=[])
    assert (resumen["transacciones"], dinero(resumen["total_ventas"])) == (0, Decimal("0"))
    assert comercial.reporte_ventas_top_productos(db_session, PERIODO, producto_ids=[]) == []
    assert comercial.reporte_ventas_serie_diaria(db_session, PERIODO, categoria_ids=[]) == []
    assert comercial.reporte_ventas_por_categoria(db_session, PERIODO, sucursal_ids=[]) == []


def test_lista_y_parametro_singular_se_combinan_con_and(db_session, a):
    centro, norte = a["sucursales"]["centro"], a["sucursales"]["norte"]
    resumen = comercial.reporte_ventas_resumen(db_session, PERIODO, sucursal_id=centro, sucursal_ids=[norte])
    assert resumen["transacciones"] == 0
    resumen = comercial.reporte_ventas_resumen(db_session, PERIODO, sucursal_id=centro, sucursal_ids=[centro, norte])
    assert resumen["transacciones"] == 2


def test_los_ids_se_pasan_como_parametros_no_como_sql(db_session, a):
    # Un valor que no es entero no llega a la consulta: falla al convertirlo, no se interpreta.
    with pytest.raises((ValueError, TypeError)):
        comercial.reporte_ventas_resumen(db_session, PERIODO, sucursal_ids=["1) OR (1=1"])  # type: ignore[list-item]


# ---- Top de productos -----------------------------------------------------------------------------


def test_top_productos_orden_descendente_por_defecto(db_session, a):
    filas = comercial.reporte_ventas_top_productos(db_session, PERIODO)
    # P2 vendió 4; P1 y P3 empatan en 3 y el desempate es el id.
    assert [(f["producto"], int(f["cantidad_vendida"]), dinero(f["total_vendido"])) for f in filas] == [
        ("Polera Básica", 4, Decimal("200")),
        ("Camisa Oxford", 3, Decimal("300")),
        ("Camisa Lino", 3, Decimal("240")),
    ]


def test_top_productos_ascendente(db_session, a):
    filas = comercial.reporte_ventas_top_productos(db_session, PERIODO, ascendente=True)
    assert [f["producto"] for f in filas] == ["Camisa Oxford", "Camisa Lino", "Polera Básica"]
    # Solo productos con ventas: P4 (inactivo y sin ventas) no aparece, ni con ascendente.
    assert len(filas) == 3


def test_top_productos_con_limite_y_filtros(db_session, a):
    p = a["productos"]
    assert [f["producto"] for f in comercial.reporte_ventas_top_productos(db_session, PERIODO, limite=1)] == ["Polera Básica"]
    solo_camisas = comercial.reporte_ventas_top_productos(db_session, PERIODO, producto_ids=[p["p1"], p["p3"]])
    assert [int(f["cantidad_vendida"]) for f in solo_camisas] == [3, 3]
    presencial = comercial.reporte_ventas_top_productos(db_session, PERIODO, canal="presencial")
    assert [(f["producto"], int(f["cantidad_vendida"])) for f in presencial] == [
        ("Polera Básica", 4),
        ("Camisa Lino", 3),
        ("Camisa Oxford", 2),
    ]
    en_centro = comercial.reporte_ventas_top_productos(
        db_session, PERIODO, sucursal_ids=[a["sucursales"]["centro"]], categoria_ids=[a["categorias"]["camisas"]], ascendente=True
    )
    assert [(f["producto"], int(f["cantidad_vendida"])) for f in en_centro] == [("Camisa Oxford", 3)]


# ---- Serie diaria -------------------------------------------------------------------------------------


def test_serie_diaria_sin_desglose(db_session, a):
    filas = comercial.reporte_ventas_serie_diaria(db_session, PERIODO)
    assert [(f["dia"], f["transacciones"], f["unidades"], f["total_ventas"]) for f in filas] == [
        (D14, 1, 3, Decimal("250.00")),
        (D15, 2, 5, Decimal("330.00")),
        (D20, 1, 2, Decimal("160.00")),
    ]
    assert all(isinstance(f["dia"], dt.date) and not isinstance(f["dia"], dt.datetime) for f in filas)
    assert all(isinstance(f["total_ventas"], Decimal) for f in filas)
    # Sin ventas los días 16 a 19: no hay fila (completar con ceros es de quien arma la serie).
    assert {f["dia"] for f in filas}.isdisjoint({dt.date(2026, 9, d) for d in range(16, 20)})


def test_serie_diaria_con_desglose_por_sucursal(db_session, a):
    filas = comercial.reporte_ventas_serie_diaria(db_session, PERIODO, desglose=("sucursal",))
    assert [(f["dia"], f["sucursal"], f["transacciones"], f["unidades"], f["total_ventas"]) for f in filas] == [
        (D14, "Centro", 1, 3, Decimal("250.00")),
        (D15, "Centro", 1, 1, Decimal("100.00")),
        (D15, "Norte", 1, 4, Decimal("230.00")),
        (D20, "Norte", 1, 2, Decimal("160.00")),
    ]
    assert filas[0]["sucursal_id"] == a["sucursales"]["centro"]
    assert "categoria" not in filas[0]


def test_serie_diaria_con_desglose_por_categoria(db_session, a):
    filas = comercial.reporte_ventas_serie_diaria(db_session, PERIODO, desglose=("categoria",))
    assert [(f["dia"], f["categoria"], f["transacciones"], f["unidades"], f["total_ventas"]) for f in filas] == [
        (D14, "Camisas", 1, 2, Decimal("200.00")),
        (D14, "Poleras", 1, 1, Decimal("50.00")),
        (D15, "Camisas", 2, 2, Decimal("180.00")),
        (D15, "Poleras", 1, 3, Decimal("150.00")),
        (D20, "Camisas", 1, 2, Decimal("160.00")),
    ]
    assert filas[0]["categoria_id"] == a["categorias"]["camisas"]


def test_serie_diaria_con_ambos_desgloses(db_session, a):
    filas = comercial.reporte_ventas_serie_diaria(db_session, PERIODO, desglose=("sucursal", "categoria"))
    assert [(f["dia"], f["sucursal"], f["categoria"], f["total_ventas"]) for f in filas] == [
        (D14, "Centro", "Camisas", Decimal("200.00")),
        (D14, "Centro", "Poleras", Decimal("50.00")),
        (D15, "Centro", "Camisas", Decimal("100.00")),
        (D15, "Norte", "Camisas", Decimal("80.00")),
        (D15, "Norte", "Poleras", Decimal("150.00")),
        (D20, "Norte", "Camisas", Decimal("160.00")),
    ]


def test_serie_diaria_con_filtros(db_session, a):
    p, s, c = a["productos"], a["sucursales"], a["categorias"]
    digital = comercial.reporte_ventas_serie_diaria(db_session, PERIODO, canal="digital")
    assert [(f["dia"], f["total_ventas"]) for f in digital] == [(D15, Decimal("100.00"))]
    # El filtro por productos solo restringe: P2 vendió 1 el 14 (50) y 3 el 15 (150).
    solo_p2 = comercial.reporte_ventas_serie_diaria(db_session, PERIODO, producto_ids=[p["p2"]])
    assert [(f["dia"], f["unidades"], f["total_ventas"]) for f in solo_p2] == [
        (D14, 1, Decimal("50.00")),
        (D15, 3, Decimal("150.00")),
    ]
    norte = comercial.reporte_ventas_serie_diaria(db_session, PERIODO, sucursal_ids=[s["norte"]])
    assert [(f["dia"], f["total_ventas"]) for f in norte] == [(D15, Decimal("230.00")), (D20, Decimal("160.00"))]
    poleras_en_centro = comercial.reporte_ventas_serie_diaria(
        db_session, PERIODO, sucursal_ids=[s["centro"]], categoria_ids=[c["poleras"]]
    )
    assert [(f["dia"], f["total_ventas"]) for f in poleras_en_centro] == [(D14, Decimal("50.00"))]


def test_serie_diaria_respeta_el_ultimo_dia_completo_y_no_incluye_el_siguiente(db_session, a):
    # La venta V4 es del 20/09 a las 23:30: entra con hasta=20. La V8 es del 21/09 a las 00:00: no.
    hasta_20 = comercial.reporte_ventas_serie_diaria(db_session, PERIODO)
    assert hasta_20[-1]["dia"] == D20 and hasta_20[-1]["total_ventas"] == Decimal("160.00")
    solo_21 = comercial.reporte_ventas_serie_diaria(
        db_session, ParametrosPeriodo(desde=dt.date(2026, 9, 21), hasta=dt.date(2026, 9, 21))
    )
    assert [(f["dia"], f["total_ventas"]) for f in solo_21] == [(dt.date(2026, 9, 21), Decimal("100.00"))]
    agosto = comercial.reporte_ventas_serie_diaria(
        db_session, ParametrosPeriodo(desde=dt.date(2026, 8, 1), hasta=dt.date(2026, 8, 31))
    )
    assert [(f["dia"], f["total_ventas"]) for f in agosto] == [(dt.date(2026, 8, 1), Decimal("100.00"))]


def test_serie_diaria_rechaza_un_desglose_desconocido(db_session, a):
    with pytest.raises(DomainError, match="Desglose no soportado: producto"):
        comercial.reporte_ventas_serie_diaria(db_session, PERIODO, desglose=("producto",))
    with pytest.raises(DomainError):
        comercial.reporte_ventas_serie_diaria(db_session, PERIODO, desglose=("sucursal; DROP TABLE venta",))


# ---- Ventas por categoría -------------------------------------------------------------------------


def test_ventas_por_categoria(db_session, a):
    filas = comercial.reporte_ventas_por_categoria(db_session, PERIODO)
    assert [
        (f["categoria"], f["unidades"], f["total_vendido"], f["margen_bruto"], f["transacciones"]) for f in filas
    ] == [
        ("Camisas", 6, Decimal("540.00"), Decimal("210.00"), 4),
        ("Poleras", 4, Decimal("200.00"), Decimal("80.00"), 2),
    ]
    assert filas[0]["categoria_id"] == a["categorias"]["camisas"]
    assert all(isinstance(f["total_vendido"], Decimal) and isinstance(f["margen_bruto"], Decimal) for f in filas)
    # La suma por categoría es el total del período.
    assert sum(f["total_vendido"] for f in filas) == Decimal("740.00")


def test_ventas_por_categoria_con_filtros(db_session, a):
    centro = a["sucursales"]["centro"]
    en_centro = comercial.reporte_ventas_por_categoria(db_session, PERIODO, sucursal_ids=[centro])
    assert [(f["categoria"], f["unidades"], f["total_vendido"], f["margen_bruto"], f["transacciones"]) for f in en_centro] == [
        ("Camisas", 3, Decimal("300.00"), Decimal("120.00"), 2),
        ("Poleras", 1, Decimal("50.00"), Decimal("20.00"), 1),
    ]
    digital = comercial.reporte_ventas_por_categoria(db_session, PERIODO, canal="digital")
    assert [(f["categoria"], f["total_vendido"], f["margen_bruto"]) for f in digital] == [
        ("Camisas", Decimal("100.00"), Decimal("40.00"))
    ]


# ---- Aislamiento por empresa -----------------------------------------------------------------------


def test_cada_empresa_ve_solo_sus_cifras_en_las_consultas_nuevas(db_session, mundo_reportes):  # noqa: F811
    a, b = mundo_reportes
    fijar_empresa(db_session, a["empresa_id"])
    serie_a = comercial.reporte_ventas_serie_diaria(db_session, PERIODO)
    categorias_a = comercial.reporte_ventas_por_categoria(db_session, PERIODO)
    assert sum(f["total_ventas"] for f in serie_a) == Decimal("740.00")
    assert sum(f["total_vendido"] for f in categorias_a) == Decimal("740.00")

    # B vendió lo mismo multiplicado por 3, con los mismos nombres: nada se mezcla.
    fijar_empresa(db_session, b["empresa_id"])
    serie_b = comercial.reporte_ventas_serie_diaria(db_session, PERIODO, desglose=("sucursal",))
    assert [(f["dia"], f["sucursal"], f["total_ventas"]) for f in serie_b] == [
        (D14, "Centro", Decimal("750.00")),
        (D15, "Centro", Decimal("300.00")),
        (D15, "Norte", Decimal("690.00")),
        (D20, "Norte", Decimal("480.00")),
    ]
    assert {f["sucursal_id"] for f in serie_b} == set(b["sucursales"].values()) - {b["sucursales"]["vieja"]}
    categorias_b = comercial.reporte_ventas_por_categoria(db_session, PERIODO)
    assert [(f["categoria"], f["total_vendido"], f["unidades"]) for f in categorias_b] == [
        ("Camisas", Decimal("1620.00"), 18),
        ("Poleras", Decimal("600.00"), 12),
    ]
    top_b = comercial.reporte_ventas_top_productos(db_session, PERIODO)
    assert [(f["producto_id"], int(f["cantidad_vendida"])) for f in top_b][0] == (b["productos"]["p2"], 12)


def test_los_ids_de_otra_empresa_en_una_lista_no_traen_nada(db_session, mundo_reportes):  # noqa: F811
    a, b = mundo_reportes
    fijar_empresa(db_session, a["empresa_id"])
    ajenas = list(b["sucursales"].values())
    assert comercial.reporte_ventas_serie_diaria(db_session, PERIODO, sucursal_ids=ajenas) == []
    assert comercial.reporte_ventas_por_categoria(db_session, PERIODO, sucursal_ids=ajenas) == []
    assert comercial.reporte_ventas_top_productos(db_session, PERIODO, producto_ids=list(b["productos"].values())) == []
    resumen = comercial.reporte_ventas_resumen(db_session, PERIODO, categoria_ids=list(b["categorias"].values()))
    assert resumen["transacciones"] == 0


def test_las_consultas_nuevas_fallan_cerrado_sin_empresa(db_session, mundo_reportes):  # noqa: F811
    fijar_empresa(db_session, None)
    with pytest.raises(EmpresaNoDefinidaError):
        comercial.reporte_ventas_serie_diaria(db_session, PERIODO)
    with pytest.raises(EmpresaNoDefinidaError):
        comercial.reporte_ventas_por_categoria(db_session, PERIODO)
    with pytest.raises(EmpresaNoDefinidaError):
        comercial.reporte_ventas_top_productos(db_session, PERIODO, ascendente=True)
