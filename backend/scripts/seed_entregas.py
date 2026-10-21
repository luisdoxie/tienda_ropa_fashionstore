"""Seed de zona_envio/regla_tarifa_envio: zonas por anillo para Santa Cruz
de la Sierra (1er al 4to anillo con tarifa fija, recargo por anillo
adicional -- 5to anillo en adelante, ver P5.3), más las mismas 3 franjas de
recargo por peso en cada zona. Los montos son un supuesto razonable (no hay
una tarifa oficial provista): ajustables después vía CRUD /zonas-envio, sin
tocar este seed. Idempotente.

Uso:
    .venv/Scripts/python -m scripts.seed_entregas
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.comercial.models import ReglaTarifaEnvio, ZonaEnvio
from app.plataforma.models import Ciudad

CIUDAD_NOMBRE = "Santa Cruz de la Sierra"
CIUDAD_DEPARTAMENTO = "Santa Cruz"

# nombre, anillo_desde, anillo_hasta, tarifa_base
ZONAS: list[tuple[str, int, int | None, Decimal]] = [
    ("1er anillo", 1, 1, Decimal("10.00")),
    ("2do anillo", 2, 2, Decimal("12.00")),
    ("3er anillo", 3, 3, Decimal("15.00")),
    ("4to anillo", 4, 4, Decimal("18.00")),
    ("5to anillo en adelante", 5, None, Decimal("25.00")),
]

# peso_desde_kg, peso_hasta_kg, recargo -- las mismas franjas para cada zona.
REGLAS_PESO: list[tuple[Decimal, Decimal | None, Decimal]] = [
    (Decimal("0"), Decimal("2"), Decimal("0")),
    (Decimal("2"), Decimal("5"), Decimal("5.00")),
    (Decimal("5"), None, Decimal("10.00")),
]


def seed(db: Session) -> None:
    ciudad = (
        db.query(Ciudad)
        .filter(Ciudad.nombre == CIUDAD_NOMBRE, Ciudad.departamento == CIUDAD_DEPARTAMENTO)
        .one_or_none()
    )
    if ciudad is None:
        ciudad = Ciudad(nombre=CIUDAD_NOMBRE, departamento=CIUDAD_DEPARTAMENTO)
        db.add(ciudad)
        db.flush()

    for nombre, anillo_desde, anillo_hasta, tarifa_base in ZONAS:
        zona = (
            db.query(ZonaEnvio)
            .filter(ZonaEnvio.ciudad_id == ciudad.id, ZonaEnvio.nombre == nombre)
            .one_or_none()
        )
        if zona is None:
            zona = ZonaEnvio(
                ciudad_id=ciudad.id,
                nombre=nombre,
                anillo_desde=anillo_desde,
                anillo_hasta=anillo_hasta,
                tarifa_base=tarifa_base,
            )
            db.add(zona)
            db.flush()

        tiene_reglas = db.query(ReglaTarifaEnvio).filter(ReglaTarifaEnvio.zona_envio_id == zona.id).first()
        if tiene_reglas is None:
            for peso_desde, peso_hasta, recargo in REGLAS_PESO:
                db.add(
                    ReglaTarifaEnvio(
                        zona_envio_id=zona.id,
                        peso_desde_kg=peso_desde,
                        peso_hasta_kg=peso_hasta,
                        recargo=recargo,
                    )
                )

    db.commit()


if __name__ == "__main__":
    from scripts._empresa import abrir_sesion

    session, _empresa = abrir_sesion()
    try:
        seed(session)
        print("Seed de entregas aplicado.")
    finally:
        session.close()
