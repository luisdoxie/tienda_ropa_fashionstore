"""CU-23 (E10): POST /api/v1/reportes-ia/exportar. Usa `mundo_ia` (hoy = 20/09/2026; A: Centro 350,00 y
Norte 390,00 en septiembre, 740,00 en total; B tiene los mismos nombres con otras cifras). Ninguna
prueba llama a Groq: el intérprete lo reemplaza `interprete_falso`."""

import builtins
import datetime as dt
import re
import tempfile
import zipfile
from io import BytesIO

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.tenant import sin_filtro
from app.inteligencia import registro_reportes
from app.inteligencia.casos_uso import cu23_generar_reportes_con_ia as cu23
from app.plataforma.models import Bitacora, Suscripcion
from tests.inteligencia.ayudas_exportacion import celdas_xlsx, personal_de, texto_pdf
from tests.inteligencia.ayudas_reportes_generativos import API, ejecutar

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
VENTAS_POR_SUCURSAL = {"tipo_reporte": "ventas_por_sucursal", "periodo": {"tipo": "este_mes"}}


def exportar(client, headers, formato="xlsx", **cuerpo):
    return client.post(f"{API}/exportar", json={"formato": formato, **cuerpo}, headers=headers)


# ---- El contrato de la descarga ---------------------------------------------------------------


def test_exporta_xlsx_con_las_cifras_reales_y_las_cabeceras(client_por_peticion, mundo_ia):
    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, "xlsx", solicitud=VENTAS_POR_SUCURSAL)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"] == XLSX
    assert re.fullmatch(
        r'attachment; filename="reporte-ventas_por_sucursal-tienda-a-\d{8}-\d{4}\.xlsx"',
        respuesta.headers["content-disposition"],
    )
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.headers["x-content-type-options"] == "nosniff"
    celdas = celdas_xlsx(respuesta)
    assert "Ventas por sucursal" in celdas and "tienda-a" in celdas
    assert "Norte" in celdas and 390.0 in celdas and 350.0 in celdas
    assert 740.0 in celdas  # fila de totales


def test_exporta_pdf_con_las_cifras_reales_y_las_cabeceras(client_por_peticion, mundo_ia):
    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, "pdf", solicitud=VENTAS_POR_SUCURSAL)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"] == "application/pdf"
    assert re.fullmatch(
        r'attachment; filename="reporte-ventas_por_sucursal-tienda-a-\d{8}-\d{4}\.pdf"',
        respuesta.headers["content-disposition"],
    )
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.content.startswith(b"%PDF-")
    texto = texto_pdf(respuesta)
    assert "Ventas por sucursal" in texto and "tienda-a" in texto
    assert "Norte" in texto and "390,00" in texto and "740,00" in texto


@pytest.mark.parametrize("formato", ["xlsx", "pdf"])
@pytest.mark.parametrize("codigo", list(registro_reportes.REGISTRO))
def test_los_seis_reportes_se_exportan_en_ambos_formatos(client_por_peticion, mundo_ia, codigo, formato):
    respuesta = exportar(
        client_por_peticion,
        mundo_ia.a.headers,
        formato,
        solicitud={"tipo_reporte": codigo, "periodo": {"tipo": "este_mes"}},
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-disposition"].startswith(f'attachment; filename="reporte-{codigo}-tienda-a-')
    assert len(respuesta.content) > 500
    if formato == "xlsx":
        assert load_workbook(BytesIO(respuesta.content)).worksheets
    else:
        assert PdfReader(BytesIO(respuesta.content)).pages


def test_sin_grafico_el_xlsx_no_trae_graficos(client_por_peticion, mundo_ia):
    con = exportar(client_por_peticion, mundo_ia.a.headers, solicitud=VENTAS_POR_SUCURSAL)
    sin = exportar(client_por_peticion, mundo_ia.a.headers, solicitud=VENTAS_POR_SUCURSAL, incluir_grafico=False)

    assert "xl/charts/chart1.xml" in zipfile.ZipFile(BytesIO(con.content)).namelist()
    assert "xl/charts/chart1.xml" not in zipfile.ZipFile(BytesIO(sin.content)).namelist()


def test_los_filtros_aplicados_salen_en_el_archivo(client_por_peticion, mundo_ia):
    respuesta = exportar(
        client_por_peticion,
        mundo_ia.a.headers,
        "pdf",
        solicitud={**VENTAS_POR_SUCURSAL, "sucursales": ["Norte"], "canal": "presencial"},
    )

    texto = texto_pdf(respuesta)
    assert "Periodo: 01/09/2026 al 20/09/2026" in texto
    assert "Sucursales: Norte" in texto and "Canal: presencial" in texto
    assert "Centro" not in texto


# ---- Cómo se pide el reporte: texto, solicitud o resuelta -------------------------------------


def test_con_solicitud_o_resuelta_no_se_interpreta_y_con_texto_si(client_por_peticion, mundo_ia, interprete_falso):
    falso = interprete_falso(VENTAS_POR_SUCURSAL)
    resuelta = ejecutar(client_por_peticion, mundo_ia.a.headers, solicitud=VENTAS_POR_SUCURSAL).json()["solicitud"]
    assert falso.textos == []

    assert exportar(client_por_peticion, mundo_ia.a.headers, solicitud=VENTAS_POR_SUCURSAL).status_code == 200
    assert exportar(client_por_peticion, mundo_ia.a.headers, resuelta=resuelta).status_code == 200
    assert falso.textos == []  # ninguna de las dos llamó al intérprete

    assert exportar(client_por_peticion, mundo_ia.a.headers, texto="ventas por sucursal de este mes").status_code == 200
    assert falso.textos == ["ventas por sucursal de este mes"]


def test_la_resuelta_trae_lo_mismo_que_la_vista_previa(client_por_peticion, mundo_ia):
    vista = ejecutar(
        client_por_peticion,
        mundo_ia.a.headers,
        solicitud={"tipo_reporte": "productos_mas_vendidos", "periodo": {"tipo": "este_mes"}, "limite": 2},
    ).json()

    celdas = celdas_xlsx(exportar(client_por_peticion, mundo_ia.a.headers, resuelta=vista["solicitud"]))

    for fila in vista["reporte"]["filas"]:
        assert fila["producto"] in celdas and fila["total_vendido"] in celdas
    assert len(vista["reporte"]["filas"]) == 2
    assert "Camisa Lino" not in celdas  # el límite también viaja


def test_la_resuelta_conserva_el_periodo_ya_calculado(client_por_peticion, mundo_ia, monkeypatch):
    vista = ejecutar(client_por_peticion, mundo_ia.a.headers, solicitud=VENTAS_POR_SUCURSAL).json()
    monkeypatch.setattr("app.core.tiempo.hoy_utc", lambda: dt.date(2026, 10, 25))  # pasó el tiempo

    celdas = celdas_xlsx(exportar(client_por_peticion, mundo_ia.a.headers, resuelta=vista["solicitud"]))

    assert "Periodo: 01/09/2026 al 20/09/2026" in celdas and 740.0 in celdas


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"texto": "ventas", "solicitud": VENTAS_POR_SUCURSAL},
        {"texto": "ventas", "resuelta": {"tipo_reporte": "ventas_por_sucursal"}},
        {"solicitud": VENTAS_POR_SUCURSAL, "resuelta": {"tipo_reporte": "ventas_por_sucursal"}},
        {"texto": ""},
        {"texto": "x" * 301},
        {"solicitud": {"tipo_reporte": "ventas_por_sucursal", "empresa_id": 2}},
        {"solicitud": VENTAS_POR_SUCURSAL, "extra": 1},
    ],
)
def test_el_cuerpo_mal_formado_da_422(client_por_peticion, mundo_ia, cuerpo):
    assert exportar(client_por_peticion, mundo_ia.a.headers, **cuerpo).status_code == 422


def test_un_formato_desconocido_da_422(client_por_peticion, mundo_ia):
    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, "csv", solicitud=VENTAS_POR_SUCURSAL)

    assert respuesta.status_code == 422


# ---- Lo que no se puede exportar --------------------------------------------------------------


@pytest.mark.parametrize(
    "solicitud, estado",
    [
        ({"tipo_reporte": "usuarios"}, "no_soportada"),
        ({"tipo_reporte": None}, "incompleta"),
        ({**VENTAS_POR_SUCURSAL, "sucursales": ["Marte"]}, "ambigua"),
        ({"tipo_reporte": "productos_mas_vendidos", "limite": 99}, "invalida"),
        ({"tipo_reporte": "ventas_por_sucursal", "periodo": {"tipo": "ultimos_dias", "n": 9999}}, "invalida"),
    ],
)
def test_un_reporte_que_no_esta_ok_da_422_reporte_no_exportable_sin_archivo(
    client_por_peticion, mundo_ia, solicitud, estado
):
    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, solicitud=solicitud)

    cuerpo = respuesta.json()
    assert respuesta.status_code == 422
    assert respuesta.headers["content-type"].startswith("application/json")
    assert "content-disposition" not in respuesta.headers
    assert cuerpo["detail"] == "reporte_no_exportable" and cuerpo["codigo"] == "reporte_no_exportable"
    assert cuerpo["estado"] == estado and cuerpo["mensaje"]
    assert isinstance(cuerpo["sugerencias"], list)


def test_el_estado_ambiguo_sugiere_las_sucursales_reales(client_por_peticion, mundo_ia):
    cuerpo = exportar(
        client_por_peticion, mundo_ia.a.headers, solicitud={**VENTAS_POR_SUCURSAL, "sucursales": ["Marte"]}
    ).json()

    assert set(cuerpo["sugerencias"]) >= {"Centro", "Norte"}


def test_un_texto_que_no_se_entiende_da_422_con_ejemplos(client_por_peticion, mundo_ia, interprete_falso):
    interprete_falso(None, error="sin_clave")

    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, texto="blablabla xyz")

    assert respuesta.status_code == 422 and respuesta.json()["detail"] == "reporte_no_exportable"
    assert respuesta.json()["sugerencias"]


# ---- Plan, permiso y suscripción --------------------------------------------------------------


def test_el_plan_basico_recibe_403_plan_no_incluye_funcionalidad(client_por_peticion, dos_empresas):
    respuesta = exportar(client_por_peticion, dos_empresas.b.headers, solicitud=VENTAS_POR_SUCURSAL)

    assert respuesta.status_code == 403
    assert respuesta.json()["detail"] == "plan_no_incluye_funcionalidad"
    assert respuesta.json()["funcionalidad"] == "reportes_ia"


def test_sin_permiso_reportes_ver_da_403_y_sin_token_401(client_por_peticion, mundo_ia, db_session):
    cajero = personal_de(db_session, mundo_ia.a.id, "cajero", "cajero@tienda-a.example.com", mundo_ia.datos_a["sucursales"]["centro"])
    cliente = personal_de(db_session, mundo_ia.a.id, "cliente", "cliente@tienda-a.example.com")

    assert exportar(client_por_peticion, cajero, solicitud=VENTAS_POR_SUCURSAL).status_code == 403
    assert exportar(client_por_peticion, cliente, solicitud=VENTAS_POR_SUCURSAL).status_code == 403
    sin_token = client_por_peticion.post(f"{API}/exportar", json={"formato": "xlsx", "solicitud": VENTAS_POR_SUCURSAL})
    assert sin_token.status_code == 401


def test_la_suscripcion_vencida_da_403_suscripcion_no_activa(client_por_peticion, mundo_ia, db_session):
    ayer = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    db_session.execute(
        sin_filtro(
            update(Suscripcion)
            .where(Suscripcion.empresa_id == mundo_ia.a.id)
            .values(fecha_inicio=ayer - dt.timedelta(days=30), fecha_vencimiento=ayer)
        ),
        execution_options={"synchronize_session": False},
    )
    db_session.commit()

    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, solicitud=VENTAS_POR_SUCURSAL)

    assert respuesta.status_code == 403 and respuesta.json()["detail"] == "suscripcion_no_activa"


# ---- Aislamiento y alcance --------------------------------------------------------------------


@pytest.mark.parametrize("formato", ["xlsx", "pdf"])
def test_el_archivo_de_a_no_trae_nada_de_b(client_por_peticion, mundo_ia, formato):
    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, formato, solicitud=VENTAS_POR_SUCURSAL)

    contenido = " ".join(map(str, celdas_xlsx(respuesta))) if formato == "xlsx" else texto_pdf(respuesta)
    assert "tienda-b" not in contenido
    assert "1170" not in contenido and "1.170,00" not in contenido  # Norte de B (m=3) vende 1170,00
    assert "390" in contenido


def test_los_ids_de_otra_empresa_en_la_resuelta_se_ignoran(client_por_peticion, mundo_ia):
    de_b = ejecutar(client_por_peticion, mundo_ia.b.headers, solicitud=VENTAS_POR_SUCURSAL).json()["solicitud"]
    de_b["sucursales"] = [{"id": s_id, "nombre": "Norte"} for s_id in mundo_ia.datos_b["sucursales"].values()][:1]

    celdas = celdas_xlsx(exportar(client_por_peticion, mundo_ia.a.headers, resuelta=de_b))

    assert 390.0 in celdas and 1170.0 not in celdas  # resolvió "Norte" en la empresa de A


def test_un_encargado_solo_exporta_su_sucursal(client_por_peticion, mundo_ia, db_session):
    centro = mundo_ia.datos_a["sucursales"]["centro"]
    encargado = personal_de(db_session, mundo_ia.a.id, "encargado_sucursal", "enc@tienda-a.example.com", centro)

    respuesta = exportar(
        client_por_peticion, encargado, "pdf", solicitud={**VENTAS_POR_SUCURSAL, "sucursales": ["Norte"]}
    )

    texto = texto_pdf(respuesta)
    assert respuesta.status_code == 200
    assert "Centro" in texto and "Norte" not in texto
    assert "Solo se muestran datos de tu sucursal." in texto


# ---- Límites, disco, tasa, CORS y bitácora ----------------------------------------------------


def test_un_reporte_mas_largo_que_el_tope_sale_recortado_con_aviso(client_por_peticion, mundo_ia, monkeypatch):
    monkeypatch.setitem(cu23.MAX_FILAS, "xlsx", 3)

    respuesta = exportar(
        client_por_peticion,
        mundo_ia.a.headers,
        solicitud={"tipo_reporte": "ventas_por_periodo", "periodo": {"tipo": "este_mes"}, "agrupacion": "dia"},
    )

    celdas = celdas_xlsx(respuesta)
    assert respuesta.status_code == 200
    assert any(isinstance(c, str) and c.startswith("Se muestran las primeras 3 filas") for c in celdas)
    assert not any(c == 740.0 for c in celdas)  # recortado: no se imprime un total que sería de otra cosa


def test_no_escribe_nada_en_disco(client_por_peticion, mundo_ia, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    abrir = builtins.open

    def vigilado(archivo, modo="r", *args, **kwargs):
        if isinstance(modo, str) and any(letra in modo for letra in "wax+"):
            raise AssertionError(f"Se intentó abrir {archivo!r} para escribir en {modo!r}")
        return abrir(archivo, modo, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", vigilado)

    for formato in ("xlsx", "pdf"):
        assert exportar(client_por_peticion, mundo_ia.a.headers, formato, solicitud=VENTAS_POR_SUCURSAL).status_code == 200

    assert list(tmp_path.iterdir()) == []


def test_la_peticion_11_en_un_minuto_da_429(client_por_peticion, mundo_ia):
    estados = [
        exportar(client_por_peticion, mundo_ia.a.headers, solicitud={"tipo_reporte": None}).status_code
        for _ in range(11)
    ]

    assert estados[:10] == [422] * 10 and estados[10] == 429


def test_cors_expone_content_disposition(client_por_peticion, mundo_ia):
    origen = get_settings().cors_origins_list[0]

    respuesta = client_por_peticion.post(
        f"{API}/exportar",
        json={"formato": "xlsx", "solicitud": VENTAS_POR_SUCURSAL},
        headers={**mundo_ia.a.headers, "Origin": origen},
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["access-control-allow-origin"] == origen
    expuestas = respuesta.headers["access-control-expose-headers"].lower()
    assert "content-disposition" in expuestas and "etag" in expuestas


def test_deja_una_fila_de_bitacora_sin_el_texto_del_usuario(client_por_peticion, mundo_ia, db_session, interprete_falso):
    interprete_falso(VENTAS_POR_SUCURSAL)

    exportar(client_por_peticion, mundo_ia.a.headers, "pdf", texto="marcador-privado-9x ventas de este mes")

    filas = db_session.scalars(
        select(Bitacora).where(Bitacora.entidad == "reporte_ia", Bitacora.accion == "exportar")
    ).all()
    assert len(filas) == 1 and filas[0].empresa_id == mundo_ia.a.id
    datos = filas[0].datos
    assert datos["tipo_reporte"] == "ventas_por_sucursal" and datos["formato"] == "pdf"
    assert datos["filas"] == 2 and datos["truncado"] is False and datos["bytes"] > 500
    assert "marcador-privado-9x" not in str(datos)


def test_un_reporte_rechazado_no_deja_fila_de_exportar(client_por_peticion, mundo_ia, db_session):
    exportar(client_por_peticion, mundo_ia.a.headers, solicitud={"tipo_reporte": "usuarios"})

    assert db_session.scalars(select(Bitacora).where(Bitacora.accion == "exportar")).all() == []
