"""Seed de estado_reserva, según el INSERT del propio
docs/fashionstore_esquema.sql. Idempotente.

Uso:
    .venv/Scripts/python -m scripts.seed_reservas
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.comercial.models import EstadoReserva

ESTADOS_RESERVA: list[tuple[str, str, bool]] = [
    # codigo, nombre, es_final
    ("pendiente", "Pendiente de preparacion", False),
    ("preparada", "Prendas preparadas", False),
    ("en_prueba", "Cliente en sucursal", False),
    ("completada", "Completada", True),
    ("cancelada", "Cancelada por el cliente", True),
    ("expirada", "Expirada por tiempo", True),
]


def seed(db: Session) -> None:
    for codigo, nombre, es_final in ESTADOS_RESERVA:
        estado = db.query(EstadoReserva).filter(EstadoReserva.codigo == codigo).one_or_none()
        if estado is None:
            db.add(EstadoReserva(codigo=codigo, nombre=nombre, es_final=es_final))

    db.commit()


if __name__ == "__main__":
    session = SessionLocal()
    try:
        seed(session)
        print("Seed de reservas aplicado.")
    finally:
        session.close()
