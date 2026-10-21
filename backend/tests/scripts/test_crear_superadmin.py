"""scripts/crear_superadmin.py (E03, D06): la única vía para crear un
superadministrador (usuario sin empresa con el rol global superadministrador).

Usa la base de pruebas completa (`db_session`) y, para main(), sustituye la
sesión real por la de pruebas. Contraseñas de prueba: 'claveSegura123' y, para
restablecer, 'nuevaClave456'."""

import pytest
from sqlalchemy import func, select

from app.core.permisos import ROL_SUPERADMINISTRADOR
from app.core.security import verificar_password
from app.core.tenant import empresa_de, fijar_empresa, fijar_plataforma, sin_filtro
from app.plataforma.models import Rol, Usuario
from app.plataforma.repository import UsuarioRepository
from scripts import crear_superadmin as script
from scripts.crear_superadmin import CREADO, EXISTENTE, RESTABLECIDO, SuperadminError, crear_superadmin

CORREO = "super@plataforma.example.com"
CLAVE = "claveSegura123"
NUEVA = "nuevaClave456"


def _superadmin(db, email: str = CORREO):
    """(usuario_id, empresa_id, roles, password_hash) del usuario sin empresa con ese correo."""
    original = empresa_de(db)
    fijar_plataforma(db)
    try:
        db.expire_all()
        usuario = UsuarioRepository().obtener_sin_empresa_por_correo(db, email)
        if usuario is None:
            return None
        return usuario.id, usuario.empresa_id, [r.nombre for r in usuario.roles], usuario.password_hash
    finally:
        fijar_empresa(db, original)


def _cuantos(db, email: str) -> int:
    return db.scalar(sin_filtro(select(func.count()).select_from(Usuario).where(func.lower(Usuario.email) == email)))


@pytest.fixture()
def entorno(monkeypatch, db_session):
    """Variables de entorno del script y la sesión de pruebas en lugar de la real."""
    monkeypatch.setenv("SUPERADMIN_EMAIL", "  SUPER@Plataforma.Example.com ")
    monkeypatch.setenv("SUPERADMIN_PASSWORD", CLAVE)
    monkeypatch.setattr(script, "abrir_sesion_plataforma", lambda: db_session)
    return monkeypatch


def test_crea_el_superadministrador_desde_las_variables_de_entorno(entorno, db_session, capsys):
    script.main([])

    fila = _superadmin(db_session)
    assert fila is not None
    _, empresa_id, roles, password_hash = fila
    assert empresa_id is None
    assert roles == [ROL_SUPERADMINISTRADOR]
    assert verificar_password(CLAVE, password_hash)
    # El correo se guarda en minúsculas y sin espacios.
    assert db_session.scalar(sin_filtro(select(Usuario.email).where(Usuario.empresa_id.is_(None)))) == CORREO
    assert "creado" in capsys.readouterr().out


def test_es_idempotente(db_session):
    assert crear_superadmin(db_session, CORREO, CLAVE) == CREADO
    primero = _superadmin(db_session)

    assert crear_superadmin(db_session, CORREO, CLAVE) == EXISTENTE
    # Aunque se invoque con otra contraseña, sin --restablecer no la cambia.
    assert crear_superadmin(db_session, CORREO.upper(), NUEVA) == EXISTENTE

    assert _cuantos(db_session, CORREO) == 1
    assert _superadmin(db_session) == primero


def test_rechaza_una_contrasena_corta(db_session, entorno, capsys):
    with pytest.raises(SuperadminError):
        crear_superadmin(db_session, CORREO, "corta123")
    assert _superadmin(db_session) is None

    entorno.setenv("SUPERADMIN_PASSWORD", "corta123")
    with pytest.raises(SystemExit) as salida:
        script.main([])
    assert "12 caracteres" in str(salida.value)
    assert _superadmin(db_session) is None


def test_se_niega_si_el_correo_ya_es_de_una_empresa(db_session, dos_empresas):
    correo = "admin@tienda-a.example.com"

    with pytest.raises(SuperadminError, match="empresa"):
        crear_superadmin(db_session, correo, CLAVE)
    with pytest.raises(SuperadminError, match="empresa"):
        crear_superadmin(db_session, correo, NUEVA, restablecer=True)

    assert _superadmin(db_session, correo) is None
    assert _cuantos(db_session, correo) == 1
    # El administrador de la empresa conserva su contraseña.
    fijar_empresa(db_session, dos_empresas.a.id)
    try:
        admin = UsuarioRepository().obtener_por_email(db_session, correo)
        assert admin.empresa_id == dos_empresas.a.id
        assert verificar_password(CLAVE, admin.password_hash)
    finally:
        fijar_empresa(db_session, dos_empresas.a.id)


def test_restablecer_cambia_la_contrasena(db_session, client_por_peticion):
    crear_superadmin(db_session, CORREO, CLAVE)

    assert crear_superadmin(db_session, CORREO, NUEVA, restablecer=True) == RESTABLECIDO

    assert _cuantos(db_session, CORREO) == 1
    assert verificar_password(NUEVA, _superadmin(db_session)[3])
    entrar = lambda clave: client_por_peticion.post(  # noqa: E731
        "/api/v1/auth/login", json={"email": CORREO, "password": clave}
    ).status_code
    assert entrar(NUEVA) == 200
    assert entrar(CLAVE) == 401


def test_el_script_nunca_imprime_la_contrasena_ni_el_correo(entorno, db_session, capsys):
    casos = [
        [],  # crea
        [],  # ya existía
        ["--restablecer"],  # cambia la contraseña
    ]
    for argumentos in casos:
        script.main(argumentos)
    # Contraseña corta: termina con un mensaje de error.
    entorno.setenv("SUPERADMIN_PASSWORD", "corta123")
    with pytest.raises(SystemExit) as corta:
        script.main([])
    # Sin variables.
    entorno.delenv("SUPERADMIN_PASSWORD")
    with pytest.raises(SystemExit) as sin_clave:
        script.main([])

    salida = capsys.readouterr()
    todo = salida.out + salida.err + str(corta.value) + str(sin_clave.value)
    for secreto in (CLAVE, "corta123", CORREO, "SUPER@"):
        assert secreto not in todo


def test_exige_que_el_rol_superadministrador_exista(db_session):
    db_session.execute(Rol.__table__.update().where(Rol.nombre == ROL_SUPERADMINISTRADOR).values(activo=False))
    db_session.commit()

    with pytest.raises(SuperadminError, match="seed_seguridad"):
        crear_superadmin(db_session, CORREO, CLAVE)

    assert _superadmin(db_session) is None


def test_main_sin_variables_termina_con_un_mensaje(monkeypatch):
    monkeypatch.delenv("SUPERADMIN_EMAIL", raising=False)
    monkeypatch.delenv("SUPERADMIN_PASSWORD", raising=False)

    with pytest.raises(SystemExit) as salida:
        script.main([])

    assert "SUPERADMIN_EMAIL" in str(salida.value)


def test_el_superadministrador_creado_inicia_sesion_sin_empresa(db_session, client_por_peticion):
    crear_superadmin(db_session, CORREO, CLAVE)

    sin_empresa = client_por_peticion.post("/api/v1/auth/login", json={"email": CORREO, "password": CLAVE})
    con_empresa = client_por_peticion.post(
        "/api/v1/auth/login", json={"empresa": "fashionstore", "email": CORREO, "password": CLAVE}
    )

    assert sin_empresa.status_code == 200
    assert con_empresa.status_code == 401
