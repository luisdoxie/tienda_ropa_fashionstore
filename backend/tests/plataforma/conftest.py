"""Fixtures de las pruebas de CU-04 (E04): el superadministrador ya logueado."""

import pytest

from tests.conftest import crear_superadmin_de_prueba
from tests.plataforma.ayudas_empresas import CLAVE, CORREO_SUPERADMIN


@pytest.fixture()
def superadmin_headers(client_por_peticion, db_session) -> dict:
    """Cabeceras del superadministrador (usuario sin empresa), logueado por
    HTTP como lo haría su pantalla: POST /auth/login sin `empresa`."""
    crear_superadmin_de_prueba(db_session, CORREO_SUPERADMIN, CLAVE)
    respuesta = client_por_peticion.post("/api/v1/auth/login", json={"email": CORREO_SUPERADMIN, "password": CLAVE})
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}
