"""E10 — Pruebas del constructor de PDF (`exportacion_pdf.construir_pdf`).

El PDF se lee con pypdf (solo en pruebas). Los documentos de ejemplo salen de `ayudas_exportacion`."""

import builtins
import datetime as dt
import tempfile
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.inteligencia.exportacion_pdf import construir_pdf
from app.inteligencia.schemas import ColumnaReporte, GraficoSugerido
from tests.inteligencia.ayudas_exportacion import COLUMNAS_VENTAS, GENERADO_EN, documento, fila_ventas


def leer(pdf: bytes) -> PdfReader:
    return PdfReader(BytesIO(pdf))


def paginas(pdf: bytes) -> list[str]:
    return [p.extract_text() for p in leer(pdf).pages]


def texto(pdf: bytes) -> str:
    return "\n".join(paginas(pdf))


def lineas(pdf: bytes) -> set[str]:
    return {linea.strip() for linea in texto(pdf).splitlines()}


def con_titulo_de_seccion(doc, titulo: str = "Seccion Alfa"):
    """El título de la sección distinto del del documento, para contar cuántas veces se imprime."""
    doc.titulo = "Informe general"
    doc.secciones[0].titulo = titulo
    return doc


# ---- Estructura básica ----------------------------------------------------------------------


def test_pdf_valido_con_inicio_y_cierre():
    pdf = construir_pdf(documento(3))
    assert pdf.startswith(b"%PDF-")
    assert b"%%EOF" in pdf[-32:]
    assert len(leer(pdf).pages) >= 1


def test_encabezado_y_valores_formateados():
    doc = documento(3, empresa="Boutique Andina", totales={"transacciones": 9, "total_ventas": 3753.0})
    contenido = texto(construir_pdf(doc))
    assert "Ventas por sucursal" in contenido
    assert "Boutique Andina" in contenido
    assert "Generado: 20/09/2026 14:05 (hora de Bolivia)" in contenido
    assert "Periodo: 01/09/2026 al 20/09/2026" in contenido
    assert "Sucursales: todas" in contenido
    assert "Entre el 01/09/2026 y el 20/09/2026" in contenido  # subtítulo
    assert "1.250,50" in contenido
    assert "Sucursal 000" in contenido
    assert "Pagina 1 de" in contenido
    assert "FashionStore" in contenido


def test_fila_de_totales_formateada_segun_el_tipo():
    doc = documento(3, totales={"transacciones": 1234, "total_ventas": 9876.5})
    marcas = lineas(construir_pdf(doc))
    assert "Total" in marcas
    assert "1.234" in marcas
    assert "9.876,50" in marcas
    sin_totales = lineas(construir_pdf(documento(3)))
    assert "Total" not in sin_totales
    assert "9.876,50" not in sin_totales


def test_sin_subtitulo_ni_filtros():
    doc = documento(2, subtitulo=None, filtros=[])
    contenido = texto(construir_pdf(doc))
    assert "Generado:" in contenido
    assert "Entre el" not in contenido


def test_varias_secciones_y_avisos_al_final():
    doc = documento(2, avisos=["Se ignoró el filtro de categoría", "Solo tu sucursal"])
    segunda = documento(2, titulo="Segunda tabla").secciones[0]
    segunda.nota = "Nota de la segunda sección"
    doc.secciones.append(segunda)
    contenido = texto(construir_pdf(doc, incluir_grafico=False))
    assert "Segunda tabla" in contenido
    assert "Nota de la segunda sección" in contenido
    assert "- Se ignoró el filtro de categoría" in contenido
    assert "- Solo tu sucursal" in contenido
    assert contenido.index("Segunda tabla") < contenido.index("Se ignoró el filtro")


# ---- Paginación -----------------------------------------------------------------------------


def test_muchas_filas_repiten_encabezado_y_numeran_paginas():
    pdf = construir_pdf(documento(120), incluir_grafico=False)
    por_pagina = paginas(pdf)
    assert len(por_pagina) > 1
    assert all("Transacciones" in pagina for pagina in por_pagina)
    total = len(por_pagina)
    contenido = "\n".join(por_pagina)
    assert "Pagina 1 de " + str(total) in contenido
    assert "Pagina 2 de " + str(total) in contenido
    assert f"Pagina {total} de {total}" in contenido


def test_mas_de_6_columnas_va_horizontal_y_6_o_menos_vertical():
    seis = leer(construir_pdf(documento(3))).pages[0].mediabox
    assert len(COLUMNAS_VENTAS) == 6
    assert seis.width < seis.height
    siete_columnas = [*COLUMNAS_VENTAS, ColumnaReporte(clave="extra", titulo="Extra", tipo="texto")]
    siete = leer(construir_pdf(documento(3, columnas=siete_columnas))).pages[0].mediabox
    assert siete.width > siete.height


# ---- Formatos -------------------------------------------------------------------------------


def test_fecha_iso_date_y_datetime_se_muestran_dd_mm_aaaa():
    filas = [
        fila_ventas(0) | {"desde": "2026-09-01"},
        fila_ventas(1) | {"desde": dt.date(2026, 10, 2)},
        fila_ventas(2) | {"desde": dt.datetime(2026, 11, 3, 8, 30)},
        fila_ventas(3) | {"desde": "fecha rara"},
        fila_ventas(4) | {"desde": None},
    ]
    marcas = lineas(construir_pdf(documento(filas=filas), incluir_grafico=False))
    assert {"01/09/2026", "02/10/2026", "03/11/2026", "fecha rara"} <= marcas
    assert "2026-09-01" not in marcas


def test_porcentaje_con_una_decimal_y_coma():
    filas = [fila_ventas(0) | {"participacion": 12.5}, fila_ventas(1) | {"participacion": 7}]
    marcas = lineas(construir_pdf(documento(filas=filas), incluir_grafico=False))
    assert "12,5%" in marcas
    assert "7,0%" in marcas


def test_booleano_si_no_y_valores_vacios():
    filas = [fila_ventas(0) | {"activa": True}, fila_ventas(1) | {"activa": False, "transacciones": None}]
    marcas = lineas(construir_pdf(documento(filas=filas), incluir_grafico=False))
    assert "Sí" in marcas
    assert "No" in marcas
    assert "None" not in marcas


def test_moneda_entero_y_texto_no_numerico_se_imprime_tal_cual():
    filas = [fila_ventas(0) | {"total_ventas": "n/d", "transacciones": 1234567}]
    marcas = lineas(construir_pdf(documento(filas=filas), incluir_grafico=False))
    assert "n/d" in marcas
    assert "1.234.567" in marcas


# ---- Seguridad del texto --------------------------------------------------------------------


def test_marcado_en_los_datos_no_rompe_y_se_imprime_literal():
    nombre = "Polera <b>&</b> Co"
    doc = documento(filas=[fila_ventas(0, nombre)], titulo="Ventas <i>& más</i>", empresa="A&B <u>SRL</u>",
                    filtros=["Sucursal: <Centro> & Norte"], subtitulo="<para>texto</para>", avisos=["Aviso <b>&"])
    contenido = texto(construir_pdf(doc))
    for esperado in (nombre, "Ventas <i>& más</i>", "A&B <u>SRL</u>", "Sucursal: <Centro> & Norte", "<para>texto</para>", "Aviso <b>&"):
        assert esperado in contenido


def test_emoji_sale_como_signo_de_pregunta_y_no_rompe():
    doc = documento(filas=[fila_ventas(0, "Camisa \U0001F600 azul")], titulo="Ventas \U0001F680")
    contenido = texto(construir_pdf(doc))
    assert "Camisa ? azul" in contenido
    assert "\U0001F600" not in contenido


def test_acentos_y_enie_se_conservan():
    doc = documento(filas=[fila_ventas(0, "Peña Ñandú Úrsula")], filtros=["Categoría: Camisería"])
    contenido = texto(construir_pdf(doc))
    assert "Peña Ñandú Úrsula" in contenido
    assert "Categoría: Camisería" in contenido
    assert "Participación" in contenido


def test_controles_y_celdas_enormes_no_rompen():
    gigante = "x" * 5000
    doc = documento(filas=[fila_ventas(0, "Linea\x00uno\x07 dos\nTres"), fila_ventas(1, gigante)])
    contenido = texto(construir_pdf(doc, incluir_grafico=False))
    assert "Lineauno dos Tres" in contenido or "Lineauno dos" in contenido
    equis = contenido.count("x")
    assert 100 < equis < 700  # la celda se recorta (con "...") en vez de desbordar la página
    assert "..." in contenido


# ---- Truncado -------------------------------------------------------------------------------


def test_max_filas_bajo_recorta_y_avisa():
    pdf = construir_pdf(documento(8), incluir_grafico=False, max_filas=5)
    contenido = texto(pdf)
    assert "Se muestran las primeras 5 filas" in contenido
    assert "Sucursal 004" in contenido
    assert "Sucursal 005" not in contenido


def test_mas_de_mil_filas_se_recortan_a_mil_con_aviso():
    pdf = construir_pdf(documento(1001), incluir_grafico=False)
    contenido = texto(pdf)
    assert "Se muestran las primeras 1.000 filas" in contenido
    assert "Sucursal 999" in contenido
    assert "Sucursal 1000" not in contenido


def test_documento_truncado_lleva_la_nota_aunque_quepan_las_filas():
    contenido = texto(construir_pdf(documento(3, truncado=True), incluir_grafico=False))
    assert "Se muestran las primeras 3 filas" in contenido
    assert "Se muestran las primeras" not in texto(construir_pdf(documento(3), incluir_grafico=False))


def test_500_filas_pesan_menos_de_un_mega():
    pdf = construir_pdf(documento(500, totales={"total_ventas": 1.0}))
    assert len(pdf) < 1_000_000


# ---- Tabla vacía ----------------------------------------------------------------------------


def test_tabla_vacia_dice_sin_datos_y_no_dibuja_totales_ni_grafico():
    doc = con_titulo_de_seccion(documento(0, totales={"total_ventas": 777.0}))
    pdf = construir_pdf(doc)
    contenido = texto(pdf)
    assert "Sin datos" in contenido
    assert "Sucursal" in contenido  # el encabezado
    assert "777,00" not in contenido
    assert contenido.count("Seccion Alfa") == 1  # sin gráfico


# ---- Gráficos -------------------------------------------------------------------------------


def doc_agrupado(n_periodos: int):
    columnas = [
        ColumnaReporte(clave="periodo", titulo="Periodo", tipo="texto"),
        ColumnaReporte(clave="sucursal", titulo="Sucursal", tipo="texto"),
        ColumnaReporte(clave="total", titulo="Total (Bs)", tipo="moneda"),
    ]
    filas = [
        {"periodo": f"2026-{m:02d}", "sucursal": suc, "total": 100.0 * (m + k)}
        for m in range(1, n_periodos + 1)
        for k, suc in enumerate(("Centro", "Norte"))
    ]
    grafico = GraficoSugerido(tipo="barras_agrupadas", eje_x="periodo", eje_y="total", serie="sucursal")
    return con_titulo_de_seccion(documento(columnas=columnas, filas=filas, grafico=grafico))


def doc_con_grafico(tipo: str, n: int = 6):
    grafico = GraficoSugerido(tipo=tipo, eje_x="sucursal", eje_y="total_ventas")
    return con_titulo_de_seccion(documento(n, grafico=grafico))


@pytest.mark.parametrize("tipo", ["barras", "barras_horizontales", "linea", "torta", "barras_agrupadas"])
def test_cada_tipo_de_grafico_genera_pdf_valido_con_su_titulo(tipo):
    doc = doc_agrupado(4) if tipo == "barras_agrupadas" else doc_con_grafico(tipo)
    pdf = construir_pdf(doc)
    assert pdf.startswith(b"%PDF-")
    contenido = texto(pdf)
    assert contenido.count("Seccion Alfa") == 2  # título de la sección y del gráfico


@pytest.mark.parametrize("tipo", ["barras", "barras_horizontales", "linea", "torta", "barras_agrupadas"])
def test_sin_grafico_el_pdf_no_dibuja_el_titulo_del_grafico_y_pesa_menos(tipo):
    doc = doc_agrupado(4) if tipo == "barras_agrupadas" else doc_con_grafico(tipo)
    con = construir_pdf(doc)
    sin = construir_pdf(doc, incluir_grafico=False)
    assert texto(sin).count("Seccion Alfa") == 1
    assert len(sin) < len(con)


def test_grafico_tabla_o_ausente_no_dibuja_nada():
    for grafico in (GraficoSugerido(tipo="tabla"), None):
        doc = con_titulo_de_seccion(documento(5, grafico=grafico))
        assert texto(construir_pdf(doc)).count("Seccion Alfa") == 1


def test_grafico_con_ejes_inexistentes_se_omite():
    grafico = GraficoSugerido(tipo="barras", eje_x="no_existe", eje_y="total_ventas")
    doc = con_titulo_de_seccion(documento(5, grafico=grafico))
    assert texto(construir_pdf(doc)).count("Seccion Alfa") == 1


def test_barras_con_mas_de_12_categorias_agrupan_en_otros_y_lo_dicen():
    contenido = texto(construir_pdf(doc_con_grafico("barras", n=20)))
    assert "Otros" in contenido
    assert "Se agruparon las categorías menores en Otros" in contenido


def test_agrupadas_con_mas_de_12_periodos_dibuja_los_ultimos_12_y_lo_dice():
    contenido = texto(construir_pdf(doc_agrupado(14)))
    assert "Se muestran los últimos 12 periodos" in contenido


def test_agrupadas_con_pocos_periodos_no_lleva_nota_y_tiene_leyenda():
    contenido = texto(construir_pdf(doc_agrupado(4)))
    assert "Se muestran los últimos" not in contenido
    assert "Centro" in contenido and "Norte" in contenido


def test_linea_con_muchos_puntos_y_una_sola_fila_no_rompe():
    assert construir_pdf(doc_con_grafico("linea", n=250)).startswith(b"%PDF-")
    assert construir_pdf(doc_con_grafico("linea", n=1)).startswith(b"%PDF-")
    assert construir_pdf(doc_con_grafico("torta", n=1)).startswith(b"%PDF-")


def test_grafico_con_valores_negativos_o_ceros_no_rompe():
    filas = [fila_ventas(i, total=valor) for i, valor in enumerate([-50.0, 0.0, 30.0, 0.0])]
    for tipo in ("barras", "barras_horizontales", "linea", "torta"):
        grafico = GraficoSugerido(tipo=tipo, eje_x="sucursal", eje_y="total_ventas")
        assert construir_pdf(documento(filas=filas, grafico=grafico)).startswith(b"%PDF-")
    todos_ceros = [fila_ventas(i, total=0.0) for i in range(3)]
    assert construir_pdf(documento(filas=todos_ceros, grafico=GraficoSugerido(tipo="torta", eje_x="sucursal", eje_y="total_ventas")))


# ---- Metadatos y memoria --------------------------------------------------------------------


def test_metadatos_del_pdf():
    meta = leer(construir_pdf(documento(3, titulo="Ventas por sucursal"))).metadata
    assert meta.title == "Ventas por sucursal"
    assert meta.author == "FashionStore"
    assert meta.creator == "FashionStore"
    assert meta.subject


def test_no_escribe_en_disco(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    abrir_real = builtins.open

    def abrir_guardado(archivo, modo="r", *args, **kwargs):
        if isinstance(modo, str) and any(letra in modo for letra in "wax+"):
            raise AssertionError(f"se intentó abrir {archivo!r} para escribir")
        return abrir_real(archivo, modo, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", abrir_guardado)
    doc = doc_con_grafico("barras", n=40)
    doc.secciones[0].totales = {"total_ventas": 1.0}
    pdf = construir_pdf(doc)
    monkeypatch.undo()
    assert pdf.startswith(b"%PDF-")
    assert list(tmp_path.iterdir()) == []


def test_no_modifica_el_documento_de_entrada():
    doc = documento(30)
    antes = doc.model_dump()
    construir_pdf(doc, max_filas=10)
    assert doc.model_dump() == antes
    assert doc.generado_en == GENERADO_EN
