"""E04 / CU-04: el administrador de la empresa ve su empresa, su plan y su
suscripción (/mi-empresa). Estas rutas están exentas de la suscripción: se
consultan aunque esté vencida o suspendida. Usan `client_por_peticion` y
`dos_empresas` (A = 'tienda-a' Profesional, B = 'tienda-b' Básico)."""

import datetime as dt

from sqlalchemy import update

from app.core.tenant import sin_filtro
from app.plataforma.models import Suscripcion
from tests.plataforma.ayudas_empresas import CLAVE, PLATAFORMA, suscripciones_de

MI_EMPRESA = "/api/v1/mi-empresa"
API = "/api/v1"


def _dos_sucursales(client, headers) -> None:
    ciudad = client.post(f"{API}/ciudades", json={"nombre": "Ciudad de prueba"}, headers=headers).json()["id"]
    for codigo in ("S1", "S2"):
        creada = client.post(
            f"{API}/sucursales",
            json={"ciudad_id": ciudad, "codigo": codigo, "nombre": codigo, "direccion": "Calle 1"},
            headers=headers,
        )
        assert creada.status_code == 201, creada.text


def test_obtener_mi_empresa(client_por_peticion, dos_empresas):
    respuesta = client_por_peticion.get(MI_EMPRESA, headers=dos_empresas.a.headers)

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "id": dos_empresas.a.id,
        "codigo": "tienda-a",
        "nombre": "tienda-a",
        "logo_url": None,
        "color_acento": None,
        "activo": True,
    }


def test_cambiar_nombre_y_color_no_cambia_el_codigo(client_por_peticion, dos_empresas):
    respuesta = client_por_peticion.put(
        MI_EMPRESA,
        json={"nombre": "Tienda A Moda", "color_acento": "#112233", "logo_url": "https://x.example.com/a.png"},
        headers=dos_empresas.a.headers,
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["nombre"] == "Tienda A Moda"
    assert respuesta.json()["color_acento"] == "#112233"
    assert respuesta.json()["codigo"] == "tienda-a"
    assert client_por_peticion.get(MI_EMPRESA, headers=dos_empresas.a.headers).json()["nombre"] == "Tienda A Moda"
    # Se puede quitar el logo con null; un color mal escrito es 422.
    sin_logo = client_por_peticion.put(MI_EMPRESA, json={"logo_url": None}, headers=dos_empresas.a.headers)
    assert sin_logo.json()["logo_url"] is None
    assert client_por_peticion.put(MI_EMPRESA, json={"color_acento": "rojo"}, headers=dos_empresas.a.headers).status_code == 422


def test_put_no_puede_cambiar_plan_estado_ni_codigo(client_por_peticion, db_session, dos_empresas):
    respuesta = client_por_peticion.put(
        MI_EMPRESA,
        json={
            "nombre": "Solo el nombre",
            "plan_codigo": "profesional",
            "estado": "cancelada",
            "activo": False,
            "codigo": "robado",
        },
        headers=dos_empresas.b.headers,  # Básico
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["nombre"] == "Solo el nombre"
    assert respuesta.json()["codigo"] == "tienda-b"
    assert respuesta.json()["activo"] is True
    suscripcion = client_por_peticion.get(f"{MI_EMPRESA}/suscripcion", headers=dos_empresas.b.headers).json()
    assert suscripcion["plan_codigo"] == "basico"
    assert suscripcion["estado"] == "activa"
    assert len(suscripciones_de(db_session, dos_empresas.b.id)) == 1


def test_mi_suscripcion_trae_plan_estado_fechas_limites_uso_y_funcionalidades(client_por_peticion, dos_empresas):
    _dos_sucursales(client_por_peticion, dos_empresas.b.headers)

    respuesta = client_por_peticion.get(f"{MI_EMPRESA}/suscripcion", headers=dos_empresas.b.headers)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["plan_codigo"] == "basico"
    assert cuerpo["plan_nombre"] == "Básico"
    assert cuerpo["estado"] == "activa"
    hoy = dt.datetime.now(dt.timezone.utc).date()
    assert cuerpo["fecha_inicio"] == hoy.isoformat()
    assert cuerpo["fecha_vencimiento"] == (hoy + dt.timedelta(days=365)).isoformat()
    assert cuerpo["max_sucursales"] == 2
    assert cuerpo["sucursales_activas"] == 2  # el uso: 2 de 2
    assert "reportes_ia" not in cuerpo["funcionalidades"]
    assert {"gestion_productos", "gestion_ventas", "reservas", "reportes_convencionales"} <= set(cuerpo["funcionalidades"])
    en_a = client_por_peticion.get(f"{MI_EMPRESA}/suscripcion", headers=dos_empresas.a.headers).json()
    assert en_a["plan_codigo"] == "profesional"
    assert "reportes_ia" in en_a["funcionalidades"] and en_a["max_sucursales"] == 10
    assert en_a["sucursales_activas"] == 0  # las sucursales de B no cuentan


def test_un_cajero_recibe_403(client_por_peticion, dos_empresas):
    creado = client_por_peticion.post(
        f"{API}/usuarios",
        json={"nombre": "Caja", "apellido": "Uno", "email": "cajero@tienda-a.example.com", "password": CLAVE},
        headers=dos_empresas.a.headers,
    )
    assert client_por_peticion.put(
        f"{API}/usuarios/{creado.json()['id']}/roles", json={"nombres_rol": ["cajero"]}, headers=dos_empresas.a.headers
    ).status_code == 200
    login = client_por_peticion.post(
        "/api/v1/auth/login", json={"empresa": "tienda-a", "email": "cajero@tienda-a.example.com", "password": CLAVE}
    )
    cajero = {"Authorization": f"Bearer {login.json()['access_token']}"}

    for metodo, ruta, cuerpo in (
        ("get", MI_EMPRESA, None),
        ("put", MI_EMPRESA, {"nombre": "X"}),
        ("get", f"{MI_EMPRESA}/suscripcion", None),
    ):
        assert client_por_peticion.request(metodo, ruta, json=cuerpo, headers=cajero).status_code == 403, ruta
        assert client_por_peticion.request(metodo, ruta, json=cuerpo).status_code == 401, ruta


def test_cada_administrador_ve_solo_su_empresa(client_por_peticion, dos_empresas):
    en_a = client_por_peticion.get(MI_EMPRESA, headers=dos_empresas.a.headers).json()
    en_b = client_por_peticion.get(MI_EMPRESA, headers=dos_empresas.b.headers).json()

    assert (en_a["codigo"], en_b["codigo"]) == ("tienda-a", "tienda-b")
    # Un cambio en A no toca a B.
    client_por_peticion.put(MI_EMPRESA, json={"nombre": "Cambiado"}, headers=dos_empresas.a.headers)
    assert client_por_peticion.get(MI_EMPRESA, headers=dos_empresas.b.headers).json()["nombre"] == "tienda-b"


def test_el_superadministrador_no_tiene_mi_empresa(client_por_peticion, superadmin_headers):
    for metodo, ruta in (("get", MI_EMPRESA), ("put", MI_EMPRESA), ("get", f"{MI_EMPRESA}/suscripcion")):
        assert client_por_peticion.request(metodo, ruta, json={}, headers=superadmin_headers).status_code == 403, ruta


def test_mi_empresa_funciona_con_la_suscripcion_suspendida_o_vencida(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    suscripcion_id = suscripciones_de(db_session, dos_empresas.b.id)[0].id
    suspender = client_por_peticion.put(
        f"{PLATAFORMA}/suscripciones/{suscripcion_id}/estado", json={"estado": "suspendida"}, headers=superadmin_headers
    )
    assert suspender.status_code == 200
    admin_b = dos_empresas.b.headers

    # Las rutas de negocio se bloquean; /mi-empresa y su suscripción siguen.
    assert client_por_peticion.get(f"{API}/sucursales", headers=admin_b).status_code == 403
    assert client_por_peticion.get(MI_EMPRESA, headers=admin_b).status_code == 200
    suspendida = client_por_peticion.get(f"{MI_EMPRESA}/suscripcion", headers=admin_b).json()
    assert suspendida["estado"] == "suspendida"
    assert suspendida["plan_codigo"] == "basico"

    # Vencida por fecha, sin correr la tarea.
    client_por_peticion.put(
        f"{PLATAFORMA}/suscripciones/{suscripcion_id}/estado", json={"estado": "activa"}, headers=superadmin_headers
    )
    ayer = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    db_session.execute(
        sin_filtro(
            update(Suscripcion)
            .where(Suscripcion.id == suscripcion_id)
            .values(fecha_inicio=ayer - dt.timedelta(days=30), fecha_vencimiento=ayer)
        ),
        execution_options={"synchronize_session": False},
    )
    db_session.commit()
    vencida = client_por_peticion.get(f"{MI_EMPRESA}/suscripcion", headers=admin_b)
    assert vencida.status_code == 200
    assert vencida.json()["estado"] == "vencida"
    assert client_por_peticion.get(f"{API}/sucursales", headers=admin_b).status_code == 403
    assert client_por_peticion.put(MI_EMPRESA, json={"nombre": "Aun puedo"}, headers=admin_b).status_code == 200
