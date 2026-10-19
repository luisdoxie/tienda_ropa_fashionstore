"""core/security.py: emisión y decodificación de JWT, get_current_user,
get_current_user_opcional y require_permission. Comportamiento fijado antes
del refactor (punto 8 de 2.1 del análisis) y actualizado donde el refactor lo
cambió (sub inválido -> 401, exp obligatoria)."""

import datetime as dt

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.core.exceptions import PermisoDenegadoError
from app.core.security import (
    _crear_token,
    crear_access_token,
    crear_refresh_token,
    crear_reset_token,
    decodificar_token,
    get_current_user,
    get_current_user_opcional,
    require_permission,
    settings,
    usuario_id_de_payload,
)
from app.main import app
from app.plataforma.models import Usuario
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear

RUTA_PROTEGIDA = "/api/v1/auth/yo"


def _credenciales(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _encabezado(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _vencido(tipo: str = "access", usuario_id: int = 1) -> str:
    return _crear_token(usuario_id, tipo=tipo, expira=dt.timedelta(seconds=-60))


def _crear_usuario(db, email: str = "seg@example.com") -> Usuario:
    return UsuarioRepository().crear(
        db, UsuarioCrear(nombre="Seg", apellido="Uridad", email=email, password="claveSegura123")
    )


def _firmar(payload: dict, secreto: str = None, algoritmo: str = None) -> str:
    return jwt.encode(
        payload, secreto or settings.jwt_secret_key, algorithm=algoritmo or settings.jwt_algorithm
    )


def _firmar_vigente(payload: dict) -> str:
    """Firmado con la clave real y con `exp` futuro: para que la prueba falle
    por lo que se quiere probar (p. ej. el `sub`) y no por falta de `exp`."""
    vence = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
    return _firmar({**payload, "exp": vence})


def _cliente_sin_reraise() -> TestClient:
    """Un TestClient que devuelve el 500 en vez de relanzar la excepción
    (los overrides de dependencias viven en `app`, así que comparte la BD del
    fixture `client`)."""
    return TestClient(app, raise_server_exceptions=False)


# ---- Emisión y decodificación -----------------------------------------------------------


def test_access_token_lleva_sub_tipo_roles_y_permisos():
    token = crear_access_token(7, ["administrador"], ["roles.gestionar"])

    payload = decodificar_token(token)

    assert payload["sub"] == "7"
    assert payload["tipo"] == "access"
    assert payload["roles"] == ["administrador"]
    assert payload["permisos"] == ["roles.gestionar"]
    assert payload["exp"] > payload["iat"]
    assert "password" not in payload


def test_refresh_token_lleva_tipo_refresh_y_no_lleva_roles_ni_permisos():
    payload = decodificar_token(crear_refresh_token(7))

    assert payload["sub"] == "7"
    assert payload["tipo"] == "refresh"
    assert "roles" not in payload
    assert "permisos" not in payload


def test_reset_token_tiene_tipo_reset_y_vence_en_treinta_minutos():
    payload = decodificar_token(crear_reset_token(7))

    assert payload["tipo"] == "reset"
    assert payload["exp"] - payload["iat"] == 30 * 60


def test_vigencias_de_access_y_refresh_salen_de_la_configuracion():
    access = decodificar_token(crear_access_token(1, [], []))
    refresh = decodificar_token(crear_refresh_token(1))

    assert access["exp"] - access["iat"] == settings.jwt_access_token_expire_minutes * 60
    assert refresh["exp"] - refresh["iat"] == settings.jwt_refresh_token_expire_days * 86400


def test_decodificar_token_vencido_lanza_401():
    with pytest.raises(HTTPException) as error:
        decodificar_token(_vencido())

    assert error.value.status_code == 401
    assert error.value.detail == "Token inválido o expirado"


def test_decodificar_token_con_firma_invalida_lanza_401():
    ajeno = _firmar({"sub": "1", "tipo": "access"}, secreto="otra-clave-distinta-de-32-bytes-minimo!!")

    with pytest.raises(HTTPException) as error:
        decodificar_token(ajeno)

    assert error.value.status_code == 401


def test_decodificar_token_basura_lanza_401():
    with pytest.raises(HTTPException) as error:
        decodificar_token("esto-no-es-un-jwt")

    assert error.value.status_code == 401


def test_decodificar_token_con_algoritmo_none_se_rechaza():
    sin_firma = jwt.encode({"sub": "1", "tipo": "access"}, key="", algorithm="none")

    with pytest.raises(HTTPException) as error:
        decodificar_token(sin_firma)

    assert error.value.status_code == 401


def test_decodificar_token_sin_exp_se_rechaza():
    # Un token firmado sin vencimiento serviría para siempre: la claim `exp`
    # es obligatoria (antes se aceptaba).
    sin_exp = _firmar({"sub": "1", "tipo": "access"})

    with pytest.raises(HTTPException) as error:
        decodificar_token(sin_exp)

    assert error.value.status_code == 401
    assert error.value.detail == "Token inválido o expirado"


def test_decodificar_token_con_tipo_acepta_el_tipo_pedido_y_rechaza_otro():
    refresh = crear_refresh_token(7)

    assert decodificar_token(refresh, tipo="refresh")["sub"] == "7"
    with pytest.raises(HTTPException) as error:
        decodificar_token(refresh, tipo="access")

    assert error.value.status_code == 401
    assert error.value.detail == "Token inválido"


def test_decodificar_token_sin_tipo_no_comprueba_el_tipo():
    assert decodificar_token(crear_reset_token(7))["tipo"] == "reset"


def test_usuario_id_de_payload_devuelve_el_entero_o_none():
    assert usuario_id_de_payload({"sub": "12"}) == 12
    assert usuario_id_de_payload({"sub": "abc"}) is None
    assert usuario_id_de_payload({"sub": None}) is None
    assert usuario_id_de_payload({}) is None


# ---- get_current_user (directo) -----------------------------------------------------------


def test_get_current_user_sin_credenciales_lanza_401(db_session):
    with pytest.raises(HTTPException) as error:
        get_current_user(None, db_session)

    assert error.value.status_code == 401
    assert error.value.detail == "No autenticado"


def test_get_current_user_con_token_valido_devuelve_el_usuario(db_session):
    usuario = _crear_usuario(db_session)
    token = crear_access_token(usuario.id, [], [])

    resultado = get_current_user(_credenciales(token), db_session)

    assert resultado.id == usuario.id


def test_get_current_user_rechaza_refresh_como_access(db_session):
    usuario = _crear_usuario(db_session)

    with pytest.raises(HTTPException) as error:
        get_current_user(_credenciales(crear_refresh_token(usuario.id)), db_session)

    assert error.value.status_code == 401
    assert error.value.detail == "Token inválido"


def test_get_current_user_rechaza_reset_como_access(db_session):
    usuario = _crear_usuario(db_session)

    with pytest.raises(HTTPException) as error:
        get_current_user(_credenciales(crear_reset_token(usuario.id)), db_session)

    assert error.value.status_code == 401


def test_get_current_user_rechaza_token_vencido(db_session):
    usuario = _crear_usuario(db_session)

    with pytest.raises(HTTPException) as error:
        get_current_user(_credenciales(_vencido("access", usuario.id)), db_session)

    assert error.value.status_code == 401


def test_get_current_user_usuario_inexistente_lanza_401(db_session):
    with pytest.raises(HTTPException) as error:
        get_current_user(_credenciales(crear_access_token(999_999, [], [])), db_session)

    assert error.value.status_code == 401
    assert error.value.detail == "Usuario inválido"


def test_get_current_user_usuario_inactivo_lanza_401(db_session):
    usuario = _crear_usuario(db_session)
    token = crear_access_token(usuario.id, [], [])
    usuario.activo = False
    db_session.commit()

    with pytest.raises(HTTPException) as error:
        get_current_user(_credenciales(token), db_session)

    assert error.value.status_code == 401
    assert error.value.detail == "Usuario inválido"


def test_get_current_user_sub_no_numerico_lanza_401(db_session):
    # Antes `int(payload["sub"])` reventaba con ValueError (500).
    token = _firmar_vigente({"sub": "abc", "tipo": "access"})

    with pytest.raises(HTTPException) as error:
        get_current_user(_credenciales(token), db_session)

    assert error.value.status_code == 401
    assert error.value.detail == "Token inválido"


def test_get_current_user_sin_claim_sub_lanza_401(db_session):
    # Antes revientaba con KeyError (500).
    token = _firmar_vigente({"tipo": "access"})

    with pytest.raises(HTTPException) as error:
        get_current_user(_credenciales(token), db_session)

    assert error.value.status_code == 401
    assert error.value.detail == "Token inválido"


def test_get_current_user_rechaza_token_sin_exp(db_session):
    usuario = _crear_usuario(db_session)
    token = _firmar({"sub": str(usuario.id), "tipo": "access"})

    with pytest.raises(HTTPException) as error:
        get_current_user(_credenciales(token), db_session)

    assert error.value.status_code == 401


# ---- get_current_user vía HTTP ------------------------------------------------------------


def test_http_sin_token_devuelve_401(client):
    respuesta = client.get(RUTA_PROTEGIDA)

    assert respuesta.status_code == 401
    assert respuesta.json()["detail"] == "No autenticado"


def test_http_token_valido_devuelve_200(client, db_session):
    usuario = _crear_usuario(db_session)

    respuesta = client.get(RUTA_PROTEGIDA, headers=_encabezado(crear_access_token(usuario.id, [], [])))

    assert respuesta.status_code == 200
    assert respuesta.json()["email"] == "seg@example.com"


def test_http_refresh_token_como_access_devuelve_401(client, db_session):
    usuario = _crear_usuario(db_session)

    respuesta = client.get(RUTA_PROTEGIDA, headers=_encabezado(crear_refresh_token(usuario.id)))

    assert respuesta.status_code == 401


def test_http_token_vencido_devuelve_401(client, db_session):
    usuario = _crear_usuario(db_session)

    respuesta = client.get(RUTA_PROTEGIDA, headers=_encabezado(_vencido("access", usuario.id)))

    assert respuesta.status_code == 401


def test_http_firma_invalida_devuelve_401(client, db_session):
    usuario = _crear_usuario(db_session)
    ajeno = _firmar(
        {"sub": str(usuario.id), "tipo": "access"}, secreto="otra-clave-distinta-de-32-bytes-minimo!!"
    )

    respuesta = client.get(RUTA_PROTEGIDA, headers=_encabezado(ajeno))

    assert respuesta.status_code == 401


def test_http_usuario_desactivado_con_token_vigente_devuelve_401(client, db_session):
    usuario = _crear_usuario(db_session)
    token = crear_access_token(usuario.id, [], [])
    usuario.activo = False
    db_session.commit()

    respuesta = client.get(RUTA_PROTEGIDA, headers=_encabezado(token))

    assert respuesta.status_code == 401


def test_http_sub_no_numerico_devuelve_401(client):
    # Antes era un 500 ("Error interno del servidor").
    token = _firmar_vigente({"sub": "abc", "tipo": "access"})

    respuesta = _cliente_sin_reraise().get(RUTA_PROTEGIDA, headers=_encabezado(token))

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "Token inválido"}


def test_http_sin_claim_sub_devuelve_401(client):
    token = _firmar_vigente({"tipo": "access"})

    respuesta = _cliente_sin_reraise().get(RUTA_PROTEGIDA, headers=_encabezado(token))

    assert respuesta.status_code == 401


def test_http_token_firmado_sin_exp_devuelve_401(client, db_session):
    usuario = _crear_usuario(db_session)
    token = _firmar({"sub": str(usuario.id), "tipo": "access"})

    respuesta = client.get(RUTA_PROTEGIDA, headers=_encabezado(token))

    assert respuesta.status_code == 401


# ---- get_current_user_opcional ------------------------------------------------------------


def test_opcional_sin_token_devuelve_none(db_session):
    assert get_current_user_opcional(None, db_session) is None


def test_opcional_con_token_valido_devuelve_el_usuario(db_session):
    usuario = _crear_usuario(db_session)

    resultado = get_current_user_opcional(_credenciales(crear_access_token(usuario.id, [], [])), db_session)

    assert resultado.id == usuario.id


def test_opcional_con_token_invalido_vencido_o_de_otro_tipo_devuelve_none(db_session):
    usuario = _crear_usuario(db_session)

    assert get_current_user_opcional(_credenciales("basura"), db_session) is None
    assert get_current_user_opcional(_credenciales(_vencido("access", usuario.id)), db_session) is None
    assert get_current_user_opcional(_credenciales(crear_refresh_token(usuario.id)), db_session) is None


def test_opcional_con_usuario_inexistente_o_inactivo_devuelve_none(db_session):
    usuario = _crear_usuario(db_session)
    token = crear_access_token(usuario.id, [], [])
    usuario.activo = False
    db_session.commit()

    assert get_current_user_opcional(_credenciales(token), db_session) is None
    assert get_current_user_opcional(_credenciales(crear_access_token(999_999, [], [])), db_session) is None


def test_opcional_con_sub_no_numerico_o_ausente_devuelve_none(db_session):
    # Antes el sub no numérico lanzaba ValueError (500), a diferencia del
    # resto de fallos.
    no_numerico = _firmar_vigente({"sub": "abc", "tipo": "access"})
    sin_sub = _firmar_vigente({"tipo": "access"})

    assert get_current_user_opcional(_credenciales(no_numerico), db_session) is None
    assert get_current_user_opcional(_credenciales(sin_sub), db_session) is None


def test_opcional_con_token_sin_exp_devuelve_none(db_session):
    usuario = _crear_usuario(db_session)
    token = _firmar({"sub": str(usuario.id), "tipo": "access"})

    assert get_current_user_opcional(_credenciales(token), db_session) is None


def test_endpoint_publico_con_opcional_acepta_peticion_anonima_y_con_token_invalido(client):
    # POST /ia/voz admite búsqueda anónima: ni sin token ni con token basura
    # debe devolver 401 por la dependencia (el cuerpo vacío da 422, no 401).
    anonima = client.post("/api/v1/ia/voz", json={})
    basura = client.post("/api/v1/ia/voz", json={}, headers=_encabezado("basura"))

    assert anonima.status_code != 401
    assert basura.status_code != 401


# ---- require_permission -------------------------------------------------------------------


def test_require_permission_sin_el_permiso_lanza_permiso_denegado(db_session):
    usuario = _crear_usuario(db_session)  # sin roles, sin permisos

    with pytest.raises(PermisoDenegadoError, match="Falta el permiso 'roles.gestionar'"):
        require_permission("roles.gestionar")(usuario, db_session)


def test_require_permission_con_el_permiso_devuelve_el_usuario(db_session):
    usuario = _crear_usuario(db_session, email="perm@example.com")
    UsuarioRepository().asignar_roles(db_session, usuario, ["administrador"])

    resultado = require_permission("roles.gestionar")(usuario, db_session)

    assert resultado is usuario


def test_require_permission_http_403_sin_permiso_y_200_con_permiso(client, admin_headers, cliente_headers):
    assert client.get("/api/v1/roles", headers=cliente_headers).status_code == 403
    assert client.get("/api/v1/roles", headers=admin_headers).status_code == 200


def test_require_permission_http_sin_token_es_401_no_403(client):
    assert client.get("/api/v1/roles").status_code == 401


def test_require_permission_ignora_los_permisos_del_jwt(client, db_session):
    # El token afirma tener el permiso, pero la fuente de verdad es la base.
    usuario = _crear_usuario(db_session, email="mentiroso@example.com")
    token = crear_access_token(usuario.id, ["administrador"], ["roles.gestionar"])

    respuesta = client.get("/api/v1/roles", headers=_encabezado(token))

    assert respuesta.status_code == 403


def test_require_permission_ignora_roles_inactivos(client, db_session, admin_headers):
    from app.plataforma.models import Rol

    rol = db_session.query(Rol).filter(Rol.nombre == "administrador").one()
    rol.activo = False
    db_session.commit()

    assert client.get("/api/v1/roles", headers=admin_headers).status_code == 403
