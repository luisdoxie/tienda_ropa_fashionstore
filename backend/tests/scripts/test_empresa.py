"""scripts/_empresa.abrir_sesion: sesión de los scripts ya fijada en una empresa."""

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.tenant import empresa_de
from scripts._empresa import abrir_sesion
from tests.conftest import crear_empresa


@pytest.fixture()
def sesion_de_scripts(db_session, monkeypatch):
    """Hace que SessionLocal (la que usan los scripts) apunte a la base de pruebas."""
    fabrica = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr("app.core.database.SessionLocal", fabrica)
    monkeypatch.delenv("SEED_EMPRESA", raising=False)
    return fabrica


def test_abrir_sesion_usa_fashionstore_por_defecto(sesion_de_scripts):
    db, empresa = abrir_sesion()
    try:
        assert empresa.codigo == "fashionstore"
        assert empresa_de(db) == empresa.id == 1
    finally:
        db.close()


def test_abrir_sesion_respeta_seed_empresa(db_session, sesion_de_scripts, monkeypatch):
    otra_id = crear_empresa(db_session, "boutique-norte").id
    db_session.commit()  # suelta la conexión compartida (SQLite en memoria)
    monkeypatch.setenv("SEED_EMPRESA", "boutique-norte")
    db, empresa = abrir_sesion()
    try:
        assert empresa.id == empresa_de(db) == otra_id
    finally:
        db.close()


def test_abrir_sesion_con_codigo_explicito_gana_sobre_la_variable(db_session, sesion_de_scripts, monkeypatch):
    otra_id = crear_empresa(db_session, "boutique-sur").id
    db_session.commit()
    monkeypatch.setenv("SEED_EMPRESA", "no-existe")
    db, empresa = abrir_sesion("boutique-sur")
    try:
        assert empresa_de(db) == otra_id
    finally:
        db.close()


def test_abrir_sesion_con_empresa_inexistente_falla_con_mensaje_claro(sesion_de_scripts):
    with pytest.raises(SystemExit) as error:
        abrir_sesion("no-existe")
    assert "no-existe" in str(error.value)
