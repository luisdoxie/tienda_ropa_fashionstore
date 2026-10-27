"""E10 — Exportación de reportes a Excel y PDF.

Punto de entrada único del constructor de archivos. Recibe un DocumentoReporte (ver
`schemas.py`, bloque "Exportación") y devuelve los bytes del archivo: todo en memoria, nada se
escribe en disco. No conoce la base, ni a los reportes de donde viene el documento, ni HTTP.

- `exportacion_xlsx.construir_xlsx`: libro de Excel con openpyxl (gráfico nativo).
- `exportacion_pdf.construir_pdf`: PDF con reportlab (gráfico vectorial).
- `exportacion_comun`: constantes, colores y la preparación de los datos del gráfico.
"""

from dataclasses import dataclass

from app.inteligencia.exportacion_comun import EXPORTACION_MAX_FILAS_PDF, EXPORTACION_MAX_FILAS_XLSX
from app.inteligencia.exportacion_pdf import construir_pdf
from app.inteligencia.exportacion_xlsx import construir_xlsx
from app.inteligencia.schemas import DocumentoReporte, FormatoExportacion

TIPO_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
MAX_FILAS = {"xlsx": EXPORTACION_MAX_FILAS_XLSX, "pdf": EXPORTACION_MAX_FILAS_PDF}


@dataclass
class ArchivoExportado:
    """Lo que un caso de uso devuelve al router: los bytes y cómo servirlos."""

    contenido: bytes
    tipo_mime: str
    nombre_archivo: str


def construir_archivo(doc: DocumentoReporte, formato: FormatoExportacion, incluir_grafico: bool = True) -> bytes:
    """Los bytes del archivo en el formato pedido."""
    if formato == "xlsx":
        return construir_xlsx(doc, incluir_grafico)
    return construir_pdf(doc, incluir_grafico)


__all__ = [
    "ArchivoExportado",
    "EXPORTACION_MAX_FILAS_PDF",
    "EXPORTACION_MAX_FILAS_XLSX",
    "MAX_FILAS",
    "TIPO_MIME",
    "construir_archivo",
    "construir_pdf",
    "construir_xlsx",
]
