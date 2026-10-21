"""Crea (o restablece la contraseña de) un superadministrador de la plataforma.

El superadministrador no pertenece a ninguna empresa (`usuario.empresa_id`
NULL) y solo tiene el rol global `superadministrador`. NO existe ningún
endpoint que cree usuarios sin empresa: este script es la única vía.

Reglas:
  - El correo y la contraseña salen SOLO de las variables de entorno
    SUPERADMIN_EMAIL y SUPERADMIN_PASSWORD (nunca por argumento, para que no
    queden en el historial de la terminal). Ninguno de los dos se imprime ni se
    registra en el log, tampoco en los mensajes de error.
  - La contraseña tiene al menos 12 caracteres.
  - El rol superadministrador tiene que existir (scripts.seed_seguridad o la
    migración de la E01); si no, el script termina con un mensaje claro.
  - Idempotente: si el correo ya es de un superadministrador no lo duplica y
    no toca su contraseña. Con --restablecer la cambia.
  - Si el correo pertenece a un usuario de una empresa, se niega.

Uso (después de scripts.seed_seguridad), una sola vez como comando del servicio:
    $env:SUPERADMIN_EMAIL="..."; $env:SUPERADMIN_PASSWORD="..."
    python -m scripts.crear_superadmin
    python -m scripts.crear_superadmin --restablecer

Después de usarlo, quitar las dos variables del entorno.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permisos import ROL_SUPERADMINISTRADOR
from app.core.security import hash_password
from app.core.tenant import fijar_plataforma, sin_filtro
from app.plataforma import models as _plataforma_models  # noqa: F401  (registra las tablas)
from app.plataforma.models import Rol, Usuario
from app.plataforma.politicas import validar_roles_asignables
from app.plataforma.repository import UsuarioRepository

LONGITUD_MINIMA = 12
LONGITUD_MAXIMA_BYTES = 72  # límite de bcrypt

CREADO = "creado"
EXISTENTE = "existente"
RESTABLECIDO = "restablecido"


class SuperadminError(Exception):
    """Error de uso del script. Su mensaje nunca incluye el correo ni la contraseña."""


def crear_superadmin(db: Session, email: str, password: str, restablecer: bool = False) -> str:
    """Crea el superadministrador `email` en la sesión `db` y devuelve
    CREADO, EXISTENTE o RESTABLECIDO. Lanza SuperadminError si no se puede."""
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 120:
        raise SuperadminError("SUPERADMIN_EMAIL no es un correo válido")
    if len(password) < LONGITUD_MINIMA:
        raise SuperadminError(f"SUPERADMIN_PASSWORD debe tener al menos {LONGITUD_MINIMA} caracteres")
    if len(password.encode("utf-8")) > LONGITUD_MAXIMA_BYTES:
        raise SuperadminError(f"SUPERADMIN_PASSWORD no puede pasar de {LONGITUD_MAXIMA_BYTES} bytes")

    # Modo plataforma: la sesión no tiene empresa. Rol es una tabla global y
    # las consultas de Usuario sin empresa usan los métodos con `sin_filtro`.
    fijar_plataforma(db)
    rol = db.scalar(select(Rol).where(Rol.nombre == ROL_SUPERADMINISTRADOR, Rol.activo.is_(True)))
    if rol is None:
        raise SuperadminError(
            f"No existe el rol '{ROL_SUPERADMINISTRADOR}'. Ejecutá antes: python -m scripts.seed_seguridad"
        )

    de_empresa = db.scalar(
        sin_filtro(select(Usuario.id).where(Usuario.empresa_id.is_not(None), func.lower(Usuario.email) == email).limit(1))
    )
    if de_empresa is not None:
        raise SuperadminError("Ese correo pertenece a un usuario de una empresa: no puede ser superadministrador")

    repo = UsuarioRepository()
    existente = repo.obtener_sin_empresa_por_correo(db, email)
    try:
        if existente is not None:
            if ROL_SUPERADMINISTRADOR not in {r.nombre for r in existente.roles}:
                raise SuperadminError("Ese correo ya existe como usuario de plataforma sin el rol superadministrador")
            if not restablecer:
                return EXISTENTE
            repo.actualizar_password(db, existente, password, commit=False)
            existente.activo = True
            db.commit()
            return RESTABLECIDO

        usuario = Usuario(
            nombre="Superadministrador",
            apellido="FashionStore",
            email=email,
            password_hash=hash_password(password),
        )
        db.add(usuario)  # empresa_id queda NULL (sesión sin empresa)
        # No se usa UsuarioRepository.asignar_roles: termina con db.refresh() y
        # en modo plataforma toda consulta ORM sobre Usuario exige sin_filtro.
        validar_roles_asignables(None, [ROL_SUPERADMINISTRADOR])
        usuario.roles = [rol]
        db.commit()
        return CREADO
    except Exception:
        db.rollback()
        raise


def abrir_sesion_plataforma() -> Session:
    import app.main  # noqa: F401  (registra todos los modelos)
    from app.core.database import SessionLocal

    return SessionLocal()


def main(argv: list[str] | None = None) -> None:
    analizador = argparse.ArgumentParser(description="Crea o restablece un superadministrador de la plataforma.")
    analizador.add_argument("--restablecer", action="store_true", help="cambia la contraseña si el correo ya existe")
    args = analizador.parse_args(argv)

    email = os.environ.get("SUPERADMIN_EMAIL", "").strip()
    password = os.environ.get("SUPERADMIN_PASSWORD", "")
    if not email or not password:
        sys.exit("Definí SUPERADMIN_EMAIL y SUPERADMIN_PASSWORD (mínimo 12 caracteres) como variables de entorno")

    db = abrir_sesion_plataforma()
    try:
        resultado = crear_superadmin(db, email, password, restablecer=args.restablecer)
    except SuperadminError as error:
        sys.exit(str(error))
    finally:
        db.close()

    if resultado == CREADO:
        print("Superadministrador creado.")
    elif resultado == RESTABLECIDO:
        print("Contraseña del superadministrador restablecida.")
    else:
        print("El superadministrador ya existía. Usá --restablecer para cambiar su contraseña.")


if __name__ == "__main__":
    main()
