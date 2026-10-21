"""scripts/seed_seguridad.py en el esquema multitenant: el administrador de una
empresa NO recibe `plataforma.gestionar` (si no, cada administrador sería
superadministrador) y el superadministrador no tiene permisos de negocio.

Usa su propia base SQLite con solo las tablas de seguridad (globales: no
dependen de ninguna empresa)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.plataforma.models import Permiso, Rol, rol_permiso
from scripts.seed_seguridad import seed


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Permiso.__table__, Rol.__table__, rol_permiso])
    with sessionmaker(bind=engine, autoflush=False)() as session:
        seed(session)
        yield session


def _codigos(db, nombre_rol: str) -> set[str]:
    rol = db.query(Rol).filter(Rol.nombre == nombre_rol).one()
    return {p.codigo for p in rol.permisos}


def test_el_administrador_no_tiene_plataforma_gestionar(db_session):
    codigos = _codigos(db_session, "administrador")

    assert "plataforma.gestionar" not in codigos
    assert "empresa.gestionar" in codigos
    assert "roles.gestionar" in codigos
    # Tiene todo lo demás: solo se le quita el permiso de la plataforma.
    todos = {p.codigo for p in db_session.query(Permiso).all()}
    assert codigos == todos - {"plataforma.gestionar"}


def test_el_superadministrador_tiene_exactamente_plataforma_y_roles(db_session):
    assert _codigos(db_session, "superadministrador") == {"plataforma.gestionar", "roles.gestionar"}


def test_el_seed_de_seguridad_es_idempotente(db_session):
    def foto():
        roles = {r.nombre: sorted(p.codigo for p in r.permisos) for r in db_session.query(Rol).all()}
        return roles, db_session.query(Permiso).count(), db_session.query(Rol).count()

    antes = foto()
    seed(db_session)
    seed(db_session)

    assert foto() == antes
