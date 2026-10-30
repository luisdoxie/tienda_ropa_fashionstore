from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.tenant import EmpresaMixin
from app.core.tipos import TipoJson
from app.inteligencia.ml.limites import ML_MAX_ARTEFACTO_BYTES

# ---- Inteligencia ----

# JSON en general (compatible con sqlite, usado en tests); JSONB solo en
# Postgres, que es lo que pide el esquema (ver catalogo/models.py, mismo
# patrón).
_TipoJson = JSON().with_variant(JSONB, "postgresql")


class ConsultaVoz(EmpresaMixin, Base):
    """Log de cada búsqueda por voz (P6.1): qué se transcribió, qué filtros
    se aplicaron (los haya resuelto Groq o el fallback de texto plano) y
    cuántos resultados dio. `cliente_id` es nullable a propósito: la
    búsqueda por voz admite uso anónimo, igual que /catalogo/buscar."""

    __tablename__ = "consulta_voz"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"))
    texto_transcrito: Mapped[str] = mapped_column(Text, nullable=False)
    filtros_json: Mapped[dict | None] = mapped_column(_TipoJson)
    cantidad_resultados: Mapped[int | None]
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class HistorialNavegacion(EmpresaMixin, Base):
    """Log de eventos de navegación (P6.2): vista, búsqueda, carrito, uso
    del probador o favorito. Alimenta la capa 2 (ponderación por historial)
    del recomendador. `cliente_id` es nullable a propósito -- el registro
    de eventos admite uso anónimo, igual que `ConsultaVoz`."""

    __tablename__ = "historial_navegacion"
    __table_args__ = (
        CheckConstraint(
            "tipo_evento IN ('vista','busqueda','carrito','probador','favorito')",
            name="ck_historial_navegacion_tipo_evento",
        ),
    )

    # BIGSERIAL en Postgres; en sqlite (tests) solo un INTEGER PRIMARY KEY
    # se autoincrementa, BIGINT no.
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"))
    sesion_anonima: Mapped[str | None] = mapped_column(String(64))
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("producto.id"))
    variante_id: Mapped[int | None] = mapped_column(ForeignKey("producto_variante.id"))
    tipo_evento: Mapped[str] = mapped_column(String(25), nullable=False)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class Recomendacion(EmpresaMixin, Base):
    """Log histórico de las recomendaciones finales que arma el
    recomendador (P6.2): qué variante, con qué motivo, para qué cliente.
    A diferencia de `ConsultaVoz`/`HistorialNavegacion`, `cliente_id` es
    obligatorio -- una recomendación anónima se calcula pero no se
    persiste, no hay a quién asociarla."""

    __tablename__ = "recomendacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"), nullable=False)
    variante_id: Mapped[int] = mapped_column(ForeignKey("producto_variante.id"), nullable=False)
    puntaje: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    motivo: Mapped[str | None] = mapped_column(String(200))
    generado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


# ---- Analítica ML ----

# Qué modelo es. 'anomalias_ventas' no se implementa en E11 (D37) pero se admite desde ya: sumarlo
# después no necesita migración.
TIPOS_MODELO_ML = ("demanda_semanal", "segmentos_rfm", "anomalias_ventas")


class ModeloML(EmpresaMixin, Base):
    """Un modelo de ML entrenado para UNA empresa (D22: jamás con datos de otra), con su versión, sus
    métricas y el artefacto serializado. El disco de Railway es efímero y no hay almacenamiento de
    objetos, por eso el artefacto es un BYTEA en la base (tope 8 MB).

    `activo` aquí NO es un borrado lógico: marca la versión VIGENTE de ese tipo (el índice parcial
    único deja una sola por empresa y tipo). No hay DELETE físico (regla 8): las versiones viejas
    pierden el artefacto pero conservan sus métricas. El artefacto es `deferred`: los listados no lo
    traen. Lo escribe solo el propio backend; jamás se sube un modelo externo."""

    __tablename__ = "modelo_ml"
    __table_args__ = (
        UniqueConstraint("empresa_id", "tipo", "version", name="uq_modelo_ml_empresa_tipo_version"),
        CheckConstraint(
            "tipo IN ('demanda_semanal','segmentos_rfm','anomalias_ventas')", name="ck_modelo_ml_tipo"
        ),
        CheckConstraint("version >= 1", name="ck_modelo_ml_version"),
        CheckConstraint("filas_entrenamiento >= 0", name="ck_modelo_ml_filas"),
        CheckConstraint(
            f"artefacto_bytes IS NULL OR (artefacto_bytes >= 0 AND artefacto_bytes <= {ML_MAX_ARTEFACTO_BYTES})",
            name="ck_modelo_ml_artefacto_bytes",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # MAE, RMSE, R2, silhouette, curvas... y los parámetros (semilla, hiperparámetros, rango de datos,
    # versión de scikit-learn, supuestos). Nunca datos personales.
    metricas: Mapped[dict] = mapped_column(TipoJson, nullable=False)
    parametros: Mapped[dict] = mapped_column(TipoJson, nullable=False)
    artefacto: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    artefacto_sha256: Mapped[str | None] = mapped_column(String(64))
    artefacto_bytes: Mapped[int | None] = mapped_column(Integer)
    filas_entrenamiento: Mapped[int] = mapped_column(Integer, nullable=False)
    datos_desde: Mapped[dt.date | None] = mapped_column(Date)
    datos_hasta: Mapped[dt.date | None] = mapped_column(Date)
    entrenado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    entrenado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


# Una sola versión vigente por empresa y tipo: índice único PARCIAL (WHERE activo). Va después de la clase
# y con la columna, sin SQL escrito a mano: bajo `inteligencia/` no se permite SQL en texto.
Index(
    "uq_modelo_ml_activo",
    ModeloML.empresa_id,
    ModeloML.tipo,
    unique=True,
    postgresql_where=ModeloML.activo,
    sqlite_where=ModeloML.activo,
)


# ---- Reportes ----
# Los reportes no tienen tablas propias: solo leen, combinando datos de
# `comercial` (ventas y reservas) y de `catalogo` (inventario y probador) a
# través de las `politicas` y los casos de uso de esos paquetes. Este bloque
# existe por consistencia con la estructura del paquete y no define ningún
# modelo.
