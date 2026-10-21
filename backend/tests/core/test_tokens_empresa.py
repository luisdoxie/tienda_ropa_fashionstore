"""E03: el claim `empresa_id` de los tokens y su cruce con la base.

Los tokens que se construyen a mano se firman con la clave real de las pruebas,
así que lo único que cambia entre uno válido y uno que debe rechazarse es el
claim."""

import datetime as dt

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import get_settings
from app.core.security import (
    crear_access_token,
    crear_refresh_token,
    crear_reset_token,
    decodificar_token,
    get_current_user_opcional,
)
from app.plataforma.models import Empresa
from tests.conftest import crear_superadmin_de_prueba

YO = "/api/v1/auth/yo"


def _firmar(**claims) -> str:
    """Un token firmado con la clave de las pruebas y SOLO los claims dados."""
    ajustes = get_settings()
    ahora = dt.datetime.now(dt.timezone.utc)
    base = {"iat": ahora, "exp": ahora + dt.timedelta(minutes=5)}
    return jwt.encode({**base, **claims}, ajustes.jwt_secret_key, algorithm=ajustes.jwt_algorithm)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_crear_token_pide_empresa_id_como_argumento():
    with pytest.raises(TypeError):
        crear_access_token(1, [], [])
    with pytest.raises(TypeError):
        crear_refresh_token(1)
    with pytest.raises(TypeError):
        crear_reset_token(1, password_hash="x")


def test_los_tres_tokens_llevan_el_claim_aunque_sea_null():
    for token, tipo in (
        (crear_access_token(1, [], [], empresa_id=7), "access"),
        (crear_refresh_token(1, empresa_id=7), "refresh"),
        (crear_reset_token(1, empresa_id=7, password_hash="h"), "reset"),
    ):
        assert decodificar_token(token, tipo=tipo)["empresa_id"] == 7
    assert decodificar_token(crear_refresh_token(1, empresa_id=None), tipo="refresh")["empresa_id"] is None


def test_un_token_sin_el_claim_no_vale_en_ninguna_parte(client_por_peticion, dos_empresas):
    a = dos_empresas.a
    sin_claim = _firmar(sub=str(a.admin_id), tipo="access", roles=[], permisos=[])
    assert client_por_peticion.get(YO, headers=_bearer(sin_claim)).status_code == 401

    refresco = _firmar(sub=str(a.admin_id), tipo="refresh")
    assert client_por_peticion.post("/api/v1/auth/refresh", json={"refresh_token": refresco}).status_code == 401

    reset = _firmar(sub=str(a.admin_id), tipo="reset", ph="0" * 16)
    cuerpo = {"token": reset, "password": "nuevaClave12345"}
    assert client_por_peticion.post("/api/v1/auth/recuperar/confirmar", json=cuerpo).status_code == 401


def test_el_usuario_opcional_ignora_un_token_sin_claim(db_session, dos_empresas):
    sin_claim = _firmar(sub=str(dos_empresas.a.admin_id), tipo="access")
    credenciales = HTTPAuthorizationCredentials(scheme="Bearer", credentials=sin_claim)
    assert get_current_user_opcional(credenciales, db_session) is None


def test_un_claim_distinto_de_la_fila_se_rechaza(client_por_peticion, dos_empresas):
    a, b = dos_empresas.a, dos_empresas.b
    token = crear_access_token(a.admin_id, ["administrador"], [], empresa_id=b.id)
    assert client_por_peticion.get(YO, headers=_bearer(token)).status_code == 401


def test_un_claim_null_con_usuario_de_empresa_se_rechaza(client_por_peticion, dos_empresas):
    token = crear_access_token(dos_empresas.a.admin_id, ["administrador"], [], empresa_id=None)
    assert client_por_peticion.get(YO, headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize("invalido", ["1", True, 1.5, [1], {"id": 1}])
def test_un_claim_que_no_es_entero_ni_null_se_rechaza(client_por_peticion, dos_empresas, invalido):
    token = _firmar(sub=str(dos_empresas.a.admin_id), tipo="access", empresa_id=invalido)
    assert client_por_peticion.get(YO, headers=_bearer(token)).status_code == 401


def test_una_empresa_inactiva_deja_sin_acceso_a_sus_tokens(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    assert client_por_peticion.get(YO, headers=a.headers).status_code == 200
    db_session.get(Empresa, a.id).activo = False
    db_session.commit()
    assert client_por_peticion.get(YO, headers=a.headers).status_code == 401


def test_el_superadministrador_entra_y_deja_el_modo_plataforma(client_por_peticion, db_session):
    usuario_id = crear_superadmin_de_prueba(db_session)
    token = crear_access_token(usuario_id, ["superadministrador"], [], empresa_id=None)
    assert client_por_peticion.get(YO, headers=_bearer(token)).status_code == 200
    # Modo plataforma: una ruta de negocio que no pide permiso responde 403.
    negocio = client_por_peticion.get("/api/v1/catalogo", headers=_bearer(token))
    assert negocio.status_code == 403


def test_un_token_adulterado_o_firmado_con_otra_clave_se_rechaza(client_por_peticion, dos_empresas):
    a, b = dos_empresas.a, dos_empresas.b
    otra_clave = jwt.encode(
        {"sub": str(a.admin_id), "tipo": "access", "empresa_id": a.id, "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)},
        "otra-clave-que-no-es-la-del-servidor",
        algorithm="HS256",
    )
    assert client_por_peticion.get(YO, headers=_bearer(otra_clave)).status_code == 401

    # Cambiar el claim sin volver a firmar invalida la firma.
    valido = crear_access_token(a.admin_id, ["administrador"], [], empresa_id=a.id)
    cabecera, cuerpo, firma = valido.split(".")
    adulterado = jwt.encode({"empresa_id": b.id}, "x", algorithm="HS256").split(".")[1]
    assert client_por_peticion.get(YO, headers=_bearer(f"{cabecera}.{adulterado}.{firma}")).status_code == 401


def test_el_token_de_una_empresa_no_alcanza_los_recursos_de_otra(client_por_peticion, dos_empresas):
    a, b = dos_empresas.a, dos_empresas.b
    propio = client_por_peticion.get(f"/api/v1/usuarios/{a.admin_id}", headers=a.headers)
    ajeno = client_por_peticion.get(f"/api/v1/usuarios/{b.admin_id}", headers=a.headers)
    assert propio.status_code == 200
    assert ajeno.status_code == 404
