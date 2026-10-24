"""Ayudas compartidas por las pruebas de los eventos de la bitácora (E06)."""

import re

from sqlalchemy import select

from app.core.auditoria import MARCA_OMITIDO
from app.plataforma.models import Bitacora

# Lo que NUNCA debe aparecer en `datos` (criterio 3 de la E06): ni como clave con
# valor, ni como texto con forma de correo, JWT o hash de contraseña.
_CLAVES_PROHIBIDAS = (
    "password", "contrasena", "clave", "secret", "token", "hash", "authorization", "bearer", "jwt",
    "api_key", "apikey", "cvv", "tarjeta", "card", "email", "correo", "telefono", "celular",
    "direccion", "ci_nit", "fecha_nacimiento", "estatura", "razon_social", "latitud", "longitud",
)  # fmt: skip
_RE_CORREO = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def filas_de(db, entidad: str | None = None, accion: str | None = None) -> list[Bitacora]:
    """Las filas de la bitácora (de cualquier empresa), de la más vieja a la más nueva."""
    db.expire_all()
    consulta = select(Bitacora).order_by(Bitacora.id)
    if entidad is not None:
        consulta = consulta.where(Bitacora.entidad == entidad)
    if accion is not None:
        consulta = consulta.where(Bitacora.accion == accion)
    return list(db.scalars(consulta))


def _recorrer(valor, ruta="datos"):
    if isinstance(valor, dict):
        for clave, item in valor.items():
            yield f"{ruta}.{clave}", str(clave), item
            yield from _recorrer(item, f"{ruta}.{clave}")
    elif isinstance(valor, list):
        for i, item in enumerate(valor):
            yield from _recorrer(item, f"{ruta}[{i}]")


def exigir_datos_sin_sensibles(fila: Bitacora) -> None:
    """Falla si `datos` trae una clave prohibida con un valor distinto de
    "[omitido]", o un texto con forma de correo, JWT o hash bcrypt."""
    for ruta, clave, valor in _recorrer(fila.datos):
        normal = clave.lower()
        if any(prohibida in normal for prohibida in _CLAVES_PROHIBIDAS):
            assert valor == MARCA_OMITIDO, f"{ruta} guarda un dato sensible en la bitácora: {valor!r}"
    for ruta, _clave, valor in _recorrer(fila.datos):
        if isinstance(valor, str):
            assert not _RE_CORREO.search(valor), f"{ruta} parece un correo: {valor!r}"
            assert not valor.startswith(("eyJ", "$2")), f"{ruta} parece un token o un hash: {valor!r}"
    for valor in (fila.datos or {}).values():
        if isinstance(valor, str):
            assert not _RE_CORREO.search(valor)
