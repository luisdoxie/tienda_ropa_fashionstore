"""E03, PASO 5: el superadministrador (D06) y los roles globales.

El rol superadministrador solo se asigna a usuarios sin empresa, y un usuario
sin empresa solo puede tener ese rol; escribir roles es de la plataforma
(`plataforma.gestionar`), no del administrador de una empresa; el token del
superadministrador deja la sesión en modo plataforma (las rutas de negocio
responden 403). Usan `client_por_peticion` y `dos_empresas` (A = 'tienda-a',
B = 'tienda-b'); el superadministrador se crea con scripts/crear_superadmin.py,
la única vía que existe para crearlo."""

import pytest

from app.core.exceptions import PermisoDenegadoError
from app.core.permisos import PERMISO_PLATAFORMA, ROL_SUPERADMINISTRADOR
from app.core.tenant import empresa_de, fijar_empresa, fijar_plataforma
from app.main import app
from app.plataforma.models import Usuario
from app.plataforma.politicas import validar_roles_asignables
from app.plataforma.repository import UsuarioRepository
from scripts.crear_superadmin import crear_superadmin

CLAVE = "claveSegura123"
CORREO_SUPER = "super@plataforma.example.com"


@pytest.fixture()
def superadmin(db_session):
    """Un superadministrador creado como lo hace el script. Devuelve su correo."""
    original = empresa_de(db_session)
    crear_superadmin(db_session, CORREO_SUPER, CLAVE)
    fijar_empresa(db_session, original)
    return CORREO_SUPER


def _login_super(client) -> dict:
    respuesta = client.post("/api/v1/auth/login", json={"email": CORREO_SUPER, "password": CLAVE})
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


def _id_de_rol(client, headers, nombre: str) -> int:
    roles = client.get("/api/v1/roles?limite=100", headers=headers).json()
    return next(r["id"] for r in roles if r["nombre"] == nombre)


def test_el_rol_superadministrador_no_se_asigna_a_un_usuario_de_empresa(client_por_peticion, dos_empresas):
    creado = client_por_peticion.post(
        "/api/v1/usuarios",
        json={"nombre": "Per", "apellido": "Sona", "email": "persona@example.com", "password": CLAVE},
        headers=dos_empresas.a.headers,
    )
    assert creado.status_code == 201

    asignado = client_por_peticion.put(
        f"/api/v1/usuarios/{creado.json()['id']}/roles",
        json={"nombres_rol": [ROL_SUPERADMINISTRADOR]},
        headers=dos_empresas.a.headers,
    )

    assert asignado.status_code == 403
    assert asignado.json() == {"detail": "Rol no asignable"}
    # Tampoco por el repositorio (la regla vive en la política, no en el router).
    with pytest.raises(PermisoDenegadoError):
        validar_roles_asignables(dos_empresas.a.id, [ROL_SUPERADMINISTRADOR])


def test_un_usuario_sin_empresa_solo_puede_tener_el_rol_superadministrador(db_session, superadmin):
    validar_roles_asignables(None, [ROL_SUPERADMINISTRADOR])
    for nombres in (["administrador"], ["cliente"], [ROL_SUPERADMINISTRADOR, "administrador"]):
        with pytest.raises(PermisoDenegadoError):
            validar_roles_asignables(None, nombres)

    # Y el repositorio lo aplica sobre un usuario real sin empresa.
    original = empresa_de(db_session)
    try:
        fijar_plataforma(db_session)
        usuario = UsuarioRepository().obtener_sin_empresa_por_correo(db_session, superadmin)
        with pytest.raises(PermisoDenegadoError):
            UsuarioRepository().asignar_roles(db_session, usuario, ["administrador"])
        db_session.rollback()
    finally:
        fijar_empresa(db_session, original)


ESCRITURAS_DE_ROLES = (
    ("post", "/api/v1/roles", {"nombre": "inventado", "descripcion": "x"}),
    ("put", "/api/v1/roles/{id}", {"descripcion": "cambiada"}),
    ("delete", "/api/v1/roles/{id}", None),
    ("put", "/api/v1/roles/{id}/permisos", {"codigos_permiso": ["catalogo.ver"]}),
)


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), ESCRITURAS_DE_ROLES)
def test_el_administrador_de_empresa_no_escribe_roles(client_por_peticion, dos_empresas, metodo, ruta, cuerpo):
    headers = dos_empresas.a.headers
    cliente_id = _id_de_rol(client_por_peticion, headers, "cliente")

    respuesta = client_por_peticion.request(metodo, ruta.format(id=cliente_id), json=cuerpo, headers=headers)

    assert respuesta.status_code == 403


def test_el_superadministrador_si_escribe_roles(client_por_peticion, dos_empresas, superadmin):
    headers = _login_super(client_por_peticion)

    creado = client_por_peticion.post(
        "/api/v1/roles", json={"nombre": "auditor", "descripcion": "Solo lectura"}, headers=headers
    )
    assert creado.status_code == 201
    rol_id = creado.json()["id"]
    actualizado = client_por_peticion.put(f"/api/v1/roles/{rol_id}", json={"descripcion": "Otra"}, headers=headers)
    con_permisos = client_por_peticion.put(
        f"/api/v1/roles/{rol_id}/permisos", json={"codigos_permiso": ["catalogo.ver"]}, headers=headers
    )
    desactivado = client_por_peticion.delete(f"/api/v1/roles/{rol_id}", headers=headers)

    assert actualizado.status_code == 200
    assert con_permisos.status_code == 200
    assert [p["codigo"] for p in con_permisos.json()["permisos"]] == ["catalogo.ver"]
    assert desactivado.status_code == 204


def test_get_roles_de_una_empresa_no_lista_al_superadministrador(client_por_peticion, dos_empresas, superadmin):
    de_empresa = client_por_peticion.get("/api/v1/roles?limite=100", headers=dos_empresas.a.headers)
    de_plataforma = client_por_peticion.get("/api/v1/roles?limite=100", headers=_login_super(client_por_peticion))

    assert de_empresa.status_code == 200
    nombres_empresa = {r["nombre"] for r in de_empresa.json()}
    assert ROL_SUPERADMINISTRADOR not in nombres_empresa
    assert {"administrador", "cliente"} <= nombres_empresa
    assert ROL_SUPERADMINISTRADOR in {r["nombre"] for r in de_plataforma.json()}
    # Tampoco por id.
    id_super = next(r["id"] for r in de_plataforma.json() if r["nombre"] == ROL_SUPERADMINISTRADOR)
    assert client_por_peticion.get(f"/api/v1/roles/{id_super}", headers=dos_empresas.a.headers).status_code == 404


def test_el_superadministrador_en_una_ruta_de_negocio_recibe_403(client_por_peticion, dos_empresas, superadmin):
    headers = _login_super(client_por_peticion)

    for ruta in ("/api/v1/productos", "/api/v1/sucursales", "/api/v1/ciudades"):
        assert client_por_peticion.get(ruta, headers=headers).status_code == 403, ruta
    # Las rutas que no tocan tablas de empresa si funcionan.
    assert client_por_peticion.get("/api/v1/permisos", headers=headers).status_code == 200


def test_auth_yo_trae_la_empresa_y_es_null_para_el_superadministrador(client_por_peticion, dos_empresas, superadmin):
    del_super = client_por_peticion.get("/api/v1/auth/yo", headers=_login_super(client_por_peticion))
    del_admin = client_por_peticion.get("/api/v1/auth/yo", headers=dos_empresas.a.headers)

    assert del_super.status_code == 200
    cuerpo = del_super.json()
    assert cuerpo["empresa_id"] is None
    assert cuerpo["empresa_codigo"] is None
    assert cuerpo["empresa_nombre"] is None
    assert cuerpo["roles"] == [ROL_SUPERADMINISTRADOR]
    assert PERMISO_PLATAFORMA in cuerpo["permisos"]
    assert del_admin.status_code == 200
    assert del_admin.json()["empresa_id"] == dos_empresas.a.id
    assert del_admin.json()["empresa_codigo"] == "tienda-a"
    assert del_admin.json()["empresa_nombre"] == "tienda-a"


def test_no_hay_forma_http_de_crear_usuarios_sin_empresa(client_por_peticion, dos_empresas, db_session):
    # Aunque el cuerpo traiga empresa_id de otra empresa, el usuario se crea en
    # la empresa del token.
    respuesta = client_por_peticion.post(
        "/api/v1/usuarios",
        json={
            "nombre": "Nue",
            "apellido": "Vo",
            "email": "nuevo@example.com",
            "password": CLAVE,
            "empresa_id": dos_empresas.b.id,
        },
        headers=dos_empresas.a.headers,
    )
    assert respuesta.status_code == 201
    original = empresa_de(db_session)
    try:
        fijar_plataforma(db_session)
        sin_empresa = UsuarioRepository().obtener_sin_empresa_por_correo(db_session, "nuevo@example.com")
        assert sin_empresa is None
        fijar_empresa(db_session, dos_empresas.a.id)
        assert db_session.get(Usuario, respuesta.json()["id"]).empresa_id == dos_empresas.a.id
    finally:
        fijar_empresa(db_session, original)

    # Ninguna ruta de usuarios acepta un campo empresa_id en su cuerpo.
    rutas = [r for r in app.routes if getattr(r, "path", "").startswith("/api/v1/usuarios")]
    assert rutas
    for ruta in rutas:
        for parametro in ruta.dependant.body_params:
            modelo = getattr(parametro.field_info, "annotation", None)
            campos = getattr(modelo, "model_fields", {})
            assert "empresa_id" not in campos, ruta.path
        assert "empresa_id" not in {p.name for p in ruta.dependant.query_params}, ruta.path


def test_el_administrador_de_empresa_no_tiene_plataforma_gestionar(client_por_peticion, dos_empresas):
    permisos = client_por_peticion.get("/api/v1/auth/yo", headers=dos_empresas.a.headers).json()["permisos"]

    assert PERMISO_PLATAFORMA not in permisos
    assert "empresa.gestionar" in permisos


def test_nadie_asigna_plataforma_gestionar_a_un_administrador_de_empresa(client_por_peticion, dos_empresas):
    headers = dos_empresas.a.headers
    admin_id = _id_de_rol(client_por_peticion, headers, "administrador")
    todos = [p["codigo"] for p in client_por_peticion.get("/api/v1/permisos", headers=headers).json()]

    respuesta = client_por_peticion.put(
        f"/api/v1/roles/{admin_id}/permisos", json={"codigos_permiso": todos}, headers=headers
    )

    assert respuesta.status_code == 403
    permisos = client_por_peticion.get("/api/v1/auth/yo", headers=headers).json()["permisos"]
    assert PERMISO_PLATAFORMA not in permisos
    # Y el rol sigue igual para la otra empresa.
    permisos_b = client_por_peticion.get("/api/v1/auth/yo", headers=dos_empresas.b.headers).json()["permisos"]
    assert PERMISO_PLATAFORMA not in permisos_b
