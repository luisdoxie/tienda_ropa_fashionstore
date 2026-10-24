from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.tenant import EmpresaMixin
from app.core.tipos import TipoJson

# ---- Operaciones offline ----

# Estados que se GUARDAN. `en_proceso` es interno: solo existe dentro de la
# transacción mientras se procesa la operación (el commit ya lleva el estado
# final). `registrada` y `enviada` son del cliente (D13), nunca del servidor.
ESTADOS = ("en_proceso", "confirmada", "rechazada", "en_conflicto")
TIPOS = ("venta_contado", "reserva")


class OperacionSync(EmpresaMixin, Base):
    """Una operación hecha sin conexión (venta de contado o reserva) y lo que el
    servidor resolvió con ella. Es evidencia de negocio: no se borra ni se
    purga, y no tiene `activo`. El UUID lo genera el cliente: la clave única
    (empresa, operación) hace idempotente el reenvío (D12).

    `sucursal_id` es NULL cuando la sucursal que mandó el cliente no existe o es
    de otra empresa: la operación se guarda igual (rechazada) y la FK no puede
    apuntar a una sucursal ajena. La sucursal pedida queda en `resultado`."""

    __tablename__ = "operacion_sync"
    __table_args__ = (
        UniqueConstraint("empresa_id", "operacion_id", name="uq_operacion_sync_empresa_operacion"),
        CheckConstraint("tipo IN ('venta_contado','reserva')", name="ck_operacion_sync_tipo"),
        CheckConstraint(
            "estado IN ('en_proceso','confirmada','rechazada','en_conflicto')", name="ck_operacion_sync_estado"
        ),
        Index("ix_operacion_sync_empresa_estado", "empresa_id", "estado", "recibida_en"),
        Index("ix_operacion_sync_sucursal_fecha", "empresa_id", "sucursal_id", "fecha_operacion"),
        Index("ix_operacion_sync_usuario", "usuario_id", "recibida_en"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursal.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), nullable=False)
    operacion_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    estado: Mapped[str] = mapped_column(String(15), nullable=False)
    payload: Mapped[dict] = mapped_column(TipoJson, nullable=False)
    # recurso, cambio, avisos, faltantes y el mensaje para mostrar.
    resultado: Mapped[dict | None] = mapped_column(TipoJson)
    motivo: Mapped[str | None] = mapped_column(String(60))
    fecha_operacion: Mapped[dt.datetime] = mapped_column(nullable=False)  # UTC naive
    recibida_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    procesada_en: Mapped[dt.datetime | None]
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    dispositivo: Mapped[str | None] = mapped_column(String(60))
