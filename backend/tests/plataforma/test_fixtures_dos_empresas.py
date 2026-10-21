"""Humo de las fixtures `dos_empresas` y `client_por_peticion` (las usan las
pruebas de aislamiento): el token de cada administrador entra a SU empresa."""

from sqlalchemy import select

from app.core.tenant import fijar_empresa
from app.plataforma.models import Usuario


def test_cada_administrador_entra_a_su_empresa(client_por_peticion, dos_empresas, db_session):
    for empresa in (dos_empresas.a, dos_empresas.b):
        respuesta = client_por_peticion.get("/api/v1/auth/yo", headers=empresa.headers)
        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["email"] == f"admin@{empresa.codigo}.example.com"


def test_las_dos_empresas_son_distintas_y_la_sesion_queda_como_estaba(dos_empresas, db_session):
    assert dos_empresas.a.id != dos_empresas.b.id
    assert db_session.info["empresa_id"] == 1  # la empresa de las semillas
    fijar_empresa(db_session, dos_empresas.b.id)
    emails = db_session.scalars(select(Usuario.email).where(Usuario.email.like("admin@tienda-%"))).all()
    assert emails == ["admin@tienda-b.example.com"]
