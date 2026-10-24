"""Tipos de columna compartidos por los modelos de todos los paquetes."""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# JSON en SQLite (pruebas) y JSONB en PostgreSQL.
TipoJson = JSON().with_variant(JSONB, "postgresql")
