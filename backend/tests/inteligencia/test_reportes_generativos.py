"""CU-23 (E09): los 6 reportes generativos con datos reales. Se usa `mundo_ia` (ver
ayudas_reportes_generativos.py): hoy = 20/09/2026; la empresa A tiene 4 ventas efectivas en septiembre
(pagadas y entregadas: 740.00 en total) y además una pendiente, una anulada y dos fuera de fecha que NO
cuentan. Las cifras esperadas se calcularon a mano con el docstring de `sembrar_mundo_reportes`:

  Centro 350.00 (V1 + V2, 2 ventas) · Norte 390.00 (V3 + V4, 2 ventas)
  P1 Camisa Oxford 3 u / 300.00 · P2 Polera Básica 4 u / 200.00 · P3 Camisa Lino 3 u / 240.00
  Camisas 540.00 (margen 210.00) · Poleras 200.00 (margen 80.00)
"""

from decimal import Decimal

import pytest

from app.inteligencia.politicas import ticket_promedio
from tests.inteligencia.ayudas_reportes_generativos import API, ejecutar, filas_de, interpretar


def _pedir(client, mundo, texto=None, **solicitud):
    cuerpo = {"texto": texto} if texto else {"solicitud": solicitud}
    return client.post(f"{API}/ejecutar", json=cuerpo, headers=mundo.a.headers)


# ---- Los 6 reportes -------------------------------------------------------------------------


def test_ventas_por_sucursal(client_por_peticion, mundo_ia):
    respuesta = _pedir(
        client_por_peticion, mundo_ia, tipo_reporte="ventas_por_sucursal", periodo={"tipo": "este_mes"}
    )

    filas = filas_de(respuesta)
    assert [f["sucursal"] for f in filas] == ["Norte", "Centro"]  # de la que más vendió a la que menos
    assert filas[0] == {
        "sucursal": "Norte", "transacciones": 2, "total_ventas": 390.0, "ticket_promedio": 195.0, "participacion": 52.7,
    }
    assert filas[1]["total_ventas"] == 350.0 and filas[1]["participacion"] == 47.3
    cuerpo = respuesta.json()
    assert cuerpo["reporte"]["resumen"] == {"total_ventas": 740.0, "transacciones": 4}
    assert cuerpo["reporte"]["grafico_sugerido"]["tipo"] == "barras"
    assert cuerpo["solicitud"]["periodo"]["desde"] == "2026-09-01" and cuerpo["solicitud"]["periodo"]["hasta"] == "2026-09-20"
    assert "Norte" in cuerpo["narrativa"] and "740,00" in cuerpo["narrativa"]


def test_productos_mas_vendidos_ordena_por_unidades_y_desempata_por_producto(client_por_peticion, mundo_ia):
    filas = filas_de(
        _pedir(client_por_peticion, mundo_ia, tipo_reporte="productos_mas_vendidos", periodo={"tipo": "este_mes"})
    )

    assert [(f["posicion"], f["producto"], f["unidades"], f["total_vendido"]) for f in filas] == [
        (1, "Polera Básica", 4, 200.0),
        (2, "Camisa Oxford", 3, 300.0),
        (3, "Camisa Lino", 3, 240.0),
    ]
    assert [f["participacion"] for f in filas] == [27.0, 40.5, 32.4]  # sobre las ventas del periodo (740)


def test_productos_mas_vendidos_con_limite_y_orden_inverso(client_por_peticion, mundo_ia):
    respuesta = _pedir(
        client_por_peticion,
        mundo_ia,
        tipo_reporte="productos_mas_vendidos",
        periodo={"tipo": "este_mes"},
        limite=2,
        orden="menor_a_mayor",
    )

    filas = filas_de(respuesta)
    assert [f["producto"] for f in filas] == ["Camisa Oxford", "Camisa Lino"]
    assert any("con ventas" in aviso for aviso in respuesta.json()["avisos"])


def test_ventas_por_periodo_por_semana_incluye_las_semanas_sin_ventas(client_por_peticion, mundo_ia):
    respuesta = _pedir(
        client_por_peticion, mundo_ia, tipo_reporte="ventas_por_periodo", agrupacion="semana"
    )  # sin periodo: las últimas 8 semanas, con aviso

    filas = filas_de(respuesta)
    assert len(filas) == 8
    assert filas[0]["periodo"] == "S31 (27/07)" and filas[0]["total_ventas"] == 100.0  # V7 del 1 de agosto
    assert filas[1]["total_ventas"] == 0.0  # semana sin ventas: aparece con 0
    assert filas[-1] == {
        "periodo": "S38 (14/09)", "desde": "2026-09-14", "transacciones": 4, "unidades": 10, "total_ventas": 740.0,
    }
    assert any("No indicaste el periodo" in aviso for aviso in respuesta.json()["avisos"])
    assert respuesta.json()["reporte"]["grafico_sugerido"]["tipo"] == "linea"


def test_ventas_por_periodo_por_dia_y_por_mes(client_por_peticion, mundo_ia):
    por_dia = filas_de(
        _pedir(
            client_por_peticion,
            mundo_ia,
            tipo_reporte="ventas_por_periodo",
            periodo={"tipo": "ultimos_dias", "n": 7},
            agrupacion="dia",
        )
    )
    por_mes = filas_de(
        _pedir(
            client_por_peticion,
            mundo_ia,
            tipo_reporte="ventas_por_periodo",
            periodo={"tipo": "ultimos_meses", "n": 2},
            agrupacion="mes",
        )
    )

    assert [(f["periodo"], f["total_ventas"]) for f in por_dia] == [
        ("14/09/2026", 250.0), ("15/09/2026", 330.0), ("16/09/2026", 0.0), ("17/09/2026", 0.0),
        ("18/09/2026", 0.0), ("19/09/2026", 0.0), ("20/09/2026", 160.0),
    ]
    assert [(f["periodo"], f["total_ventas"]) for f in por_mes] == [("08/2026", 100.0), ("09/2026", 740.0)]


def test_comparacion_sucursales_calcula_la_variacion_contra_el_periodo_anterior(client_por_peticion, mundo_ia):
    respuesta = _pedir(client_por_peticion, mundo_ia, tipo_reporte="comparacion_sucursales")  # últimos 3 meses

    filas = filas_de(respuesta)
    assert [(f["periodo"], f["sucursal"], f["total_ventas"], f["variacion_pct"]) for f in filas] == [
        ("07/2026", "Centro", 0.0, None),
        ("07/2026", "Norte", 0.0, None),
        ("08/2026", "Centro", 100.0, None),  # antes 0: sin variación
        ("08/2026", "Norte", 0.0, None),
        ("09/2026", "Centro", 350.0, 250.0),
        ("09/2026", "Norte", 390.0, None),
    ]
    cuerpo = respuesta.json()
    assert cuerpo["reporte"]["grafico_sugerido"] == {
        "tipo": "barras_agrupadas", "eje_x": "periodo", "eje_y": "total_ventas", "serie": "sucursal",
    }
    assert any("Últimos 3 meses" in aviso and "01/07/2026" in aviso for aviso in cuerpo["avisos"])


def test_productos_menor_existencia_suma_las_sucursales_y_ordena_de_menor_a_mayor(client_por_peticion, mundo_ia):
    filas = filas_de(_pedir(client_por_peticion, mundo_ia, tipo_reporte="productos_menor_existencia"))

    # Totales entre Centro y Norte; no cuentan la variante inactiva ni el producto descontinuado.
    assert [(f["producto"], f["disponible"], f["stock_minimo"], f["bajo_minimo"]) for f in filas] == [
        ("Camisa Lino", 8, 4, False),
        ("Polera Básica", 11, 7, False),
        ("Camisa Oxford", 14, 4, False),
    ]


def test_productos_menor_existencia_de_una_sucursal_marca_los_bajo_minimo(client_por_peticion, mundo_ia):
    filas = filas_de(
        _pedir(client_por_peticion, mundo_ia, tipo_reporte="productos_menor_existencia", sucursales=["centro"], limite=2)
    )

    assert [(f["producto"], f["disponible"], f["bajo_minimo"]) for f in filas] == [
        ("Polera Básica", 3, True),
        ("Camisa Lino", 6, False),
    ]


def test_ingresos_por_categoria(client_por_peticion, mundo_ia):
    respuesta = _pedir(
        client_por_peticion, mundo_ia, tipo_reporte="ingresos_por_categoria", periodo={"tipo": "este_mes"}
    )

    filas = filas_de(respuesta)
    assert filas == [
        {"categoria": "Camisas", "unidades": 6, "total_vendido": 540.0, "margen_bruto": 210.0, "participacion": 73.0},
        {"categoria": "Poleras", "unidades": 4, "total_vendido": 200.0, "margen_bruto": 80.0, "participacion": 27.0},
    ]
    assert respuesta.json()["reporte"]["grafico_sugerido"]["tipo"] == "torta"
    assert respuesta.json()["reporte"]["resumen"]["margen_bruto"] == 290.0


def test_ingresos_por_categoria_de_menor_a_mayor_con_limite(client_por_peticion, mundo_ia):
    filas = filas_de(
        _pedir(
            client_por_peticion,
            mundo_ia,
            tipo_reporte="ingresos_por_categoria",
            periodo={"tipo": "este_mes"},
            orden="menor_a_mayor",
            limite=1,
        )
    )

    assert [f["categoria"] for f in filas] == ["Poleras"]


# ---- Filtros --------------------------------------------------------------------------------


def test_filtro_por_sucursal_categoria_canal_y_producto(client_por_peticion, mundo_ia):
    por_sucursal = filas_de(
        _pedir(client_por_peticion, mundo_ia, tipo_reporte="ventas_por_sucursal", periodo={"tipo": "este_mes"}, sucursales=["Centro"])
    )
    por_categoria = filas_de(
        _pedir(client_por_peticion, mundo_ia, tipo_reporte="ventas_por_sucursal", periodo={"tipo": "este_mes"}, categorias=["poleras"])
    )
    por_canal = filas_de(
        _pedir(client_por_peticion, mundo_ia, tipo_reporte="ventas_por_sucursal", periodo={"tipo": "este_mes"}, canal="digital")
    )
    por_producto = filas_de(
        _pedir(
            client_por_peticion,
            mundo_ia,
            tipo_reporte="ventas_por_periodo",
            periodo={"tipo": "ultimos_dias", "n": 7},
            agrupacion="dia",
            productos=["lino"],
        )
    )

    assert [(f["sucursal"], f["total_ventas"]) for f in por_sucursal] == [("Centro", 350.0)]
    assert {(f["sucursal"], f["total_ventas"]) for f in por_categoria} == {("Centro", 50.0), ("Norte", 150.0)}  # P2
    assert [(f["sucursal"], f["total_ventas"]) for f in por_canal] == [("Centro", 100.0)]  # solo V2 es digital
    assert sum(f["total_ventas"] for f in por_producto) == 240.0  # solo P3 Camisa Lino


def test_un_filtro_que_el_reporte_no_usa_se_ignora_con_aviso(client_por_peticion, mundo_ia):
    respuesta = _pedir(
        client_por_peticion,
        mundo_ia,
        tipo_reporte="ventas_por_sucursal",
        periodo={"tipo": "este_mes"},
        limite=3,
    )

    assert respuesta.json()["estado"] == "ok"
    assert any("no usa el filtro «limite»" in aviso for aviso in respuesta.json()["avisos"])


def test_el_periodo_por_defecto_se_avisa_con_las_fechas(client_por_peticion, mundo_ia):
    respuesta = _pedir(client_por_peticion, mundo_ia, tipo_reporte="ventas_por_sucursal")

    aviso = next(a for a in respuesta.json()["avisos"] if "No indicaste el periodo" in a)
    assert "22/08/2026 al 20/09/2026" in aviso  # los últimos 30 días


def test_el_tope_de_filas_trunca_y_avisa(client_por_peticion, mundo_ia, monkeypatch):
    monkeypatch.setattr(
        "app.inteligencia.casos_uso.cu23_generar_reportes_con_ia.get_settings",
        lambda: type("A", (), {"reportes_ia_max_filas": 3})(),
    )

    respuesta = _pedir(
        client_por_peticion,
        mundo_ia,
        tipo_reporte="ventas_por_periodo",
        periodo={"tipo": "ultimos_dias", "n": 7},
        agrupacion="dia",
    )

    reporte = respuesta.json()["reporte"]
    assert len(reporte["filas"]) == 3 and reporte["truncado"] is True
    assert any("más de 3 filas" in aviso for aviso in respuesta.json()["avisos"])


# ---- Texto, intérprete de reglas y catálogo ----------------------------------------------------


@pytest.mark.parametrize(
    "frase, reporte",
    [
        ("Mostrame las ventas de septiembre agrupadas por sucursal", "ventas_por_sucursal"),
        ("cuales fueron los diez productos mas vendidos este mes", "productos_mas_vendidos"),
        ("genera un grafico de ventas por semana", "ventas_por_periodo"),
        ("compara las ventas de las sucursales durante los ultimos tres meses", "comparacion_sucursales"),
        ("mostrame los productos con menor existencia", "productos_menor_existencia"),
        ("que categorias generaron mayores ingresos durante este periodo", "ingresos_por_categoria"),
    ],
)
def test_las_seis_frases_del_enunciado_con_el_interprete_de_reglas(client_por_peticion, mundo_ia, frase, reporte):
    # Sin clave de Groq (fixture autouse) el intérprete cae a las reglas y lo avisa.
    respuesta = ejecutar(client_por_peticion, mundo_ia.a.headers, texto=frase)

    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "ok", cuerpo
    assert cuerpo["solicitud"]["tipo_reporte"] == reporte
    assert cuerpo["interprete"] == "reglas"
    assert any("interpretación básica" in aviso for aviso in cuerpo["avisos"])
    assert cuerpo["reporte"]["filas"], "el reporte trae datos reales"


def test_las_ventas_de_septiembre_por_sucursal_coinciden_con_los_reportes_convencionales(
    client_por_peticion, mundo_ia, monkeypatch
):
    # SQLite (solo las pruebas) devuelve float en SUM(); CU-22 espera el Decimal de PostgreSQL.
    monkeypatch.setattr(
        "app.inteligencia.casos_uso.cu22_consultar_reportes_indicadores.ticket_promedio",
        lambda total, transacciones: ticket_promedio(Decimal(str(total)), transacciones),
    )
    generativo = ejecutar(
        client_por_peticion, mundo_ia.a.headers, texto="Mostrame las ventas de septiembre agrupadas por sucursal"
    ).json()
    convencional = client_por_peticion.get(
        "/api/v1/reportes/ventas?desde=2026-09-01&hasta=2026-09-20", headers=mundo_ia.a.headers
    ).json()

    assert generativo["reporte"]["resumen"]["total_ventas"] == float(convencional["resumen"]["total_ventas"])
    assert generativo["reporte"]["resumen"]["transacciones"] == convencional["resumen"]["transacciones"]


def test_con_groq_la_respuesta_marca_el_interprete(client_por_peticion, mundo_ia, interprete_falso):
    falso = interprete_falso({"tipo_reporte": "ingresos_por_categoria", "periodo": {"tipo": "este_mes"}})

    cuerpo = ejecutar(client_por_peticion, mundo_ia.a.headers, texto="lo que sea").json()

    assert cuerpo["estado"] == "ok" and cuerpo["interprete"] == "groq"
    assert not any("interpretación básica" in aviso for aviso in cuerpo["avisos"])
    assert falso.textos == ["lo que sea"]


def test_interpretar_devuelve_lo_entendido_sin_ejecutar(client_por_peticion, mundo_ia):
    respuesta = interpretar(
        client_por_peticion, mundo_ia.a.headers, texto="los productos mas vendidos de la sucursal Norte este mes"
    )

    cuerpo = respuesta.json()
    assert respuesta.status_code == 200 and cuerpo["estado"] == "ok"
    assert cuerpo["reporte"] is None and cuerpo["narrativa"] is None
    assert cuerpo["solicitud"]["tipo_reporte"] == "productos_mas_vendidos"
    assert cuerpo["solicitud"]["sucursales"] == [{"id": mundo_ia.datos_a["sucursales"]["norte"], "nombre": "Norte"}]
    assert "Entendí" in cuerpo["mensaje"]


def test_el_catalogo_lista_los_seis_reportes_con_sus_ejemplos(client_por_peticion, mundo_ia):
    respuesta = client_por_peticion.get(f"{API}/catalogo", headers=mundo_ia.a.headers)

    assert respuesta.status_code == 200
    catalogo = respuesta.json()
    assert [r["codigo"] for r in catalogo] == [
        "ventas_por_sucursal", "productos_mas_vendidos", "ventas_por_periodo",
        "comparacion_sucursales", "productos_menor_existencia", "ingresos_por_categoria",
    ]
    assert all(r["ejemplos"] and r["columnas"] and r["grafico"] and r["filtros"] for r in catalogo)
    assert "ejecutor" not in catalogo[0]
