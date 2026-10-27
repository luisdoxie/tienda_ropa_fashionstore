"""E10 — Piezas compartidas por los constructores de Excel y de PDF.

Aquí no hay formato de archivo: solo constantes, los colores del diseño y la preparación de los
datos del gráfico (qué categorías y series se dibujan), para que ambos archivos muestren lo mismo.
Todo es puro: recibe un DocumentoReporte o una SeccionReporte, no toca la base ni el disco."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.inteligencia.schemas import SeccionReporte

# Topes de filas por archivo. El caso de uso consulta con este tope y marca `truncado`.
EXPORTACION_MAX_FILAS_XLSX = 5000
EXPORTACION_MAX_FILAS_PDF = 1000

# Un gráfico de barras o de torta con más categorías es ilegible: las menores se agrupan.
MAX_CATEGORIAS_GRAFICO = 12
ETIQUETA_OTROS = "Otros"
# Barras agrupadas (periodo x serie): se dibujan los últimos periodos.
MAX_PERIODOS_AGRUPADAS = 12

# Colores del rediseño (CLAUDE.md, "Tokens de diseño"), sin "#" para openpyxl; reportlab usa
# `HexColor("#" + valor)`.
COLOR_ENCABEZADO = "1B1916"  # carbón: encabezado de tabla
COLOR_TEXTO_ENCABEZADO = "FFFFFF"
COLOR_FILA_ALTERNA = "F7F5F1"  # fondo hueso
COLOR_BORDE = "E4DFD6"
COLOR_TEXTO_TENUE = "6B645C"
COLOR_ACENTO = "5D6B34"  # oliva (sobre claro): serie principal de los gráficos
# Series adicionales (barras agrupadas, torta): oliva, carbón, lima, ámbar, gris cálido, tinta.
PALETA_SERIES = ("5D6B34", "1B1916", "8FAE5B", "A4480A", "6B645C", "B5B2AA", "15803D", "C62828", "232019", "A3C26C", "DCD8D0", "9A6B34")

ZONA_TEXTO = "(hora de Bolivia)"


def texto_de_generacion(generado_en: dt.datetime) -> str:
    """'27/10/2026 14:05 (hora de Bolivia)'. `generado_en` ya viene en hora de Bolivia."""
    return f"{generado_en:%d/%m/%Y %H:%M} {ZONA_TEXTO}"


def a_decimal(valor) -> Decimal | None:
    """El valor como Decimal, o None si no es un número (None, texto, booleano)."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


@dataclass
class DatosGrafico:
    """Lo que se dibuja: las categorías del eje y una o más series con un valor por categoría.
    `tipo` es el de GraficoSugerido (barras, barras_horizontales, barras_agrupadas, linea, torta)."""

    tipo: str
    categorias: list[str]
    series: dict[str, list[float]]
    titulo_valores: str  # título de la columna de valores (para el eje o la leyenda)
    titulo_categorias: str
    recortado: bool = False  # hubo categorías agrupadas en "Otros" o se dibujaron solo las últimas


def _etiqueta(valor) -> str:
    return "" if valor is None else str(valor)


def _titulo_de(seccion: SeccionReporte, clave: str | None) -> str:
    for columna in seccion.columnas:
        if columna.clave == clave:
            return columna.titulo
    return clave or ""


def datos_de_grafico(seccion: SeccionReporte) -> DatosGrafico | None:
    """Los datos del gráfico de la sección, o None si no hay nada que dibujar: tipo `tabla` o
    sin gráfico, sin filas, ejes que no son columnas de la sección o valores no numéricos.

    - barras, barras_horizontales y torta: una serie. Si hay más de MAX_CATEGORIAS_GRAFICO
      categorías se conservan las mayores y el resto se suma en "Otros".
    - linea: una serie con todos los puntos, en el orden de las filas (el tiempo).
    - barras_agrupadas: una serie por cada valor de `serie`; las categorías son los últimos
      MAX_PERIODOS_AGRUPADAS periodos. Un periodo sin dato de una serie vale 0.
    """
    grafico = seccion.grafico
    if grafico is None or grafico.tipo == "tabla" or not seccion.filas:
        return None
    claves = {c.clave for c in seccion.columnas}
    if grafico.eje_x not in claves or grafico.eje_y not in claves:
        return None
    if grafico.tipo == "barras_agrupadas" and grafico.serie not in claves:
        return None

    titulo_x = _titulo_de(seccion, grafico.eje_x)
    titulo_y = _titulo_de(seccion, grafico.eje_y)

    if grafico.tipo == "barras_agrupadas":
        periodos: list[str] = []
        acumulado: dict[str, dict[str, float]] = {}
        for fila in seccion.filas:
            valor = a_decimal(fila.get(grafico.eje_y))
            if valor is None:
                continue
            periodo = _etiqueta(fila.get(grafico.eje_x))
            serie = _etiqueta(fila.get(grafico.serie))
            if periodo not in periodos:
                periodos.append(periodo)
            por_periodo = acumulado.setdefault(serie, {})
            por_periodo[periodo] = por_periodo.get(periodo, 0.0) + float(valor)
        if not periodos:
            return None
        recortado = len(periodos) > MAX_PERIODOS_AGRUPADAS
        periodos = periodos[-MAX_PERIODOS_AGRUPADAS:]
        series = {nombre: [por.get(p, 0.0) for p in periodos] for nombre, por in sorted(acumulado.items())}
        return DatosGrafico("barras_agrupadas", periodos, series, titulo_y, titulo_x, recortado)

    pares: list[tuple[str, float]] = []
    for fila in seccion.filas:
        valor = a_decimal(fila.get(grafico.eje_y))
        if valor is not None:
            pares.append((_etiqueta(fila.get(grafico.eje_x)), float(valor)))
    if not pares:
        return None

    recortado = False
    if grafico.tipo != "linea" and len(pares) > MAX_CATEGORIAS_GRAFICO:
        mayores = sorted(pares, key=lambda par: par[1], reverse=True)[: MAX_CATEGORIAS_GRAFICO - 1]
        elegidas = {id(par) for par in mayores}
        resto = sum(par[1] for par in pares if id(par) not in elegidas)
        # Se conserva el orden original entre las categorías elegidas y "Otros" va al final.
        pares = [par for par in pares if id(par) in elegidas] + [(ETIQUETA_OTROS, resto)]
        recortado = True
    categorias = [etiqueta for etiqueta, _ in pares]
    return DatosGrafico(grafico.tipo, categorias, {titulo_y: [valor for _, valor in pares]}, titulo_y, titulo_x, recortado)
