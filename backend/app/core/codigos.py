"""Generación de códigos legibles únicos (RES-XXXXXXXX, VTA-..., DEV-...)."""

import secrets

from sqlalchemy.orm import Session

from app.core.exceptions import DomainError


def generar_codigo(db: Session, prefijo: str, existe_codigo) -> str:
    """`prefijo` + 4 bytes aleatorios en hexadecimal mayúscula. `existe_codigo(db, codigo)`
    devuelve algo distinto de None si el código ya está usado; se reintenta hasta 5 veces."""
    for _ in range(5):
        codigo = f"{prefijo}-{secrets.token_hex(4).upper()}"
        if existe_codigo(db, codigo) is None:
            return codigo
    raise DomainError("No se pudo generar un código único, reintentá")
