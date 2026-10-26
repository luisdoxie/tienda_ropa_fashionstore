"""E09, paso 1: períodos relativos de core/tiempo.py. Todas son puras: `hoy` se inyecta.

Calendario de referencia, hoy = 2026-09-20 (domingo):
  la semana en curso es lunes 14/09 a domingo 20/09; la anterior, 07/09 a 13/09.
"""

import datetime as dt
from types import SimpleNamespace

import pytest

from app.core.exceptions import DomainError
from app.core.tiempo import inicio_de_semana, resolver_periodo_relativo, restar_meses

HOY = dt.date(2026, 9, 20)


def d(anio: int, mes: int, dia: int) -> dt.date:
    return dt.date(anio, mes, dia)


# ---- inicio_de_semana ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fecha", "lunes"),
    [
        (d(2026, 9, 14), d(2026, 9, 14)),  # un lunes es su propio inicio
        (d(2026, 9, 17), d(2026, 9, 14)),  # jueves
        (d(2026, 9, 20), d(2026, 9, 14)),  # domingo: sigue en la semana que empezó el lunes
        (d(2026, 1, 1), d(2025, 12, 29)),  # el lunes cae en el año anterior
    ],
)
def test_inicio_de_semana(fecha, lunes):
    assert inicio_de_semana(fecha) == lunes
    assert inicio_de_semana(fecha).weekday() == 0


# ---- restar_meses --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fecha", "n", "esperada"),
    [
        (d(2026, 9, 20), 0, d(2026, 9, 20)),
        (d(2026, 9, 20), 2, d(2026, 7, 20)),
        (d(2026, 3, 31), 1, d(2026, 2, 28)),  # febrero no tiene 31: el último día
        (d(2024, 3, 31), 1, d(2024, 2, 29)),  # año bisiesto
        (d(2026, 1, 15), 1, d(2025, 12, 15)),  # cruza de año
        (d(2026, 1, 31), 14, d(2024, 11, 30)),  # más de un año atrás, noviembre tiene 30
        (d(2026, 9, 20), -1, d(2026, 10, 20)),  # n negativo suma
    ],
)
def test_restar_meses(fecha, n, esperada):
    assert restar_meses(fecha, n) == esperada


# ---- Períodos con fecha fija respecto de hoy -----------------------------------------------


@pytest.mark.parametrize(
    ("tipo", "esperado"),
    [
        ("hoy", (d(2026, 9, 20), d(2026, 9, 20))),
        ("ayer", (d(2026, 9, 19), d(2026, 9, 19))),
        ("esta_semana", (d(2026, 9, 14), d(2026, 9, 20))),
        ("semana_pasada", (d(2026, 9, 7), d(2026, 9, 13))),
        ("este_mes", (d(2026, 9, 1), d(2026, 9, 20))),
        ("mes_pasado", (d(2026, 8, 1), d(2026, 8, 31))),
        ("este_anio", (d(2026, 1, 1), d(2026, 9, 20))),
        ("anio_pasado", (d(2025, 1, 1), d(2025, 12, 31))),
    ],
)
def test_periodos_sin_parametros(tipo, esperado):
    assert resolver_periodo_relativo(tipo, hoy=HOY) == esperado


def test_esta_semana_un_lunes_es_solo_hoy():
    lunes = d(2026, 9, 14)
    assert resolver_periodo_relativo("esta_semana", hoy=lunes) == (lunes, lunes)


def test_semana_pasada_desde_un_lunes():
    # El lunes 14/09: la semana pasada es 07/09 a 13/09.
    assert resolver_periodo_relativo("semana_pasada", hoy=d(2026, 9, 14)) == (d(2026, 9, 7), d(2026, 9, 13))


def test_ultimos_dias_incluye_hoy():
    assert resolver_periodo_relativo("ultimos_dias", n=7, hoy=HOY) == (d(2026, 9, 14), HOY)
    assert resolver_periodo_relativo("ultimos_dias", n=1, hoy=HOY) == (HOY, HOY)
    assert resolver_periodo_relativo("ultimos_dias", n=366, hoy=HOY) == (d(2025, 9, 20), HOY)


def test_ultimas_semanas_empieza_en_lunes():
    # 4 semanas: la actual y 3 anteriores completas -> lunes 24/08.
    assert resolver_periodo_relativo("ultimas_semanas", n=4, hoy=HOY) == (d(2026, 8, 24), HOY)
    assert resolver_periodo_relativo("ultimas_semanas", n=1, hoy=HOY) == (d(2026, 9, 14), HOY)
    assert resolver_periodo_relativo("ultimas_semanas", n=8, hoy=HOY)[0] == d(2026, 7, 27)


def test_ultimos_meses_son_meses_completos_mas_el_actual():
    # "ultimos tres meses" = julio y agosto completos + lo que va de septiembre.
    assert resolver_periodo_relativo("ultimos_meses", n=3, hoy=HOY) == (d(2026, 7, 1), HOY)
    assert resolver_periodo_relativo("ultimos_meses", n=1, hoy=HOY) == (d(2026, 9, 1), HOY)
    assert resolver_periodo_relativo("ultimos_meses", n=24, hoy=HOY) == (d(2024, 10, 1), HOY)


# ---- mes_calendario ------------------------------------------------------------------------


def test_mes_calendario_en_curso_se_recorta_a_hoy():
    assert resolver_periodo_relativo("mes_calendario", mes=9, hoy=HOY) == (d(2026, 9, 1), HOY)


def test_mes_calendario_ya_terminado_es_completo():
    assert resolver_periodo_relativo("mes_calendario", mes=2, hoy=HOY) == (d(2026, 2, 1), d(2026, 2, 28))


def test_mes_calendario_sin_anio_toma_el_mas_reciente_que_ya_empezo():
    # Diciembre todavía no llegó en septiembre de 2026: es diciembre de 2025.
    assert resolver_periodo_relativo("mes_calendario", mes=12, hoy=HOY) == (d(2025, 12, 1), d(2025, 12, 31))
    # Septiembre visto desde octubre: es septiembre de 2026 completo.
    assert resolver_periodo_relativo("mes_calendario", mes=9, hoy=d(2026, 10, 5)) == (d(2026, 9, 1), d(2026, 9, 30))


def test_mes_calendario_con_anio_explicito():
    assert resolver_periodo_relativo("mes_calendario", mes=2, anio=2024, hoy=HOY) == (d(2024, 2, 1), d(2024, 2, 29))


# ---- rango_fechas --------------------------------------------------------------------------


def test_rango_fechas_con_anio():
    rango = resolver_periodo_relativo("rango_fechas", desde=(1, 8, 2026), hasta=(15, 8, 2026), hoy=HOY)
    assert rango == (d(2026, 8, 1), d(2026, 8, 15))


def test_rango_fechas_sin_anio_toma_la_mas_reciente_que_no_es_futura():
    # 15/08 y 05/09 ya pasaron este año; 20/12 todavía no: es el de 2025.
    assert resolver_periodo_relativo("rango_fechas", desde=(15, 8), hasta=(5, 9), hoy=HOY) == (
        d(2026, 8, 15),
        d(2026, 9, 5),
    )
    assert resolver_periodo_relativo("rango_fechas", desde=(20, 12), hasta=(5, 1), hoy=HOY) == (
        d(2025, 12, 20),
        d(2026, 1, 5),
    )


def test_rango_fechas_acepta_date_dict_y_objetos_con_dia_mes_anio():
    fecha_parcial = SimpleNamespace(dia=1, mes=9, anio=None)  # como el esquema FechaParcial
    rango = resolver_periodo_relativo(
        "rango_fechas", desde=fecha_parcial, hasta={"dia": 10, "mes": 9, "anio": None}, hoy=HOY
    )
    assert rango == (d(2026, 9, 1), d(2026, 9, 10))
    rango = resolver_periodo_relativo("rango_fechas", desde=d(2026, 9, 1), hasta=HOY, hoy=HOY)
    assert rango == (d(2026, 9, 1), HOY)


def test_rango_de_un_dia_y_de_366_dias_son_validos():
    assert resolver_periodo_relativo("rango_fechas", desde=(5, 9), hasta=(5, 9), hoy=HOY) == (
        d(2026, 9, 5),
        d(2026, 9, 5),
    )
    # 20/09/2025 a 20/09/2026 son 366 días contados con los dos extremos.
    rango = resolver_periodo_relativo("rango_fechas", desde=(20, 9, 2025), hasta=(20, 9, 2026), hoy=HOY)
    assert (rango[1] - rango[0]).days + 1 == 366


# ---- Cruce de año y bisiestos --------------------------------------------------------------


def test_cruce_de_anio_en_enero():
    hoy = d(2026, 1, 5)
    assert resolver_periodo_relativo("mes_pasado", hoy=hoy) == (d(2025, 12, 1), d(2025, 12, 31))
    assert resolver_periodo_relativo("este_mes", hoy=hoy) == (d(2026, 1, 1), hoy)
    assert resolver_periodo_relativo("esta_semana", hoy=hoy) == (d(2026, 1, 5), hoy)  # hoy es lunes
    assert resolver_periodo_relativo("semana_pasada", hoy=hoy) == (d(2025, 12, 29), d(2026, 1, 4))
    assert resolver_periodo_relativo("ultimos_meses", n=3, hoy=hoy) == (d(2025, 11, 1), hoy)
    assert resolver_periodo_relativo("ultimas_semanas", n=2, hoy=hoy) == (d(2025, 12, 29), hoy)
    assert resolver_periodo_relativo("mes_calendario", mes=11, hoy=hoy) == (d(2025, 11, 1), d(2025, 11, 30))


def test_mes_pasado_desde_marzo_respeta_febrero_bisiesto_y_no_bisiesto():
    assert resolver_periodo_relativo("mes_pasado", hoy=d(2024, 3, 10)) == (d(2024, 2, 1), d(2024, 2, 29))
    assert resolver_periodo_relativo("mes_pasado", hoy=d(2026, 3, 10)) == (d(2026, 2, 1), d(2026, 2, 28))


def test_ultimos_meses_desde_el_29_de_febrero():
    hoy = d(2028, 2, 29)  # 2028 es bisiesto
    assert resolver_periodo_relativo("ultimos_meses", n=2, hoy=hoy) == (d(2028, 1, 1), hoy)
    assert resolver_periodo_relativo("ultimos_meses", n=13, hoy=hoy) == (d(2027, 2, 1), hoy)


def test_rango_con_29_de_febrero_sin_anio_busca_el_bisiesto_mas_reciente():
    # Hoy es 2026: el 29/02 más reciente que ya ocurrió es el de 2024.
    assert resolver_periodo_relativo("rango_fechas", desde=(29, 2), hasta=(29, 2), hoy=HOY) == (
        d(2024, 2, 29),
        d(2024, 2, 29),
    )
    # Y si hoy es el propio 29/02 de un año bisiesto, es hoy.
    hoy_bisiesto = d(2028, 2, 29)
    assert resolver_periodo_relativo("rango_fechas", desde=(29, 2), hasta=(29, 2), hoy=hoy_bisiesto) == (
        hoy_bisiesto,
        hoy_bisiesto,
    )


def test_rango_con_29_de_febrero_en_anio_no_bisiesto_es_error():
    with pytest.raises(DomainError, match="no existe"):
        resolver_periodo_relativo("rango_fechas", desde=(29, 2, 2026), hasta=(1, 3, 2026), hoy=HOY)


def test_29_de_febrero_con_anio_bisiesto_es_valido():
    rango = resolver_periodo_relativo("rango_fechas", desde=(29, 2, 2024), hasta=(1, 3, 2024), hoy=HOY)
    assert rango == (d(2024, 2, 29), d(2024, 3, 1))


# ---- Errores -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argumentos", "fragmento"),
    [
        ({"tipo": "ultimos_dias", "n": 0}, "entre 1 y 366"),
        ({"tipo": "ultimos_dias", "n": 367}, "entre 1 y 366"),
        ({"tipo": "ultimos_dias", "n": 999}, "entre 1 y 366"),
        ({"tipo": "ultimos_dias"}, "Indica cuántos"),
        ({"tipo": "ultimas_semanas", "n": 105}, "entre 1 y 104"),
        ({"tipo": "ultimos_meses", "n": 25}, "entre 1 y 24"),
        ({"tipo": "ultimos_meses", "n": -3}, "entre 1 y 24"),
        ({"tipo": "ultimos_meses", "n": True}, "entre 1 y 24"),
        ({"tipo": "ultimos_meses", "n": 2.5}, "entre 1 y 24"),
        ({"tipo": "mes_calendario", "mes": 13}, "del 1 al 12"),
        ({"tipo": "mes_calendario", "mes": 0}, "del 1 al 12"),
        ({"tipo": "mes_calendario"}, "Indica el mes"),
        ({"tipo": "mes_calendario", "mes": 12, "anio": 2026}, "todavía no empieza"),
        ({"tipo": "mes_calendario", "mes": 3, "anio": 1999}, "entre 2000 y 2100"),
        ({"tipo": "rango_fechas", "desde": (1, 10, 2026), "hasta": (5, 10, 2026)}, "futura"),
        ({"tipo": "rango_fechas", "desde": (1, 9, 2026), "hasta": (21, 9, 2026)}, "futura"),
        ({"tipo": "rango_fechas", "desde": (10, 9, 2026), "hasta": (1, 9, 2026)}, "posterior"),
        ({"tipo": "rango_fechas", "desde": (1, 1, 2025), "hasta": (2, 1, 2026)}, "demasiado largo"),  # 367 días
        ({"tipo": "rango_fechas", "desde": (1, 9, 2026)}, "Falta la fecha 'hasta'"),
        ({"tipo": "rango_fechas", "desde": (31, 4), "hasta": (1, 5)}, "no existe"),
        ({"tipo": "rango_fechas", "desde": (1, 13), "hasta": (1, 9)}, "del 1 al 12"),
        ({"tipo": "rango_fechas", "desde": (0, 9), "hasta": (1, 9)}, "día"),
        ({"tipo": "rango_fechas", "desde": "ayer", "hasta": (1, 9)}, "con día y mes"),
        ({"tipo": "proximo_mes"}, "No reconozco"),
    ],
)
def test_errores_son_domain_error_con_mensaje_claro(argumentos, fragmento):
    with pytest.raises(DomainError) as error:
        resolver_periodo_relativo(hoy=HOY, **argumentos)
    assert fragmento in str(error.value)


def test_sin_hoy_inyectado_usa_el_reloj_utc(monkeypatch):
    monkeypatch.setattr("app.core.tiempo.hoy_utc", lambda: d(2030, 6, 15))
    assert resolver_periodo_relativo("este_mes") == (d(2030, 6, 1), d(2030, 6, 15))


def test_ningun_periodo_termina_despues_de_hoy():
    for hoy in (d(2026, 1, 1), d(2026, 2, 28), d(2026, 9, 20), d(2026, 12, 31), d(2028, 2, 29)):
        casos = [
            ("hoy", {}),
            ("ayer", {}),
            ("esta_semana", {}),
            ("semana_pasada", {}),
            ("este_mes", {}),
            ("mes_pasado", {}),
            ("este_anio", {}),
            ("anio_pasado", {}),
            ("ultimos_dias", {"n": 30}),
            ("ultimas_semanas", {"n": 8}),
            ("ultimos_meses", {"n": 3}),
            ("mes_calendario", {"mes": 7}),
            ("mes_calendario", {"mes": 12}),
        ]
        for tipo, extra in casos:
            desde, hasta = resolver_periodo_relativo(tipo, hoy=hoy, **extra)
            assert desde <= hasta <= hoy, (tipo, hoy)
