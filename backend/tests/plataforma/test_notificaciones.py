"""Notificacion vive en `plataforma` (antes en `core`) con la MISMA tabla y la
MISMA ruta: GET /api/v1/notificaciones y PUT /api/v1/notificaciones/{id}/leida."""

import ast
import pathlib

import app
from app.core.database import Base
from app.plataforma import politicas
from app.plataforma.models import Notificacion

NOTIFICACIONES = "/api/v1/notificaciones"


def _usuario_id(client, headers) -> int:
    return client.get("/api/v1/auth/yo", headers=headers).json()["id"]


def test_la_tabla_sigue_siendo_notificacion_y_esta_registrada_en_el_metadata():
    assert Notificacion.__tablename__ == "notificacion"
    assert Base.metadata.tables["notificacion"] is Notificacion.__table__
    assert {fk.target_fullname for fk in Notificacion.__table__.foreign_keys} == {"usuario.id"}


def test_listar_devuelve_las_del_usuario_de_la_mas_nueva_a_la_mas_vieja(client, db_session, cliente_headers):
    usuario_id = _usuario_id(client, cliente_headers)
    politicas.crear_notificacion(db_session, usuario_id, "Primera", tipo="reserva", referencia_id=7)
    politicas.crear_notificacion(db_session, usuario_id, "Segunda")

    respuesta = client.get(NOTIFICACIONES, headers=cliente_headers)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert [n["titulo"] for n in cuerpo] == ["Segunda", "Primera"]
    assert set(cuerpo[0]) == {"id", "titulo", "mensaje", "tipo", "referencia_id", "leida", "creado_en"}
    assert cuerpo[1]["tipo"] == "reserva" and cuerpo[1]["referencia_id"] == 7
    assert cuerpo[1]["leida"] is False


def test_listar_exige_sesion(client):
    assert client.get(NOTIFICACIONES).status_code == 401


def test_marcar_leida_por_http(client, db_session, cliente_headers):
    usuario_id = _usuario_id(client, cliente_headers)
    aviso = politicas.crear_notificacion(db_session, usuario_id, "Tu pedido salió")

    marcada = client.put(f"{NOTIFICACIONES}/{aviso.id}/leida", headers=cliente_headers)

    assert marcada.status_code == 200
    assert marcada.json()["leida"] is True
    assert client.get(NOTIFICACIONES, headers=cliente_headers).json()[0]["leida"] is True


def test_no_se_puede_marcar_la_notificacion_de_otro_usuario(client, db_session, admin_headers, cliente_headers):
    aviso = politicas.crear_notificacion(db_session, _usuario_id(client, cliente_headers), "Privada")

    respuesta = client.put(f"{NOTIFICACIONES}/{aviso.id}/leida", headers=admin_headers)

    assert respuesta.status_code == 404
    assert client.get(NOTIFICACIONES, headers=admin_headers).json() == []
    assert client.get(NOTIFICACIONES, headers=cliente_headers).json()[0]["leida"] is False


def test_marcar_una_inexistente_da_404(client, cliente_headers):
    assert client.put(f"{NOTIFICACIONES}/99999/leida", headers=cliente_headers).status_code == 404


def test_crear_sin_commit_deja_la_notificacion_en_la_transaccion_de_quien_llama(
    client, db_session, cliente_headers
):
    usuario_id = _usuario_id(client, cliente_headers)

    politicas.crear_notificacion(db_session, usuario_id, "Pendiente", commit=False)
    db_session.rollback()

    assert client.get(NOTIFICACIONES, headers=cliente_headers).json() == []


def test_core_no_importa_paquetes_de_negocio_a_nivel_de_modulo():
    # Regla 1: core <- plataforma. core solo puede traer plataforma con import
    # diferido (dentro de una función), nunca arriba del archivo.
    prohibidos = ("app.plataforma", "app.catalogo", "app.comercial", "app.inteligencia")
    raiz = pathlib.Path(app.__file__).parent / "core"
    infractores = []
    for archivo in sorted(raiz.glob("*.py")):
        for nodo in ast.parse(archivo.read_text(encoding="utf-8")).body:
            modulos = (
                [a.name for a in nodo.names]
                if isinstance(nodo, ast.Import)
                else [nodo.module or ""] if isinstance(nodo, ast.ImportFrom) else []
            )
            infractores += [f"{archivo.name}: {m}" for m in modulos if m.startswith(prohibidos)]

    assert infractores == []


def test_core_ya_no_tiene_modelo_servicio_ni_router_de_notificaciones():
    raiz = pathlib.Path(app.__file__).parent / "core"

    assert not [nombre for nombre in ("models.py", "service.py", "router.py", "schemas.py") if (raiz / nombre).exists()]
