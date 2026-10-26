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

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer, model_validator

from app.core.tipos import FechaUTC

VERSION_CONTRATO = "1.0"
MAX_OPERACIONES_POR_LOTE = 50

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


class AjusteResolucion(BaseModel):
    """Un ajuste positivo de inventario que hizo 'forzar' para cubrir un faltante."""

    variante_id: int
    cantidad: int
    movimiento_id: int


class ResolucionConflicto(BaseModel):
    """Cómo se cerró una operación que estaba en conflicto (E08)."""

    accion: Literal["forzar", "rechazar"]
    por_usuario_id: int
    en: FechaUTC
    motivo: str | None = None
    ajustes: list[AjusteResolucion] = []


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
    resolucion: ResolucionConflicto | None = None  # solo si un encargado la resolvió


class ResolverEntrada(BaseModel):
    """Body de `POST /operaciones/{operacion_id}/resolver`. El motivo es obligatorio para
    rechazar y opcional para forzar."""

    accion: Literal["forzar", "rechazar"]
    motivo: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _motivo_de_rechazo(self) -> "ResolverEntrada":
        self.motivo = (self.motivo or "").strip() or None
        if self.accion == "rechazar" and self.motivo is None:
            raise ValueError("El motivo es obligatorio para rechazar una operación")
        return self


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


# ---- Paquete de descarga (E08) -------------------------------------------------------------
# Lo que el cliente descarga para operar sin conexión. Contrato v1 como el resto: montos en TEXTO,
# marcas de tiempo en UTC con "Z", horas "HH:MM". Solo lo mínimo para vender y reservar: nada de
# costos, márgenes, límites de stock, proveedores ni datos personales (salvo nombre, apellido y
# ci_nit del cliente). `generado_en` es el instante en que el servidor leyó los datos: con él el
# cliente decide cuándo mostrar "información desactualizada".

HoraHM = Annotated[dt.time, PlainSerializer(lambda hora: hora.strftime("%H:%M"), return_type=str, when_used="json")]


class PaqueteBase(BaseModel):
    version_contrato: str = VERSION_CONTRATO
    generado_en: FechaUTC


class EmpresaPaquete(BaseModel):
    id: int
    codigo: str
    nombre: str


class HorarioPaquete(BaseModel):
    dia_semana: int  # 1 = lunes ... 7 = domingo
    hora_apertura: HoraHM
    hora_cierre: HoraHM


class SucursalPaquete(BaseModel):
    id: int
    codigo: str
    nombre: str
    direccion: str
    es_deposito: bool
    horarios: list[HorarioPaquete]


class CategoriaPaquete(BaseModel):
    id: int
    nombre: str
    categoria_padre_id: int | None = None


class TallaPaquete(BaseModel):
    id: int
    codigo: str
    orden: int


class ColorPaquete(BaseModel):
    id: int
    nombre: str
    codigo_hex: str | None = None


class ReferenciaPaquete(BaseModel):
    categorias: list[CategoriaPaquete]
    tallas: list[TallaPaquete]
    colores: list[ColorPaquete]


class AlcancePromocionPaquete(BaseModel):
    producto_id: int | None = None
    categoria_id: int | None = None
    temporada_id: int | None = None


class PromocionPaquete(BaseModel):
    id: int
    nombre: str
    tipo: Literal["porcentaje", "monto"]
    valor: Decimal
    fecha_inicio: dt.date
    fecha_fin: dt.date
    alcances: list[AlcancePromocionPaquete]


class ReglasPaquete(BaseModel):
    metodos_pago_offline: list[str]
    max_operaciones_por_lote: int
    plazo_cambio_horas: int
    cambios_y_devoluciones: str
    reservas_offline: str


class PaqueteManifiesto(PaqueteBase):
    aviso_desactualizado_horas: int
    empresa: EmpresaPaquete
    sucursales: list[SucursalPaquete]
    referencia: ReferenciaPaquete
    promociones_vigentes: list[PromocionPaquete]
    reglas: ReglasPaquete


class VariantePaquete(BaseModel):
    id: int
    talla_id: int
    color_id: int
    sku: str
    codigo_barras: str | None = None
    precio: Decimal  # el efectivo: el de la variante o, si no tiene, el del producto
    descuento_unitario: Decimal  # el mayor descuento vigente al `generado_en`


class ProductoPaquete(BaseModel):
    id: int
    codigo: str
    nombre: str
    categoria_id: int
    genero: str
    temporada_id: int | None = None
    imagen_principal: str | None = None
    variantes: list[VariantePaquete]


class PaqueteCatalogo(PaqueteBase):
    total: int  # productos activos de la empresa: para verificar que no faltó ninguna página
    siguiente_desde_id: int | None = None  # None = última página
    items: list[ProductoPaquete]


class StockPaquete(BaseModel):
    variante_id: int
    cantidad_disponible: int  # física menos reservada
    actualizado_en: FechaUTC


class PaqueteStock(PaqueteBase):
    sucursal_id: int
    incremental: bool  # True si se pidió `desde`: solo vienen las filas modificadas
    siguiente_desde_variante_id: int | None = None
    items: list[StockPaquete]


class ClientePaquete(BaseModel):
    id: int
    nombre: str
    apellido: str
    ci_nit: str | None = None


class PaqueteClientes(PaqueteBase):
    total: int
    siguiente_desde_id: int | None = None
    items: list[ClientePaquete]
