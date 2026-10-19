"""Seed de estado_venta, según el INSERT del propio
docs/fashionstore_esquema.sql. Idempotente.

Uso:
    .venv/Scripts/python -m scripts.seed_ventas
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.comercial.models import EstadoVenta

ESTADOS_VENTA: list[tuple[str, str, bool]] = [
    # codigo, nombre, es_final
    ("pendiente_pago", "Pendiente de pago", False),
    ("pagada", "Pagada", False),
    ("entregada", "Entregada", True),
    ("anulada", "Anulada", True),
]


def seed(db: Session) -> None:
    for codigo, nombre, es_final in ESTADOS_VENTA:
        estado = db.query(EstadoVenta).filter(EstadoVenta.codigo == codigo).one_or_none()
        if estado is None:
            db.add(EstadoVenta(codigo=codigo, nombre=nombre, es_final=es_final))

    db.commit()


if __name__ == "__main__":
    session = SessionLocal()
    try:
        seed(session)
        print("Seed de ventas aplicado.")
    finally:
        session.close()
