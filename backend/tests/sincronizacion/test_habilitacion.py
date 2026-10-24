"""E07: quién puede sincronizar. El POST del lote se atiende aunque el plan o la suscripción no
alcancen, para GUARDAR el rechazo de cada operación con su motivo (D16); las consultas (GET) sí
exigen plan con operación sin conexión y suscripción activa. El superadministrador, un usuario
sin el permiso `sincronizacion.operar` y una petición sin token no entran."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.core.tenant import empresa_de, en_empresa, fijar_empresa
from app.core.tiempo import hoy_utc
from app.plataforma.models import Plan, Suscripcion
from app.sincronizacion.models import OperacionSync
from tests.conftest import crear_superadmin_de_prueba
from tests.sincronizacion.ayudas import API, STOCK_V1, armar_reserva, armar_venta, enviar, stock_de

AYER = hoy_utc() - dt.timedelta(days=1)  # UTC, como la aplicación

# (cambios a la suscripción de la empresa de pruebas)
SUSCRIPCION_NO_ACTIVA = [
    pytest.param({"fecha_inicio": AYER - dt.timedelta(days=30), "fecha_vencimiento": AYER}, id="vencida-por-fecha"),
    pytest.param({"estado": "suspendida"}, id="suspendida"),
    pytest.param({"estado": "cancelada"}, id="cancelada"),
]


def _cambiar_suscripcion(db, empresa_id: int, **campos) -> None:
    with en_empresa(db, empresa_id):
        suscripcion = db.scalar(select(Suscripcion).where(Suscripcion.estado != "cancelada"))
        for campo, valor in campos.items():
            setattr(suscripcion, campo, valor)
    db.commit()


def _apagar_offline(db, plan: str = "profesional") -> None:
    """Edita la fila del plan: la empresa de pruebas (Profesional) ya no incluye la operación sin conexión."""
    fila = db.scalar(select(Plan).where(Plan.codigo == plan))
    fila.operacion_offline = False
    db.commit()


def _empresa_de_las_semillas(db_session) -> int:
    return empresa_de(db_session)


def _guardadas(db, empresa_id: int) -> list[OperacionSync]:
    db.expire_all()
    with en_empresa(db, empresa_id):
        return list(db.scalars(select(OperacionSync).order_by(OperacionSync.id)))


# ---- POST: el rechazo se guarda con su motivo ----------------------------------------------------


def test_plan_sin_operacion_offline_rechaza_todo_y_lo_deja_guardado(client, db_session, escenario):
    empresa_id = _empresa_de_las_semillas(db_session)
    _apagar_offline(db_session)
    venta, reserva = armar_venta(escenario), armar_reserva(escenario)

    respuesta = enviar(client, escenario.cajero, [venta, reserva])

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["resumen"]["total"] == 2 and cuerpo["resumen"]["rechazadas"] == 2
    for resultado in cuerpo["resultados"]:
        assert resultado["estado"] == "rechazada" and resultado["motivo"] == "plan_sin_operacion_offline"
        assert resultado["mensaje"] and resultado["recurso"] is None
    guardadas = _guardadas(db_session, empresa_id)
    assert [(f.estado, f.motivo) for f in guardadas] == [("rechazada", "plan_sin_operacion_offline")] * 2
    assert {str(f.operacion_id) for f in guardadas} == {venta["operacion_id"], reserva["operacion_id"]}
    # Nada se vendió ni se apartó.
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 0)


@pytest.mark.parametrize("cambios", SUSCRIPCION_NO_ACTIVA)
def test_sin_suscripcion_activa_rechaza_todo_con_su_motivo_y_lo_guarda(client, db_session, escenario, cambios):
    empresa_id = _empresa_de_las_semillas(db_session)
    _cambiar_suscripcion(db_session, empresa_id, **cambios)
    venta, reserva = armar_venta(escenario), armar_reserva(escenario)

    respuesta = enviar(client, escenario.cajero, [venta, reserva])

    assert respuesta.status_code == 200, respuesta.text
    resultados = respuesta.json()["resultados"]
    assert [(r["estado"], r["motivo"]) for r in resultados] == [("rechazada", "suscripcion_no_activa")] * 2
    guardadas = _guardadas(db_session, empresa_id)
    assert [(f.estado, f.motivo) for f in guardadas] == [("rechazada", "suscripcion_no_activa")] * 2
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 0)


def test_una_operacion_ya_confirmada_reenviada_con_la_suscripcion_vencida_sigue_confirmada(
    client, db_session, escenario
):
    """La idempotencia gana: el reenvío devuelve lo guardado y no vuelve a evaluar la suscripción."""
    empresa_id = _empresa_de_las_semillas(db_session)
    venta = armar_venta(escenario)
    primera = enviar(client, escenario.cajero, [venta]).json()["resultados"][0]
    assert primera["estado"] == "confirmada"

    _cambiar_suscripcion(db_session, empresa_id, fecha_inicio=AYER - dt.timedelta(days=30), fecha_vencimiento=AYER)
    nueva = armar_venta(escenario)  # otra operación, esa sí se rechaza
    respuesta = enviar(client, escenario.cajero, [venta, nueva])

    reenviada, rechazada = respuesta.json()["resultados"]
    assert reenviada["estado"] == "confirmada" and reenviada["duplicada"] is True
    assert reenviada["recurso"] == primera["recurso"]
    assert (rechazada["estado"], rechazada["motivo"]) == ("rechazada", "suscripcion_no_activa")
    assert rechazada["duplicada"] is False
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)


def test_el_rechazo_por_plan_es_final_reenviar_con_el_plan_restablecido_devuelve_el_mismo_rechazo(
    client, db_session, escenario
):
    """Riesgo documentado en la especificación (sección 8): el rechazo por plan o suscripción
    se guarda y es idempotente, aunque la empresa lo corrija después."""
    _apagar_offline(db_session)
    venta = armar_venta(escenario)
    assert enviar(client, escenario.cajero, [venta]).json()["resultados"][0]["motivo"] == "plan_sin_operacion_offline"

    fila = db_session.scalar(select(Plan).where(Plan.codigo == "profesional"))
    fila.operacion_offline = True
    db_session.commit()
    reenviada = enviar(client, escenario.cajero, [venta]).json()["resultados"][0]

    assert reenviada["duplicada"] is True
    assert (reenviada["estado"], reenviada["motivo"]) == ("rechazada", "plan_sin_operacion_offline")
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 0)


# ---- Quién entra ---------------------------------------------------------------------------------


def _headers_de_superadmin(client, db) -> dict:
    """Un superadministrador (usuario sin empresa), logueado por HTTP sin `empresa`."""
    crear_superadmin_de_prueba(db, "super@plataforma.example.com", "claveSegura123")
    respuesta = client.post(
        "/api/v1/auth/login", json={"email": "super@plataforma.example.com", "password": "claveSegura123"}
    )
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


def test_el_superadministrador_recibe_403_en_el_lote_y_en_las_consultas(client, db_session, escenario):
    original = empresa_de(db_session)
    superadmin = _headers_de_superadmin(client, db_session)
    try:
        lote = enviar(client, superadmin, [armar_venta(escenario)])
        lista = client.get(f"{API}/operaciones", headers=superadmin)
        detalle = client.get(f"{API}/operaciones/{uuid.uuid4()}", headers=superadmin)
    finally:
        fijar_empresa(db_session, original)

    assert lote.status_code == 403, lote.text
    assert lista.status_code == 403, lista.text
    assert detalle.status_code == 403, detalle.text
    assert _guardadas(db_session, original) == []


def test_un_usuario_sin_el_permiso_de_operar_recibe_403_y_no_se_guarda_nada(
    client, db_session, escenario, cliente_headers
):
    empresa_id = _empresa_de_las_semillas(db_session)

    lote = enviar(client, cliente_headers, [armar_venta(escenario)])
    lista = client.get(f"{API}/operaciones", headers=cliente_headers)

    assert lote.status_code == 403, lote.text
    assert lista.status_code == 403, lista.text
    assert _guardadas(db_session, empresa_id) == []
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 0)


def test_sin_token_todas_las_rutas_responden_401(client, escenario):
    assert enviar(client, {}, [armar_venta(escenario)]).status_code == 401
    assert client.get(f"{API}/operaciones").status_code == 401
    assert client.get(f"{API}/operaciones/{uuid.uuid4()}").status_code == 401


# ---- Las consultas exigen plan y suscripción -----------------------------------------------------


def test_las_consultas_con_el_plan_sin_operacion_offline_responden_403_plan_no_incluye_funcionalidad(
    client, db_session, escenario
):
    venta = armar_venta(escenario)
    assert enviar(client, escenario.cajero, [venta]).status_code == 200
    _apagar_offline(db_session)

    for respuesta in (
        client.get(f"{API}/operaciones", headers=escenario.cajero),
        client.get(f"{API}/operaciones/{venta['operacion_id']}", headers=escenario.cajero),
    ):
        assert respuesta.status_code == 403, respuesta.text
        cuerpo = respuesta.json()
        assert cuerpo["detail"] == cuerpo["codigo"] == "plan_no_incluye_funcionalidad"
        assert cuerpo["funcionalidad"] == "operacion_offline" and cuerpo["plan"] == "profesional"


@pytest.mark.parametrize("cambios", SUSCRIPCION_NO_ACTIVA)
def test_las_consultas_con_la_suscripcion_no_activa_responden_403_suscripcion_no_activa(
    client, db_session, escenario, cambios
):
    venta = armar_venta(escenario)
    assert enviar(client, escenario.cajero, [venta]).status_code == 200
    _cambiar_suscripcion(db_session, _empresa_de_las_semillas(db_session), **cambios)

    for respuesta in (
        client.get(f"{API}/operaciones", headers=escenario.cajero),
        client.get(f"{API}/operaciones/{venta['operacion_id']}", headers=escenario.cajero),
    ):
        assert respuesta.status_code == 403, respuesta.text
        cuerpo = respuesta.json()
        assert cuerpo["detail"] == cuerpo["codigo"] == "suscripcion_no_activa"
