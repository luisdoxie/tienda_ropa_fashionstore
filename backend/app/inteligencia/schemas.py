from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.catalogo.schemas import (
    CatalogoItemRespuesta,
    ConsolidadoRespuesta,
    FiltrosCatalogo,
    ValuacionRespuesta,
)

# ---- Inteligencia ----

# Los únicos valores que catalogo.schemas.Genero acepta. FiltrosVoz recibe el
# género tal cual lo devuelve Groq (str libre, no el Literal), porque un
# valor fuera de esta lista no debe tirar abajo la validación de todo el
# JSON -- se descarta ese campo puntual en el caso de uso, no la respuesta entera.
GENEROS_VALIDOS = {"hombre", "mujer", "unisex", "nino"}


class VozRequest(BaseModel):
    texto: str = Field(min_length=1, max_length=300)


class FiltrosVoz(BaseModel):
    """Contrato exacto que debe devolver Groq (P6.1): un JSON con estas
    ocho claves, sin texto adicional ni markdown. Todo opcional -- Groq
    manda `null` en lo que la frase no menciona."""

    categoria: str | None = None
    temporada: str | None = None
    material: str | None = None
    color: str | None = None
    talla: str | None = None
    genero: str | None = None
    precio_max: Decimal | None = None
    sucursal: str | None = None


class VozRespuesta(BaseModel):
    resultados: list[CatalogoItemRespuesta]
    filtros: FiltrosCatalogo
    etiquetas: dict[str, str]
    cantidad: int


# ---- Recomendador ------------------------------------------------------


class EventoCrear(BaseModel):
    """Body de POST /ia/eventos. El mobile manda también `texto` en los
    eventos de búsqueda, pero `historial_navegacion` no tiene columna para
    texto libre (el esquema documentado no la tiene); Pydantic v2 ignora
    ese campo extra por default, no hace falta declararlo.

    `tipo` se acepta en lugar de `tipo_evento`: las versiones de la app
    anteriores a la corrección del contrato mandaban `tipo` y recibían 422
    en todos los eventos."""

    tipo_evento: Literal["vista", "busqueda", "carrito", "probador", "favorito"]
    producto_id: int | None = None
    variante_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _aceptar_tipo_de_apps_viejas(cls, datos):
        if isinstance(datos, dict) and "tipo_evento" not in datos and "tipo" in datos:
            datos = {**datos, "tipo_evento": datos["tipo"]}
        return datos


class CandidatoRecomendacion(BaseModel):
    """Uno de los ≤20 candidatos que se le pasan a Groq para rankear."""

    variante_id: int
    nombre: str
    categoria_id: int
    precio_base: Decimal


class PerfilClienteRecomendacion(BaseModel):
    """Contexto breve para el prompt de Groq: si hay historial real
    ponderado detrás de estos candidatos, o si son el fallback de
    popularidad (cliente nuevo/anónimo) -- para que el motivo que arma
    Groq sea coherente con el origen real de la lista."""

    hay_historial: bool


class RecomendacionGroq(BaseModel):
    """Una fila de lo que devuelve Groq al rankear candidatos."""

    variante_id: int
    motivo: str = Field(max_length=200)


class RecomendacionItemRespuesta(BaseModel):
    variante_id: int
    producto: CatalogoItemRespuesta
    motivo: str


class RecomendacionesRespuesta(BaseModel):
    recomendaciones: list[RecomendacionItemRespuesta]


# ---- Reporte por voz ----------------------------------------------------

TIPOS_REPORTE_VALIDOS = {"ventas", "inventario", "reservas", "dashboard"}


class ReporteVozRequest(BaseModel):
    texto: str = Field(min_length=1, max_length=300)


class FiltrosReporteVoz(BaseModel):
    """Contrato exacto que debe devolver Groq: qué reporte y con qué
    filtros -- nunca SQL, nunca texto libre que se ejecute. `tipo_reporte`
    es uno de los 4 valores fijos; los filtros son nombres/fechas que
    `inteligencia.casos_uso.cu23_generar_reportes_con_ia` resuelve a id
    antes de llamar a los reportes (CU-22)."""

    tipo_reporte: str
    desde: dt.date | None = None
    hasta: dt.date | None = None
    sucursal: str | None = None
    categoria: str | None = None
    canal: str | None = None


class ReporteVozRespuesta(BaseModel):
    # La pregunta contestada en español, con las cifras del reporte.
    respuesta: str
    tipo_reporte: str
    filtros_aplicados: dict
    resultado: dict


# ---- Reportes ----

# ---- Ventas ---------------------------------------------------------------------


class FilaVentasDetalle(BaseModel):
    """Una fila de vw_ventas_detalle (comercial/repository.py)."""

    venta_id: int
    codigo: str
    canal: str
    fecha: dt.datetime
    sucursal_id: int
    sucursal: str
    producto_id: int
    producto: str
    categoria_id: int
    categoria: str
    cantidad: int
    precio_unitario: Decimal
    subtotal: Decimal
    costo_unitario: Decimal | None
    margen: Decimal


class ResumenVentas(BaseModel):
    transacciones: int
    total_ventas: Decimal
    ticket_promedio: Decimal
    margen_bruto: Decimal


class FilaTopProducto(BaseModel):
    producto_id: int
    producto: str
    cantidad_vendida: int
    total_vendido: Decimal


class FilaVentasPorCanal(BaseModel):
    canal: str
    transacciones: int
    total_ventas: Decimal


class FilaVentasPorSucursal(BaseModel):
    sucursal_id: int
    sucursal: str
    transacciones: int
    total_ventas: Decimal


class ReporteVentasRespuesta(BaseModel):
    resumen: ResumenVentas
    top_productos: list[FilaTopProducto]
    por_canal: list[FilaVentasPorCanal]
    por_sucursal: list[FilaVentasPorSucursal]
    detalle: list[FilaVentasDetalle]


# ---- Inventario -------------------------------------------------------------------


class ReporteInventarioRespuesta(BaseModel):
    consolidado: list[ConsolidadoRespuesta]
    alertas: list[ConsolidadoRespuesta]
    valuacion: list[ValuacionRespuesta]


# ---- Reservas ---------------------------------------------------------------------


class FilaReservasPorEstado(BaseModel):
    codigo: str
    nombre: str
    cantidad: int


class ReporteReservasRespuesta(BaseModel):
    por_estado: list[FilaReservasPorEstado]
    tasa_conversion: float


# ---- Probador -----------------------------------------------------------------------


class FilaUsoProbador(BaseModel):
    estado: str
    cantidad: int


# ---- Dashboard ---------------------------------------------------------------------


class DashboardRespuesta(BaseModel):
    """Los 12 indicadores del enunciado, livianos (sin el detalle fila por
    fila de ventas -- eso es solo para /reportes/ventas)."""

    desde: dt.date
    hasta: dt.date
    ventas_del_periodo: Decimal
    transacciones: int
    ticket_promedio: Decimal
    margen_bruto: Decimal
    top_productos: list[FilaTopProducto]
    ventas_por_canal: list[FilaVentasPorCanal]
    ventas_por_sucursal: list[FilaVentasPorSucursal]
    valor_inventario_total: Decimal
    variantes_bajo_minimo: int
    reservas_por_estado: list[FilaReservasPorEstado]
    tasa_conversion_reservas: float
    uso_probador: list[FilaUsoProbador]
