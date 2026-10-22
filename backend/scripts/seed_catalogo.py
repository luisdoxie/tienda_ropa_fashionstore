"""Seed de tallas y materiales, según los INSERT del propio
docs/fashionstore_esquema.sql. Idempotente.

Los datos (TALLAS_BASE, MATERIALES_BASE) viven en app/catalogo/politicas.py: son
los mismos que recibe toda empresa nueva al registrarse.

Uso:
    .venv/Scripts/python -m scripts.seed_catalogo
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.catalogo.models import Material, Talla
from app.catalogo.politicas import MATERIALES_BASE, TALLAS_BASE


def seed(db: Session) -> None:
    for codigo, descripcion, orden in TALLAS_BASE:
        talla = db.query(Talla).filter(Talla.codigo == codigo).one_or_none()
        if talla is None:
            db.add(Talla(codigo=codigo, descripcion=descripcion, orden=orden))

    for nombre in MATERIALES_BASE:
        material = db.query(Material).filter(Material.nombre == nombre).one_or_none()
        if material is None:
            db.add(Material(nombre=nombre))

    db.commit()


if __name__ == "__main__":
    from scripts._empresa import abrir_sesion

    session, _empresa = abrir_sesion()
    try:
        seed(session)
        print("Seed de catálogo aplicado.")
    finally:
        session.close()
