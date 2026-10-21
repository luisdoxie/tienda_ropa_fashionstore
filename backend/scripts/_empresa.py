"""Sesión de base de datos ya fijada en una empresa, para los scripts.

Las tablas propias de cada empresa exigen `empresa_id` al insertar: los
scripts abren la sesión con `abrir_sesion`, que busca la empresa por código y
llama a `fijar_empresa`. Código por defecto: variable de entorno SEED_EMPRESA
o 'fashionstore'.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

EMPRESA_POR_DEFECTO = "fashionstore"


def codigo_por_defecto() -> str:
    return os.environ.get("SEED_EMPRESA", "").strip() or EMPRESA_POR_DEFECTO


def abrir_sesion(codigo: str | None = None) -> tuple[Session, "Empresa"]:  # noqa: F821
    """Abre una sesión, busca la empresa por `codigo` y la fija en la sesión.

    Si la empresa no existe cierra la sesión y termina con un mensaje claro.
    """
    import app.main  # noqa: F401  (registra todos los modelos)
    from app.core.database import SessionLocal
    from app.core.tenant import fijar_empresa
    from app.plataforma.models import Empresa

    codigo = (codigo or "").strip() or codigo_por_defecto()
    db = SessionLocal()
    empresa = db.scalar(select(Empresa).where(Empresa.codigo == codigo))
    if empresa is None:
        db.close()
        sys.exit(
            f"No existe la empresa con código '{codigo}'. Aplicá la migración "
            "(crea 'fashionstore') o indicá otra con --empresa / SEED_EMPRESA."
        )
    fijar_empresa(db, empresa.id)
    print(f"Empresa: {empresa.codigo} (id {empresa.id})")
    return db, empresa
