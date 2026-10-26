"""E08 (D15): resolver una operación en conflicto. `forzar` registra un AJUSTE POSITIVO de inventario por
el faltante exacto y confirma la venta tal como la hizo el operador original (nunca deja stock negativo);
`rechazar` la cierra con el motivo escrito. `confirmada` y `rechazada` son finales: repetir la misma acción
devuelve lo guardado y la contraria es 409. Todo va en una transacción, con aviso al operador y bitácora."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.catalogo.models import MovimientoInventario, ProductoVariante
from app.comercial.models import Venta
from app.comercial.politicas import mapa_codigos_estado_venta
from app.core.auditoria import ACCION_RESOLVER_CONFLICTO, ENTIDAD_OPERACION_SYNC
from app.core.tenant import empresa_de, en_empresa, fijar_empresa
from app.core.tiempo import hoy_utc
from app.plataforma.models import Empleado, Notificacion, Plan, Suscripcion, Usuario
from app.sincronizacion.models import OperacionSync
from tests.ayudas_bitacora import exigir_datos_sin_sensibles, filas_de
from tests.conftest import crear_superadmin_de_prueba
from tests.sincronizacion.ayudas import (
    API,
    STOCK_V1,
    STOCK_V2,
    _crear_staff,
    armar_reserva,
    armar_venta,
    enviar,
    en_utc_naive,
    stock_de,
)


def _linea(variante_id: int, cantidad: int) -> dict:
    return {"variante_id": variante_id, "cantidad": cantidad, "precio_unitario": "100.00", "descuento_unitario": "0.00"}


def _en_conflicto(client, escenario, *, cantidad=5, lineas=None, **extra) -> dict:
    """Envía una venta que pide más de lo que hay (v2 tiene 3) y devuelve la operación en conflicto."""
    operacion = armar_venta(
        escenario, lineas=lineas or [_linea(escenario.v2, cantidad)], monto_recibido="900.00", **extra
    )
    resultado = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]
    assert resultado["estado"] == "en_conflicto", resultado
    return operacion


def _resolver(client, headers, operacion, accion, motivo=None):
    cuerpo = {"accion": accion}
    if motivo is not None:
        cuerpo["motivo"] = motivo
    return client.post(f"{API}/operaciones/{operacion['operacion_id']}/resolver", json=cuerpo, headers=headers)


def _guardada(db, operacion) -> OperacionSync:
    db.expire_all()
    return db.scalars(select(OperacionSync).where(OperacionSync.operacion_id == uuid.UUID(operacion["operacion_id"]))).one()


def _ajustes(db) -> list[MovimientoInventario]:
    db.expire_all()
    return list(
        db.scalars(
            select(MovimientoInventario)
            .where(MovimientoInventario.referencia_tipo == "sync_forzada")
            .order_by(MovimientoInventario.id)
        )
    )


def _ventas(db) -> list[Venta]:
    db.expire_all()
    return list(db.scalars(select(Venta).order_by(Venta.id)))


def _hoja_de_kardex(db, variante_id: int, sucursal_id: int) -> list[MovimientoInventario]:
    db.expire_all()
    return list(
        db.scalars(
            select(MovimientoInventario)
            .where(MovimientoInventario.variante_id == variante_id, MovimientoInventario.sucursal_id == sucursal_id)
            .order_by(MovimientoInventario.id)
        )
    )


def _segunda_sucursal(client, headers: dict) -> int:
    ciudad = client.post("/api/v1/ciudades", json={"nombre": "Potosí resolver", "departamento": "Potosí"}, headers=headers)
    assert ciudad.status_code in (200, 201), ciudad.text
    sucursal = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad.json()["id"], "codigo": "SUC-RES2", "nombre": "Otra sucursal", "direccion": "Av. 2"},
        headers=headers,
    )
    assert sucursal.status_code in (200, 201), sucursal.text
    return sucursal.json()["id"]


# ---- forzar: el ajuste positivo y la venta ----------------------------------------------------------------


def test_forzar_registra_el_ajuste_exacto_confirma_la_venta_y_deja_el_stock_en_cero(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario, cantidad=5)  # v2 tiene 3: faltan 2

    respuesta = _resolver(client, escenario.encargado, operacion, "forzar", "La prenda ya salió")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "confirmada" and cuerpo["motivo"] is None
    assert cuerpo["recurso"]["tipo"] == "venta" and cuerpo["faltantes"] == []
    assert cuerpo["resolucion"]["accion"] == "forzar"
    assert cuerpo["resolucion"]["por_usuario_id"] == escenario.encargado_usuario_id
    assert cuerpo["resolucion"]["motivo"] == "La prenda ya salió"

    ajustes = _ajustes(db_session)
    assert len(ajustes) == 1
    ajuste = ajustes[0]
    assert (ajuste.variante_id, ajuste.sucursal_id, ajuste.cantidad) == (escenario.v2, escenario.sucursal_id, 2)
    assert ajuste.usuario_id == escenario.encargado_usuario_id  # el actor del ajuste es el encargado
    assert ajuste.referencia_id == _guardada(db_session, operacion).id
    assert ajuste.saldo_post == STOCK_V2 + 2
    assert cuerpo["resolucion"]["ajustes"] == [
        {"variante_id": escenario.v2, "cantidad": 2, "movimiento_id": ajuste.id}
    ]
    # Físico 3 + 2 = 5, menos las 5 vendidas = 0: nunca negativo.
    assert stock_de(db_session, escenario, escenario.v2) == (0, 0)


def test_la_venta_forzada_queda_pagada_a_nombre_del_operador_original_con_la_fecha_de_la_operacion(
    client, db_session, escenario
):
    operacion = _en_conflicto(client, escenario)

    assert _resolver(client, escenario.encargado, operacion, "forzar").status_code == 200

    venta = _ventas(db_session)[0]
    assert mapa_codigos_estado_venta(db_session)[venta.estado_id] == "pagada"
    cajero = db_session.scalars(select(Empleado).where(Empleado.usuario_id == escenario.cajero_usuario_id)).one()
    assert venta.cajero_id == cajero.id  # el operador original, no el encargado
    assert venta.fecha == en_utc_naive(operacion["fecha_operacion"])  # la fecha de la operación, no la de hoy
    assert venta.cliente_id == escenario.cliente_id
    assert str(venta.total) == "500.00"


def test_forzar_no_toca_las_unidades_apartadas_por_reservas_de_otras_personas(client, db_session, escenario):
    # Una reserva aparta 1 de las 3 de v2: físico 3, reservado 1, disponible 2.
    reserva = armar_reserva(escenario, lineas=[{"variante_id": escenario.v2, "cantidad": 1}])
    assert enviar(client, escenario.cajero, [reserva]).json()["resultados"][0]["estado"] == "confirmada"
    operacion = _en_conflicto(client, escenario, cantidad=4)  # piden 4, disponible 2: faltan 2

    assert _resolver(client, escenario.encargado, operacion, "forzar").status_code == 200

    (ajuste,) = _ajustes(db_session)
    assert ajuste.cantidad == 2
    # Físico 3 + 2 - 4 = 1 y sigue 1 reservada: el disponible queda en 0, nunca debajo.
    assert stock_de(db_session, escenario, escenario.v2) == (1, 1)


def test_el_ejemplo_de_la_especificacion_disponible_1_se_vendieron_3_ajusta_2_y_deja_0(client, db_session, escenario):
    # Dos unidades de v2 se venden antes: quedan 1 de 3.
    antes = armar_venta(escenario, lineas=[_linea(escenario.v2, 2)], monto_recibido="200.00")
    assert enviar(client, escenario.cajero, [antes]).json()["resultados"][0]["estado"] == "confirmada"
    assert stock_de(db_session, escenario, escenario.v2) == (1, 0)
    operacion = _en_conflicto(client, escenario, cantidad=3)

    assert _resolver(client, escenario.encargado, operacion, "forzar").status_code == 200

    assert [a.cantidad for a in _ajustes(db_session)] == [2]
    assert stock_de(db_session, escenario, escenario.v2) == (0, 0)


def test_dos_lineas_de_la_misma_variante_se_suman_para_calcular_el_faltante(client, db_session, escenario):
    lineas = [_linea(escenario.v2, 2), _linea(escenario.v2, 2)]  # 4 en total, hay 3
    operacion = _en_conflicto(client, escenario, lineas=lineas)

    assert _resolver(client, escenario.encargado, operacion, "forzar").status_code == 200

    assert [a.cantidad for a in _ajustes(db_session)] == [1]  # 4 - 3, un solo ajuste
    assert stock_de(db_session, escenario, escenario.v2) == (0, 0)


def test_forzar_con_varias_variantes_ajusta_solo_la_que_falta(client, db_session, escenario):
    lineas = [_linea(escenario.v1, 2), _linea(escenario.v2, 5)]  # v1 sobra (10), v2 falta 2
    operacion = _en_conflicto(client, escenario, lineas=lineas)

    assert _resolver(client, escenario.encargado, operacion, "forzar").status_code == 200

    (ajuste,) = _ajustes(db_session)
    assert (ajuste.variante_id, ajuste.cantidad) == (escenario.v2, 2)
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)
    assert stock_de(db_session, escenario, escenario.v2) == (0, 0)


def test_si_el_stock_se_recupero_entre_tanto_no_hay_ajuste(client, db_session, admin_headers, escenario):
    operacion = _en_conflicto(client, escenario, cantidad=5)
    entrada = client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": escenario.v2,
            "sucursal_id": escenario.sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 10,
            "costo_unitario": "40.00",
        },
        headers=admin_headers,
    )
    assert entrada.status_code in (200, 201), entrada.text

    respuesta = _resolver(client, escenario.encargado, operacion, "forzar")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["resolucion"]["ajustes"] == []
    assert _ajustes(db_session) == []
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2 + 10 - 5, 0)


def test_el_kardex_queda_consistente_el_saldo_es_la_suma_de_sus_movimientos(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario, cantidad=5)
    _resolver(client, escenario.encargado, operacion, "forzar")

    movimientos = _hoja_de_kardex(db_session, escenario.v2, escenario.sucursal_id)

    assert [m.cantidad for m in movimientos] == [STOCK_V2, 2, -5]  # recepción, ajuste positivo, venta
    saldo = 0
    for movimiento in movimientos:
        saldo += movimiento.cantidad
        assert movimiento.saldo_post == saldo
    assert saldo == 0


def test_el_administrador_con_alcance_global_tambien_puede_forzar(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)

    respuesta = _resolver(client, escenario.admin, operacion, "forzar")

    assert respuesta.status_code == 200, respuesta.text
    (ajuste,) = _ajustes(db_session)
    assert ajuste.cantidad == 2


def test_forzar_deja_bitacora_y_avisa_al_operador_sin_datos_sensibles(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)
    _resolver(client, escenario.encargado, operacion, "forzar", "Ya se entregó")

    filas = filas_de(db_session, ENTIDAD_OPERACION_SYNC, ACCION_RESOLVER_CONFLICTO)
    assert len(filas) == 1
    fila = filas[0]
    assert fila.usuario_id == escenario.encargado_usuario_id
    assert fila.entidad_id == _guardada(db_session, operacion).id
    assert fila.datos["operacion_id"] == operacion["operacion_id"]
    assert fila.datos["decision"] == "forzar" and fila.datos["tipo"] == "venta_contado"
    assert fila.datos["motivo"] == "Ya se entregó"
    assert fila.datos["ajustes"] and fila.datos["ajustes"][0]["cantidad"] == 2
    exigir_datos_sin_sensibles(fila)

    avisos = list(
        db_session.scalars(select(Notificacion).where(Notificacion.usuario_id == escenario.cajero_usuario_id))
    )
    (aviso,) = [n for n in avisos if n.tipo == "sincronizacion"]
    assert aviso.titulo == "Operación sincronizada resuelta"
    assert "confirmada" in aviso.mensaje and operacion["operacion_id"][:8] in aviso.mensaje
    assert aviso.referencia_id == _guardada(db_session, operacion).id and aviso.leida is False


def test_el_operador_ve_su_operacion_confirmada_al_consultarla_o_reenviarla(client, escenario):
    operacion = _en_conflicto(client, escenario)
    _resolver(client, escenario.encargado, operacion, "forzar")

    detalle = client.get(f"{API}/operaciones/{operacion['operacion_id']}", headers=escenario.cajero).json()
    reenviado = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]

    assert detalle["estado"] == "confirmada" and detalle["resolucion"]["accion"] == "forzar"
    assert reenviado["estado"] == "confirmada" and reenviado["duplicada"] is True
    assert reenviado["recurso"]["tipo"] == "venta" and reenviado["faltantes"] == []


# ---- rechazar ---------------------------------------------------------------------------------------------


def test_rechazar_cierra_la_operacion_sin_tocar_el_stock(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)
    antes = stock_de(db_session, escenario, escenario.v2)

    respuesta = _resolver(client, escenario.encargado, operacion, "rechazar", "No había la prenda")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert (cuerpo["estado"], cuerpo["motivo"]) == ("rechazada", "rechazada_por_encargado")
    assert cuerpo["mensaje"] == "No había la prenda" and cuerpo["recurso"] is None
    assert cuerpo["resolucion"]["accion"] == "rechazar" and cuerpo["resolucion"]["ajustes"] == []
    assert stock_de(db_session, escenario, escenario.v2) == antes == (STOCK_V2, 0)
    assert _ajustes(db_session) == [] and _ventas(db_session) == []


def test_rechazar_sin_motivo_es_422_y_no_cambia_nada(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)

    for cuerpo in ({"accion": "rechazar"}, {"accion": "rechazar", "motivo": "   "}, {"accion": "rechazar", "motivo": None}):
        respuesta = client.post(
            f"{API}/operaciones/{operacion['operacion_id']}/resolver", json=cuerpo, headers=escenario.encargado
        )
        assert respuesta.status_code == 422, cuerpo

    assert _guardada(db_session, operacion).estado == "en_conflicto"


def test_un_motivo_de_mas_de_300_caracteres_es_422(client, escenario):
    operacion = _en_conflicto(client, escenario)

    assert _resolver(client, escenario.encargado, operacion, "rechazar", "x" * 301).status_code == 422
    assert _resolver(client, escenario.encargado, operacion, "rechazar", "x" * 300).status_code == 200


def test_una_accion_invalida_es_422(client, escenario):
    operacion = _en_conflicto(client, escenario)

    assert _resolver(client, escenario.encargado, operacion, "borrar").status_code == 422


def test_rechazar_deja_bitacora_y_avisa_al_operador_con_el_motivo(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)
    _resolver(client, escenario.encargado, operacion, "rechazar", "Dos cajeros vendieron la última")

    (fila,) = filas_de(db_session, ENTIDAD_OPERACION_SYNC, ACCION_RESOLVER_CONFLICTO)
    assert fila.datos["decision"] == "rechazar" and fila.datos["ajustes"] == []
    assert fila.datos["motivo"] == "Dos cajeros vendieron la última"
    exigir_datos_sin_sensibles(fila)
    (aviso,) = [
        n
        for n in db_session.scalars(select(Notificacion).where(Notificacion.usuario_id == escenario.cajero_usuario_id))
        if n.tipo == "sincronizacion"
    ]
    assert "rechazada" in aviso.mensaje and "Dos cajeros vendieron la última" in aviso.mensaje


def test_reenviar_el_lote_de_una_operacion_rechazada_devuelve_el_estado_final(client, escenario):
    operacion = _en_conflicto(client, escenario)
    _resolver(client, escenario.encargado, operacion, "rechazar", "Sin stock real")

    reenviado = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]

    assert (reenviado["estado"], reenviado["motivo"]) == ("rechazada", "rechazada_por_encargado")
    assert reenviado["duplicada"] is True and reenviado["mensaje"] == "Sin stock real"


def test_una_reserva_en_conflicto_se_puede_rechazar(client, db_session, escenario):
    reserva = armar_reserva(escenario, lineas=[{"variante_id": escenario.v2, "cantidad": 5}])
    assert enviar(client, escenario.cajero, [reserva]).json()["resultados"][0]["estado"] == "en_conflicto"

    respuesta = _resolver(client, escenario.encargado, reserva, "rechazar", "No hay stock")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == "rechazada"
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2, 0)


# ---- estados finales e idempotencia ---------------------------------------------------------------------------


def test_forzar_una_reserva_en_conflicto_es_409_y_sigue_en_conflicto(client, db_session, escenario):
    reserva = armar_reserva(escenario, lineas=[{"variante_id": escenario.v2, "cantidad": 5}])
    enviar(client, escenario.cajero, [reserva])

    respuesta = _resolver(client, escenario.encargado, reserva, "forzar")

    assert respuesta.status_code == 409
    assert "solo se pueden rechazar" in respuesta.json()["detail"]
    assert _guardada(db_session, reserva).estado == "en_conflicto"
    assert _ajustes(db_session) == []


def test_repetir_forzar_devuelve_lo_mismo_sin_duplicar_el_ajuste_ni_la_venta(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)
    primera = _resolver(client, escenario.encargado, operacion, "forzar", "uno")

    segunda = _resolver(client, escenario.encargado, operacion, "forzar", "otro motivo")

    assert segunda.status_code == 200, segunda.text
    assert segunda.json() == primera.json()  # lo guardado, no lo nuevo
    assert len(_ajustes(db_session)) == 1 and len(_ventas(db_session)) == 1
    assert len(filas_de(db_session, ENTIDAD_OPERACION_SYNC, ACCION_RESOLVER_CONFLICTO)) == 1
    assert stock_de(db_session, escenario, escenario.v2) == (0, 0)


def test_repetir_rechazar_devuelve_lo_mismo(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)
    primera = _resolver(client, escenario.encargado, operacion, "rechazar", "uno")

    segunda = _resolver(client, escenario.admin, operacion, "rechazar", "dos")

    assert segunda.status_code == 200 and segunda.json() == primera.json()
    assert len(filas_de(db_session, ENTIDAD_OPERACION_SYNC, ACCION_RESOLVER_CONFLICTO)) == 1


def test_la_accion_contraria_sobre_una_operacion_ya_resuelta_es_409(client, db_session, escenario):
    forzada = _en_conflicto(client, escenario)
    _resolver(client, escenario.encargado, forzada, "forzar")
    rechazada = _en_conflicto(client, escenario, cantidad=4)
    _resolver(client, escenario.encargado, rechazada, "rechazar", "no")

    contra_forzada = _resolver(client, escenario.encargado, forzada, "rechazar", "tarde")
    contra_rechazada = _resolver(client, escenario.encargado, rechazada, "forzar")

    assert contra_forzada.status_code == 409 and "confirmada" in contra_forzada.json()["detail"]
    assert contra_rechazada.status_code == 409 and "rechazada" in contra_rechazada.json()["detail"]
    assert _guardada(db_session, forzada).estado == "confirmada"
    assert _guardada(db_session, rechazada).estado == "rechazada"
    assert len(_ajustes(db_session)) == 1


@pytest.mark.parametrize("accion", ["forzar", "rechazar"])
def test_resolver_una_operacion_confirmada_o_rechazada_desde_el_lote_es_409(client, escenario, accion):
    confirmada = armar_venta(escenario)
    rechazada = armar_venta(escenario, lineas=[_linea(999999, 1)], monto_recibido="100.00")
    enviar(client, escenario.cajero, [confirmada, rechazada])

    for operacion, estado in ((confirmada, "confirmada"), (rechazada, "rechazada")):
        respuesta = _resolver(client, escenario.encargado, operacion, accion, "motivo")
        assert respuesta.status_code == 409, (estado, respuesta.text)
        assert estado in respuesta.json()["detail"]


# ---- permisos y alcance ---------------------------------------------------------------------------------------


def test_un_cajero_no_puede_resolver_conflictos(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)

    for accion in ("forzar", "rechazar"):
        assert _resolver(client, escenario.cajero, operacion, accion, "x").status_code == 403
    assert _guardada(db_session, operacion).estado == "en_conflicto"


def test_sin_token_es_401(client, escenario):
    operacion = _en_conflicto(client, escenario)

    assert client.post(f"{API}/operaciones/{operacion['operacion_id']}/resolver", json={"accion": "forzar"}).status_code == 401


def test_el_encargado_de_otra_sucursal_no_la_ve_y_el_estado_no_cambia(client, db_session, admin_headers, escenario):
    operacion = _en_conflicto(client, escenario)
    otra = _segunda_sucursal(client, admin_headers)
    encargado_otro = _crear_staff(
        client, admin_headers, "fashionstore", "encargado_sucursal", "Encargado", otra, "encargado-otro@example.com"
    )

    respuesta = _resolver(client, encargado_otro, operacion, "forzar")

    assert respuesta.status_code == 404  # fuera de su alcance se ve igual que inexistente
    assert _guardada(db_session, operacion).estado == "en_conflicto"
    assert _ajustes(db_session) == [] and _ventas(db_session) == []


def test_una_operacion_inexistente_es_404(client, escenario):
    inexistente = {"operacion_id": "00000000-0000-4000-8000-000000000000"}

    assert _resolver(client, escenario.encargado, inexistente, "rechazar", "x").status_code == 404


def test_una_operacion_de_otra_empresa_es_404_y_no_cambia(client_por_peticion, dos_empresas, db_session):
    from tests.sincronizacion.ayudas import construir_escenario

    client = client_por_peticion
    a = construir_escenario(client, dos_empresas.a.headers, db_session, sufijo="-a", codigo_empresa="tienda-a")
    b = construir_escenario(client, dos_empresas.b.headers, db_session, sufijo="-b", codigo_empresa="tienda-b")
    operacion_b = _en_conflicto(client, b)

    for accion in ("forzar", "rechazar"):
        assert _resolver(client, a.encargado, operacion_b, accion, "x").status_code == 404
        assert _resolver(client, dos_empresas.a.headers, operacion_b, accion, "x").status_code == 404

    assert _resolver(client, b.encargado, operacion_b, "rechazar", "propia").status_code == 200  # la propia sí


def test_el_superadministrador_no_puede_resolver(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)
    original = empresa_de(db_session)
    crear_superadmin_de_prueba(db_session, "super@plataforma.example.com", "claveSegura123")
    login = client.post("/api/v1/auth/login", json={"email": "super@plataforma.example.com", "password": "claveSegura123"})
    assert login.status_code == 200, login.text
    superadmin = {"Authorization": f"Bearer {login.json()['access_token']}"}
    try:
        respuesta = _resolver(client, superadmin, operacion, "rechazar", "x")
    finally:
        fijar_empresa(db_session, original)

    assert respuesta.status_code == 403


# ---- plan y suscripción ---------------------------------------------------------------------------------------


def test_con_la_suscripcion_vencida_resolver_da_403(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)
    empresa_id = db_session.scalar(select(Suscripcion.empresa_id))
    ayer = hoy_utc() - dt.timedelta(days=1)
    with en_empresa(db_session, empresa_id):
        suscripcion = db_session.scalar(select(Suscripcion).where(Suscripcion.estado != "cancelada"))
        suscripcion.fecha_inicio, suscripcion.fecha_vencimiento = ayer - dt.timedelta(days=30), ayer
    db_session.commit()

    respuesta = _resolver(client, escenario.encargado, operacion, "rechazar", "x")

    assert respuesta.status_code == 403 and respuesta.json()["detail"] == "suscripcion_no_activa"
    assert _guardada(db_session, operacion).estado == "en_conflicto"


def test_con_un_plan_sin_operacion_offline_resolver_da_403(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)
    plan = db_session.scalar(select(Plan).where(Plan.codigo == "profesional"))
    plan.operacion_offline = False
    db_session.commit()

    respuesta = _resolver(client, escenario.encargado, operacion, "rechazar", "x")

    assert respuesta.status_code == 403 and respuesta.json()["detail"] == "plan_no_incluye_funcionalidad"


# ---- revalidación del operador y de las variantes -----------------------------------------------------------------


def test_si_el_operador_fue_desactivado_forzar_es_409_y_la_operacion_sigue_en_conflicto(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)
    db_session.get(Usuario, escenario.cajero_usuario_id).activo = False
    db_session.commit()

    respuesta = _resolver(client, escenario.encargado, operacion, "forzar")

    assert respuesta.status_code == 409
    assert "ya no está activo" in respuesta.json()["detail"]
    assert _guardada(db_session, operacion).estado == "en_conflicto"
    assert _ajustes(db_session) == [] and _ventas(db_session) == []
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2, 0)
    # Lo que corresponde entonces es rechazarla.
    assert _resolver(client, escenario.encargado, operacion, "rechazar", "El operador ya no existe").status_code == 200


def test_si_el_operador_perdio_el_permiso_de_vender_forzar_es_409(client, db_session, escenario):
    from app.plataforma.models import Permiso, Rol, rol_permiso
    from sqlalchemy import delete

    operacion = _en_conflicto(client, escenario)
    permiso_id = db_session.scalar(select(Permiso.id).where(Permiso.codigo == "ventas.presencial"))
    rol_id = db_session.scalar(select(Rol.id).where(Rol.nombre == "cajero"))
    db_session.execute(delete(rol_permiso).where(rol_permiso.c.rol_id == rol_id, rol_permiso.c.permiso_id == permiso_id))
    db_session.commit()

    respuesta = _resolver(client, escenario.encargado, operacion, "forzar")

    assert respuesta.status_code == 409
    assert _guardada(db_session, operacion).estado == "en_conflicto" and _ajustes(db_session) == []


def test_si_la_variante_fue_desactivada_forzar_es_409_sin_ajuste(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)
    db_session.get(ProductoVariante, escenario.v2).activo = False
    db_session.commit()

    respuesta = _resolver(client, escenario.encargado, operacion, "forzar")

    assert respuesta.status_code == 409
    assert _guardada(db_session, operacion).estado == "en_conflicto"
    assert _ajustes(db_session) == [] and _ventas(db_session) == []
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2, 0)


def test_si_algo_falla_a_la_mitad_no_queda_ni_el_ajuste_ni_la_venta(client, db_session, escenario, monkeypatch):
    """Si la venta falla DESPUÉS del ajuste, todo se deshace (un solo SAVEPOINT)."""
    from app.sincronizacion import politicas

    operacion = _en_conflicto(client, escenario)

    def explota(*_args, **_kwargs):
        raise politicas.RechazoOperacion("regla_de_negocio", "falló la venta")

    monkeypatch.setattr(politicas, "ejecutar_venta_contado", explota)

    respuesta = _resolver(client, escenario.encargado, operacion, "forzar")

    assert respuesta.status_code == 409 and respuesta.json()["detail"] == "falló la venta"
    assert _ajustes(db_session) == []
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2, 0)
    assert _guardada(db_session, operacion).estado == "en_conflicto"


def test_la_empresa_no_tiene_mas_filas_de_las_esperadas_tras_resolver(client, db_session, escenario):
    operacion = _en_conflicto(client, escenario)
    _resolver(client, escenario.encargado, operacion, "forzar")

    assert db_session.scalar(select(func.count()).select_from(OperacionSync)) == 1
    assert len(_ventas(db_session)) == 1
