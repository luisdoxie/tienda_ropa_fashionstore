"""Seed de tallas y materiales, según los INSERT del propio
docs/fashionstore_esquema.sql. Idempotente.

Uso:
    .venv/Scripts/python -m scripts.seed_catalogo
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.catalogo.models import Material, Talla

TALLAS: list[tuple[str, str, int]] = [
    ("XS", "Extra small", 1),
    ("S", "Small", 2),
    ("M", "Medium", 3),
    ("L", "Large", 4),
    ("XL", "Extra large", 5),
    ("XXL", "Doble extra large", 6),
]

MATERIALES: list[str] = [
    "Algodon",
    "Hilo",
    "Poliester",
    "Lino",
    "Mezclilla",
    "Lana",
    "Seda",
    "Cuero sintetico",
]


def seed(db: Session) -> None:
    for codigo, descripcion, orden in TALLAS:
        talla = db.query(Talla).filter(Talla.codigo == codigo).one_or_none()
        if talla is None:
            db.add(Talla(codigo=codigo, descripcion=descripcion, orden=orden))

    for nombre in MATERIALES:
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
