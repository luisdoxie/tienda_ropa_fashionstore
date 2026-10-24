"""E04: lo que bloquea (y lo que no) una suscripción que no está activa.

Suspendida, vencida (por fecha, SIN correr la tarea) o cancelada: todo usuario
autenticado de la empresa y su tienda pública reciben 403 `suscripcion_no_activa`.
Siguen funcionando /health, /auth/*, el webhook de pagos, la pantalla QR y las
tareas de servicio (y /mi-empresa y /plataforma/*, que cubre la lista
`RUTAS_SIN_SUSCRIPCION`). Renovar o reactivar restablece. Con la empresa A
(Profesional) y la B (Básico) de `dos_empresas`, una sesión nueva por petición."""

import datetime as dt
import hashlib
import hmac
import json

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import crear_access_token
from app.core.tenant import en_empresa
from app.core.tiempo import hoy_utc
from app.plataforma.models import Suscripcion
from tests.comercial._datos_empresa import TOKEN_SERVICIO, iniciar_pago, sembrar_empresa
from tests.conftest import crear_superadmin_de_prueba

SECRETO_LIBELULA = get_settings().libelula_webhook_secret


@pytest.fixture()
def mundo(client_por_peticion, dos_empresas, db_session):
    return {
        "a": sembrar_empresa(client_por_peticion, db_session, dos_empresas.a),
        "b": sembrar_empresa(client_por_peticion, db_session, dos_empresas.b),
    }


def _cambiar_suscripcion(db, empresa_id: int, **campos) -> None:
    with en_empresa(db, empresa_id):
        suscripcion = db.scalar(select(Suscripcion).where(Suscripcion.estado != "cancelada"))
        for campo, valor in campos.items():
            setattr(suscripcion, campo, valor)
    db.commit()


def _webhook(client, id_transaccion: str):
    cuerpo = json.dumps({"id_transaccion": id_transaccion, "estado": "aprobado"}).encode("utf-8")
    firma = hmac.new(SECRETO_LIBELULA.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()
    return client.post(
        "/api/v1/pagos/webhook/libelula", content=cuerpo, headers={"Content-Type": "application/json", "x-signature": firma}
    )


AYER = hoy_utc() - dt.timedelta(days=1)  # UTC, como la aplicación

# (cambios a la suscripción, estado que informa el 403)
SIN_SUSCRIPCION_ACTIVA = [
    pytest.param({"estado": "suspendida"}, "suspendida", id="suspendida"),
    pytest.param({"estado": "vencida"}, "vencida", id="vencida-persistida"),
    pytest.param({"fecha_inicio": AYER - dt.timedelta(days=30), "fecha_vencimiento": AYER}, "vencida", id="vencida-por-fecha"),
    pytest.param({"estado": "cancelada"}, "sin_suscripcion", id="cancelada"),
]


@pytest.mark.parametrize("cambios, estado", SIN_SUSCRIPCION_ACTIVA)
def test_sin_suscripcion_activa_toda_ruta_de_negocio_responde_403(
    client_por_peticion, db_session, dos_empresas, mundo, cambios, estado
):
    client = client_por_peticion
    _cambiar_suscripcion(db_session, dos_empresas.b.id, **cambios)
    b = mundo["b"]

    peticiones = [
        client.get("/api/v1/productos", headers=b["admin"]),
        client.get("/api/v1/catalogo", headers=b["cliente"]),  # lectura, pero con usuario
        client.get("/api/v1/categorias", headers=b["admin"]),
        client.get("/api/v1/sucursales", headers=b["admin"]),
        client.get("/api/v1/clientes/perfil", headers=b["cliente"]),
        client.post("/api/v1/carrito", json={"variante_id": b["variante_id"], "cantidad": 1}, headers=b["cliente"]),
        client.post("/api/v1/ia/voz", json={"texto": "camisa"}, headers=b["cliente"]),  # usuario opcional
    ]
    for respuesta in peticiones:
        assert respuesta.status_code == 403, f"{respuesta.request.method} {respuesta.request.url.path}: {respuesta.text}"
        cuerpo = respuesta.json()
        assert cuerpo["detail"] == cuerpo["codigo"] == "suscripcion_no_activa"
        assert cuerpo["estado"] == estado

    # La otra empresa no se entera.
    assert client.get("/api/v1/productos", headers=mundo["a"]["admin"]).status_code == 200


@pytest.mark.parametrize("cambios, estado", SIN_SUSCRIPCION_ACTIVA)
def test_la_tienda_publica_de_la_empresa_sin_suscripcion_responde_403(
    client_por_peticion, db_session, dos_empresas, mundo, cambios, estado
):
    client = client_por_peticion
    assert client.get("/api/v1/public/tienda-b/catalogo").status_code == 200

    _cambiar_suscripcion(db_session, dos_empresas.b.id, **cambios)

    for ruta in ("catalogo", "categorias", "zonas-envio", "inventario/disponibilidad?variante_id=1"):
        respuesta = client.get(f"/api/v1/public/tienda-b/{ruta}")
        assert respuesta.status_code == 403, f"{ruta}: {respuesta.text}"
        assert respuesta.json()["codigo"] == "suscripcion_no_activa"
        assert respuesta.json()["estado"] == estado
    registro = client.post(
        "/api/v1/public/tienda-b/registro",
        json={"nombre": "Nuevo", "apellido": "Cliente", "email": "nuevo@example.com", "password": "claveSegura123"},
    )
    assert registro.status_code == 403 and registro.json()["codigo"] == "suscripcion_no_activa"
    # La tienda de A sigue abierta.
    assert client.get("/api/v1/public/tienda-a/catalogo").status_code == 200


@pytest.mark.parametrize("cambios, estado", SIN_SUSCRIPCION_ACTIVA)
def test_siguen_funcionando_sesion_salud_webhook_qr_y_tareas(
    client_por_peticion, db_session, dos_empresas, mundo, cambios, estado
):
    client = client_por_peticion
    b = mundo["b"]
    _, pago_libelula = iniciar_pago(client, b)
    _, pago_qr = iniciar_pago(client, b, metodo="qr_online")  # antes de que la suscripción cambie
    _cambiar_suscripcion(db_session, dos_empresas.b.id, **cambios)

    # El dinero ya se movió: el webhook y la pantalla QR se resuelven igual.
    webhook = _webhook(client, pago_libelula["referencia_externa"])
    assert webhook.status_code == 200 and webhook.json()["estado"] == "aprobado"
    ref = pago_qr["referencia_externa"]
    assert client.get(f"/api/v1/pagos/qr/{ref}").status_code == 200
    confirmacion = client.post(f"/api/v1/pagos/qr/{ref}/confirmar")
    assert confirmacion.status_code == 200 and confirmacion.json()["estado"] == "aprobado"

    # Tareas de servicio y salud.
    assert client.get("/health").status_code == 200
    assert client.post("/api/v1/tareas/expirar-reservas", headers=TOKEN_SERVICIO).status_code == 200
    assert client.post("/api/v1/tareas/expirar-ventas-pendientes", headers=TOKEN_SERVICIO).status_code == 200

    # La sesión: login (el administrador puede entrar a renovar), /auth/yo y refresco.
    login = client.post(
        "/api/v1/auth/login", json={"empresa": "tienda-b", "email": "admin@tienda-b.example.com", "password": "claveSegura123"}
    )
    assert login.status_code == 200, login.text
    assert client.get("/api/v1/auth/yo", headers=b["admin"]).status_code == 200
    refresco = client.post("/api/v1/auth/refresh", json={"refresh_token": login.json()["refresh_token"]})
    assert refresco.status_code == 200, refresco.text


@pytest.mark.parametrize("cambios, estado", SIN_SUSCRIPCION_ACTIVA)
def test_mi_empresa_plataforma_y_tiendas_publicas_siguen_con_la_suscripcion_caida(
    client_por_peticion, db_session, dos_empresas, superadmin_headers, cambios, estado
):
    """Las rutas exentas de `RUTAS_SIN_SUSCRIPCION` responden igual: el
    administrador puede ver su estado y pedir la renovación; el superadministrador
    puede renovar; y las tiendas siguen listadas para mostrar sus datos."""
    client = client_por_peticion
    b = dos_empresas.b
    _cambiar_suscripcion(db_session, b.id, **cambios)

    assert client.get("/api/v1/mi-empresa", headers=b.headers).status_code == 200
    mi_suscripcion = client.get("/api/v1/mi-empresa/suscripcion", headers=b.headers)
    assert mi_suscripcion.status_code == 200
    assert mi_suscripcion.json()["estado"] == estado
    assert client.put("/api/v1/mi-empresa", json={"color_acento": "#112233"}, headers=b.headers).status_code == 200

    assert client.get("/api/v1/plataforma/empresas", headers=superadmin_headers).status_code == 200
    assert client.get("/api/v1/plataforma/suscripciones", headers=superadmin_headers).status_code == 200

    assert client.get("/api/v1/public/tiendas").status_code == 200
    # La empresa con la suscripción caída ya no se ofrece como tienda, pero sus datos públicos sí responden.
    assert "tienda-b" not in [t["codigo"] for t in client.get("/api/v1/public/tiendas").json()]
    assert client.get("/api/v1/public/tienda-b/tienda").status_code == 200
    assert "tienda-a" in [t["codigo"] for t in client.get("/api/v1/public/tiendas").json()]


def test_renovar_o_reactivar_restablece_el_acceso(client_por_peticion, db_session, dos_empresas, mundo):
    client = client_por_peticion
    b = mundo["b"]
    _cambiar_suscripcion(db_session, dos_empresas.b.id, estado="suspendida")
    assert client.get("/api/v1/productos", headers=b["admin"]).status_code == 403
    assert client.get("/api/v1/public/tienda-b/catalogo").status_code == 403

    _cambiar_suscripcion(db_session, dos_empresas.b.id, estado="activa")

    assert client.get("/api/v1/productos", headers=b["admin"]).status_code == 200
    assert client.get("/api/v1/public/tienda-b/catalogo").status_code == 200


def test_una_activa_que_vence_hoy_todavia_opera_y_ayer_ya_no(client_por_peticion, db_session, dos_empresas, mundo):
    b = mundo["b"]
    hoy = hoy_utc()
    _cambiar_suscripcion(db_session, dos_empresas.b.id, fecha_inicio=hoy - dt.timedelta(days=30), fecha_vencimiento=hoy)
    assert client_por_peticion.get("/api/v1/productos", headers=b["admin"]).status_code == 200

    _cambiar_suscripcion(db_session, dos_empresas.b.id, fecha_vencimiento=hoy - dt.timedelta(days=1))
    respuesta = client_por_peticion.get("/api/v1/productos", headers=b["admin"])
    assert respuesta.status_code == 403 and respuesta.json()["estado"] == "vencida"


def test_el_superadministrador_no_se_ve_afectado_por_la_suscripcion(client_por_peticion, db_session, dos_empresas):
    # Sin empresa no hay suscripción que mirar: en una ruta de negocio no recibe
    # suscripcion_no_activa sino el 403 de siempre del modo plataforma.
    superadmin_id = crear_superadmin_de_prueba(db_session)
    token = crear_access_token(superadmin_id, ["superadministrador"], [], empresa_id=None)
    headers = {"Authorization": f"Bearer {token}"}
    _cambiar_suscripcion(db_session, dos_empresas.b.id, estado="suspendida")

    assert client_por_peticion.get("/api/v1/auth/yo", headers=headers).status_code == 200
    respuesta = client_por_peticion.get("/api/v1/productos", headers=headers)
    assert respuesta.status_code == 403
    assert respuesta.json().get("codigo") != "suscripcion_no_activa"


def test_un_token_de_otra_empresa_no_hereda_la_suscripcion_de_la_publica(client_por_peticion, db_session, dos_empresas):
    # El token de A en la tienda de B (suspendida): la tienda responde 403 por su
    # suscripción, antes de mirar de quién es el token.
    _cambiar_suscripcion(db_session, dos_empresas.b.id, estado="suspendida")
    respuesta = client_por_peticion.get("/api/v1/public/tienda-b/catalogo", headers=dos_empresas.a.headers)
    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == "suscripcion_no_activa"
