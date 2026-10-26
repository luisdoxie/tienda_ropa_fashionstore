from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.catalogo.schemas import (
    CatalogoItemRespuesta,
    ConsolidadoRespuesta,
    FiltrosCatalogo,
    ValuacionRespuesta,
)
from app.core.tipos import FechaUTC

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


# ---- Reportes generativos ---------------------------------------------------------
# CU-23 (E09). Un solo modelo, SolicitudReporte, sirve para dos usos: es lo que debe
# devolver el intérprete (Groq o reglas) y lo que puede mandar el cliente ya armado.
# Por eso es estricto: extra="forbid" y SIN ningún campo de id ni de empresa. Los
# nombres de sucursales, categorías y productos se resuelven después, siempre contra
# la empresa de la sesión.

TipoPeriodo = Literal[
    "hoy",
    "ayer",
    "esta_semana",
    "semana_pasada",
    "este_mes",
    "mes_pasado",
    "este_anio",
    "anio_pasado",
    "ultimos_dias",
    "ultimas_semanas",
    "ultimos_meses",
    "mes_calendario",
    "rango_fechas",
]
CanalReporte = Literal["digital", "presencial"]
AgrupacionReporte = Literal["dia", "semana", "mes"]
OrdenReporte = Literal["mayor_a_menor", "menor_a_mayor"]
OrigenSolicitud = Literal["texto", "voz"]
TipoColumna = Literal["texto", "entero", "moneda", "porcentaje", "fecha", "booleano"]
TipoGrafico = Literal[
    "barras", "barras_horizontales", "barras_agrupadas", "linea", "torta", "tabla"
]
EstadoReporte = Literal[
    "ok", "incompleta", "ambigua", "invalida", "no_soportada", "no_disponible"
]
InterpreteUsado = Literal["groq", "reglas"]

TIPOS_PERIODO = get_args(TipoPeriodo)
CANALES_REPORTE = get_args(CanalReporte)
AGRUPACIONES_REPORTE = get_args(AgrupacionReporte)
ORDENES_REPORTE = get_args(OrdenReporte)

MAX_NOMBRES_POR_FILTRO = 5
MAX_LARGO_NOMBRE = 80
LIMITE_MINIMO = 1
LIMITE_MAXIMO = 50
MAX_LARGO_TEXTO_REPORTE = 300

NombreFiltro = Annotated[str, StringConstraints(max_length=MAX_LARGO_NOMBRE)]


class FechaParcial(BaseModel):
    """Una fecha escrita a medias ("el 5 de septiembre"). Sin año se toma el más
    reciente que no sea futuro: lo resuelve core/tiempo, nunca la IA."""

    model_config = ConfigDict(extra="forbid")

    dia: int = Field(ge=1, le=31)
    mes: int = Field(ge=1, le=12)
    anio: int | None = Field(default=None, ge=2000, le=2100)


class PeriodoSolicitado(BaseModel):
    """Periodo pedido, en términos relativos. La IA solo nombra el tipo ("este_mes",
    "mes_calendario" con mes=9, "ultimos_meses" con n=3); las fechas las calcula el
    backend. Los rangos de n y mes se validan en core/tiempo (estado "invalida"),
    no aquí, para que un valor absurdo no se confunda con un JSON mal formado."""

    model_config = ConfigDict(extra="forbid")

    tipo: TipoPeriodo
    n: int | None = None
    mes: int | None = None
    anio: int | None = None
    desde: FechaParcial | None = None
    hasta: FechaParcial | None = None


class SolicitudReporte(BaseModel):
    """Lo que el intérprete devuelve y lo que el cliente puede mandar ya armado.
    Sin ids ni empresa_id: extra="forbid" rechaza cualquier campo que no esté aquí.
    `tipo_reporte` es str libre a propósito: un código fuera del registro no es un
    error de forma sino el estado "no_soportada" (lo decide el caso de uso).
    La IA manda `null` en las listas que la frase no menciona: se toman como []."""

    model_config = ConfigDict(extra="forbid")

    tipo_reporte: str | None = Field(default=None, max_length=80)
    periodo: PeriodoSolicitado | None = None
    sucursales: list[NombreFiltro] = Field(default_factory=list, max_length=MAX_NOMBRES_POR_FILTRO)
    categorias: list[NombreFiltro] = Field(default_factory=list, max_length=MAX_NOMBRES_POR_FILTRO)
    productos: list[NombreFiltro] = Field(default_factory=list, max_length=MAX_NOMBRES_POR_FILTRO)
    canal: CanalReporte | None = None
    agrupacion: AgrupacionReporte | None = None
    orden: OrdenReporte | None = None
    limite: int | None = None  # el rango 1..50 lo valida el caso de uso (estado "invalida", no 422)
    solicitud_multiple: bool = False

    @field_validator("sucursales", "categorias", "productos", mode="before")
    @classmethod
    def _null_es_lista_vacia(cls, valor):
        return [] if valor is None else valor


class ReporteGenerativoRequest(BaseModel):
    """Cuerpo de POST /reportes-ia/ejecutar: o `texto` (escrito, o voz ya transcrita
    por el cliente) o `solicitud` ya estructurada; exactamente uno de los dos."""

    model_config = ConfigDict(extra="forbid")

    texto: str | None = Field(default=None, min_length=1, max_length=MAX_LARGO_TEXTO_REPORTE)
    solicitud: SolicitudReporte | None = None
    origen: OrigenSolicitud = "texto"

    @model_validator(mode="after")
    def _exactamente_uno(self):
        if (self.texto is None) == (self.solicitud is None):
            raise ValueError("Envía exactamente uno de 'texto' o 'solicitud'.")
        return self


class ColumnaReporte(BaseModel):
    clave: str
    titulo: str
    tipo: TipoColumna


class GraficoSugerido(BaseModel):
    """Sugerencia para el cliente: qué dibujar y con qué columnas. `tabla` = no
    graficar. Los ejes son claves de ColumnaReporte."""

    tipo: TipoGrafico
    eje_x: str | None = None
    eje_y: str | None = None
    serie: str | None = None


class ReporteEjecutado(BaseModel):
    """Resultado de un reporte. Los valores monetarios van como número JSON (float
    con 2 decimales) dentro de `filas` y `resumen`: sirven para mostrar, no para
    calcular (los totales se calculan en Decimal antes de convertir)."""

    codigo: str
    titulo: str
    columnas: list[ColumnaReporte]
    filas: list[dict[str, Any]]
    resumen: dict[str, Any] = Field(default_factory=dict)
    grafico_sugerido: GraficoSugerido
    truncado: bool = False
    generado_en: FechaUTC


class PeriodoResuelto(BaseModel):
    desde: dt.date
    hasta: dt.date
    etiqueta: str


class ReferenciaResuelta(BaseModel):
    """Un nombre ya resuelto contra la empresa de la sesión. Es de SALIDA: el id
    nunca entra por SolicitudReporte."""

    id: int
    nombre: str


class SolicitudResuelta(BaseModel):
    """La solicitud validada y con fechas e ids resueltos ("entendí esto: ..."). Es lo
    que E10 reenvía para exportar. `periodo` es None en los reportes sin periodo."""

    tipo_reporte: str
    periodo: PeriodoResuelto | None = None
    sucursales: list[ReferenciaResuelta] = Field(default_factory=list)
    categorias: list[ReferenciaResuelta] = Field(default_factory=list)
    productos: list[ReferenciaResuelta] = Field(default_factory=list)
    canal: CanalReporte | None = None
    agrupacion: AgrupacionReporte | None = None
    orden: OrdenReporte | None = None
    limite: int | None = None


class ReporteGenerativoRespuesta(BaseModel):
    """Respuesta de /interpretar y /ejecutar. Todo estado de negocio sale con HTTP 200;
    solo plan, permiso, suscripción (403), cuerpo mal formado (422) y rate limit (429)
    son errores HTTP. Con estado distinto de "ok" nunca hay `reporte`."""

    estado: EstadoReporte
    mensaje: str
    sugerencias: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)
    interprete: InterpreteUsado | None = None
    solicitud: SolicitudResuelta | None = None
    reporte: ReporteEjecutado | None = None
    narrativa: str | None = None
