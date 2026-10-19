"""Unidad de trabajo (G1) en comercial: `registrar_venta`, `crear_reserva` y
`cobrar_en_caja` aceptan `commit=False` y dejan todo en flush, de modo que quien
llama (la sincronización offline, CU-25) decide el commit o el rollback de TODA
la operación. Con el valor por defecto el comportamiento HTTP no cambia (lo
cubren test_ventas, test_reservas y test_pagos).
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.catalogo.models import MovimientoInventario
from app.catalogo.politicas import obtener_stock
from app.comercial.casos_uso.cu12_gestionar_reservas import ReservarPrendas
from app.comercial.casos_uso.cu18_procesar_pagos import ProcesarPagoCaja
from app.comercial.models import Pago, Reserva, ReservaHistorial, Venta, VentaDetalle
from app.comercial.politicas import cobrar_en_caja, crear_reserva, mapa_codigos_estado_venta, registrar_venta
from app.comercial.schemas import PagoCajaRequest, ReservaCrear, ReservaDetalleCrear
from app.core.exceptions import ConflictoError, DomainError, PermisoDenegadoError
from app.plataforma.models import Notificacion
from app.plataforma.politicas import obtener_empleado_por_usuario
from app.plataforma.repository import UsuarioRepository
from tests.conftest import crear_cajero


def _proxima_fecha_con_dia_semana(dia_semana: int) -> dt.date:
    base = dt.date.today() + dt.timedelta(days=7)
    delta = (dia_semana - base.isoweekday()) % 7
    return base + dt.timedelta(days=delta)


@pytest.fixture()
def contexto(client, admin_headers, db_session, cliente_headers):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas UoW"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul UoW"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "UOW-1",
            "nombre": "Camisa UoW",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante_id = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]["id"]

    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Santa Cruz UoW", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    sucursal_id = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-UOW", "nombre": "Sucursal UoW", "direccion": "Av. 1"},
        headers=admin_headers,
    ).json()["id"]
    client.post(
        f"/api/v1/sucursales/{sucursal_id}/horarios",
        json={"dia_semana": 3, "hora_apertura": "08:00:00", "hora_cierre": "20:00:00"},
        headers=admin_headers,
    )

    # Stock inicial: 10 unidades a costo 10.
    client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 10,
            "costo_unitario": "10.00",
        },
        headers=admin_headers,
    )

    cajero_headers = crear_cajero(client, admin_headers, db_session, sucursal_id=sucursal_id)
    usuarios = UsuarioRepository()
    cajero_usuario_id = usuarios.obtener_por_email(db_session, "cajero@example.com").id
    return {
        "variante_id": variante_id,
        "sucursal_id": sucursal_id,
        "cajero_headers": cajero_headers,
        "cajero_usuario_id": cajero_usuario_id,
        "cajero_id": obtener_empleado_por_usuario(db_session, cajero_usuario_id).id,
        "cliente_usuario_id": usuarios.obtener_por_email(db_session, "cliente@example.com").id,
        "fecha_visita": _proxima_fecha_con_dia_semana(3),  # miércoles
    }


def _contar(db, modelo) -> int:
    return db.scalar(select(func.count()).select_from(modelo))


def _stock(db, ctx):
    stock = obtener_stock(db, ctx["variante_id"], ctx["sucursal_id"])
    return stock.cantidad_fisica, stock.cantidad_reservada


def _registrar_venta(db, ctx, cantidad=1, commit=True) -> Venta:
    return registrar_venta(
        db,
        canal="presencial",
        sucursal_id=ctx["sucursal_id"],
        lineas=[(ctx["variante_id"], cantidad)],
        cliente_id=None,
        cajero_id=ctx["cajero_id"],
        reserva_id=None,
        costo_envio=Decimal("0"),
        usuario_id=ctx["cajero_usuario_id"],
        commit=commit,
    )


def _datos_reserva(ctx, cantidad=1) -> ReservaCrear:
    return ReservaCrear(
        sucursal_id=ctx["sucursal_id"],
        fecha_visita=ctx["fecha_visita"],
        hora_visita_desde=dt.time(10, 0),
        hora_visita_hasta=dt.time(11, 0),
        detalle=[ReservaDetalleCrear(variante_id=ctx["variante_id"], cantidad=cantidad)],
    )


# ---- registrar_venta(commit=False) ------------------------------------------------------


def test_registrar_venta_commit_false_mas_rollback_no_deja_venta_ni_stock_apartado(db_session, contexto):
    ventas = _contar(db_session, Venta)
    detalles = _contar(db_session, VentaDetalle)
    movimientos = _contar(db_session, MovimientoInventario)
    assert _stock(db_session, contexto) == (10, 0)

    venta = _registrar_venta(db_session, contexto, cantidad=2, commit=False)

    # Dentro de la unidad de trabajo todo es visible (flush)...
    assert venta.id is not None
    assert _contar(db_session, Venta) == ventas + 1
    assert _stock(db_session, contexto) == (10, 2)

    # ...y el rollback lo deshace entero.
    db_session.rollback()
    assert _contar(db_session, Venta) == ventas
    assert _contar(db_session, VentaDetalle) == detalles
    assert _contar(db_session, MovimientoInventario) == movimientos
    assert _stock(db_session, contexto) == (10, 0)


def test_registrar_venta_commit_false_mas_commit_persiste(db_session, contexto):
    venta = _registrar_venta(db_session, contexto, cantidad=2, commit=False)
    db_session.commit()
    db_session.rollback()

    assert db_session.get(Venta, venta.id) is not None
    assert _stock(db_session, contexto) == (10, 2)


def test_registrar_venta_por_defecto_hace_commit(db_session, contexto):
    venta = _registrar_venta(db_session, contexto)
    db_session.rollback()

    assert db_session.get(Venta, venta.id) is not None
    assert _stock(db_session, contexto) == (10, 1)


# ---- cobrar_en_caja ----------------------------------------------------------------------


def test_venta_mas_cobro_commit_false_mas_rollback_no_deja_venta_pago_ni_movimiento(db_session, contexto):
    ventas = _contar(db_session, Venta)
    pagos = _contar(db_session, Pago)
    movimientos = _contar(db_session, MovimientoInventario)

    venta = _registrar_venta(db_session, contexto, cantidad=2, commit=False)
    pago, cambio = cobrar_en_caja(
        db_session, contexto["cajero_usuario_id"], venta.id, "efectivo", Decimal("250.00"), commit=False
    )

    # Venta pagada y stock descontado, pero todavía dentro de la unidad de trabajo.
    assert cambio == Decimal("50.00")
    assert mapa_codigos_estado_venta(db_session)[venta.estado_id] == "pagada"
    assert _contar(db_session, MovimientoInventario) == movimientos + 1
    assert _stock(db_session, contexto) == (8, 0)

    db_session.rollback()
    assert _contar(db_session, Venta) == ventas
    assert _contar(db_session, Pago) == pagos
    assert _contar(db_session, MovimientoInventario) == movimientos
    assert _stock(db_session, contexto) == (10, 0)


def test_venta_mas_cobro_commit_false_mas_commit_es_una_sola_unidad(db_session, contexto):
    venta = _registrar_venta(db_session, contexto, cantidad=2, commit=False)
    pago, _ = cobrar_en_caja(
        db_session, contexto["cajero_usuario_id"], venta.id, "efectivo", Decimal("200.00"), commit=False
    )
    db_session.commit()
    db_session.rollback()

    assert db_session.get(Pago, pago.id) is not None
    assert mapa_codigos_estado_venta(db_session)[db_session.get(Venta, venta.id).estado_id] == "pagada"
    assert _stock(db_session, contexto) == (8, 0)


def test_cobrar_en_caja_equivale_al_flujo_http_actual(client, db_session, contexto):
    """Dos ventas iguales: una cobrada por el endpoint (ProcesarPagoCaja) y otra
    con la función extraída. El resultado (pago, cambio, estado de la venta y
    stock) es el mismo."""
    venta_http = client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": contexto["sucursal_id"], "detalle": [{"variante_id": contexto["variante_id"], "cantidad": 2}]},
        headers=contexto["cajero_headers"],
    ).json()
    respuesta = client.post(
        "/api/v1/pagos/caja",
        json={"venta_id": venta_http["id"], "metodo_pago": "efectivo", "monto_recibido": "250.00"},
        headers=contexto["cajero_headers"],
    )
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert _stock(db_session, contexto) == (8, 0)

    venta_fn = _registrar_venta(db_session, contexto, cantidad=2)
    pago, cambio = cobrar_en_caja(
        db_session, contexto["cajero_usuario_id"], venta_fn.id, "efectivo", Decimal("250.00")
    )
    db_session.rollback()  # lo confirmado sobrevive

    assert str(cambio) == cuerpo["cambio"] == "50.00"
    assert pago.monto == Decimal(cuerpo["pago"]["monto"]) == Decimal("200.00")
    assert cuerpo["pago"]["estado"] == "aprobado"
    estados = mapa_codigos_estado_venta(db_session)
    assert estados[db_session.get(Venta, venta_fn.id).estado_id] == "pagada"
    assert estados[db_session.get(Venta, venta_http["id"]).estado_id] == "pagada"
    assert _stock(db_session, contexto) == (6, 0)


def test_procesar_pago_caja_delega_en_cobrar_en_caja_y_mantiene_su_contrato(db_session, contexto):
    venta = _registrar_venta(db_session, contexto, cantidad=1)

    pago, cambio = ProcesarPagoCaja().ejecutar(
        db_session,
        contexto["cajero_usuario_id"],
        PagoCajaRequest(venta_id=venta.id, metodo_pago="efectivo", monto_recibido=Decimal("150.00")),
    )
    db_session.rollback()  # ejecutar() confirma (commit=True)

    assert cambio == Decimal("50.00")
    assert db_session.get(Pago, pago.id) is not None
    assert _stock(db_session, contexto) == (9, 0)


def test_cobrar_en_caja_conserva_las_validaciones_y_mensajes(db_session, contexto):
    venta = _registrar_venta(db_session, contexto, cantidad=1)

    with pytest.raises(PermisoDenegadoError, match="no puede cobrar en caja"):
        cobrar_en_caja(db_session, contexto["cliente_usuario_id"], venta.id, "efectivo", Decimal("100.00"))

    with pytest.raises(DomainError, match="necesita monto_recibido"):
        cobrar_en_caja(db_session, contexto["cajero_usuario_id"], venta.id, "efectivo", None)

    with pytest.raises(DomainError, match="no cubre el total"):
        cobrar_en_caja(db_session, contexto["cajero_usuario_id"], venta.id, "efectivo", Decimal("10.00"))

    # Ninguno de los intentos fallidos cobró nada.
    assert _contar(db_session, Pago) == 0
    assert _stock(db_session, contexto) == (10, 1)


# ---- crear_reserva(commit=False) ---------------------------------------------------------


def test_crear_reserva_commit_false_mas_rollback_no_deja_reserva_ni_stock_apartado(db_session, contexto):
    reservas = _contar(db_session, Reserva)
    historiales = _contar(db_session, ReservaHistorial)
    notificaciones = _contar(db_session, Notificacion)

    reserva = crear_reserva(
        db_session, contexto["cliente_usuario_id"], _datos_reserva(contexto, cantidad=2), commit=False
    )

    assert reserva.id is not None
    assert _contar(db_session, Reserva) == reservas + 1
    assert _stock(db_session, contexto) == (10, 2)
    assert _contar(db_session, Notificacion) == notificaciones + 1  # al cajero-empleado de la sucursal

    db_session.rollback()
    assert _contar(db_session, Reserva) == reservas
    assert _contar(db_session, ReservaHistorial) == historiales
    assert _contar(db_session, Notificacion) == notificaciones
    assert _stock(db_session, contexto) == (10, 0)


def test_crear_reserva_commit_false_mas_commit_persiste(db_session, contexto):
    reserva = crear_reserva(
        db_session, contexto["cliente_usuario_id"], _datos_reserva(contexto, cantidad=2), commit=False
    )
    db_session.commit()
    db_session.rollback()

    assert db_session.get(Reserva, reserva.id) is not None
    assert _stock(db_session, contexto) == (10, 2)


def test_crear_reserva_sin_stock_suficiente_lanza_conflicto_y_el_rollback_limpia(db_session, contexto):
    reservas = _contar(db_session, Reserva)

    with pytest.raises(ConflictoError):
        crear_reserva(
            db_session, contexto["cliente_usuario_id"], _datos_reserva(contexto, cantidad=999), commit=False
        )

    db_session.rollback()
    assert _contar(db_session, Reserva) == reservas
    assert _stock(db_session, contexto) == (10, 0)


def test_reservar_prendas_delega_en_crear_reserva_y_hace_commit(db_session, contexto):
    reserva = ReservarPrendas().ejecutar(db_session, contexto["cliente_usuario_id"], _datos_reserva(contexto))
    db_session.rollback()  # ejecutar() confirma (commit=True)

    assert db_session.get(Reserva, reserva.id) is not None
    assert _stock(db_session, contexto) == (10, 1)
