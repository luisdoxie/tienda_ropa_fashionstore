"""core/tenant.py: la empresa vive en la sesión y `before_flush` rellena
`empresa_id` en los objetos nuevos (y se niega a crear en otra empresa)."""

import pytest
from sqlalchemy import select

from app.catalogo.models import Color
from app.core.tenant import (
    CLAVE_EMPRESA,
    EmpresaNoDefinidaError,
    empresa_de,
    exigir_empresa,
    fijar_empresa,
)
from app.plataforma.models import Ciudad, Rol, Suscripcion, Usuario
from tests.conftest import crear_empresa


def _usuario(email: str = "tenant@example.com") -> Usuario:
    return Usuario(nombre="Ten", apellido="Ant", email=email, password_hash="hash")


def test_fijar_empresa_y_empresa_de(db_session):
    # La fixture deja fijada la empresa semilla (id 1).
    assert empresa_de(db_session) == 1
    assert db_session.info[CLAVE_EMPRESA] == 1

    fijar_empresa(db_session, 7)
    assert empresa_de(db_session) == 7
    assert exigir_empresa(db_session) == 7

    fijar_empresa(db_session, None)
    assert empresa_de(db_session) is None
    assert CLAVE_EMPRESA not in db_session.info


def test_exigir_empresa_sin_empresa_lanza(db_session):
    fijar_empresa(db_session, None)
    with pytest.raises(EmpresaNoDefinidaError):
        exigir_empresa(db_session)
    # Es un error de programación, no de usuario.
    assert issubclass(EmpresaNoDefinidaError, RuntimeError)


def test_objeto_nuevo_recibe_la_empresa_de_la_sesion(db_session):
    ciudad = Ciudad(nombre="Sucre", departamento="Chuquisaca")
    assert ciudad.empresa_id is None
    db_session.add(ciudad)
    db_session.flush()
    assert ciudad.empresa_id == 1


def test_objeto_con_la_misma_empresa_de_la_sesion_se_acepta(db_session):
    ciudad = Ciudad(nombre="Oruro", departamento="Oruro", empresa_id=1)
    db_session.add(ciudad)
    db_session.flush()
    assert ciudad.empresa_id == 1


def test_objeto_con_otra_empresa_lanza_error(db_session):
    otra = crear_empresa(db_session, "otra")
    db_session.add(Color(nombre="Rojo", empresa_id=otra.id))
    with pytest.raises(EmpresaNoDefinidaError):
        db_session.flush()
    db_session.rollback()


def test_cambiar_la_empresa_de_la_sesion_hace_expunge_all(db_session):
    otra = crear_empresa(db_session, "otra")
    rol = db_session.scalar(select(Rol).limit(1))
    assert rol in db_session

    fijar_empresa(db_session, otra.id)

    assert rol not in db_session
    assert empresa_de(db_session) == otra.id


def test_fijar_la_misma_empresa_no_vacia_la_sesion(db_session):
    rol = db_session.scalar(select(Rol).limit(1))
    fijar_empresa(db_session, empresa_de(db_session))
    assert rol in db_session


def test_usuario_sin_empresa_en_la_sesion_queda_con_empresa_null(db_session):
    fijar_empresa(db_session, None)
    usuario = _usuario("super@example.com")
    db_session.add(usuario)
    db_session.flush()
    assert usuario.empresa_id is None


def test_usuario_con_empresa_en_la_sesion_la_recibe(db_session):
    usuario = _usuario()
    db_session.add(usuario)
    db_session.flush()
    assert usuario.empresa_id == 1


def test_tabla_global_se_inserta_sin_empresa_en_la_sesion(db_session):
    fijar_empresa(db_session, None)
    rol = Rol(nombre="rol_global_de_prueba")
    db_session.add(rol)
    db_session.flush()
    assert rol.id is not None
    assert not hasattr(rol, "empresa_id")


def test_tabla_de_empresa_sin_empresa_en_la_sesion_lanza(db_session):
    fijar_empresa(db_session, None)
    db_session.add(Ciudad(nombre="Tarija"))
    with pytest.raises(EmpresaNoDefinidaError):
        db_session.flush()
    db_session.rollback()


def test_sesion_sin_empresa_respeta_el_empresa_id_explicito(db_session):
    """Así crea el superadministrador la suscripción de una empresa nueva."""
    otra_id = crear_empresa(db_session, "otra").id
    fijar_empresa(db_session, None)
    ciudad = Ciudad(nombre="Cobija", empresa_id=otra_id)
    db_session.add(ciudad)
    db_session.flush()
    assert ciudad.empresa_id == otra_id
    assert db_session.scalar(select(Suscripcion.id).where(Suscripcion.empresa_id == otra_id)) is not None
