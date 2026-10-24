"""Contrato JSON v1 de la sincronización offline (CU-25), compartido por la PWA
(E14) y Flutter (E20).

- Montos: TEXTO decimal ("120.00"), nunca float.
- Fechas de entrada: ISO-8601 CON zona ("2026-10-20T14:05:00-04:00" o "...Z"); el
  servidor las normaliza a UTC. Las de salida van en UTC con "Z".
- `operacion_id`: UUID v4 en minúscula, generado en el cliente.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer

VERSION_CONTRATO = "1.0"
MAX_OPERACIONES_POR_LOTE = 50


def _a_utc_con_z(valor: dt.datetime) -> str:
    """Naive (UTC, como se guarda) o con zona -> '2026-10-20T18:07:11Z'."""
    if valor.tzinfo is not None:
        valor = valor.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return valor.replace(microsecond=0).isoformat() + "Z"


FechaUTC = Annotated[dt.datetime, PlainSerializer(_a_utc_con_z, return_type=str, when_used="json")]

TipoOperacion = Literal["venta_contado", "reserva"]
EstadoResultado = Literal["confirmada", "rechazada", "en_conflicto", "error_temporal"]


# ---- Entrada ----------------------------------------------------------------------


class VentaContadoLinea(BaseModel):
    variante_id: int
    cantidad: int = Field(gt=0)
    precio_unitario: Decimal = Field(ge=0)
    descuento_unitario: Decimal = Field(default=Decimal("0"), ge=0)


class PagoContado(BaseModel):
    metodo: str = Field(max_length=30)
    monto_recibido: Decimal = Field(ge=0)


class VentaContadoPayload(BaseModel):
    cliente_id: int | None = None
    lineas: list[VentaContadoLinea] = Field(min_length=1, max_length=100)
    total: Decimal
    pago: PagoContado


class ReservaLinea(BaseModel):
    variante_id: int
    cantidad: int = Field(gt=0)


class ReservaPayload(BaseModel):
    cliente_id: int
    fecha_visita: dt.date
    hora_visita_desde: dt.time
    hora_visita_hasta: dt.time
    observacion: str | None = Field(default=None, max_length=300)
    lineas: list[ReservaLinea] = Field(min_length=1, max_length=100)


PAYLOAD_POR_TIPO: dict[str, type[BaseModel]] = {
    "venta_contado": VentaContadoPayload,
    "reserva": ReservaPayload,
}


class OperacionEntrada(BaseModel):
    """`tipo` y `payload` se validan POR OPERACIÓN (no aquí): un tipo desconocido o
    un payload mal formado rechaza esa operación con su motivo y no tumba el lote."""

    operacion_id: uuid.UUID
    tipo: str = Field(max_length=20)
    sucursal_id: int
    fecha_operacion: AwareDatetime
    payload: dict[str, Any]


class LoteEntrada(BaseModel):
    """`version_contrato` se valida en el caso de uso (400 si no es la soportada)."""

    version_contrato: str = Field(max_length=10)
    empresa_id: int | None = None  # solo informativo: la empresa real es la del token
    dispositivo: str | None = Field(default=None, max_length=60)
    operaciones: list[OperacionEntrada] = Field(min_length=1, max_length=MAX_OPERACIONES_POR_LOTE)


# ---- Salida -----------------------------------------------------------------------


class RecursoCreado(BaseModel):
    tipo: Literal["venta", "reserva"]
    id: int
    codigo: str
    total: Decimal | None = None  # venta
    fecha_expiracion: FechaUTC | None = None  # reserva


class AvisoPrecio(BaseModel):
    codigo: Literal["precio_distinto"] = "precio_distinto"
    variante_id: int
    precio_operacion: Decimal
    precio_actual: Decimal


class Faltante(BaseModel):
    variante_id: int
    solicitado: int
    disponible: int


class ResultadoOperacion(BaseModel):
    operacion_id: uuid.UUID
    estado: EstadoResultado
    motivo: str | None = None
    mensaje: str | None = None
    duplicada: bool = False
    procesada_en: FechaUTC | None = None
    recurso: RecursoCreado | None = None
    cambio: Decimal | None = None
    avisos: list[AvisoPrecio] = []
    faltantes: list[Faltante] = []


class ResumenLote(BaseModel):
    total: int
    confirmadas: int
    rechazadas: int
    en_conflicto: int
    errores_temporales: int
    duplicadas: int


class LoteRespuesta(BaseModel):
    version_contrato: str = VERSION_CONTRATO
    procesado_en: FechaUTC
    resumen: ResumenLote
    resultados: list[ResultadoOperacion]


# ---- Consulta ---------------------------------------------------------------------


class OperacionSyncRespuesta(BaseModel):
    """Una operación guardada, SIN su payload."""

    model_config = ConfigDict(from_attributes=True)

    operacion_id: uuid.UUID
    tipo: str
    estado: str
    motivo: str | None = None
    mensaje: str | None = None
    sucursal_id: int | None = None
    usuario_id: int
    fecha_operacion: FechaUTC
    recibida_en: FechaUTC
    procesada_en: FechaUTC | None = None
    intentos: int
    dispositivo: str | None = None
    recurso: RecursoCreado | None = None
    cambio: Decimal | None = None
    avisos: list[AvisoPrecio] = []
    faltantes: list[Faltante] = []


class OperacionSyncDetalle(OperacionSyncRespuesta):
    """Para supervisores: suma el payload (lo necesita quien decide un conflicto)."""

    payload: dict[str, Any] | None = None


class OperacionSyncPagina(BaseModel):
    total: int
    pagina: int
    tamanio: int
    items: list[OperacionSyncRespuesta]


class FiltrosOperaciones(BaseModel):
    estado: str | None = None
    tipo: str | None = None
    sucursal_id: int | None = None
    usuario_id: int | None = None
    desde: dt.date | None = None
    hasta: dt.date | None = None
