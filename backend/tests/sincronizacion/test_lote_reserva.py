"""E07: la operación `reserva` del lote. La registra el personal a nombre de un cliente, se
valida contra el horario de la sucursal, aparta el stock y queda con la fecha de la operación.
Todo lo que no se puede aplicar deja la operación guardada con su motivo y SIN apartado."""

import datetime as dt

import pytest
from sqlalchemy import delete, func, select

from app.comercial.models import Reserva
from app.comercial.politicas import mapa_codigos_estado_reserva
from app.plataforma.models import Permiso, Rol, rol_permiso
from app.sincronizacion.models import OperacionSync
from tests.sincronizacion.ayudas import (
    STOCK_V1,
    STOCK_V2,
    _crear_staff,
    armar_reserva,
    armar_venta,
    enviar,
    en_utc_naive,
    stock_de,
)


def _contar(db, modelo) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(modelo))


def _unico_resultado(respuesta) -> dict:
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["resultados"][0]


def _nada_apartado(db, escenario) -> None:
    assert stock_de(db, escenario, escenario.v1) == (STOCK_V1, 0)
    assert stock_de(db, escenario, escenario.v2) == (STOCK_V2, 0)
    assert _contar(db, Reserva) == 0


def test_una_reserva_confirmada_queda_pendiente_a_nombre_del_cliente_con_la_fecha_de_la_operacion(
    client, db_session, escenario
):
    operacion = armar_reserva(escenario, observacion="Viene por la camisa azul")
    resultado = _unico_resultado(enviar(client, escenario.cajero, [operacion]))

    assert resultado["estado"] == "confirmada" and resultado["motivo"] is None, resultado
    assert resultado["recurso"]["tipo"] == "reserva"
    assert resultado["recurso"]["codigo"].startswith("RES-")
    # La visita termina a las 11:00; la reserva vence 24 h después.
    siguiente = escenario.fecha_visita + dt.timedelta(days=1)
    assert resultado["recurso"]["fecha_expiracion"] == f"{siguiente.isoformat()}T11:00:00Z"

    db_session.expire_all()
    reserva = db_session.scalars(select(Reserva)).one()
    assert reserva.id == resultado["recurso"]["id"]
    assert mapa_codigos_estado_reserva(db_session)[reserva.estado_id] == "pendiente"
    assert reserva.cliente_id == escenario.cliente_id
    assert reserva.sucursal_id == escenario.sucursal_id
    assert reserva.fecha_visita == escenario.fecha_visita
    assert reserva.observacion == "Viene por la camisa azul"
    assert [(d.variante_id, d.cantidad) for d in reserva.detalle] == [(escenario.v1, 1)]
    # La fecha REAL de la operación (UTC), no la hora a la que se sincronizó.
    assert reserva.creado_en == en_utc_naive(operacion["fecha_operacion"])
    # El stock queda apartado, no descontado.
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 1)


def test_el_historial_de_la_reserva_nombra_al_cajero_como_actor_y_al_personal_como_origen(
    client, db_session, escenario
):
    resultado = _unico_resultado(enviar(client, escenario.cajero, [armar_reserva(escenario)]))
    assert resultado["estado"] == "confirmada", resultado

    db_session.expire_all()
    reserva = db_session.scalars(select(Reserva)).one()
    assert len(reserva.historial) == 1
    entrada = reserva.historial[0]
    assert entrada.usuario_id == escenario.cajero_usuario_id  # el actor, no el cliente
    assert entrada.usuario_id != escenario.cliente_usuario_id
    assert entrada.comentario == "Reserva registrada por el personal"
    assert mapa_codigos_estado_reserva(db_session)[entrada.estado_id] == "pendiente"


def test_una_reserva_fuera_del_horario_de_la_sucursal_se_rechaza_sin_apartar_nada(client, db_session, escenario):
    # La sucursal abre de 08:00 a 20:00: 19:00 a 21:00 se sale del horario.
    operacion = armar_reserva(escenario, desde="19:00", hasta="21:00")
    resultado = _unico_resultado(enviar(client, escenario.cajero, [operacion]))

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "reserva_fuera_de_horario", resultado
    assert resultado["recurso"] is None and resultado["mensaje"]
    _nada_apartado(db_session, escenario)
    guardada = db_session.scalars(select(OperacionSync)).one()
    assert (guardada.estado, guardada.motivo) == ("rechazada", "reserva_fuera_de_horario")


def test_una_reserva_en_un_deposito_se_rechaza_como_fuera_de_horario(client, db_session, escenario):
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Potosí sync dep", "departamento": "Potosí"}, headers=escenario.admin
    )
    assert ciudad.status_code in (200, 201), ciudad.text
    deposito = client.post(
        "/api/v1/sucursales",
        json={
            "ciudad_id": ciudad.json()["id"],
            "codigo": "DEP-SYNC",
            "nombre": "Depósito sync",
            "direccion": "Av. Almacén 1",
            "es_deposito": True,
        },
        headers=escenario.admin,
    )
    assert deposito.status_code in (200, 201), deposito.text
    assert deposito.json()["es_deposito"] is True
    deposito_id = deposito.json()["id"]
    # Un cajero que sí trabaja en el depósito: así el rechazo es por el depósito y no por la sucursal.
    cajero_deposito = _crear_staff(
        client, escenario.admin, "fashionstore", "cajero", "Cajero", deposito_id, "cajero-deposito@example.com"
    )

    operacion = armar_reserva(escenario, sucursal_id=deposito_id)
    resultado = _unico_resultado(enviar(client, cajero_deposito, [operacion]))

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "reserva_fuera_de_horario", resultado
    assert "depósito" in resultado["mensaje"]
    _nada_apartado(db_session, escenario)


def test_una_reserva_sin_stock_suficiente_queda_en_conflicto_y_no_aparta_nada(client, db_session, escenario):
    # v1 sí alcanza (1 de 10) pero v2 no (5 de 3): la reserva entera se deshace, también lo de v1.
    lineas = [{"variante_id": escenario.v1, "cantidad": 1}, {"variante_id": escenario.v2, "cantidad": 5}]
    resultado = _unico_resultado(enviar(client, escenario.cajero, [armar_reserva(escenario, lineas=lineas)]))

    assert resultado["estado"] == "en_conflicto" and resultado["motivo"] == "stock_insuficiente", resultado
    assert resultado["recurso"] is None
    assert resultado["faltantes"] == [{"variante_id": escenario.v2, "solicitado": 5, "disponible": STOCK_V2}]
    _nada_apartado(db_session, escenario)
    guardada = db_session.scalars(select(OperacionSync)).one()
    assert (guardada.estado, guardada.motivo) == ("en_conflicto", "stock_insuficiente")


def test_una_reserva_cuya_visita_ya_paso_se_rechaza_como_vencida_sin_apartar_nada(client, db_session, escenario):
    # Visita hace 3 días (el horario es el mismo todos los días): la reserva venció hace 2.
    visita = dt.date.today() - dt.timedelta(days=3)
    operacion = armar_reserva(escenario, fecha_visita=visita)
    resultado = _unico_resultado(enviar(client, escenario.cajero, [operacion]))

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "reserva_vencida", resultado
    assert resultado["recurso"] is None
    _nada_apartado(db_session, escenario)  # el SAVEPOINT deshizo el apartado
    guardada = db_session.scalars(select(OperacionSync)).one()
    assert (guardada.estado, guardada.motivo) == ("rechazada", "reserva_vencida")


def test_una_reserva_de_un_cliente_inexistente_se_rechaza(client, db_session, escenario):
    resultado = _unico_resultado(enviar(client, escenario.cajero, [armar_reserva(escenario, cliente_id=999999)]))

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "cliente_inexistente", resultado
    _nada_apartado(db_session, escenario)


def test_un_usuario_sin_el_permiso_de_reservas_no_puede_registrarlas_pero_si_ventas(client, db_session, escenario):
    # Se le quita al rol cajero SOLO `reservas.gestionar_sucursal` (los roles son globales y la base
    # de la prueba es desechable). Conserva `sincronizacion.operar` y `ventas.presencial`.
    permiso_id = db_session.scalar(select(Permiso.id).where(Permiso.codigo == "reservas.gestionar_sucursal"))
    rol_id = db_session.scalar(select(Rol.id).where(Rol.nombre == "cajero"))
    quitados = db_session.execute(
        delete(rol_permiso).where(rol_permiso.c.rol_id == rol_id, rol_permiso.c.permiso_id == permiso_id)
    ).rowcount
    assert quitados == 1
    db_session.commit()

    reserva = armar_reserva(escenario)
    venta = armar_venta(escenario)
    respuesta = enviar(client, escenario.cajero, [reserva, venta])

    assert respuesta.status_code == 200, respuesta.text
    por_id = {r["operacion_id"]: r for r in respuesta.json()["resultados"]}
    assert por_id[reserva["operacion_id"]]["estado"] == "rechazada"
    assert por_id[reserva["operacion_id"]]["motivo"] == "permiso_denegado"
    assert por_id[venta["operacion_id"]]["estado"] == "confirmada"
    assert _contar(db_session, Reserva) == 0
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)  # solo la venta tocó el stock


@pytest.mark.parametrize("variante", ["ausente", "nulo"])
def test_una_reserva_sin_cliente_es_un_payload_invalido(client, db_session, escenario, variante):
    operacion = armar_reserva(escenario, cliente_id=None)
    if variante == "ausente":
        del operacion["payload"]["cliente_id"]
    resultado = _unico_resultado(enviar(client, escenario.cajero, [operacion]))

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "payload_invalido", resultado
    assert "cliente_id" in resultado["mensaje"]
    _nada_apartado(db_session, escenario)


@pytest.mark.parametrize(("desde", "hasta"), [("11:00", "10:00"), ("10:00", "10:00")])
def test_una_franja_con_la_hora_de_inicio_no_anterior_a_la_de_fin_se_rechaza(
    client, db_session, escenario, desde, hasta
):
    resultado = _unico_resultado(enviar(client, escenario.cajero, [armar_reserva(escenario, desde=desde, hasta=hasta)]))

    assert resultado["estado"] == "rechazada", resultado
    assert resultado["motivo"] == "payload_invalido"
    assert resultado["recurso"] is None
    _nada_apartado(db_session, escenario)
