"""E10, paso 8: GET /api/v1/reportes/{ventas|inventario|reservas}/exportar. Son los reportes de CU-22 en
Excel o PDF; están en los dos planes (D07). Se usa `mundo_ia` (hoy = 20/09/2026; A vende 740,00 del 14 al
20 de septiembre) y se compara contra la respuesta JSON de la ruta de siempre."""

import re
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.comercial.repository import VW_VENTAS_DETALLE_V2_SQL
from app.inteligencia.casos_uso import cu22_consultar_reportes_indicadores as cu22
from app.inteligencia.politicas import ticket_promedio
from app.plataforma.models import Bitacora
from tests.inteligencia.ayudas_exportacion import celdas_xlsx, hojas_xlsx, personal_de, texto_pdf

API = "/api/v1/reportes"
RANGO = {"desde": "2026-09-14", "hasta": "2026-09-20"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(autouse=True)
def _sumas_decimales(monkeypatch):
    """SQLite (solo las pruebas) devuelve float en SUM(); PostgreSQL devuelve Decimal, que es lo que
    espera ticket_promedio(). Mismo parche que tests/inteligencia/test_reporte_voz.py."""
    monkeypatch.setattr(cu22, "ticket_promedio", lambda total, transacciones: ticket_promedio(Decimal(str(total)), transacciones))


def exportar(client, headers, reporte, formato="xlsx", **consulta):
    return client.get(f"{API}/{reporte}/exportar", params={"formato": formato, **consulta}, headers=headers)


# ---- Ventas -----------------------------------------------------------------------------------


def test_ventas_xlsx_trae_las_mismas_cifras_que_el_json(client_por_peticion, mundo_ia):
    json_ventas = client_por_peticion.get(f"{API}/ventas", params=RANGO, headers=mundo_ia.a.headers).json()

    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, "ventas", **RANGO)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"] == XLSX
    assert re.fullmatch(
        r'attachment; filename="reporte-ventas-tienda-a-\d{8}-\d{4}\.xlsx"', respuesta.headers["content-disposition"]
    )
    assert respuesta.headers["cache-control"] == "no-store"
    assert hojas_xlsx(respuesta) == [
        "Resumen", "Productos más vendidos", "Ventas por canal", "Ventas por sucursal", "Detalle de ventas",
        "Datos del grafico", "Datos del grafico 2", "Datos del grafico 3",
    ]
    celdas = celdas_xlsx(respuesta)
    assert "Reporte de ventas" in celdas and "tienda-a" in celdas
    assert "Periodo: 14/09/2026 al 20/09/2026" in celdas
    assert float(json_ventas["resumen"]["total_ventas"]) == 740.0 and 740.0 in celdas
    for fila in json_ventas["top_productos"]:
        assert fila["producto"] in celdas and float(fila["total_vendido"]) in celdas
    for fila in json_ventas["detalle"]:
        assert fila["codigo"] in celdas
    assert len(json_ventas["detalle"]) == 6


def test_ventas_pdf_es_horizontal_porque_el_detalle_tiene_muchas_columnas(client_por_peticion, mundo_ia):
    from io import BytesIO

    from pypdf import PdfReader

    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, "ventas", "pdf", **RANGO)

    assert respuesta.status_code == 200 and respuesta.headers["content-type"] == "application/pdf"
    assert respuesta.headers["content-disposition"].startswith('attachment; filename="reporte-ventas-tienda-a-')
    pagina = PdfReader(BytesIO(respuesta.content)).pages[0]
    assert pagina.mediabox.width > pagina.mediabox.height
    texto = texto_pdf(respuesta)
    assert "Reporte de ventas" in texto and "740,00" in texto and "Detalle de ventas" in texto


def test_los_filtros_de_ventas_se_aplican_y_se_escriben(client_por_peticion, mundo_ia):
    centro = mundo_ia.datos_a["sucursales"]["centro"]

    celdas = celdas_xlsx(
        exportar(client_por_peticion, mundo_ia.a.headers, "ventas", sucursal_id=centro, canal="presencial", **RANGO)
    )

    assert "Sucursal: Centro" in celdas and "Canal: presencial" in celdas and "Categoría: todas" in celdas
    assert 250.0 in celdas  # V1 (presencial, Centro); la V2 de Centro es digital
    assert 390.0 not in celdas and "Norte" not in celdas


def test_el_detalle_largo_se_recorta_con_una_nota_y_sin_total(client_por_peticion, mundo_ia, monkeypatch):
    monkeypatch.setitem(cu22.MAX_FILAS, "xlsx", 2)

    celdas = celdas_xlsx(exportar(client_por_peticion, mundo_ia.a.headers, "ventas", **RANGO))

    assert "Se muestran las primeras 2 de 6 filas." in celdas
    assert 740.0 in celdas  # el resumen y los totales de las tablas completas siguen ahí


def test_sin_ventas_en_el_periodo_el_archivo_igual_se_genera(client_por_peticion, mundo_ia):
    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, "ventas", desde="2026-01-01", hasta="2026-01-31")

    assert respuesta.status_code == 200
    celdas = celdas_xlsx(respuesta)
    assert "No hubo ventas con estos filtros." in celdas and "Sin datos" in celdas


# ---- Inventario y reservas --------------------------------------------------------------------


@pytest.mark.parametrize("formato", ["xlsx", "pdf"])
def test_inventario_se_exporta_con_las_cifras_del_json(client_por_peticion, mundo_ia, formato):
    json_inv = client_por_peticion.get(f"{API}/inventario", headers=mundo_ia.a.headers).json()
    fisico = sum(f["cantidad_fisica"] for f in json_inv["consolidado"])
    disponible = sum(f["cantidad_disponible"] for f in json_inv["consolidado"])

    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, "inventario", formato)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-disposition"].startswith('attachment; filename="reporte-inventario-tienda-a-')
    if formato == "xlsx":
        celdas = celdas_xlsx(respuesta)
        assert hojas_xlsx(respuesta)[:3] == ["Stock por variante", "Alertas de stock bajo el mínimo", "Valuación por sucursal"]
        assert fisico in celdas and disponible in celdas  # la fila de totales
        for fila in json_inv["consolidado"]:
            assert fila["sku"] in celdas
    else:
        texto = texto_pdf(respuesta)
        assert "Reporte de inventario" in texto and "Stock por variante" in texto
        assert all(f["sku"] in texto for f in json_inv["consolidado"])


@pytest.mark.parametrize("formato", ["xlsx", "pdf"])
def test_reservas_se_exporta_con_la_tasa_de_conversion(client_por_peticion, mundo_ia, formato):
    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, "reservas", formato, **RANGO)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-disposition"].startswith('attachment; filename="reporte-reservas-tienda-a-')
    contenido = " ".join(map(str, celdas_xlsx(respuesta))) if formato == "xlsx" else texto_pdf(respuesta)
    assert "Reporte de reservas" in contenido and "Tasa de conversión de reservas a ventas: 0,0%." in contenido


# ---- Plan, permiso, alcance y aislamiento -----------------------------------------------------


def test_el_plan_basico_si_puede_exportar_los_convencionales(client_por_peticion, dos_empresas, db_session):
    db_session.execute(text(VW_VENTAS_DETALLE_V2_SQL))
    db_session.commit()
    basico = dos_empresas.b.headers

    for reporte in ("ventas", "inventario", "reservas"):
        for formato in ("xlsx", "pdf"):
            assert exportar(client_por_peticion, basico, reporte, formato).status_code == 200, (reporte, formato)


@pytest.mark.parametrize("reporte", ["ventas", "inventario", "reservas"])
def test_sin_permiso_403_y_sin_token_401(client_por_peticion, mundo_ia, db_session, reporte):
    cajero = personal_de(db_session, mundo_ia.a.id, "cajero", f"cajero-{reporte}@tienda-a.example.com")

    assert exportar(client_por_peticion, cajero, reporte).status_code == 403
    assert client_por_peticion.get(f"{API}/{reporte}/exportar", params={"formato": "xlsx"}).status_code == 401


@pytest.mark.parametrize("reporte", ["ventas", "inventario", "reservas"])
def test_la_sucursal_de_otra_empresa_da_404(client_por_peticion, mundo_ia, reporte):
    de_b = mundo_ia.datos_b["sucursales"]["centro"]

    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, reporte, sucursal_id=de_b)

    assert respuesta.status_code == 404
    assert "content-disposition" not in respuesta.headers


def test_la_categoria_de_otra_empresa_da_404(client_por_peticion, mundo_ia):
    de_b = mundo_ia.datos_b["categorias"]["camisas"]

    assert exportar(client_por_peticion, mundo_ia.a.headers, "ventas", categoria_id=de_b, **RANGO).status_code == 404


@pytest.mark.parametrize("formato", ["xlsx", "pdf"])
def test_el_archivo_de_a_no_trae_nada_de_b(client_por_peticion, mundo_ia, formato):
    for reporte in ("ventas", "inventario", "reservas"):
        respuesta = exportar(client_por_peticion, mundo_ia.a.headers, reporte, formato, **RANGO)

        contenido = " ".join(map(str, celdas_xlsx(respuesta))) if formato == "xlsx" else texto_pdf(respuesta)
        assert "tienda-b" not in contenido, reporte
        assert "1170" not in contenido and "1.170,00" not in contenido, reporte  # Norte de B vende 1170,00


def test_un_encargado_solo_exporta_su_sucursal(client_por_peticion, mundo_ia, db_session):
    centro = mundo_ia.datos_a["sucursales"]["centro"]
    encargado = personal_de(db_session, mundo_ia.a.id, "encargado_sucursal", "enc@tienda-a.example.com", centro)
    norte = mundo_ia.datos_a["sucursales"]["norte"]

    celdas = celdas_xlsx(exportar(client_por_peticion, encargado, "ventas", **RANGO))  # sin pedir sucursal

    assert "Sucursal: Centro" in celdas and "Norte" not in celdas
    assert 350.0 in celdas and 390.0 not in celdas
    # Igual que la ruta JSON: pedir la sucursal de otro es 403, no se recorta en silencio.
    assert exportar(client_por_peticion, encargado, "ventas", sucursal_id=norte, **RANGO).status_code == 403
    assert client_por_peticion.get(f"{API}/ventas", params={**RANGO, "sucursal_id": norte}, headers=encargado).status_code == 403


# ---- Cuerpo de la consulta y bitácora ---------------------------------------------------------


@pytest.mark.parametrize("consulta", [{}, {"formato": "csv"}, {"formato": ""}])
def test_el_formato_es_obligatorio_y_solo_xlsx_o_pdf(client_por_peticion, mundo_ia, consulta):
    respuesta = client_por_peticion.get(f"{API}/ventas/exportar", params=consulta, headers=mundo_ia.a.headers)

    assert respuesta.status_code == 422


def test_un_rango_invertido_da_400_como_el_json(client_por_peticion, mundo_ia):
    respuesta = exportar(client_por_peticion, mundo_ia.a.headers, "ventas", desde="2026-09-20", hasta="2026-09-01")

    assert respuesta.status_code == 400


def test_la_peticion_11_en_un_minuto_da_429(client_por_peticion, mundo_ia):
    estados = [exportar(client_por_peticion, mundo_ia.a.headers, "reservas").status_code for _ in range(11)]

    assert estados[:10] == [200] * 10 and estados[10] == 429


def test_deja_una_fila_de_bitacora_por_descarga(client_por_peticion, mundo_ia, db_session):
    exportar(client_por_peticion, mundo_ia.a.headers, "ventas", "pdf", **RANGO)

    filas = db_session.scalars(select(Bitacora).where(Bitacora.entidad == "reporte", Bitacora.accion == "exportar")).all()
    assert len(filas) == 1 and filas[0].empresa_id == mundo_ia.a.id
    datos = filas[0].datos
    assert datos["tipo_reporte"] == "ventas" and datos["formato"] == "pdf" and datos["bytes"] > 500
    assert datos["periodo"] == {"desde": "2026-09-14", "hasta": "2026-09-20"}


def test_las_rutas_json_de_siempre_no_cambian(client_por_peticion, mundo_ia):
    for reporte in ("ventas", "inventario", "reservas", "dashboard"):
        respuesta = client_por_peticion.get(f"{API}/{reporte}", params=RANGO, headers=mundo_ia.a.headers)

        assert respuesta.status_code == 200 and respuesta.headers["content-type"] == "application/json"
