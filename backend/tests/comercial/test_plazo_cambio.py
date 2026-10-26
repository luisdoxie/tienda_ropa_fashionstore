"""E08 / CU-17 (D19): plazo para devolver o cambiar prendas. Se cuenta desde la fecha REAL de la
venta (`Venta.fecha`), el límite es inclusivo y el plazo es de la empresa (o de su plan, o el
respaldo). El reloj se controla: la venta se fecha a mano y `ahora_utc_naive` de `comercial.politicas`
se fija, así los bordes (24 h exactas, 24 h y 1 s) son exactos."""

import datetime as dt

import pytest
from sqlalchemy import select

from app.comercial.models import Venta
from app.comercial.politicas import mapa_codigos_estado_venta
from app.core.auditoria import ACCION_ACTUALIZAR, ACCION_CAMBIAR_PLAZO_CAMBIO, ENTIDAD_EMPRESA
from app.plataforma import politicas as plataforma_politicas
from app.plataforma.models import Cliente, Usuario
from tests.ayudas_bitacora import filas_de
from tests.conftest import EMPRESA_DEFECTO, crear_cajero

AHORA = dt.datetime(2026, 10, 26, 15, 0, 0)
MI_EMPRESA = "/api/v1/mi-empresa"


@pytest.fixture()
def contexto(client, admin_headers, db_session):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas Plazo"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul Plazo"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "PLZ-1",
            "nombre": "Camisa plazo",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante_id = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]["id"]
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Santa Cruz Plazo", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    sucursal_id = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-PLZ", "nombre": "Sucursal Plazo", "direccion": "Av. 1"},
        headers=admin_headers,
    ).json()["id"]
    client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 20,
            "costo_unitario": "10.00",
        },
        headers=admin_headers,
    )
    return {
        "variante_id": variante_id,
        "sucursal_id": sucursal_id,
        "cajero_headers": crear_cajero(client, admin_headers, db_session, sucursal_id=sucursal_id),
    }


def _venta(client, ctx, *, cantidad=4, pagar=True, cliente_id=None) -> dict:
    cuerpo = {
        "sucursal_id": ctx["sucursal_id"],
        "detalle": [{"variante_id": ctx["variante_id"], "cantidad": cantidad}],
    }
    if cliente_id is not None:
        cuerpo["cliente_id"] = cliente_id
    venta = client.post("/api/v1/ventas/presencial", json=cuerpo, headers=ctx["cajero_headers"])
    assert venta.status_code == 201, venta.text
    if pagar:
        pago = client.post(
            "/api/v1/pagos/caja", json={"venta_id": venta.json()["id"], "metodo_pago": "qr"}, headers=ctx["cajero_headers"]
        )
        assert pago.status_code in (200, 201), pago.text
    return venta.json()


def _fechar(db_session, venta_id: int, hace: dt.timedelta) -> None:
    """La venta pasa a haberse hecho `hace` antes de AHORA (el reloj de la política queda fijo en AHORA)."""
    venta = db_session.get(Venta, venta_id)
    venta.fecha = AHORA - hace
    db_session.commit()


@pytest.fixture()
def reloj(monkeypatch):
    monkeypatch.setattr("app.comercial.politicas.ahora_utc_naive", lambda: AHORA)


def _devolver(client, ctx, venta: dict, cantidad=1):
    return client.post(
        "/api/v1/devoluciones",
        json={"venta_id": venta["id"], "motivo": "Talle", "detalle": [{"venta_detalle_id": venta["detalle"][0]["id"], "cantidad": cantidad}]},
        headers=ctx["cajero_headers"],
    )


def _poner_plazo(client, admin_headers, horas):
    return client.put(MI_EMPRESA, json={"plazo_cambio_horas": horas}, headers=admin_headers)


# ---- bordes del plazo de 24 h ------------------------------------------------------------


@pytest.mark.parametrize(
    ("hace", "esperado"),
    [
        (dt.timedelta(hours=23, minutes=59), 201),
        (dt.timedelta(hours=24), 201),  # el límite es inclusivo
        (dt.timedelta(hours=24, seconds=1), 409),
        (dt.timedelta(hours=24, minutes=1), 409),
    ],
)
def test_bordes_del_plazo_de_24_horas(client, db_session, contexto, reloj, hace, esperado):
    venta = _venta(client, contexto)
    _fechar(db_session, venta["id"], hace)

    assert _devolver(client, contexto, venta).status_code == esperado


def test_el_mensaje_dice_cuanto_hace_y_cual_es_el_plazo(client, db_session, contexto, reloj):
    venta = _venta(client, contexto)
    _fechar(db_session, venta["id"], dt.timedelta(hours=26, minutes=10))

    respuesta = _devolver(client, contexto, venta)

    assert respuesta.status_code == 409
    detalle = respuesta.json()["detail"]
    assert "26 h 10 min" in detalle and "24 horas" in detalle
    assert detalle.startswith("El plazo para cambiar prendas de esta venta ya venció")


def test_pasados_dos_dias_el_mensaje_cuenta_en_dias(client, db_session, contexto, reloj):
    venta = _venta(client, contexto)
    _fechar(db_session, venta["id"], dt.timedelta(days=2, hours=3, minutes=5))

    assert "2 días 3 h" in _devolver(client, contexto, venta).json()["detail"]


def test_un_plazo_de_una_hora_se_escribe_en_singular(client, admin_headers, db_session, contexto, reloj):
    assert _poner_plazo(client, admin_headers, 1).status_code == 200
    venta = _venta(client, contexto)
    _fechar(db_session, venta["id"], dt.timedelta(hours=1, minutes=30))

    assert "el plazo es de 1 hora." in _devolver(client, contexto, venta).json()["detail"]


def test_un_rechazo_por_plazo_no_deja_devolucion_ni_toca_el_stock(client, admin_headers, db_session, contexto, reloj):
    venta = _venta(client, contexto)
    _fechar(db_session, venta["id"], dt.timedelta(hours=30))
    antes = client.get(
        f"/api/v1/inventario/stock/{contexto['variante_id']}/{contexto['sucursal_id']}", headers=admin_headers
    ).json()

    assert _devolver(client, contexto, venta).status_code == 409

    despues = client.get(
        f"/api/v1/inventario/stock/{contexto['variante_id']}/{contexto['sucursal_id']}", headers=admin_headers
    ).json()
    assert despues["cantidad_disponible"] == antes["cantidad_disponible"]


# ---- plazo propio de la empresa, del plan y respaldo -----------------------------------------


def test_plazo_propio_de_48_horas_acepta_una_venta_de_30_horas(client, admin_headers, db_session, contexto, reloj):
    assert _poner_plazo(client, admin_headers, 48).status_code == 200
    venta = _venta(client, contexto)
    _fechar(db_session, venta["id"], dt.timedelta(hours=30))

    assert _devolver(client, contexto, venta).status_code == 201


def test_plazo_propio_de_12_horas_rechaza_una_venta_de_13_horas(client, admin_headers, db_session, contexto, reloj):
    assert _poner_plazo(client, admin_headers, 12).status_code == 200
    venta = _venta(client, contexto)
    _fechar(db_session, venta["id"], dt.timedelta(hours=13))

    respuesta = _devolver(client, contexto, venta)

    assert respuesta.status_code == 409
    assert "13 h 0 min" in respuesta.json()["detail"] and "12 horas" in respuesta.json()["detail"]


def test_sin_plazo_propio_se_usa_el_del_plan(client, db_session, contexto, reloj):
    plan = plataforma_politicas.plan_de_la_empresa(db_session)
    plan.plazo_cambio_horas_defecto = 36
    db_session.commit()
    venta = _venta(client, contexto)
    _fechar(db_session, venta["id"], dt.timedelta(hours=30))

    assert _devolver(client, contexto, venta).status_code == 201


def test_sin_plan_vigente_se_usa_el_respaldo_de_24_horas(db_session, monkeypatch):
    monkeypatch.setattr(plataforma_politicas, "plan_de_la_empresa", lambda db: None)

    assert plataforma_politicas.obtener_plazo_cambio_horas(db_session) == 24


def test_un_plan_con_plazo_cero_cae_al_respaldo(db_session):
    plan = plataforma_politicas.plan_de_la_empresa(db_session)
    plan.plazo_cambio_horas_defecto = 0
    db_session.commit()

    assert plataforma_politicas.obtener_plazo_cambio_horas(db_session) == 24


# ---- el error de estado va antes que el de plazo ---------------------------------------------


def test_una_venta_pendiente_de_pago_sigue_dando_su_error_de_estado(client, db_session, contexto, reloj):
    venta = _venta(client, contexto, pagar=False)
    _fechar(db_session, venta["id"], dt.timedelta(hours=100))

    respuesta = _devolver(client, contexto, venta)

    assert respuesta.status_code == 400
    assert "pendiente_pago" in respuesta.json()["detail"]


def test_una_venta_anulada_sigue_dando_su_error_de_estado(client, db_session, contexto, reloj):
    venta = _venta(client, contexto)
    ids = {codigo: id_ for id_, codigo in mapa_codigos_estado_venta(db_session).items()}
    fila = db_session.get(Venta, venta["id"])
    fila.estado_id = ids["anulada"]
    fila.fecha = AHORA - dt.timedelta(hours=100)
    db_session.commit()

    respuesta = _devolver(client, contexto, venta)

    assert respuesta.status_code == 400
    assert "anulada" in respuesta.json()["detail"]


# ---- cada devolución se evalúa por separado -------------------------------------------------


def test_devolver_parte_dentro_del_plazo_y_el_resto_despues_da_409(client, db_session, contexto, monkeypatch):
    venta = _venta(client, contexto)
    _fechar(db_session, venta["id"], dt.timedelta(hours=10))
    monkeypatch.setattr("app.comercial.politicas.ahora_utc_naive", lambda: AHORA)
    assert _devolver(client, contexto, venta, cantidad=1).status_code == 201

    # Pasan 20 horas más: la venta ya tiene 30.
    monkeypatch.setattr("app.comercial.politicas.ahora_utc_naive", lambda: AHORA + dt.timedelta(hours=20))
    segunda = _devolver(client, contexto, venta, cantidad=1)

    assert segunda.status_code == 409
    assert "30 h 0 min" in segunda.json()["detail"]


# ---- configuración del plazo (PUT /mi-empresa) ---------------------------------------------


def test_cada_empresa_tiene_su_plazo(client_por_peticion, dos_empresas):
    assert _poner_plazo(client_por_peticion, dos_empresas.a.headers, 48).status_code == 200

    en_a = client_por_peticion.get(MI_EMPRESA, headers=dos_empresas.a.headers).json()
    en_b = client_por_peticion.get(MI_EMPRESA, headers=dos_empresas.b.headers).json()

    assert (en_a["plazo_cambio_horas"], en_a["plazo_cambio_horas_efectivo"]) == (48, 48)
    assert (en_b["plazo_cambio_horas"], en_b["plazo_cambio_horas_efectivo"]) == (None, 24)


@pytest.mark.parametrize("horas", [0, -1, 721, 100000])
def test_un_plazo_fuera_de_rango_es_422(client, admin_headers, horas):
    assert _poner_plazo(client, admin_headers, horas).status_code == 422
    assert client.get(MI_EMPRESA, headers=admin_headers).json()["plazo_cambio_horas"] is None


@pytest.mark.parametrize("horas", [1, 720])
def test_los_extremos_del_rango_se_aceptan(client, admin_headers, horas):
    respuesta = _poner_plazo(client, admin_headers, horas)

    assert respuesta.status_code == 200
    assert respuesta.json()["plazo_cambio_horas"] == horas == respuesta.json()["plazo_cambio_horas_efectivo"]


def test_null_vuelve_al_plazo_del_plan(client, admin_headers):
    _poner_plazo(client, admin_headers, 72)

    respuesta = _poner_plazo(client, admin_headers, None)

    assert respuesta.status_code == 200
    assert respuesta.json()["plazo_cambio_horas"] is None
    assert respuesta.json()["plazo_cambio_horas_efectivo"] == 24


def test_otros_cambios_de_la_empresa_no_tocan_el_plazo(client, admin_headers):
    _poner_plazo(client, admin_headers, 72)

    respuesta = client.put(MI_EMPRESA, json={"nombre": "Otro nombre"}, headers=admin_headers)

    assert respuesta.json()["plazo_cambio_horas"] == 72


def test_cambiar_el_plazo_deja_bitacora_con_antes_y_despues(client, admin_headers, db_session):
    _poner_plazo(client, admin_headers, 48)
    _poner_plazo(client, admin_headers, None)

    filas = filas_de(db_session, ENTIDAD_EMPRESA, ACCION_CAMBIAR_PLAZO_CAMBIO)

    assert [fila.datos for fila in filas] == [
        {"antes": None, "despues": 48},
        {"antes": 48, "despues": None},
    ]
    # Si solo se tocó el plazo no hay además un "actualizar" vacío.
    assert filas_de(db_session, ENTIDAD_EMPRESA, ACCION_ACTUALIZAR) == []


def test_repetir_el_mismo_plazo_no_deja_otra_fila(client, admin_headers, db_session):
    _poner_plazo(client, admin_headers, 48)
    _poner_plazo(client, admin_headers, 48)

    assert len(filas_de(db_session, ENTIDAD_EMPRESA, ACCION_CAMBIAR_PLAZO_CAMBIO)) == 1


def test_cambiar_nombre_y_plazo_juntos_deja_las_dos_filas(client, admin_headers, db_session):
    respuesta = client.put(MI_EMPRESA, json={"nombre": "Doble", "plazo_cambio_horas": 60}, headers=admin_headers)

    assert respuesta.status_code == 200
    assert len(filas_de(db_session, ENTIDAD_EMPRESA, ACCION_ACTUALIZAR)) == 1
    assert len(filas_de(db_session, ENTIDAD_EMPRESA, ACCION_CAMBIAR_PLAZO_CAMBIO)) == 1


def test_un_cajero_no_puede_cambiar_el_plazo(client, contexto):
    respuesta = client.put(MI_EMPRESA, json={"plazo_cambio_horas": 500}, headers=contexto["cajero_headers"])

    assert respuesta.status_code == 403


# ---- GET /ventas/{id}/plazo-cambio ----------------------------------------------------------


def test_el_plazo_de_una_venta_dentro_del_plazo(client, db_session, contexto, reloj):
    venta = _venta(client, contexto)
    _fechar(db_session, venta["id"], dt.timedelta(hours=10))

    respuesta = client.get(f"/api/v1/ventas/{venta['id']}/plazo-cambio", headers=contexto["cajero_headers"])

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "venta_id": venta["id"],
        "fecha_venta": "2026-10-26T05:00:00Z",
        "plazo_horas": 24,
        "vence_en": "2026-10-27T05:00:00Z",
        "vigente": True,
        "estado_venta": "pagada",
    }


def test_el_plazo_de_una_venta_vencida_no_esta_vigente(client, db_session, contexto, reloj):
    venta = _venta(client, contexto)
    _fechar(db_session, venta["id"], dt.timedelta(hours=24, seconds=1))

    assert client.get(f"/api/v1/ventas/{venta['id']}/plazo-cambio", headers=contexto["cajero_headers"]).json()["vigente"] is False


def test_el_dueno_de_la_venta_ve_su_plazo_y_otro_cliente_no(client, db_session, contexto, cliente_headers, reloj):
    usuario = db_session.scalar(select(Usuario).where(Usuario.email == "cliente@example.com"))
    cliente = db_session.scalar(select(Cliente).where(Cliente.usuario_id == usuario.id))
    venta = _venta(client, contexto, cliente_id=cliente.id)
    client.post(
        f"/api/v1/public/{EMPRESA_DEFECTO}/registro",
        json={"nombre": "Otro", "apellido": "Cliente", "email": "otro@example.com", "password": "claveSegura123"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"empresa": EMPRESA_DEFECTO, "email": "otro@example.com", "password": "claveSegura123"},
    )
    ajeno = {"Authorization": f"Bearer {login.json()['access_token']}"}

    ruta = f"/api/v1/ventas/{venta['id']}/plazo-cambio"
    assert client.get(ruta, headers=cliente_headers).status_code == 200
    assert client.get(ruta, headers=ajeno).status_code == 403


def test_el_plazo_de_una_venta_inexistente_es_404(client, contexto):
    assert client.get("/api/v1/ventas/999999/plazo-cambio", headers=contexto["cajero_headers"]).status_code == 404
