"""CU-23 (E09) — Registro cerrado de reportes generativos y esquemas de la solicitud.
Sin base de datos y sin red."""

import dataclasses
import re
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.inteligencia import registro_reportes as registro
from app.inteligencia.schemas import (
    ReporteGenerativoRequest,
    ReporteGenerativoRespuesta,
    SolicitudReporte,
)

CODIGOS = {
    "ventas_por_sucursal",
    "productos_mas_vendidos",
    "ventas_por_periodo",
    "comparacion_sucursales",
    "productos_menor_existencia",
    "ingresos_por_categoria",
}
# E12: los reportes que salen del Machine Learning (plan con analitica_ml); el resto es de reportes_ia.
CODIGOS_ANALITICA = {
    "prediccion_demanda",
    "segmentacion_clientes",
    "metricas_modelos",
    "anomalias_ventas",
    "reposicion_sugerida",
}

FRASES_DEL_ENUNCIADO = {
    "ventas_por_sucursal": "Mostrame las ventas de septiembre agrupadas por sucursal",
    "productos_mas_vendidos": "cuales fueron los diez productos mas vendidos este mes",
    "ventas_por_periodo": "genera un grafico de ventas por semana",
    "comparacion_sucursales": "compara las ventas de las sucursales durante los ultimos tres meses",
    "productos_menor_existencia": "mostrame los productos con menor existencia",
    "ingresos_por_categoria": "que categorias generaron mayores ingresos durante este periodo",
}

APP_INTELIGENCIA = Path(__file__).resolve().parents[2] / "app" / "inteligencia"


# ---- Registro ---------------------------------------------------------------------------


def test_hay_al_menos_seis_reportes_con_los_codigos_esperados():
    assert len(registro.REGISTRO) >= 6
    assert CODIGOS <= set(registro.REGISTRO)


def test_cada_reporte_tiene_columnas_grafico_y_ejemplos():
    for definicion in registro.REGISTRO.values():
        assert definicion.titulo and definicion.descripcion
        assert len(definicion.columnas) >= 3, definicion.codigo
        assert definicion.grafico.tipo, definicion.codigo
        assert 2 <= len(definicion.ejemplos) <= 3, definicion.codigo
        assert definicion.funcionalidad_plan == ("analitica_ml" if definicion.codigo in CODIGOS_ANALITICA else "reportes_ia")
        claves = {c.clave for c in definicion.columnas}
        for eje in (definicion.grafico.eje_x, definicion.grafico.eje_y, definicion.grafico.serie):
            assert eje is None or eje in claves, (definicion.codigo, eje)


def test_los_filtros_declarados_tienen_tipo_y_rango():
    for definicion in registro.REGISTRO.values():
        # Solo la segmentación y las métricas (E12) no tienen filtros: son del modelo entero de la empresa.
        assert definicion.filtros or definicion.codigo in {"segmentacion_clientes", "metricas_modelos"}, definicion.codigo
        for nombre, filtro in definicion.filtros.items():
            assert filtro.tipo in {"periodo", "lista_nombres", "enum", "entero"}, nombre
            if filtro.tipo == "entero":
                assert filtro.minimo is not None and filtro.maximo is not None
                assert filtro.minimo <= filtro.defecto <= filtro.maximo
            if filtro.tipo == "enum":
                assert filtro.valores
                assert filtro.defecto is None or filtro.defecto in filtro.valores
            if filtro.tipo == "lista_nombres":
                assert filtro.maximo == 5


def test_defectos_de_periodo_del_paso_4():
    periodo = lambda codigo: registro.REGISTRO[codigo].filtros["periodo"].defecto  # noqa: E731
    assert periodo("ventas_por_sucursal") == {"tipo": "ultimos_dias", "n": 30}
    assert periodo("ventas_por_periodo") == {"tipo": "ultimas_semanas", "n": 8}
    assert periodo("comparacion_sucursales") == {"tipo": "ultimos_meses", "n": 3}
    assert "periodo" not in registro.REGISTRO["productos_menor_existencia"].filtros
    assert registro.REGISTRO["productos_mas_vendidos"].filtros["limite"].defecto == 10
    assert registro.REGISTRO["ventas_por_periodo"].filtros["agrupacion"].defecto == "semana"
    assert registro.REGISTRO["comparacion_sucursales"].filtros["agrupacion"].valores == ("mes", "semana")


def test_las_seis_frases_del_enunciado_estan_en_los_ejemplos():
    for codigo, frase in FRASES_DEL_ENUNCIADO.items():
        assert frase in registro.REGISTRO[codigo].ejemplos, codigo


def test_obtener_devuelve_la_definicion_o_none():
    assert registro.obtener("ventas_por_sucursal").codigo == "ventas_por_sucursal"
    assert registro.obtener("usuarios") is None
    assert registro.obtener(None) is None
    assert registro.obtener("../etc") is None


def test_disponibles_para_filtra_por_funcionalidad():
    assert {d.codigo for d in registro.disponibles_para(["reportes_ia", "gestion_ventas"])} == CODIGOS
    assert registro.disponibles_para(["reportes_convencionales"]) == []
    assert registro.disponibles_para([]) == []
    assert [d["codigo"] for d in registro.catalogo_para(["reportes_ia"])] == [
        d.codigo for d in registro.REGISTRO.values() if d.codigo not in CODIGOS_ANALITICA
    ]
    assert {d["codigo"] for d in registro.catalogo_para(["analitica_ml"])} == CODIGOS_ANALITICA
    assert registro.catalogo_para(["gestion_ventas"]) == []


def test_descripcion_para_prompt_lista_codigos_filtros_y_enums_sin_datos():
    texto = registro.descripcion_para_prompt()
    for codigo in CODIGOS:
        assert codigo in texto
    for valor in ("digital", "presencial", "mayor_a_menor", "menor_a_mayor", "ultimos_meses", "mes_calendario"):
        assert valor in texto
    assert registro.descripcion_para_prompt(["gestion_ventas"]).count("- ") == 0
    # Con solo reportes_ia no se describe ningún reporte de analítica, y viceversa.
    solo_ia = registro.descripcion_para_prompt(["reportes_ia"])
    assert not any(codigo in solo_ia for codigo in CODIGOS_ANALITICA)
    solo_ml = registro.descripcion_para_prompt(["analitica_ml"])
    assert all(codigo in solo_ml for codigo in CODIGOS_ANALITICA) and not any(codigo in solo_ml for codigo in CODIGOS)


def test_el_registro_es_cerrado_y_conectar_ejecutor_solo_acepta_codigos_existentes():
    with pytest.raises(TypeError):
        registro.REGISTRO["nuevo"] = None  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        registro.REGISTRO["ventas_por_sucursal"].titulo = "x"  # type: ignore[misc]
    with pytest.raises(KeyError):
        registro.conectar_ejecutor("usuarios", lambda *a: None)


def test_conectar_ejecutor_reemplaza_la_definicion_y_el_registro_lo_ve(monkeypatch):
    # Se aísla el registro interno para no dejar el ejecutor conectado a otras pruebas.
    monkeypatch.setattr(registro, "_REGISTRO_INTERNO", dict(registro._REGISTRO_INTERNO))
    monkeypatch.setattr(
        registro, "REGISTRO", registro.MappingProxyType(registro._REGISTRO_INTERNO)
    )
    ejecutor = lambda db, usuario_id, contexto: "ok"  # noqa: E731
    registro.conectar_ejecutor("ventas_por_sucursal", ejecutor)
    assert registro.obtener("ventas_por_sucursal").ejecutor is ejecutor


# ---- Guardia: sin SQL en inteligencia ----------------------------------------------------


def test_guardia_sin_sql_en_app_inteligencia():
    prohibidos = {
        "text(": re.compile(r"(?<![A-Za-z0-9_])text\("),
        "SELECT ": re.compile(r"SELECT "),
        "execute(": re.compile(r"execute\("),
    }
    archivos = sorted(APP_INTELIGENCIA.rglob("*.py"))
    assert any(a.name == "registro_reportes.py" for a in archivos)
    hallazgos = []
    for archivo in archivos:
        contenido = archivo.read_text(encoding="utf-8")
        for etiqueta, patron in prohibidos.items():
            if patron.search(contenido):
                hallazgos.append(f"{archivo.relative_to(APP_INTELIGENCIA)}: {etiqueta}")
    assert not hallazgos, hallazgos


# ---- Esquemas ----------------------------------------------------------------------------


def test_solicitud_acepta_lo_valido_y_trata_null_como_lista_vacia():
    s = SolicitudReporte.model_validate(
        {
            "tipo_reporte": "ventas_por_sucursal",
            "periodo": {"tipo": "mes_calendario", "mes": 9},
            "sucursales": None,
            "canal": "presencial",
            "limite": 10,
        }
    )
    assert s.sucursales == [] and s.categorias == [] and s.productos == []
    assert s.periodo.tipo == "mes_calendario" and s.periodo.mes == 9
    assert s.solicitud_multiple is False


@pytest.mark.parametrize(
    "campo",
    [
        {"empresa_id": 2},
        {"sucursal_id": 1},
        {"sucursal_ids": [1, 2]},
        {"usuario_id": 5},
        {"sql": "DROP TABLE venta"},
    ],
)
def test_solicitud_rechaza_campos_extra_ids_y_empresa(campo):
    with pytest.raises(ValidationError):
        SolicitudReporte.model_validate({"tipo_reporte": "ventas_por_sucursal", **campo})


def test_el_periodo_y_las_fechas_parciales_rechazan_campos_extra():
    with pytest.raises(ValidationError):
        SolicitudReporte.model_validate({"periodo": {"tipo": "hoy", "empresa_id": 1}})
    with pytest.raises(ValidationError):
        SolicitudReporte.model_validate(
            {"periodo": {"tipo": "rango_fechas", "desde": {"dia": 1, "mes": 1, "x": 1}}}
        )
    with pytest.raises(ValidationError):
        SolicitudReporte.model_validate(
            {"periodo": {"tipo": "rango_fechas", "desde": {"dia": 32, "mes": 1}}}
        )
    with pytest.raises(ValidationError):
        SolicitudReporte.model_validate(
            {"periodo": {"tipo": "rango_fechas", "desde": {"dia": 1, "mes": 13}}}
        )


@pytest.mark.parametrize(
    "datos",
    [
        {"canal": "telefono"},
        {"agrupacion": "anio"},
        {"orden": "alfabetico"},
        {"periodo": {"tipo": "proximo_mes"}},
        {"periodo": {}},
    ],
)
def test_solicitud_rechaza_enums_fuera_de_lista(datos):
    with pytest.raises(ValidationError):
        SolicitudReporte.model_validate(datos)


@pytest.mark.parametrize("limite", [0, 1, 50, 51, -3, 500])
def test_solicitud_deja_pasar_el_limite_y_el_caso_de_uso_valida_el_rango(limite):
    # El rango 1..50 lo valida el caso de uso (estado "invalida"), no el esquema.
    assert SolicitudReporte.model_validate({"limite": limite}).limite == limite


def test_solicitud_limita_la_cantidad_y_el_largo_de_los_nombres():
    with pytest.raises(ValidationError):
        SolicitudReporte.model_validate({"sucursales": ["a"] * 6})
    with pytest.raises(ValidationError):
        SolicitudReporte.model_validate({"categorias": ["x" * 81]})
    assert len(SolicitudReporte.model_validate({"productos": ["p"] * 5}).productos) == 5
    assert SolicitudReporte.model_validate({"productos": ["x" * 80]}).productos


def test_request_limita_el_texto_a_300_caracteres():
    assert ReporteGenerativoRequest(texto="a" * 300).origen == "texto"
    with pytest.raises(ValidationError):
        ReporteGenerativoRequest(texto="a" * 301)
    with pytest.raises(ValidationError):
        ReporteGenerativoRequest(texto="")


def test_request_exige_exactamente_uno_de_texto_o_solicitud():
    solicitud = SolicitudReporte(tipo_reporte="ventas_por_sucursal")
    assert ReporteGenerativoRequest(solicitud=solicitud, origen="voz").origen == "voz"
    with pytest.raises(ValidationError):
        ReporteGenerativoRequest()
    with pytest.raises(ValidationError):
        ReporteGenerativoRequest(texto="ventas", solicitud=solicitud)
    with pytest.raises(ValidationError):
        ReporteGenerativoRequest(texto="ventas", origen="telepatia")
    with pytest.raises(ValidationError):
        ReporteGenerativoRequest(texto="ventas", empresa_id=3)


def test_respuesta_acepta_los_seis_estados_y_rechaza_otros():
    for estado in ("ok", "incompleta", "ambigua", "invalida", "no_soportada", "no_disponible"):
        r = ReporteGenerativoRespuesta(estado=estado, mensaje="m")
        assert r.reporte is None and r.sugerencias == [] and r.avisos == []
    with pytest.raises(ValidationError):
        ReporteGenerativoRespuesta(estado="error", mensaje="m")


# ---- conftest: sin red hacia Groq ---------------------------------------------------------


def test_sin_red_groq_bloquea_httpx_hacia_groq():
    url = "https://api.groq.com/openai/v1/chat/completions"
    with pytest.raises(AssertionError, match="Groq"):
        httpx.post(url, json={})
    with httpx.Client() as cliente:
        with pytest.raises(AssertionError, match="Groq"):
            cliente.post(url, json={})
