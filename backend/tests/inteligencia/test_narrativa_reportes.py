"""CU-23 (E09): la narrativa por plantilla y las funciones puras que la arman. Sin base de datos."""

import datetime as dt
from decimal import Decimal

import pytest

from app.inteligencia.politicas import (
    a_decimal,
    agrupar_serie,
    armar_resumen,
    calcular_participacion,
    etiqueta_bucket,
    etiqueta_periodo,
    redactar_narrativa_reporte,
)


def _dia(dia: int, total: str, trans: int = 1, unidades: int = 1, **extra) -> dict:
    return {"dia": dt.date(2026, 9, dia), "transacciones": trans, "unidades": unidades, "total_ventas": Decimal(total), **extra}


# ---- Funciones puras --------------------------------------------------------------------------


def test_a_decimal_acepta_float_de_sqlite_y_none():
    assert a_decimal(740.0) == Decimal("740.00")
    assert a_decimal(Decimal("10.005")) == Decimal("10.01")
    assert a_decimal(None) == Decimal("0.00")


def test_participacion_suma_cien_y_con_total_cero_es_cero():
    assert calcular_participacion([Decimal("350"), Decimal("390")]) == [47.3, 52.7]
    assert calcular_participacion([Decimal("0"), Decimal("0")]) == [0.0, 0.0]
    assert calcular_participacion([Decimal("50")], total=Decimal("200")) == [25.0]  # sobre un total ajeno


def test_resumen_suma_enteros_como_int_y_montos_como_numero():
    filas = [{"unidades": 2, "total": 10.5}, {"unidades": 3, "total": 4.25}]

    assert armar_resumen(filas, ["unidades", "total"]) == {"unidades": 5, "total": 14.75}
    assert armar_resumen([], ["unidades"]) == {"unidades": 0.0}


@pytest.mark.parametrize(
    "agrupacion, fecha, etiqueta",
    [("dia", dt.date(2026, 9, 14), "14/09/2026"), ("semana", dt.date(2026, 9, 14), "S38 (14/09)"), ("mes", dt.date(2026, 9, 1), "09/2026")],
)
def test_etiquetas_de_periodo(agrupacion, fecha, etiqueta):
    assert etiqueta_bucket(fecha, agrupacion) == etiqueta


def test_etiqueta_de_un_rango_y_de_un_dia():
    assert etiqueta_periodo(dt.date(2026, 9, 1), dt.date(2026, 9, 20)) == "01/09/2026 al 20/09/2026"
    assert etiqueta_periodo(dt.date(2026, 9, 20), dt.date(2026, 9, 20)) == "20/09/2026"


def test_agrupar_por_semana_rellena_semanas_sin_ventas_y_recorta_el_inicio():
    filas = [_dia(2, "10.00"), _dia(15, "20.00", trans=2, unidades=5)]

    semanas = agrupar_serie(filas, "semana", dt.date(2026, 9, 2), dt.date(2026, 9, 20))

    assert [(s["periodo"], s["desde"], s["total_ventas"]) for s in semanas] == [
        ("S36 (31/08)", dt.date(2026, 9, 2), Decimal("10.00")),  # la semana empieza el 31/08 pero el rango, el 2/09
        ("S37 (07/09)", dt.date(2026, 9, 7), Decimal("0")),
        ("S38 (14/09)", dt.date(2026, 9, 14), Decimal("20.00")),
    ]
    assert semanas[-1]["transacciones"] == 2 and semanas[-1]["unidades"] == 5


def test_agrupar_por_mes_cruza_el_cambio_de_anio():
    filas = [{"dia": dt.date(2025, 12, 31), "transacciones": 1, "unidades": 1, "total_ventas": Decimal("5")},
             {"dia": dt.date(2026, 1, 1), "transacciones": 1, "unidades": 1, "total_ventas": Decimal("7")}]

    meses = agrupar_serie(filas, "mes", dt.date(2025, 11, 15), dt.date(2026, 1, 10))

    assert [(m["periodo"], m["total_ventas"]) for m in meses] == [
        ("11/2025", Decimal("0")), ("12/2025", Decimal("5")), ("01/2026", Decimal("7")),
    ]


def test_agrupar_con_serie_trae_una_fila_por_periodo_y_por_valor():
    filas = [_dia(14, "10.00", sucursal="Centro"), _dia(15, "5.00", sucursal="Norte")]

    salida = agrupar_serie(filas, "dia", dt.date(2026, 9, 14), dt.date(2026, 9, 15), serie="sucursal")

    assert [(f["periodo"], f["sucursal"], f["total_ventas"]) for f in salida] == [
        ("14/09/2026", "Centro", Decimal("10.00")),
        ("14/09/2026", "Norte", Decimal("0")),
        ("15/09/2026", "Centro", Decimal("0")),
        ("15/09/2026", "Norte", Decimal("5.00")),
    ]


def test_una_agrupacion_desconocida_falla():
    with pytest.raises(ValueError):
        agrupar_serie([], "trimestre", dt.date(2026, 9, 1), dt.date(2026, 9, 2))


# ---- Narrativa por reporte ----------------------------------------------------------------------

PERIODO = "01/09/2026 al 20/09/2026"


def test_narrativa_ventas_por_sucursal():
    filas = [
        {"sucursal": "Norte", "total_ventas": 390.0, "participacion": 52.7},
        {"sucursal": "Centro", "total_ventas": 350.0, "participacion": 47.3},
    ]

    texto = redactar_narrativa_reporte("ventas_por_sucursal", PERIODO, filas, {"total_ventas": 740.0})

    assert texto == (
        "Entre el 01/09/2026 y el 20/09/2026 se vendió Bs 740,00 en 2 sucursales. La que más vendió fue Norte "
        "con Bs 390,00 (52,7% del total)."
    )


def test_narrativa_productos_mas_vendidos():
    filas = [{"producto": "Polera Básica", "unidades": 4, "total_vendido": 200.0}]

    texto = redactar_narrativa_reporte("productos_mas_vendidos", PERIODO, filas, {"total_vendido": 200.0})

    assert "Polera Básica encabeza la lista con 4 unidades y Bs 200,00" in texto


def test_narrativa_ventas_por_periodo_y_comparacion():
    por_periodo = [
        {"periodo": "S37 (07/09)", "total_ventas": 10.0},
        {"periodo": "S38 (14/09)", "total_ventas": 30.0},
    ]
    comparacion = [
        {"periodo": "08/2026", "sucursal": "Centro", "total_ventas": 100.0},
        {"periodo": "09/2026", "sucursal": "Norte", "total_ventas": 390.0},
    ]

    assert "El mejor periodo fue S38 (14/09) con Bs 30,00" in redactar_narrativa_reporte(
        "ventas_por_periodo", PERIODO, por_periodo, {"total_ventas": 40.0, "transacciones": 2}
    )
    assert "El mayor monto fue de Norte en 09/2026" in redactar_narrativa_reporte(
        "comparacion_sucursales", PERIODO, comparacion, {"total_ventas": 490.0}
    )


def test_narrativa_existencias_con_y_sin_productos_bajo_el_minimo():
    bajo = [{"producto": "Polera", "disponible": 3, "bajo_minimo": True}, {"producto": "Camisa", "disponible": 9, "bajo_minimo": False}]
    sano = [{"producto": "Camisa", "disponible": 9, "bajo_minimo": False}]

    assert "1 producto está por debajo del stock mínimo" in redactar_narrativa_reporte("productos_menor_existencia", None, bajo, {})
    assert "Ninguno está por debajo del stock mínimo" in redactar_narrativa_reporte("productos_menor_existencia", None, sano, {})
    assert "No hay productos" in redactar_narrativa_reporte("productos_menor_existencia", None, [], {})


def test_narrativa_ingresos_por_categoria():
    filas = [{"categoria": "Camisas", "total_vendido": 540.0, "participacion": 73.0}]

    texto = redactar_narrativa_reporte("ingresos_por_categoria", PERIODO, filas, {"total_vendido": 540.0})

    assert "la categoría con más ingresos fue Camisas con Bs 540,00 (73% del total)" in texto


@pytest.mark.parametrize("codigo", ["ventas_por_sucursal", "productos_mas_vendidos", "ventas_por_periodo", "ingresos_por_categoria"])
def test_sin_ventas_la_narrativa_lo_dice_y_no_inventa_cifras(codigo):
    texto = redactar_narrativa_reporte(codigo, "20/09/2026", [], {})

    assert texto == "El 20/09/2026 no hubo ventas con esos filtros."
