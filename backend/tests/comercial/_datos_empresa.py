"""Ayudas de las pruebas con dos empresas (tareas por empresa y webhook/QR):
siembra en una empresa un catálogo mínimo, stock y un cliente, usando la API
con el token de su administrador y, donde la API no llega (el cliente), la
sesión de la prueba con la empresa fijada."""

import datetime as dt

from app.core.tenant import empresa_de, fijar_empresa
from app.plataforma.repository import ClienteRepository, UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.conftest import token_de

TOKEN_SERVICIO = {"X-Service-Token": "token-de-pruebas"}


def proxima_fecha_con_dia_semana(dia_semana: int) -> dt.date:
    """Primera fecha, desde una semana adelante, que cae en `dia_semana`
    (isoweekday: 1=lunes ... 7=domingo)."""
    base = dt.date.today() + dt.timedelta(days=7)
    return base + dt.timedelta(days=(dia_semana - base.isoweekday()) % 7)


def _ok(respuesta):
    assert respuesta.status_code < 300, f"{respuesta.request.method} {respuesta.request.url.path}: {respuesta.text}"
    return respuesta.json()


def sembrar_empresa(client, db_session, empresa, *, stock: int = 10) -> dict:
    """Catálogo mínimo (categoría, talla, color, producto), sucursal con horario
    de miércoles, `stock` unidades y un cliente con su token, todo DENTRO de
    `empresa` (una `EmpresaDePrueba` de la fixture `dos_empresas`). `client`
    debe ser `client_por_peticion`. Deja la sesión de la prueba como estaba."""
    admin = empresa.headers
    sufijo = empresa.codigo
    cat = _ok(client.post("/api/v1/categorias", json={"nombre": f"Camisas {sufijo}"}, headers=admin))
    talla = _ok(client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin))
    color = _ok(client.post("/api/v1/colores", json={"nombre": f"Azul {sufijo}"}, headers=admin))
    producto = _ok(client.post(
        "/api/v1/productos",
        json={
            "codigo": "EMP-1",
            "nombre": f"Camisa {sufijo}",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin,
    ))
    variante_id = _ok(client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin))[0]["id"]
    ciudad = _ok(client.post(
        "/api/v1/ciudades", json={"nombre": f"Ciudad {sufijo}", "departamento": "Santa Cruz"}, headers=admin
    ))
    sucursal = _ok(client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-EMP", "nombre": f"Sucursal {sufijo}", "direccion": "Av. 1"},
        headers=admin,
    ))
    _ok(client.post(
        f"/api/v1/sucursales/{sucursal['id']}/horarios",
        json={"dia_semana": 3, "hora_apertura": "08:00:00", "hora_cierre": "20:00:00"},
        headers=admin,
    ))
    _ok(client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": sucursal["id"],
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": stock,
            "costo_unitario": "10.00",
        },
        headers=admin,
    ))

    original = empresa_de(db_session)
    fijar_empresa(db_session, empresa.id)
    try:
        repo = UsuarioRepository()
        usuario = repo.crear(
            db_session,
            UsuarioCrear(nombre="Cli", apellido=sufijo, email=f"cliente@{sufijo}.example.com", password="claveSegura123"),
        )
        repo.asignar_roles(db_session, usuario, ["cliente"])
        ClienteRepository().crear_o_actualizar_perfil(db_session, usuario.id, None)
        cliente_headers = token_de(db_session, usuario)
    finally:
        fijar_empresa(db_session, original)

    return {
        "variante_id": variante_id,
        "sucursal_id": sucursal["id"],
        "fecha_visita": proxima_fecha_con_dia_semana(3).isoformat(),
        "admin": admin,
        "cliente": cliente_headers,
    }


def stock_de(client, datos: dict) -> dict:
    return _ok(client.get(
        f"/api/v1/inventario/stock/{datos['variante_id']}/{datos['sucursal_id']}", headers=datos["admin"]
    ))


def reservar(client, datos: dict, cantidad: int = 1) -> dict:
    respuesta = client.post(
        "/api/v1/reservas",
        json={
            "sucursal_id": datos["sucursal_id"],
            "fecha_visita": datos["fecha_visita"],
            "hora_visita_desde": "10:00:00",
            "hora_visita_hasta": "11:00:00",
            "detalle": [{"variante_id": datos["variante_id"], "cantidad": cantidad}],
        },
        headers=datos["cliente"],
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def iniciar_pago(client, datos: dict, metodo: str = "libelula", cantidad: int = 1) -> tuple[dict, dict]:
    """Venta digital pendiente de pago con un pago iniciado. Devuelve (venta, pago)."""
    client.post(
        "/api/v1/carrito", json={"variante_id": datos["variante_id"], "cantidad": cantidad}, headers=datos["cliente"]
    )
    venta = client.post(
        "/api/v1/ventas/digital", json={"sucursal_id": datos["sucursal_id"]}, headers=datos["cliente"]
    ).json()
    inicio = client.post(
        "/api/v1/pagos/iniciar", json={"venta_id": venta["id"], "metodo_pago": metodo}, headers=datos["cliente"]
    )
    assert inicio.status_code == 201, inicio.text
    return venta, inicio.json()["pago"]


def envejecer_reserva(db_session, empresa, reserva_id: int) -> None:
    from app.comercial.models import Reserva

    original = empresa_de(db_session)
    fijar_empresa(db_session, empresa.id)
    try:
        db_session.get(Reserva, reserva_id).fecha_expiracion = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        db_session.commit()
    finally:
        fijar_empresa(db_session, original)


def envejecer_venta(db_session, empresa, venta_id: int) -> None:
    from app.comercial.models import Venta

    original = empresa_de(db_session)
    fijar_empresa(db_session, empresa.id)
    try:
        db_session.get(Venta, venta_id).fecha = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(
            hours=2
        )
        db_session.commit()
    finally:
        fijar_empresa(db_session, original)
