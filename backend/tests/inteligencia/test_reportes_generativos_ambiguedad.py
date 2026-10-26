"""CU-23 (E09): lo que NO se puede hacer se responde con un estado, un mensaje y sugerencias (HTTP 200),
nunca con datos inventados: incompleta, ambigua, invalida y no_soportada."""

import pytest

from tests.inteligencia.ayudas_reportes_generativos import ejecutar, interpretar


def _caso(client, mundo, **solicitud):
    respuesta = client.post(
        "/api/v1/reportes-ia/ejecutar", json={"solicitud": solicitud}, headers=mundo.a.headers
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _sin_datos(cuerpo):
    assert cuerpo["reporte"] is None, "una solicitud rechazada nunca trae filas"
    assert cuerpo["narrativa"] is None


def test_sin_tipo_de_reporte_es_incompleta_y_sugiere_ejemplos(client_por_peticion, mundo_ia):
    cuerpo = _caso(client_por_peticion, mundo_ia)

    assert cuerpo["estado"] == "incompleta"
    assert len(cuerpo["sugerencias"]) == 6  # una frase por cada reporte del plan
    _sin_datos(cuerpo)


def test_un_reporte_fuera_del_registro_es_no_soportado(client_por_peticion, mundo_ia):
    cuerpo = _caso(client_por_peticion, mundo_ia, tipo_reporte="usuarios")

    assert cuerpo["estado"] == "no_soportada"
    assert "Ventas por sucursal" in cuerpo["mensaje"] and "Reportes convencionales" in cuerpo["mensaje"]
    assert cuerpo["sugerencias"]
    _sin_datos(cuerpo)


def test_una_sucursal_inexistente_es_ambigua_y_lista_las_validas(client_por_peticion, mundo_ia):
    cuerpo = _caso(
        client_por_peticion, mundo_ia, tipo_reporte="ventas_por_sucursal", periodo={"tipo": "este_mes"}, sucursales=["Marte"]
    )

    assert cuerpo["estado"] == "ambigua"
    assert "Marte" in cuerpo["mensaje"]
    assert set(cuerpo["sugerencias"]) == {"Centro", "Norte"}  # la sucursal inactiva no se ofrece
    _sin_datos(cuerpo)


def test_una_categoria_inexistente_es_ambigua(client_por_peticion, mundo_ia):
    cuerpo = _caso(
        client_por_peticion, mundo_ia, tipo_reporte="ventas_por_sucursal", periodo={"tipo": "este_mes"}, categorias=["Zapatos"]
    )

    assert cuerpo["estado"] == "ambigua"
    assert set(cuerpo["sugerencias"]) == {"Camisas", "Poleras"}  # sin la categoría inactiva
    _sin_datos(cuerpo)


def test_un_producto_inexistente_es_ambiguo(client_por_peticion, mundo_ia):
    cuerpo = _caso(
        client_por_peticion, mundo_ia, tipo_reporte="ventas_por_periodo", periodo={"tipo": "este_mes"}, productos=["Zapato"]
    )

    assert cuerpo["estado"] == "ambigua" and "Zapato" in cuerpo["mensaje"]
    _sin_datos(cuerpo)


def test_un_producto_que_coincide_con_demasiados_es_ambiguo(client_por_peticion, mundo_ia, monkeypatch):
    monkeypatch.setattr(
        "app.catalogo.politicas.resolver_productos_por_nombres", lambda db, nombres, tope=10: ([], ["camisa"], [])
    )

    cuerpo = _caso(
        client_por_peticion, mundo_ia, tipo_reporte="ventas_por_periodo", periodo={"tipo": "este_mes"}, productos=["camisa"]
    )

    assert cuerpo["estado"] == "ambigua" and "demasiados" in cuerpo["mensaje"]
    _sin_datos(cuerpo)


@pytest.mark.parametrize(
    "periodo",
    [
        {"tipo": "rango_fechas", "desde": {"dia": 1, "mes": 12, "anio": 2026}, "hasta": {"dia": 5, "mes": 12, "anio": 2026}},
        {"tipo": "rango_fechas", "desde": {"dia": 1, "mes": 1, "anio": 2025}, "hasta": {"dia": 1, "mes": 9, "anio": 2026}},
        {"tipo": "rango_fechas", "desde": {"dia": 10, "mes": 9, "anio": 2026}, "hasta": {"dia": 5, "mes": 9, "anio": 2026}},
        {"tipo": "mes_calendario", "mes": 13},
        {"tipo": "ultimos_dias", "n": 999},
        {"tipo": "ultimos_dias"},
    ],
    ids=["futuro", "mas_de_366_dias", "desde_despues_de_hasta", "mes_13", "n_999", "sin_n"],
)
def test_un_periodo_imposible_es_invalido_con_el_motivo(client_por_peticion, mundo_ia, periodo):
    cuerpo = _caso(client_por_peticion, mundo_ia, tipo_reporte="ventas_por_sucursal", periodo=periodo)

    assert cuerpo["estado"] == "invalida"
    assert cuerpo["mensaje"] and cuerpo["sugerencias"]
    _sin_datos(cuerpo)


@pytest.mark.parametrize("limite", [0, -3, 51, 500])
def test_un_limite_fuera_de_rango_es_invalido_y_no_un_422(client_por_peticion, mundo_ia, limite):
    cuerpo = _caso(
        client_por_peticion,
        mundo_ia,
        tipo_reporte="productos_mas_vendidos",
        periodo={"tipo": "este_mes"},
        limite=limite,
    )

    assert cuerpo["estado"] == "invalida" and "entre 1 y 50" in cuerpo["mensaje"]
    _sin_datos(cuerpo)


def test_una_agrupacion_que_el_reporte_no_admite_es_invalida(client_por_peticion, mundo_ia):
    cuerpo = _caso(client_por_peticion, mundo_ia, tipo_reporte="comparacion_sucursales", agrupacion="dia")

    assert cuerpo["estado"] == "invalida" and "mes, semana" in cuerpo["mensaje"]
    _sin_datos(cuerpo)


def test_varios_reportes_a_la_vez_se_avisan_y_se_muestra_uno(client_por_peticion, mundo_ia):
    cuerpo = _caso(
        client_por_peticion,
        mundo_ia,
        tipo_reporte="ventas_por_sucursal",
        periodo={"tipo": "este_mes"},
        solicitud_multiple=True,
    )

    assert cuerpo["estado"] == "ok"
    assert any("varios reportes" in aviso for aviso in cuerpo["avisos"])


def test_un_texto_sin_sentido_es_incompleto_con_sugerencias(client_por_peticion, mundo_ia):
    cuerpo = ejecutar(client_por_peticion, mundo_ia.a.headers, texto="asdf qwerty zzz").json()

    assert cuerpo["estado"] == "incompleta" and cuerpo["sugerencias"]
    _sin_datos(cuerpo)


def test_un_texto_solo_de_espacios_y_control_es_incompleto(client_por_peticion, mundo_ia):
    cuerpo = ejecutar(client_por_peticion, mundo_ia.a.headers, texto="  \t\n\x00 ").json()

    assert cuerpo["estado"] == "incompleta"
    _sin_datos(cuerpo)


def test_si_groq_no_entiende_no_se_inventa_nada(client_por_peticion, mundo_ia, interprete_falso):
    interprete_falso({"tipo_reporte": None})  # respondió, pero no hay reporte que pedir

    cuerpo = ejecutar(client_por_peticion, mundo_ia.a.headers, texto="cuéntame un chiste").json()

    assert cuerpo["estado"] == "incompleta" and cuerpo["interprete"] == "groq"
    _sin_datos(cuerpo)


def test_si_groq_falla_se_usan_las_reglas_y_se_avisa(client_por_peticion, mundo_ia, interprete_falso):
    interprete_falso(None, error="timeout")

    cuerpo = ejecutar(client_por_peticion, mundo_ia.a.headers, texto="productos con menor existencia").json()

    assert cuerpo["estado"] == "ok" and cuerpo["interprete"] == "reglas"
    assert any("interpretación básica" in aviso for aviso in cuerpo["avisos"])


def test_interpretar_tambien_responde_con_estados(client_por_peticion, mundo_ia):
    cuerpo = interpretar(client_por_peticion, mundo_ia.a.headers, texto="ventas de la sucursal Marte este mes").json()

    assert cuerpo["estado"] == "ambigua" and cuerpo["reporte"] is None
