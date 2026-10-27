"""E10 — Constructor de PDF con reportlab.

Recibe un DocumentoReporte y devuelve los bytes del PDF; todo en memoria (BytesIO), nada se escribe
en disco. Decisiones de formato:

- A4 vertical; A4 horizontal si alguna sección tiene más de 6 columnas (el documento entero usa
  una sola orientación).
- Encabezado: título, empresa, fecha de generación, una línea por filtro y el subtítulo. Pie con
  "FashionStore" y "Pagina X de Y" (canvas de dos pasadas, para conocer el total).
- Cada sección: título, tabla con encabezado repetido en cada página, fila de totales opcional,
  nota de truncado y gráfico vectorial opcional. Los avisos del documento (`doc.avisos`) se
  imprimen al FINAL del documento, uno por línea con guion ("- ").
- Sin `keepWithNext` en el título de la sección: reportlab lo agrupa con la tabla y, si la tabla es
  más larga que una página, la manda entera a la página siguiente dejando la primera vacía. En su
  lugar, `CondPageBreak` evita un título huérfano al pie de la página.
- Seguridad del texto: todo texto que viene de datos pasa por `_seguro` (control fuera, escape de
  marcado XML, cp1252). Un "<b>" en un nombre de producto se imprime literal.
- Fuentes estándar (Helvetica): no se incrusta nada ni se descarga ninguna imagen.
"""

import datetime as dt
import math
import re
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import CondPageBreak, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.inteligencia.exportacion_comun import (
    COLOR_ACENTO,
    COLOR_BORDE,
    COLOR_ENCABEZADO,
    COLOR_FILA_ALTERNA,
    COLOR_TEXTO_ENCABEZADO,
    COLOR_TEXTO_TENUE,
    EXPORTACION_MAX_FILAS_PDF,
    MAX_PERIODOS_AGRUPADAS,
    PALETA_SERIES,
    DatosGrafico,
    a_decimal,
    datos_de_grafico,
    texto_de_generacion,
)
from app.inteligencia.politicas import formato_fecha, formato_numero
from app.inteligencia.schemas import ColumnaReporte, DocumentoReporte, SeccionReporte

MARGEN = 1.5 * cm
MARGEN_INFERIOR = 2.0 * cm  # deja sitio al pie de página
MAX_COLUMNAS_VERTICAL = 6
MAX_CARACTERES_CELDA = 600  # una celda gigante no cabría en una página y rompería el diseño
TEXTO_SIN_DATOS = "Sin datos"
ALTO_GRAFICO = 240

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_BLANCOS = re.compile(r"[\t\n\r]+")

_TIPOS_NUMERICOS = ("entero", "moneda", "porcentaje")


def _color(hex_sin_almohadilla: str) -> colors.Color:
    return colors.HexColor("#" + hex_sin_almohadilla)


# ---- Texto seguro ---------------------------------------------------------------------------


def _limpiar(texto) -> str:
    """Texto plano apto para Helvetica: sin caracteres de control y solo con lo que cabe en cp1252
    (lo demás, como un emoji, sale como "?")."""
    texto = _BLANCOS.sub(" ", "" if texto is None else str(texto))
    texto = _CONTROL.sub("", texto)
    return texto.encode("cp1252", "replace").decode("cp1252")


def _seguro(texto) -> str:
    """Texto listo para un Paragraph: el marcado ("<", ">", "&") se escapa y se limpia a cp1252."""
    return _limpiar(escape(_BLANCOS.sub(" ", "" if texto is None else str(texto))))


def _recortar(texto: str, largo: int) -> str:
    return texto if len(texto) <= largo else texto[: largo - 3] + "..."


# ---- Formato de valores ---------------------------------------------------------------------


def _como_fecha(valor) -> dt.date | None:
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    if isinstance(valor, str):
        try:
            return dt.date.fromisoformat(valor.strip()[:10])
        except ValueError:
            return None
    return None


def _formatear(valor, tipo: str) -> str:
    """El valor ya redactado para mostrar. Si no tiene la forma del tipo, se imprime tal cual."""
    if valor is None:
        return ""
    if tipo in ("moneda", "entero", "porcentaje"):
        numero = a_decimal(valor)
        if numero is None or not numero.is_finite():
            return str(valor)
        if tipo == "moneda":
            return formato_numero(numero, 2)
        if tipo == "entero":
            return formato_numero(numero, 0)
        return formato_numero(numero, 1) + "%"
    if tipo == "fecha":
        fecha = _como_fecha(valor)
        return formato_fecha(fecha) if fecha is not None else str(valor)
    if tipo == "booleano":
        if isinstance(valor, bool):
            return "Sí" if valor else "No"
        return str(valor)
    return str(valor)


# ---- Estilos --------------------------------------------------------------------------------


def _estilos() -> dict[str, ParagraphStyle]:
    tenue = _color(COLOR_TEXTO_TENUE)

    def estilo(nombre, **kw):
        return ParagraphStyle(nombre, fontName=kw.pop("fontName", "Helvetica"), **kw)

    return {
        "titulo": estilo("titulo", fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=2),
        "empresa": estilo("empresa", fontSize=10, leading=13),
        "tenue": estilo("tenue", fontSize=8.5, leading=11, textColor=tenue),
        "subtitulo": estilo("subtitulo", fontSize=9, leading=12, textColor=tenue, spaceBefore=4),
        "seccion": estilo("seccion", fontName="Helvetica-Bold", fontSize=12, leading=15, spaceBefore=10, spaceAfter=5),
        "celda": estilo("celda", fontSize=8, leading=10, alignment=TA_LEFT),
        "celda_der": estilo("celda_der", fontSize=8, leading=10, alignment=TA_RIGHT),
        "celda_cen": estilo("celda_cen", fontSize=8, leading=10, alignment=TA_CENTER),
        "encab": estilo("encab", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=_color(COLOR_TEXTO_ENCABEZADO)),
        "encab_der": estilo("encab_der", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=_color(COLOR_TEXTO_ENCABEZADO), alignment=TA_RIGHT),
        "encab_cen": estilo("encab_cen", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=_color(COLOR_TEXTO_ENCABEZADO), alignment=TA_CENTER),
        "total": estilo("total", fontName="Helvetica-Bold", fontSize=8, leading=10, alignment=TA_LEFT),
        "total_der": estilo("total_der", fontName="Helvetica-Bold", fontSize=8, leading=10, alignment=TA_RIGHT),
        "total_cen": estilo("total_cen", fontName="Helvetica-Bold", fontSize=8, leading=10, alignment=TA_CENTER),
        "nota": estilo("nota", fontSize=7.5, leading=10, textColor=tenue, spaceBefore=3),
        "aviso": estilo("aviso", fontSize=8, leading=10.5, textColor=tenue, leftIndent=10, firstLineIndent=-8, spaceBefore=1),
    }


def _sufijo(tipo: str) -> str:
    """Alineación según el tipo: números a la derecha, fecha y booleano centrados, texto a la izquierda."""
    if tipo in _TIPOS_NUMERICOS:
        return "_der"
    if tipo in ("fecha", "booleano"):
        return "_cen"
    return ""


# ---- Pie de página con "Pagina X de Y" ------------------------------------------------------


class NumeradorPaginas(canvas.Canvas):
    """Canvas de dos pasadas: guarda cada página y, al cerrar, dibuja el pie con el total conocido."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estados: list[dict] = []

    def showPage(self):  # noqa: N802 (nombre de reportlab)
        self._estados.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._estados)
        for estado in self._estados:
            self.__dict__.update(estado)
            self._dibujar_pie(total)
            super().showPage()
        super().save()

    def _dibujar_pie(self, total: int) -> None:
        ancho, _ = self._pagesize
        y = MARGEN_INFERIOR - 0.9 * cm
        self.saveState()
        self.setStrokeColor(_color(COLOR_BORDE))
        self.setLineWidth(0.5)
        self.line(MARGEN, y + 0.35 * cm, ancho - MARGEN, y + 0.35 * cm)
        self.setFillColor(_color(COLOR_TEXTO_TENUE))
        self.setFont("Helvetica", 8)
        self.drawString(MARGEN, y, "FashionStore")
        self.drawRightString(ancho - MARGEN, y, f"Pagina {self._pageNumber} de {total}")
        self.restoreState()


# ---- Tabla ----------------------------------------------------------------------------------


def _anchos(columnas: list[ColumnaReporte], formateadas: list[list[str]], disponible: float) -> list[float]:
    """Reparte el ancho útil: cada columna pide lo que mide su contenido (con tope); las de texto
    reciben más holgura y ninguna baja de lo que mide su palabra más larga del encabezado."""
    pesos: list[float] = []
    minimos: list[float] = []
    for i, columna in enumerate(columnas):
        contenido = max((len(fila[i]) for fila in formateadas), default=0)
        palabra_encabezado = max((len(p) for p in columna.titulo.split()), default=4)
        titulo_corrido = min(len(columna.titulo), 24) * 0.6  # que un título corto no se parta en 3 líneas
        ideal = max(min(contenido, 40), palabra_encabezado, titulo_corrido, 4) + 2
        pesos.append(ideal * (1.6 if columna.tipo == "texto" else 1.0))
        minimos.append(
            max(stringWidth(p, "Helvetica-Bold", 8) for p in (columna.titulo.split() or ["x"])) + 10
        )
    anchos = [0.0] * len(columnas)
    libres = set(range(len(columnas)))
    restante = disponible
    while libres:
        suma = sum(pesos[i] for i in libres)
        fijados = [i for i in libres if restante * pesos[i] / suma < minimos[i]]
        if not fijados:
            for i in libres:
                anchos[i] = restante * pesos[i] / suma
            break
        for i in fijados:
            anchos[i] = minimos[i]
            restante -= minimos[i]
            libres.discard(i)
        if restante <= 0:  # no cabe ni el mínimo: se reparte proporcional
            total = sum(minimos)
            return [disponible * m / total for m in minimos]
    return anchos


def _tabla(seccion: SeccionReporte, filas: list[dict], disponible: float, estilos: dict) -> Table | None:
    columnas = seccion.columnas
    if not columnas:
        return None
    n = len(columnas)

    formateadas = [
        [_recortar(_formatear(fila.get(c.clave), c.tipo), MAX_CARACTERES_CELDA) for c in columnas] for fila in filas
    ]
    textos_totales: list[str] | None = None
    if seccion.totales is not None and filas:
        textos_totales = [
            _formatear(seccion.totales.get(c.clave), c.tipo) if c.clave in seccion.totales else "" for c in columnas
        ]
        textos_totales[0] = "Total"

    para = lambda texto, estilo: Paragraph(_seguro(texto), estilos[estilo])  # noqa: E731
    datos: list[list] = [[para(c.titulo, "encab" + _sufijo(c.tipo)) for c in columnas]]
    if filas:
        for textos in formateadas:
            datos.append([para(t, "celda" + _sufijo(c.tipo)) for t, c in zip(textos, columnas)])
        if textos_totales is not None:
            datos.append([para(t, "total" + _sufijo(c.tipo)) for t, c in zip(textos_totales, columnas)])
    else:
        datos.append([para(TEXTO_SIN_DATOS, "celda_cen")] + [""] * (n - 1))

    cuerpo = formateadas + ([textos_totales] if textos_totales is not None else [])
    anchos = _anchos(columnas, cuerpo, disponible)
    tabla = Table(datos, colWidths=anchos, repeatRows=1)
    reglas = [
        ("BACKGROUND", (0, 0), (-1, 0), _color(COLOR_ENCABEZADO)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _color(COLOR_BORDE)),
        ("BOX", (0, 0), (-1, -1), 0.25, _color(COLOR_BORDE)),
    ]
    if filas:
        reglas.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _color(COLOR_FILA_ALTERNA)]))
        if textos_totales is not None:
            reglas.append(("LINEABOVE", (0, -1), (-1, -1), 1.2, _color(COLOR_ENCABEZADO)))
    else:
        reglas.append(("SPAN", (0, 1), (-1, 1)))
    tabla.setStyle(TableStyle(reglas))
    return tabla


# ---- Gráfico vectorial ----------------------------------------------------------------------


def _etiqueta(texto: str, largo: int) -> str:
    return _recortar(_limpiar(texto), largo)


def _formato_eje(maximo: float):
    decimales = 0 if maximo >= 100 else 2
    return lambda valor: formato_numero(valor, decimales)


def _ejes_valores(eje, valores: list[float], desde_cero: bool) -> None:
    eje.labels.fontName = "Helvetica"
    eje.labels.fontSize = 7
    eje.labelTextFormat = _formato_eje(max((abs(v) for v in valores), default=0))
    eje.visibleGrid = 1
    eje.gridStrokeColor = _color(COLOR_BORDE)
    eje.gridStrokeWidth = 0.5
    eje.strokeColor = _color(COLOR_BORDE)
    if desde_cero:
        eje.valueMin = min(0, min(valores))
        if max(valores) <= 0:
            eje.valueMax = 0


def _color_serie(indice: int, total: int) -> colors.Color:
    if total == 1:
        return _color(COLOR_ACENTO)
    return _color(PALETA_SERIES[indice % len(PALETA_SERIES)])


def _leyenda(dibujo: Drawing, pares: list[tuple], x: float, y: float, columnas: int = 1) -> None:
    leyenda = Legend()
    leyenda.x, leyenda.y = x, y
    leyenda.fontName = "Helvetica"
    leyenda.fontSize = 7.5
    leyenda.alignment = "right"
    leyenda.dxTextSpace = 5
    leyenda.deltay = 11
    leyenda.deltax = 120
    leyenda.columnMaximum = max(1, math.ceil(len(pares) / columnas))
    leyenda.colorNamePairs = pares
    dibujo.add(leyenda)


def _grafico(datos: DatosGrafico, titulo: str, ancho: float) -> Drawing:
    alto = ALTO_GRAFICO
    dibujo = Drawing(ancho, alto)
    dibujo.add(String(0, alto - 12, _etiqueta(titulo, 90), fontName="Helvetica-Bold", fontSize=10, fillColor=_color(COLOR_ENCABEZADO)))
    n = len(datos.categorias)
    nombres = list(datos.series)
    valores = [list(datos.series[nombre]) for nombre in nombres]
    todos = [v for serie in valores for v in serie]

    if datos.tipo == "torta":
        positivos = [max(v, 0.0) for v in valores[0]]
        total = sum(positivos)
        lado = alto - 60
        torta = Pie()
        torta.x, torta.y, torta.width, torta.height = 30, 20, lado, lado
        torta.data = positivos if total > 0 else [1.0] * n
        torta.labels = None
        torta.sideLabels = 0
        torta.slices.strokeColor = colors.white
        torta.slices.strokeWidth = 0.75
        pares = []
        for i, categoria in enumerate(datos.categorias):
            color = _color(PALETA_SERIES[i % len(PALETA_SERIES)])
            torta.slices[i].fillColor = color
            porcentaje = positivos[i] / total * 100 if total > 0 else 0.0
            pares.append((color, f"{_etiqueta(categoria, 28)} ({formato_numero(porcentaje, 1)}%)"))
        dibujo.add(torta)
        _leyenda(dibujo, pares, 30 + lado + 30, alto - 40)
        return dibujo

    agrupadas = datos.tipo == "barras_agrupadas"
    reserva_derecha = 10.0
    if agrupadas:
        reserva_derecha = 140.0
    etiquetas = [_etiqueta(c, 16) for c in datos.categorias]

    if datos.tipo == "barras_horizontales":
        izquierda = min(max((len(e) for e in etiquetas), default=1), 24) * 4.2 + 12
        grafico = HorizontalBarChart()
        grafico.x, grafico.y = izquierda, 24
        grafico.width, grafico.height = ancho - izquierda - reserva_derecha - 15, alto - 24 - 30
        grafico.categoryAxis.categoryNames = [_etiqueta(c, 24) for c in datos.categorias]
        grafico.categoryAxis.reverseDirection = 1
        grafico.categoryAxis.labels.boxAnchor = "e"
        grafico.categoryAxis.labels.dx = -3
        grafico.categoryAxis.labelAxisMode = "low"
    elif datos.tipo == "linea":
        grafico = HorizontalLineChart()
        grafico.x, grafico.y = 55, 55
        grafico.width, grafico.height = ancho - 55 - reserva_derecha - 15, alto - 55 - 30
        paso = max(1, math.ceil(n / 10))
        grafico.categoryAxis.categoryNames = [e if i % paso == 0 else "" for i, e in enumerate(etiquetas)]
        grafico.categoryAxis.labels.angle = 30
        grafico.categoryAxis.labels.boxAnchor = "ne"
        grafico.categoryAxis.labels.dy = -2
        grafico.categoryAxis.joinAxisMode = "bottom"
    else:  # barras y barras_agrupadas
        grafico = VerticalBarChart()
        grafico.x, grafico.y = 55, 55
        grafico.width, grafico.height = ancho - 55 - reserva_derecha - 15, alto - 55 - 30
        grafico.categoryAxis.categoryNames = etiquetas
        if n > 5 or max((len(e) for e in etiquetas), default=0) > 9:
            grafico.categoryAxis.labels.angle = 30
            grafico.categoryAxis.labels.boxAnchor = "ne"
            grafico.categoryAxis.labels.dy = -2
        grafico.categoryAxis.labelAxisMode = "low"
        if agrupadas:
            grafico.groupSpacing = 6
    grafico.data = [tuple(serie) for serie in valores]
    grafico.categoryAxis.labels.fontName = "Helvetica"
    grafico.categoryAxis.labels.fontSize = 7
    grafico.categoryAxis.strokeColor = _color(COLOR_BORDE)
    _ejes_valores(grafico.valueAxis, todos, desde_cero=datos.tipo != "linea")

    for i in range(len(valores)):
        color = _color_serie(i, len(valores))
        if datos.tipo == "linea":
            grafico.lines[i].strokeColor = color
            grafico.lines[i].strokeWidth = 1.8
            if n <= 40:
                grafico.lines[i].symbol = makeMarker("Circle")
                grafico.lines[i].symbol.fillColor = color
                grafico.lines[i].symbol.strokeColor = color
                grafico.lines[i].symbol.size = 4
        else:
            grafico.bars[i].fillColor = color
            grafico.bars[i].strokeColor = None
            grafico.bars[i].strokeWidth = 0
    dibujo.add(grafico)

    if agrupadas:
        pares = [(_color_serie(i, len(nombres)), _etiqueta(nombre or "(sin nombre)", 24)) for i, nombre in enumerate(nombres)]
        _leyenda(dibujo, pares, ancho - reserva_derecha - 5, alto - 40)
    return dibujo


def _nota_grafico(datos: DatosGrafico) -> str | None:
    if not datos.recortado:
        return None
    if datos.tipo == "barras_agrupadas":
        return f"Se muestran los últimos {MAX_PERIODOS_AGRUPADAS} periodos."
    return "Se agruparon las categorías menores en Otros."


# ---- Documento ------------------------------------------------------------------------------


def construir_pdf(
    doc: DocumentoReporte, incluir_grafico: bool = True, max_filas: int = EXPORTACION_MAX_FILAS_PDF
) -> bytes:
    """Los bytes del PDF del documento. `max_filas` limita las filas escritas por sección; si hay
    recorte (o `doc.truncado`) la sección lleva la nota "Se muestran las primeras N filas"."""
    max_filas = max(0, max_filas)
    estilos = _estilos()
    ancha = any(len(s.columnas) > MAX_COLUMNAS_VERTICAL for s in doc.secciones)
    tamano = landscape(A4) if ancha else A4
    disponible = tamano[0] - 2 * MARGEN

    historia: list = [
        Paragraph(_seguro(doc.titulo), estilos["titulo"]),
        Paragraph(_seguro(doc.empresa_nombre), estilos["empresa"]),
        Paragraph(_seguro("Generado: " + texto_de_generacion(doc.generado_en)), estilos["tenue"]),
    ]
    historia += [Paragraph(_seguro(filtro), estilos["tenue"]) for filtro in doc.filtros]
    if doc.subtitulo:
        historia.append(Paragraph(_seguro(doc.subtitulo), estilos["subtitulo"]))

    for seccion in doc.secciones:
        historia.append(CondPageBreak(4 * cm))
        historia.append(Paragraph(_seguro(seccion.titulo), estilos["seccion"]))
        filas = seccion.filas[:max_filas]
        tabla = _tabla(seccion, filas, disponible, estilos)
        if tabla is not None:
            historia.append(tabla)
        if doc.truncado or len(seccion.filas) > max_filas:
            texto_nota = f"Se muestran las primeras {formato_numero(len(filas), 0)} filas."
            historia.append(Paragraph(_seguro(texto_nota), estilos["nota"]))
        if seccion.nota:
            historia.append(Paragraph(_seguro(seccion.nota), estilos["nota"]))
        if incluir_grafico and filas:
            datos = datos_de_grafico(seccion.model_copy(update={"filas": filas}))
            if datos is not None:
                bloque: list = [Spacer(1, 8), _grafico(datos, seccion.titulo, disponible)]
                nota = _nota_grafico(datos)
                if nota:
                    bloque.append(Paragraph(_seguro(nota), estilos["nota"]))
                historia.append(KeepTogether(bloque))

    if doc.avisos:
        historia.append(Spacer(1, 10))
        historia.append(Paragraph("Avisos", estilos["seccion"]))
        historia += [Paragraph("- " + _seguro(aviso), estilos["aviso"]) for aviso in doc.avisos]

    salida = BytesIO()
    plantilla = SimpleDocTemplate(
        salida,
        pagesize=tamano,
        leftMargin=MARGEN,
        rightMargin=MARGEN,
        topMargin=MARGEN,
        bottomMargin=MARGEN_INFERIOR,
        title=_limpiar(doc.titulo),
        author="FashionStore",
        creator="FashionStore",
        subject=_limpiar(f"Reporte de {doc.empresa_nombre}"),
        pageCompression=1,
    )
    plantilla.build(historia, canvasmaker=NumeradorPaginas)
    return salida.getvalue()
