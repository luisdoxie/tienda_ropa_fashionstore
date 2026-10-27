"""Documentos de ejemplo para probar los constructores de Excel y de PDF (E10) sin base de datos.

Un DocumentoReporte es puro (solo datos), así que estas pruebas no necesitan la API."""

import datetime as dt
from io import BytesIO

from openpyxl import load_workbook
from pypdf import PdfReader

from app.core.tenant import empresa_de, fijar_empresa
from app.inteligencia.schemas import ColumnaReporte, DocumentoReporte, GraficoSugerido, SeccionReporte
from app.plataforma.models import Empleado
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.conftest import token_de

CLAVE = "claveSegura123"
BOLIVIA = dt.timezone(dt.timedelta(hours=-4))
GENERADO_EN = dt.datetime(2026, 9, 20, 14, 5, tzinfo=BOLIVIA)

COLUMNAS_VENTAS = [
    ColumnaReporte(clave="sucursal", titulo="Sucursal", tipo="texto"),
    ColumnaReporte(clave="transacciones", titulo="Transacciones", tipo="entero"),
    ColumnaReporte(clave="total_ventas", titulo="Total vendido (Bs)", tipo="moneda"),
    ColumnaReporte(clave="participacion", titulo="Participación", tipo="porcentaje"),
    ColumnaReporte(clave="desde", titulo="Desde", tipo="fecha"),
    ColumnaReporte(clave="activa", titulo="Activa", tipo="booleano"),
]


def fila_ventas(i: int, sucursal: str | None = None, total: float | None = None) -> dict:
    return {
        "sucursal": sucursal if sucursal is not None else f"Sucursal {i:03d}",
        "transacciones": i + 1,
        "total_ventas": total if total is not None else 1250.5 + i,
        "participacion": 12.5,
        "desde": "2026-09-01",
        "activa": i % 2 == 0,
    }


def documento(
    n_filas: int = 3,
    *,
    grafico: GraficoSugerido | None = GraficoSugerido(tipo="barras", eje_x="sucursal", eje_y="total_ventas"),
    columnas: list[ColumnaReporte] | None = None,
    filas: list[dict] | None = None,
    totales: dict | None = None,
    titulo: str = "Ventas por sucursal",
    empresa: str = "FashionStore",
    filtros: list[str] | None = None,
    truncado: bool = False,
    subtitulo: str | None = "Entre el 01/09/2026 y el 20/09/2026 se vendió Bs 3.753,00 en 3 sucursales.",
    avisos: list[str] | None = None,
) -> DocumentoReporte:
    """Una sección con `n_filas` filas de ventas por sucursal (o las `filas` dadas)."""
    filas = filas if filas is not None else [fila_ventas(i) for i in range(n_filas)]
    seccion = SeccionReporte(
        titulo=titulo,
        columnas=columnas if columnas is not None else COLUMNAS_VENTAS,
        filas=filas,
        totales=totales,
        grafico=grafico,
    )
    return DocumentoReporte(
        titulo=titulo,
        subtitulo=subtitulo,
        empresa_nombre=empresa,
        filtros=filtros if filtros is not None else ["Periodo: 01/09/2026 al 20/09/2026", "Sucursales: todas"],
        generado_en=GENERADO_EN,
        secciones=[seccion],
        truncado=truncado,
        avisos=avisos or [],
    )


def celdas_xlsx(respuesta) -> list:
    """Todos los valores de todas las hojas del .xlsx devuelto."""
    libro = load_workbook(BytesIO(respuesta.content))
    return [c.value for hoja in libro.worksheets for fila in hoja.iter_rows() for c in fila if c.value is not None]


def hojas_xlsx(respuesta) -> list[str]:
    return load_workbook(BytesIO(respuesta.content)).sheetnames


def texto_pdf(respuesta) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(respuesta.content)).pages)


def personal_de(db, empresa_id: int, rol: str, correo: str, sucursal_id: int | None = None) -> dict:
    """Un usuario de la empresa con ese rol (y ficha de empleado si lleva sucursal). Devuelve sus cabeceras."""
    original = empresa_de(db)
    fijar_empresa(db, empresa_id)
    try:
        repo = UsuarioRepository()
        usuario = repo.crear(db, UsuarioCrear(nombre=rol[:5], apellido="Ex", email=correo, password=CLAVE))
        repo.asignar_roles(db, usuario, [rol])
        if sucursal_id is not None:
            db.add(Empleado(usuario_id=usuario.id, sucursal_id=sucursal_id, cargo=rol))
        db.commit()
        db.refresh(usuario)
        return token_de(db, usuario)
    finally:
        fijar_empresa(db, original)
