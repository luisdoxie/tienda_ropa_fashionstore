"""Escenario común de las pruebas de la analítica (E12): las organizaciones de demostración pequeñas con su historial
sintético, y ayudas para entrenar y para armar las cabeceras HTTP de su administrador. Reutiliza el escenario de las
pruebas del ML (`tests/inteligencia/ml/_escenario.py`: 40 semanas, 80 clientes, fin el 25/10/2026)."""

import datetime as dt

from sqlalchemy import select

from app.core.tenant import en_empresa
from app.inteligencia.casos_uso.cu24_analizar_con_machine_learning import EntrenarModelosAnaliticos
from app.plataforma.models import Usuario
from scripts.demo_organizaciones import por_codigo
from tests.conftest import token_de
from tests.inteligencia.ml._escenario import FIN, cargar_historia, crear_vista_de_ventas, id_de, poblar
from tests.scripts._prendas_falsas import crear_carpeta

# Las organizaciones del escenario: FashionStore y Chaski Sport (Profesional, con ML) y Pampa Casual (Básico, sin ML).
HOY = FIN + dt.timedelta(days=1)  # el día siguiente al fin del historial: el modelo recién entrenado queda "vigente"

__all__ = [
    "FIN",
    "HOY",
    "cargar_historia",
    "cabeceras_de",
    "entrenar",
    "id_de",
    "poblar_mundo",
    "usuario_de",
]


def poblar_mundo(db, tmp_path) -> None:
    """Pobla las tres organizaciones (sin fotos) y crea la vista de ventas que lee la serie diaria."""
    poblar(db, crear_carpeta(tmp_path))
    crear_vista_de_ventas(db)


def usuario_de(db, codigo_empresa: str, email: str | None = None) -> Usuario:
    """El usuario con ese correo en esa empresa (por defecto, su administrador)."""
    empresa_id = id_de(db, codigo_empresa)
    email = email or por_codigo(codigo_empresa).admin_email
    with en_empresa(db, empresa_id):
        usuario = db.scalar(select(Usuario).where(Usuario.email == email))
        assert usuario is not None, email
        db.refresh(usuario)
        _ = usuario.roles  # cargar los roles antes de salir del alcance de la empresa
        return usuario


def cabeceras_de(db, codigo_empresa: str, email: str | None = None) -> dict:
    """Cabeceras `Authorization` con el token de ese usuario (como las que da el login)."""
    return token_de(db, usuario_de(db, codigo_empresa, email))


def entrenar(db, codigo_empresa: str, tipos: list[str] | None = None):
    """Entrena los modelos de la empresa con el historial ya cargado (fin del escenario: `FIN`)."""
    with en_empresa(db, id_de(db, codigo_empresa)):
        return EntrenarModelosAnaliticos().ejecutar(db, None, tipos, hasta=FIN)
