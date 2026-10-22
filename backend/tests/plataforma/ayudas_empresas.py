"""Apoyo de las pruebas de CU-04: cuerpos de petición y consultas de verificación."""

from sqlalchemy import func, select

from app.core.tenant import en_empresa, sin_filtro
from app.plataforma.models import Suscripcion

CLAVE = "claveSegura123"
CORREO_SUPERADMIN = "super@plataforma.example.com"
PLATAFORMA = "/api/v1/plataforma"


def cuerpo_registro(nombre: str = "Boutique Andina", correo: str | None = None, **extra) -> dict:
    """Cuerpo de POST /plataforma/empresas."""
    return {
        "nombre": nombre,
        "administrador": {
            "nombre": "Ana",
            "apellido": "Rojas",
            "email": correo or "ana@boutiqueandina.example.com",
            "password": CLAVE,
            "telefono": "70000000",
        },
        **extra,
    }


def registrar(client, headers, nombre: str = "Boutique Andina", correo: str | None = None, **extra):
    """Registra una empresa por HTTP y devuelve la respuesta."""
    return client.post(f"{PLATAFORMA}/empresas", json=cuerpo_registro(nombre, correo, **extra), headers=headers)


def login_de_empresa(client, empresa: str, correo: str, password: str = CLAVE):
    return client.post("/api/v1/auth/login", json={"empresa": empresa, "email": correo, "password": password})


def contar(db, modelo, empresa_id: int) -> int:
    """Filas de `modelo` de la empresa, sin cambiar la empresa de la sesión."""
    with en_empresa(db, empresa_id):
        return db.scalar(select(func.count()).select_from(modelo))


def contar_suscripciones(db, empresa_id: int | None = None) -> int:
    """Suscripciones (vigentes y canceladas) de una empresa o de todas."""
    consulta = select(func.count()).select_from(Suscripcion)
    if empresa_id is not None:
        consulta = consulta.where(Suscripcion.empresa_id == empresa_id)
    return db.scalar(sin_filtro(consulta))


def suscripciones_de(db, empresa_id: int) -> list[Suscripcion]:
    """Todas las suscripciones de la empresa (vigente e historial), por id."""
    consulta = select(Suscripcion).where(Suscripcion.empresa_id == empresa_id).order_by(Suscripcion.id)
    return list(db.scalars(sin_filtro(consulta)))
