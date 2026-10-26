"""Tipos compartidos por los paquetes: columnas de los modelos y campos de los schemas."""

import datetime as dt
from typing import Annotated

from pydantic import PlainSerializer
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# JSON en SQLite (pruebas) y JSONB en PostgreSQL.
TipoJson = JSON().with_variant(JSONB, "postgresql")


def _a_utc_con_z(valor: dt.datetime) -> str:
    """Naive (UTC, como se guarda) o con zona -> '2026-10-20T18:07:11Z'."""
    if valor.tzinfo is not None:
        valor = valor.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return valor.replace(microsecond=0).isoformat() + "Z"


# Fecha de salida en JSON: UTC con "Z" y sin microsegundos (contrato de sincronización
# y marcas del plazo de cambio). En Python sigue siendo un datetime.
FechaUTC = Annotated[dt.datetime, PlainSerializer(_a_utc_con_z, return_type=str, when_used="json")]
