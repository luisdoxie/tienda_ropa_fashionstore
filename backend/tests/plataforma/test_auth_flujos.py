"""Flujos de autenticación que test_auth.py no cubre: /auth/refresh,
/auth/recuperar, /auth/recuperar/confirmar, /auth/yo y bordes de /auth/login.
Comportamiento actual, fijado antes del refactor (puntos 6, 8 y 9 de 2.1)."""

import datetime as dt
from types import SimpleNamespace

import jwt

from app.core.security import (
    _crear_token,
    crear_access_token,
    crear_refresh_token,
    crear_reset_token,
    decodificar_token,
    settings,
)
from app.plataforma import router as router_plataforma
from app.plataforma.models import Usuario
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear

CLAVE = "claveSegura123"


def _usuario(db, email="flujo@example.com", password=CLAVE) -> Usuario:
    return UsuarioRepository().crear(
        db, UsuarioCrear(nombre="Flu", apellido="Jo", email=email, password=password)
    )


def _login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _con(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _firmar(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _vencido(tipo: str, usuario_id: int) -> str:
    return _crear_token(usuario_id, tipo=tipo, expira=dt.timedelta(seconds=-60))


def _pedir_reset(client, email) -> str:
    respuesta = client.post("/api/v1/auth/recuperar", json={"email": email})
    assert respuesta.status_code == 202
    return respuesta.json()["token_dev"]


# ---- /auth/login (bordes) -------------------------------------------------------------------


def test_login_con_email_inexistente_devuelve_el_mismo_401_generico(client, db_session):
    _usuario(db_session)

    inexistente = _login(client, "nadie@example.com", CLAVE)
    mala_clave = _login(client, "flujo@example.com", "otra-clave-cualquiera")

    assert inexistente.status_code == 401
    assert mala_clave.status_code == 401
    assert inexistente.json() == mala_clave.json() == {"detail": "Credenciales inválidas"}


def test_login_de_usuario_desactivado_devuelve_401(client, db_session):
    usuario = _usuario(db_session)
    usuario.activo = False
    db_session.commit()

    assert _login(client, "flujo@example.com", CLAVE).status_code == 401


def test_login_actualiza_ultimo_acceso(client, db_session):
    usuario = _usuario(db_session)
    assert usuario.ultimo_acceso is None

    assert _login(client, "flujo@example.com", CLAVE).status_code == 200

    db_session.refresh(usuario)
    assert usuario.ultimo_acceso is not None


def test_login_con_email_malformado_devuelve_422(client):
    assert _login(client, "no-es-un-correo", CLAVE).status_code == 422


def test_el_access_token_del_login_trae_los_roles_y_permisos_vigentes(client, admin_headers):
    token = _login(client, "admin@example.com", CLAVE).json()["access_token"]

    payload = decodificar_token(token)

    assert payload["tipo"] == "access"
    assert payload["roles"] == ["administrador"]
    assert "roles.gestionar" in payload["permisos"]


# ---- /auth/refresh --------------------------------------------------------------------------


def test_refresh_con_refresh_token_valido_emite_nuevos_tokens(client, db_session):
    _usuario(db_session)
    tokens = _login(client, "flujo@example.com", CLAVE).json()

    respuesta = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["token_type"] == "bearer"
    assert decodificar_token(cuerpo["access_token"])["tipo"] == "access"
    assert decodificar_token(cuerpo["refresh_token"])["tipo"] == "refresh"
    # el access nuevo sirve
    assert client.get("/api/v1/auth/yo", headers=_con(cuerpo["access_token"])).status_code == 200


def test_refresh_toma_los_roles_vigentes_y_no_los_del_token_anterior(client, db_session):
    usuario = _usuario(db_session)
    refresh = _login(client, "flujo@example.com", CLAVE).json()["refresh_token"]
    UsuarioRepository().asignar_roles(db_session, usuario, ["cajero"])

    nuevo = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).json()

    payload = decodificar_token(nuevo["access_token"])
    assert payload["roles"] == ["cajero"]
    assert "ventas.presencial" in payload["permisos"]


def test_refresh_con_access_token_devuelve_401(client, db_session):
    _usuario(db_session)
    tokens = _login(client, "flujo@example.com", CLAVE).json()

    respuesta = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})

    assert respuesta.status_code == 401
    assert respuesta.json()["detail"] == "Token inválido"


def test_refresh_con_reset_token_devuelve_401(client, db_session):
    usuario = _usuario(db_session)

    respuesta = client.post("/api/v1/auth/refresh", json={"refresh_token": crear_reset_token(usuario.id)})

    assert respuesta.status_code == 401


def test_refresh_con_token_basura_devuelve_401(client):
    respuesta = client.post("/api/v1/auth/refresh", json={"refresh_token": "esto-no-es-un-jwt"})

    assert respuesta.status_code == 401
    assert respuesta.json()["detail"] == "Token inválido o expirado"


def test_refresh_con_token_vencido_devuelve_401(client, db_session):
    usuario = _usuario(db_session)

    respuesta = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": _vencido("refresh", usuario.id)}
    )

    assert respuesta.status_code == 401


def test_refresh_con_firma_ajena_devuelve_401(client, db_session):
    usuario = _usuario(db_session)
    ajeno = jwt.encode(
        {"sub": str(usuario.id), "tipo": "refresh"},
        "otra-clave-distinta-de-32-bytes-minimo!!",
        algorithm=settings.jwt_algorithm,
    )

    assert client.post("/api/v1/auth/refresh", json={"refresh_token": ajeno}).status_code == 401


def test_refresh_de_usuario_desactivado_devuelve_401(client, db_session):
    usuario = _usuario(db_session)
    refresh = _login(client, "flujo@example.com", CLAVE).json()["refresh_token"]
    usuario.activo = False
    db_session.commit()

    respuesta = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})

    assert respuesta.status_code == 401
    assert respuesta.json()["detail"] == "Usuario inválido"


def test_refresh_de_usuario_inexistente_devuelve_401(client):
    respuesta = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": crear_refresh_token(999_999)}
    )

    assert respuesta.status_code == 401


def test_refresh_sin_cuerpo_valido_devuelve_422(client):
    assert client.post("/api/v1/auth/refresh", json={}).status_code == 422


def test_refresh_no_rota_ni_revoca_el_token_anterior(client, db_session):
    # comportamiento actual: no hay lista de revocación ni rotación; el mismo
    # refresh token se puede usar varias veces.
    _usuario(db_session)
    refresh = _login(client, "flujo@example.com", CLAVE).json()["refresh_token"]

    primero = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    segundo = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})

    assert primero.status_code == 200
    assert segundo.status_code == 200


def test_refresh_con_sub_no_numerico_o_ausente_devuelve_401(client):
    # Antes era un 500 (`int(payload["sub"])` sin capturar).
    from fastapi.testclient import TestClient

    from app.main import app

    cliente = TestClient(app, raise_server_exceptions=False)
    vence = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
    for claims in ({"sub": "abc", "tipo": "refresh"}, {"tipo": "refresh"}):
        token = _firmar({**claims, "exp": vence})

        respuesta = cliente.post("/api/v1/auth/refresh", json={"refresh_token": token})

        assert respuesta.status_code == 401
        assert respuesta.json() == {"detail": "Token inválido"}


def test_refresh_con_token_sin_exp_devuelve_401(client, db_session):
    usuario = _usuario(db_session)
    token = _firmar({"sub": str(usuario.id), "tipo": "refresh"})

    respuesta = client.post("/api/v1/auth/refresh", json={"refresh_token": token})

    assert respuesta.status_code == 401


def test_confirmar_reset_con_sub_no_numerico_devuelve_401(client):
    vence = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
    token = _firmar({"sub": "abc", "tipo": "reset", "exp": vence})

    respuesta = client.post(
        "/api/v1/auth/recuperar/confirmar", json={"token": token, "password": "nuevaClave456"}
    )

    assert respuesta.status_code == 401


# ---- /auth/yo -------------------------------------------------------------------------------


def test_yo_sin_token_devuelve_401(client):
    assert client.get("/api/v1/auth/yo").status_code == 401


def test_yo_del_administrador_trae_todos_los_permisos_del_seed(client, admin_headers):
    cuerpo = client.get("/api/v1/auth/yo", headers=admin_headers).json()

    assert cuerpo["email"] == "admin@example.com"
    assert cuerpo["roles"] == ["administrador"]
    assert cuerpo["activo"] is True
    assert {"usuarios.gestionar", "roles.gestionar", "organizacion.gestionar"} <= set(cuerpo["permisos"])
    assert "password_hash" not in cuerpo


def test_yo_refleja_permisos_en_vivo_aunque_el_token_sea_viejo(client, db_session):
    usuario = _usuario(db_session)
    token = _login(client, "flujo@example.com", CLAVE).json()["access_token"]
    assert client.get("/api/v1/auth/yo", headers=_con(token)).json()["permisos"] == []

    UsuarioRepository().asignar_roles(db_session, usuario, ["cajero"])

    cuerpo = client.get("/api/v1/auth/yo", headers=_con(token)).json()
    assert cuerpo["roles"] == ["cajero"]
    assert "ventas.presencial" in cuerpo["permisos"]


def test_yo_rechaza_un_refresh_token(client, db_session):
    usuario = _usuario(db_session)

    assert client.get("/api/v1/auth/yo", headers=_con(crear_refresh_token(usuario.id))).status_code == 401


# ---- /auth/recuperar ------------------------------------------------------------------------


def test_recuperar_en_entorno_local_devuelve_token_dev(client, db_session):
    usuario = _usuario(db_session)

    respuesta = client.post("/api/v1/auth/recuperar", json={"email": "flujo@example.com"})

    assert respuesta.status_code == 202
    cuerpo = respuesta.json()
    assert cuerpo["detail"] == "Si el correo está registrado, se enviarán instrucciones de recuperación."
    payload = decodificar_token(cuerpo["token_dev"])
    assert payload["tipo"] == "reset"
    assert payload["sub"] == str(usuario.id)


def test_recuperar_fuera_de_local_no_devuelve_token_dev(client, db_session, monkeypatch):
    _usuario(db_session)
    monkeypatch.setattr(router_plataforma, "get_settings", lambda: SimpleNamespace(environment="production"))

    respuesta = client.post("/api/v1/auth/recuperar", json={"email": "flujo@example.com"})

    assert respuesta.status_code == 202
    assert respuesta.json()["token_dev"] is None


def test_recuperar_con_email_desconocido_responde_igual_sin_token(client):
    respuesta = client.post("/api/v1/auth/recuperar", json={"email": "nadie@example.com"})

    assert respuesta.status_code == 202
    assert respuesta.json() == {
        "detail": "Si el correo está registrado, se enviarán instrucciones de recuperación.",
        "token_dev": None,
    }


def test_recuperar_con_usuario_desactivado_responde_igual_sin_token(client, db_session):
    usuario = _usuario(db_session)
    usuario.activo = False
    db_session.commit()

    respuesta = client.post("/api/v1/auth/recuperar", json={"email": "flujo@example.com"})

    assert respuesta.status_code == 202
    assert respuesta.json()["token_dev"] is None


def test_recuperar_con_email_malformado_devuelve_422(client):
    assert client.post("/api/v1/auth/recuperar", json={"email": "no-es-correo"}).status_code == 422


# ---- /auth/recuperar/confirmar ----------------------------------------------------------------


def test_restablecer_cambia_la_contrasena_la_nueva_sirve_y_la_vieja_no(client, db_session):
    _usuario(db_session)
    token = _pedir_reset(client, "flujo@example.com")

    respuesta = client.post(
        "/api/v1/auth/recuperar/confirmar", json={"token": token, "password": "nuevaClave456"}
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"detail": "Contraseña actualizada."}
    assert _login(client, "flujo@example.com", "nuevaClave456").status_code == 200
    assert _login(client, "flujo@example.com", CLAVE).status_code == 401


def test_el_token_de_reset_puede_reutilizarse(client, db_session):
    # comportamiento actual; el refactor podria volverlo de un solo uso (2.1
    # punto 6): no hay registro de tokens usados, mientras no venza (30 min)
    # el mismo token cambia la contraseña cuantas veces se quiera.
    _usuario(db_session)
    token = _pedir_reset(client, "flujo@example.com")

    primero = client.post("/api/v1/auth/recuperar/confirmar", json={"token": token, "password": "primeraNueva1"})
    segundo = client.post("/api/v1/auth/recuperar/confirmar", json={"token": token, "password": "segundaNueva2"})

    assert primero.status_code == 200
    assert segundo.status_code == 200
    assert _login(client, "flujo@example.com", "segundaNueva2").status_code == 200
    assert _login(client, "flujo@example.com", "primeraNueva1").status_code == 401


def test_restablecer_con_token_basura_devuelve_401(client):
    respuesta = client.post(
        "/api/v1/auth/recuperar/confirmar", json={"token": "no-es-un-jwt", "password": "nuevaClave456"}
    )

    assert respuesta.status_code == 401
    assert respuesta.json()["detail"] == "Token inválido o expirado"


def test_restablecer_con_token_vencido_devuelve_401_y_no_cambia_la_clave(client, db_session):
    usuario = _usuario(db_session)

    respuesta = client.post(
        "/api/v1/auth/recuperar/confirmar",
        json={"token": _vencido("reset", usuario.id), "password": "nuevaClave456"},
    )

    assert respuesta.status_code == 401
    assert _login(client, "flujo@example.com", CLAVE).status_code == 200


def test_restablecer_con_access_o_refresh_token_devuelve_401(client, db_session):
    usuario = _usuario(db_session)

    for token in (crear_access_token(usuario.id, [], []), crear_refresh_token(usuario.id)):
        respuesta = client.post(
            "/api/v1/auth/recuperar/confirmar", json={"token": token, "password": "nuevaClave456"}
        )
        assert respuesta.status_code == 401
        assert respuesta.json()["detail"] == "Token inválido"

    assert _login(client, "flujo@example.com", CLAVE).status_code == 200


def test_el_token_de_reset_no_sirve_como_access_token(client, db_session):
    usuario = _usuario(db_session)

    assert client.get("/api/v1/auth/yo", headers=_con(crear_reset_token(usuario.id))).status_code == 401


def test_restablecer_de_usuario_desactivado_devuelve_401(client, db_session):
    usuario = _usuario(db_session)
    token = _pedir_reset(client, "flujo@example.com")
    usuario.activo = False
    db_session.commit()

    respuesta = client.post(
        "/api/v1/auth/recuperar/confirmar", json={"token": token, "password": "nuevaClave456"}
    )

    assert respuesta.status_code == 401


def test_restablecer_con_contrasena_corta_o_larga_devuelve_422(client, db_session):
    _usuario(db_session)
    token = _pedir_reset(client, "flujo@example.com")

    corta = client.post("/api/v1/auth/recuperar/confirmar", json={"token": token, "password": "corta"})
    larga = client.post("/api/v1/auth/recuperar/confirmar", json={"token": token, "password": "x" * 73})

    assert corta.status_code == 422
    assert larga.status_code == 422
    assert _login(client, "flujo@example.com", CLAVE).status_code == 200


def test_restablecer_no_desactiva_ni_toca_los_demas_datos_del_usuario(client, db_session):
    usuario = _usuario(db_session)
    UsuarioRepository().asignar_roles(db_session, usuario, ["cajero"])
    token = _pedir_reset(client, "flujo@example.com")

    client.post("/api/v1/auth/recuperar/confirmar", json={"token": token, "password": "nuevaClave456"})

    db_session.refresh(usuario)
    assert usuario.activo is True
    assert [r.nombre for r in usuario.roles] == ["cajero"]
