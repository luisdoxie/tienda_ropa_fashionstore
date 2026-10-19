"""Seed de tipo_movimiento, según los INSERT del propio
docs/fashionstore_esquema.sql. Idempotente.

Uso:
    .venv/Scripts/python -m scripts.seed_inventario
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.catalogo.models import TipoMovimiento

TIPOS_MOVIMIENTO: list[tuple[str, str, int, bool]] = [
    # codigo, nombre, signo, afecta_costo
    ("recepcion", "Recepcion de mercaderia", 1, True),
    ("venta", "Salida por venta", -1, False),
    ("devolucion", "Ingreso por devolucion", 1, False),
    ("transferencia_in", "Ingreso por transferencia", 1, True),
    ("transferencia_out", "Salida por transferencia", -1, False),
    ("ajuste_positivo", "Ajuste por sobrante", 1, False),
    ("ajuste_negativo", "Ajuste por faltante", -1, False),
]


def seed(db: Session) -> None:
    for codigo, nombre, signo, afecta_costo in TIPOS_MOVIMIENTO:
        tipo = db.query(TipoMovimiento).filter(TipoMovimiento.codigo == codigo).one_or_none()
        if tipo is None:
            db.add(TipoMovimiento(codigo=codigo, nombre=nombre, signo=signo, afecta_costo=afecta_costo))

    db.commit()


if __name__ == "__main__":
    session = SessionLocal()
    try:
        seed(session)
        print("Seed de inventario aplicado.")
    finally:
        session.close()
