"""E03, PASO 5: recuperar la contraseña con empresa.

/auth/recuperar responde SIEMPRE lo mismo (202, mismo texto) exista o no la
empresa o el correo; el token de reset lleva `empresa_id` y la huella del hash
("ph"), así que solo cambia la contraseña de esa empresa y solo sirve una vez;
el superadministrador no recupera su clave por aquí. Usan `client_por_peticion`
(sesión nueva y sin empresa por petición) y `dos_empresas`."""

import datetime as dt
import logging
from types import SimpleNamespace

import jwt

from app.core.rate_limit import limiter
from app.core.security import crear_reset_token, huella_de_password, settings
from app.core.tenant import empresa_de, fijar_empresa, fijar_plataforma
from app.plataforma import router as router_plataforma
from app.plataforma.casos_uso import cu01_autenticar_registrar_usuarios as cu01
from app.plataforma.models import Empresa, Usuario
from app.plataforma.repository import UsuarioRepository
from scripts.crear_superadmin import crear_superadmin

CLAVE = "claveSegura123"
NUEVA = "nuevaClave456"
CORREO = "cliente@example.com"
CORREO_SUPER = "super@plataforma.example.com"
TEXTO = "Si el correo está registrado, se enviarán instrucciones de recuperación."


def _registrar(client, codigo: str, email: str = CORREO) -> dict:
    respuesta = client.post(
        f"/api/v1/public/{codigo}/registro",
        json={"nombre": "Cli", "apellido": "Ente", "email": email, "password": CLAVE},
    )
    assert respuesta.status_code == 201
    return respuesta.json()


def _recuperar(client, empresa: str | None, email: str = CORREO):
    cuerpo = {"email": email} if empresa is None else {"empresa": empresa, "email": email}
    return client.post("/api/v1/auth/recuperar", json=cuerpo)


def _confirmar(client, token: str, password: str = NUEVA):
    return client.post("/api/v1/auth/recuperar/confirmar", json={"token": token, "password": password})


def _login(client, empresa: str, password: str, email: str = CORREO):
    return client.post("/api/v1/auth/login", json={"empresa": empresa, "email": email, "password": password})


def _hash_de(db, empresa_id: int, usuario_id: int) -> str:
    original = empresa_de(db)
    fijar_empresa(db, empresa_id)
    try:
        db.expire_all()
        return db.get(Usuario, usuario_id).password_hash
    finally:
        fijar_empresa(db, original)


def test_recuperar_con_empresa_devuelve_token_dev_en_local(client_por_peticion, dos_empresas):
    usuario = _registrar(client_por_peticion, "tienda-a")

    respuesta = _recuperar(client_por_peticion, "tienda-a")

    assert respuesta.status_code == 202
    assert respuesta.json()["detail"] == TEXTO
    payload = jwt.decode(respuesta.json()["token_dev"], settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["tipo"] == "reset"
    assert payload["sub"] == str(usuario["id"])
    assert payload["empresa_id"] == dos_empresas.a.id
    assert "ph" in payload


def test_la_respuesta_es_identica_con_empresa_o_correo_desconocidos(client_por_peticion, dos_empresas, db_session):
    _registrar(client_por_peticion, "tienda-a")
    # B queda inactiva, aunque su administrador exista.
    db_session.execute(Empresa.__table__.update().where(Empresa.id == dos_empresas.b.id).values(activo=False))
    db_session.commit()

    desconocidas = {
        "empresa inexistente": _recuperar(client_por_peticion, "no-existe"),
        "correo inexistente": _recuperar(client_por_peticion, "tienda-a", "nadie@example.com"),
        "correo de otra empresa": _recuperar(client_por_peticion, "tienda-b"),
        "empresa inactiva": _recuperar(client_por_peticion, "tienda-b", "admin@tienda-b.example.com"),
        "empresa vacia": _recuperar(client_por_peticion, "   "),
    }

    for nombre, respuesta in desconocidas.items():
        assert respuesta.status_code == 202, nombre
        assert respuesta.json() == {"detail": TEXTO, "token_dev": None}, nombre

    limiter.reset()  # el límite de 5/minute por IP ya se gastó con las de arriba
    # La existente se distingue SOLO por token_dev (que solo se entrega en local).
    existente = _recuperar(client_por_peticion, "tienda-a")
    assert existente.status_code == 202
    assert {k: v for k, v in existente.json().items() if k != "token_dev"} == {"detail": TEXTO}


def test_confirmar_cambia_solo_la_contrasena_de_esa_empresa(client_por_peticion, dos_empresas, db_session):
    en_a = _registrar(client_por_peticion, "tienda-a")
    en_b = _registrar(client_por_peticion, "tienda-b")
    hash_b = _hash_de(db_session, dos_empresas.b.id, en_b["id"])
    token = _recuperar(client_por_peticion, "tienda-a").json()["token_dev"]

    respuesta = _confirmar(client_por_peticion, token)

    assert respuesta.status_code == 200
    assert _login(client_por_peticion, "tienda-a", NUEVA).status_code == 200
    assert _login(client_por_peticion, "tienda-a", CLAVE).status_code == 401
    # El mismo correo en la otra tienda no se toca.
    assert _hash_de(db_session, dos_empresas.b.id, en_b["id"]) == hash_b
    assert _login(client_por_peticion, "tienda-b", CLAVE).status_code == 200
    assert _login(client_por_peticion, "tienda-b", NUEVA).status_code == 401
    assert en_a["id"] != en_b["id"]


def test_un_token_de_reset_sin_empresa_id_devuelve_401(client_por_peticion, dos_empresas, db_session):
    usuario = _registrar(client_por_peticion, "tienda-a")
    hash_actual = _hash_de(db_session, dos_empresas.a.id, usuario["id"])
    sin_claim = jwt.encode(
        {
            "sub": str(usuario["id"]),
            "tipo": "reset",
            "ph": huella_de_password(hash_actual),
            "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    respuesta = _confirmar(client_por_peticion, sin_claim)

    assert respuesta.status_code == 401
    assert _login(client_por_peticion, "tienda-a", CLAVE).status_code == 200


def test_el_superadministrador_no_recupera_su_clave_por_aqui(client_por_peticion, dos_empresas, db_session):
    original = empresa_de(db_session)
    crear_superadmin(db_session, CORREO_SUPER, CLAVE)
    fijar_empresa(db_session, original)

    sin_empresa = _recuperar(client_por_peticion, None, CORREO_SUPER)
    con_empresa = _recuperar(client_por_peticion, "tienda-a", CORREO_SUPER)

    assert sin_empresa.status_code == con_empresa.status_code == 202
    assert sin_empresa.json() == con_empresa.json() == {"detail": TEXTO, "token_dev": None}

    # Y un token de reset fabricado a mano para el superadministrador tampoco sirve.
    fijar_plataforma(db_session)
    try:
        superadmin = UsuarioRepository().obtener_sin_empresa_por_correo(db_session, CORREO_SUPER)
        token = crear_reset_token(superadmin.id, empresa_id=None, password_hash=superadmin.password_hash)
    finally:
        fijar_empresa(db_session, original)

    assert _confirmar(client_por_peticion, token).status_code == 401
    assert client_por_peticion.post(
        "/api/v1/auth/login", json={"email": CORREO_SUPER, "password": CLAVE}
    ).status_code == 200


def test_el_token_de_reset_no_se_puede_reutilizar(client_por_peticion, dos_empresas):
    _registrar(client_por_peticion, "tienda-a")
    token = _recuperar(client_por_peticion, "tienda-a").json()["token_dev"]

    primero = _confirmar(client_por_peticion, token, "primeraNueva1")
    segundo = _confirmar(client_por_peticion, token, "segundaNueva2")

    assert primero.status_code == 200
    assert segundo.status_code == 401
    assert _login(client_por_peticion, "tienda-a", "primeraNueva1").status_code == 200
    assert _login(client_por_peticion, "tienda-a", "segundaNueva2").status_code == 401


def test_un_token_de_reset_de_a_no_sirve_para_un_usuario_de_b(client_por_peticion, dos_empresas, db_session):
    _registrar(client_por_peticion, "tienda-a")
    en_b = _registrar(client_por_peticion, "tienda-b")
    hash_b = _hash_de(db_session, dos_empresas.b.id, en_b["id"])
    # El usuario es de B pero el token dice que es de A.
    token = crear_reset_token(en_b["id"], empresa_id=dos_empresas.a.id, password_hash=hash_b)

    respuesta = _confirmar(client_por_peticion, token)

    assert respuesta.status_code == 401
    assert _hash_de(db_session, dos_empresas.b.id, en_b["id"]) == hash_b
    assert _login(client_por_peticion, "tienda-b", CLAVE).status_code == 200


def test_el_token_solo_se_registra_en_el_log_en_entorno_local(client_por_peticion, dos_empresas, monkeypatch, caplog):
    _registrar(client_por_peticion, "tienda-a")

    with caplog.at_level(logging.INFO):
        token = _recuperar(client_por_peticion, "tienda-a").json()["token_dev"]
    assert any(token in registro.getMessage() for registro in caplog.records)

    caplog.clear()
    produccion = lambda: SimpleNamespace(environment="production")  # noqa: E731
    monkeypatch.setattr(cu01, "get_settings", produccion)
    monkeypatch.setattr(router_plataforma, "get_settings", produccion)
    with caplog.at_level(logging.INFO):
        respuesta = _recuperar(client_por_peticion, "tienda-a")
    assert respuesta.status_code == 202
    assert respuesta.json()["token_dev"] is None
    assert not [r for r in caplog.records if "Token de recuperación" in r.getMessage()]
