"""Ayudas de las pruebas de la sincronización offline (E07): el escenario de una empresa
con todo lo que una venta o una reserva necesita, y constructores de operaciones y lotes
con el contrato v1 (montos como texto, fechas con zona, UUID)."""

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.catalogo.politicas import obtener_stock
from app.plataforma.models import Cliente, Empresa, Usuario
API = "/api/v1/sincronizacion"
STOCK_V1 = 10
STOCK_V2 = 3
PRECIO = Decimal("100.00")
CLAVE = "claveSegura123"


@dataclass
class Escenario:
    """Una empresa lista para sincronizar. `v1` tiene 10 unidades y `v2` 3, a 100.00 cada una."""

    sucursal_id: int
    v1: int
    v2: int
    admin: dict
    cajero: dict
    cajero_usuario_id: int
    encargado: dict
    encargado_usuario_id: int
    cliente_id: int
    cliente_usuario_id: int
    producto_id: int
    fecha_visita: dt.date  # un miércoles futuro, con horario de 08:00 a 20:00


def nuevo_uuid() -> str:
    return str(uuid.uuid4())


def hace(minutos: int = 10) -> str:
    """Un instante pasado, ISO-8601 con offset de Bolivia (-04:00)."""
    ahora = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutos)
    return ahora.astimezone(dt.timezone(dt.timedelta(hours=-4))).isoformat(timespec="seconds")


def en_utc_naive(texto: str) -> dt.datetime:
    return dt.datetime.fromisoformat(texto).astimezone(dt.timezone.utc).replace(tzinfo=None)


def proximo_dia_semana(dia_semana: int, desde_hoy: int = 7) -> dt.date:
    base = dt.date.today() + dt.timedelta(days=desde_hoy)
    return base + dt.timedelta(days=(dia_semana - base.isoweekday()) % 7)


def construir_escenario(
    client,
    admin_headers: dict,
    db,
    *,
    sufijo: str = "",
    codigo_empresa: str = "fashionstore",
    cliente_email: str | None = None,
) -> Escenario:
    """Catálogo con dos variantes (stock 10 y 3), una sucursal abierta todos los días, un cajero y
    un encargado de esa sucursal y un cliente. El administrador es quien lo arma. Con `sufijo`
    se puede llamar más de una vez en la misma base (códigos y correos distintos).

    `cliente_email`: un cliente que YA se registró en la tienda (fixture `cliente_headers`); sin él
    se registra uno nuevo en `/public/{codigo_empresa}/registro`. Con `client_por_peticion` y
    `dos_empresas` se arma una empresa por llamada (`codigo_empresa` y `admin_headers` de cada una)."""
    def crear(ruta, cuerpo):
        respuesta = client.post(f"/api/v1/{ruta}", json=cuerpo, headers=admin_headers)
        assert respuesta.status_code in (200, 201), f"{ruta}: {respuesta.status_code} {respuesta.text}"
        return respuesta.json()

    categoria = crear("categorias", {"nombre": f"Camisas sync{sufijo}"})
    tallas = [crear("tallas", {"codigo": f"{codigo}{sufijo}"[:10], "orden": orden}) for orden, codigo in enumerate(("S", "M"), 1)]
    color = crear("colores", {"nombre": f"Azul sync{sufijo}"})
    producto = crear(
        "productos",
        {
            "codigo": f"SYNC-1{sufijo}",
            "nombre": f"Camisa sync{sufijo}",
            "categoria_id": categoria["id"],
            "precio_base": str(PRECIO),
            "tallas_ids": [t["id"] for t in tallas],
            "colores_ids": [color["id"]],
        },
    )
    variantes = sorted(
        v["id"] for v in client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()
    )
    ciudad = crear("ciudades", {"nombre": f"Sucre sync{sufijo}", "departamento": "Chuquisaca"})
    sucursal = crear(
        "sucursales",
        {"ciudad_id": ciudad["id"], "codigo": f"SUC-SYNC{sufijo}", "nombre": f"Sucursal sync{sufijo}", "direccion": "Av. 1"},
    )
    for dia in range(1, 8):
        crear(f"sucursales/{sucursal['id']}/horarios", {"dia_semana": dia, "hora_apertura": "08:00:00", "hora_cierre": "20:00:00"})
    for variante_id, cantidad in zip(variantes, (STOCK_V1, STOCK_V2)):
        crear(
            "inventario/movimientos",
            {
                "variante_id": variante_id,
                "sucursal_id": sucursal["id"],
                "tipo_movimiento_codigo": "recepcion",
                "cantidad": cantidad,
                "costo_unitario": "40.00",
            },
        )

    correo_cajero, correo_encargado = f"cajero-sync{sufijo}@example.com", f"encargado-sync{sufijo}@example.com"
    cajero = _crear_staff(client, admin_headers, codigo_empresa, "cajero", "Cajero", sucursal["id"], correo_cajero)
    encargado = _crear_staff(
        client, admin_headers, codigo_empresa, "encargado_sucursal", "Encargado", sucursal["id"], correo_encargado
    )
    if cliente_email is None:
        cliente_email = f"cliente-sync{sufijo}@example.com"
        registro = client.post(
            f"/api/v1/public/{codigo_empresa}/registro",
            json={"nombre": "Cli", "apellido": "Sync", "email": cliente_email, "password": CLAVE},
        )
        assert registro.status_code == 201, registro.text
    db.expire_all()
    cliente_usuario = _buscar(db, codigo_empresa, Usuario, Usuario.email == cliente_email)
    cliente = _buscar(db, codigo_empresa, Cliente, Cliente.usuario_id == cliente_usuario.id)
    return Escenario(
        sucursal_id=sucursal["id"],
        v1=variantes[0],
        v2=variantes[1],
        admin=admin_headers,
        cajero=cajero,
        cajero_usuario_id=_buscar(db, codigo_empresa, Usuario, Usuario.email == correo_cajero).id,
        encargado=encargado,
        encargado_usuario_id=_buscar(db, codigo_empresa, Usuario, Usuario.email == correo_encargado).id,
        cliente_id=cliente.id,
        cliente_usuario_id=cliente_usuario.id,
        producto_id=producto["id"],
        fecha_visita=proximo_dia_semana(3),
    )


def _crear_staff(client, admin_headers: dict, codigo_empresa: str, rol: str, cargo: str, sucursal_id: int, email: str) -> dict:
    """Un usuario con `rol`, empleado de la sucursal, ya con sesión iniciada en `codigo_empresa`.
    Devuelve sus cabeceras. (`tests.conftest.crear_staff` solo sirve para la empresa de las semillas.)"""
    usuario = client.post(
        "/api/v1/usuarios",
        json={"nombre": cargo, "apellido": "Sync", "email": email, "password": CLAVE},
        headers=admin_headers,
    )
    assert usuario.status_code == 201, usuario.text
    usuario_id = usuario.json()["id"]
    roles = client.put(f"/api/v1/usuarios/{usuario_id}/roles", json={"nombres_rol": [rol]}, headers=admin_headers)
    assert roles.status_code == 200, roles.text
    empleado = client.post(
        "/api/v1/empleados",
        json={"usuario_id": usuario_id, "sucursal_id": sucursal_id, "cargo": cargo},
        headers=admin_headers,
    )
    assert empleado.status_code == 201, empleado.text
    return iniciar_sesion(client, codigo_empresa, email)


def iniciar_sesion(client, codigo_empresa: str, email: str, password: str = CLAVE) -> dict:
    respuesta = client.post("/api/v1/auth/login", json={"empresa": codigo_empresa, "email": email, "password": password})
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


def _buscar(db, codigo_empresa: str, modelo, condicion):
    """Una fila de la empresa `codigo_empresa`, sea cual sea la empresa que tenga fijada la sesión
    de pruebas (se la fija un momento y se restaura)."""
    from app.core.tenant import empresa_de, fijar_empresa

    original = empresa_de(db)
    try:
        empresa_id = db.scalar(select(Empresa.id).where(Empresa.codigo == codigo_empresa))  # `empresa` no se filtra
        fijar_empresa(db, empresa_id)
        return db.scalars(select(modelo).where(condicion)).one()
    finally:
        fijar_empresa(db, original)


# ---- Operaciones y lotes (contrato v1) ----


def armar_venta(
    escenario: Escenario,
    *,
    operacion_id: str | None = None,
    sucursal_id: int | None = None,
    lineas: list[dict] | None = None,
    total: str | None = None,
    monto_recibido: str | None = None,
    cliente_id: int | None = ...,  # ... = el cliente del escenario; None = venta anónima
    fecha_operacion: str | None = None,
    metodo: str = "efectivo",
) -> dict:
    """Una operación venta_contado. Por defecto: 2 unidades de `v1` a 100.00 (total 200.00)
    pagadas con 250.00, con el cliente del escenario."""
    lineas = lineas or [{"variante_id": escenario.v1, "cantidad": 2, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    if total is None:
        total = str(sum((Decimal(l["precio_unitario"]) - Decimal(l.get("descuento_unitario", "0"))) * l["cantidad"] for l in lineas))
        total = f"{Decimal(total):.2f}"
    return {
        "operacion_id": operacion_id or nuevo_uuid(),
        "tipo": "venta_contado",
        "sucursal_id": sucursal_id if sucursal_id is not None else escenario.sucursal_id,
        "fecha_operacion": fecha_operacion or hace(10),
        "payload": {
            "cliente_id": escenario.cliente_id if cliente_id is ... else cliente_id,
            "lineas": lineas,
            "total": total,
            "pago": {"metodo": metodo, "monto_recibido": monto_recibido or "250.00"},
        },
    }


def armar_reserva(
    escenario: Escenario,
    *,
    operacion_id: str | None = None,
    sucursal_id: int | None = None,
    lineas: list[dict] | None = None,
    cliente_id: int | None = ...,
    fecha_visita: dt.date | None = None,
    desde: str = "10:00",
    hasta: str = "11:00",
    fecha_operacion: str | None = None,
    observacion: str | None = "Viene por la camisa azul",
) -> dict:
    """Una operación reserva: 1 unidad de `v1` para el cliente del escenario, un miércoles futuro."""
    return {
        "operacion_id": operacion_id or nuevo_uuid(),
        "tipo": "reserva",
        "sucursal_id": sucursal_id if sucursal_id is not None else escenario.sucursal_id,
        "fecha_operacion": fecha_operacion or hace(10),
        "payload": {
            "cliente_id": escenario.cliente_id if cliente_id is ... else cliente_id,
            "fecha_visita": (fecha_visita or escenario.fecha_visita).isoformat(),
            "hora_visita_desde": desde,
            "hora_visita_hasta": hasta,
            "observacion": observacion,
            "lineas": lineas or [{"variante_id": escenario.v1, "cantidad": 1}],
        },
    }


def armar_lote(operaciones: list[dict], **extra) -> dict:
    return {"version_contrato": "1.0", "operaciones": operaciones, **extra}


def enviar(client, headers: dict, operaciones: list[dict], **extra):
    """POST /sincronizacion/lote."""
    return client.post(f"{API}/lote", json=armar_lote(operaciones, **extra), headers=headers)


def stock_de(db, escenario: Escenario, variante_id: int) -> tuple[int, int]:
    """(físico, reservado) de la variante en la sucursal del escenario."""
    db.expire_all()
    stock = obtener_stock(db, variante_id, escenario.sucursal_id)
    return stock.cantidad_fisica, stock.cantidad_reservada
