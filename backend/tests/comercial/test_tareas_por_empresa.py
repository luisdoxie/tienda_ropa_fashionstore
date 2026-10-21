"""Tareas sin usuario (expirar reservas y ventas pendientes): corren POR empresa,
cada una con la suya fijada, y liberan el stock solo en la empresa dueña."""

import pytest
from sqlalchemy import update

from app.comercial import politicas as comercial_politicas
from app.core.tenant import empresa_de
from app.plataforma.models import Empresa
from tests.comercial._datos_empresa import (
    TOKEN_SERVICIO,
    envejecer_reserva,
    envejecer_venta,
    iniciar_pago,
    reservar,
    sembrar_empresa,
    stock_de,
)


@pytest.fixture()
def mundo(client_por_peticion, dos_empresas, db_session):
    """Cada empresa con su catálogo, 10 unidades y su cliente."""
    return {
        "a": sembrar_empresa(client_por_peticion, db_session, dos_empresas.a),
        "b": sembrar_empresa(client_por_peticion, db_session, dos_empresas.b),
    }


def _estado_reserva(client, datos, reserva_id):
    return client.get(f"/api/v1/reservas/{reserva_id}", headers=datos["cliente"]).json()["estado"]


def _estado_venta(client, datos, venta_id):
    return client.get(f"/api/v1/ventas/{venta_id}/comprobante", headers=datos["admin"]).json()["estado"]


def test_expirar_reservas_libera_el_stock_solo_en_la_empresa_dueña(
    client_por_peticion, dos_empresas, mundo, db_session
):
    client = client_por_peticion
    reserva_a = reservar(client, mundo["a"], cantidad=2)
    reserva_b = reservar(client, mundo["b"], cantidad=3)
    envejecer_reserva(db_session, dos_empresas.a, reserva_a["id"])  # solo A tiene una vencida

    respuesta = client.post("/api/v1/tareas/expirar-reservas", headers=TOKEN_SERVICIO)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"expiradas": 1}
    assert stock_de(client, mundo["a"])["cantidad_reservada"] == 0  # A recuperó sus 2
    assert stock_de(client, mundo["b"])["cantidad_reservada"] == 3  # B no se tocó
    assert _estado_reserva(client, mundo["a"], reserva_a["id"]) == "expirada"
    assert _estado_reserva(client, mundo["b"], reserva_b["id"]) == "pendiente"


def test_expirar_ventas_pendientes_libera_el_stock_solo_en_la_empresa_dueña(
    client_por_peticion, dos_empresas, mundo, db_session
):
    client = client_por_peticion
    venta_a, _ = iniciar_pago(client, mundo["a"], cantidad=2)
    venta_b, _ = iniciar_pago(client, mundo["b"], cantidad=3)
    envejecer_venta(db_session, dos_empresas.a, venta_a["id"])

    respuesta = client.post("/api/v1/tareas/expirar-ventas-pendientes", headers=TOKEN_SERVICIO)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"anuladas": 1, "pagadas": 0}
    assert _estado_venta(client, mundo["a"], venta_a["id"]) == "anulada"
    assert _estado_venta(client, mundo["b"], venta_b["id"]) == "pendiente_pago"
    assert stock_de(client, mundo["a"])["cantidad_reservada"] == 0
    assert stock_de(client, mundo["b"])["cantidad_reservada"] == 3


def test_el_resultado_suma_todas_las_empresas(client_por_peticion, dos_empresas, mundo, db_session):
    client = client_por_peticion
    reservas = [reservar(client, mundo[c]) for c in ("a", "b")]
    for empresa, reserva in zip((dos_empresas.a, dos_empresas.b), reservas):
        envejecer_reserva(db_session, empresa, reserva["id"])
    ventas = [iniciar_pago(client, mundo[c])[0] for c in ("a", "b")]
    for empresa, venta in zip((dos_empresas.a, dos_empresas.b), ventas):
        envejecer_venta(db_session, empresa, venta["id"])

    assert client.post("/api/v1/tareas/expirar-reservas", headers=TOKEN_SERVICIO).json() == {"expiradas": 2}
    assert client.post("/api/v1/tareas/expirar-ventas-pendientes", headers=TOKEN_SERVICIO).json() == {
        "anuladas": 2,
        "pagadas": 0,
    }


def test_una_empresa_que_falla_no_frena_a_las_demas(
    client_por_peticion, dos_empresas, mundo, db_session, monkeypatch
):
    client = client_por_peticion
    reserva_a = reservar(client, mundo["a"], cantidad=2)
    reserva_b = reservar(client, mundo["b"], cantidad=3)
    for empresa, reserva in ((dos_empresas.a, reserva_a), (dos_empresas.b, reserva_b)):
        envejecer_reserva(db_session, empresa, reserva["id"])

    original = comercial_politicas.expirar_reservas_vencidas

    def _falla_en_a(db):
        if empresa_de(db) == dos_empresas.a.id:
            raise RuntimeError("falla simulada de la empresa A")
        return original(db)

    monkeypatch.setattr(comercial_politicas, "expirar_reservas_vencidas", _falla_en_a)

    respuesta = client.post("/api/v1/tareas/expirar-reservas", headers=TOKEN_SERVICIO)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"expiradas": 1}  # la de B; la que falló no suma
    assert _estado_reserva(client, mundo["a"], reserva_a["id"]) == "pendiente"
    assert _estado_reserva(client, mundo["b"], reserva_b["id"]) == "expirada"
    assert stock_de(client, mundo["b"])["cantidad_reservada"] == 0


def test_los_endpoints_de_tareas_exigen_el_token_de_servicio(client_por_peticion, mundo):
    client = client_por_peticion
    for ruta, forma in (
        ("/api/v1/tareas/expirar-reservas", {"expiradas": 0}),
        ("/api/v1/tareas/expirar-ventas-pendientes", {"anuladas": 0, "pagadas": 0}),
    ):
        assert client.post(ruta).status_code == 401
        assert client.post(ruta, headers={"X-Service-Token": "otro"}).status_code == 401
        # Con el token y sin empresa en la petición: igual responde, por empresa.
        ok = client.post(ruta, headers=TOKEN_SERVICIO)
        assert ok.status_code == 200
        assert ok.json() == forma


def test_una_empresa_inactiva_no_se_procesa(client_por_peticion, dos_empresas, mundo, db_session):
    client = client_por_peticion
    reserva_a = reservar(client, mundo["a"], cantidad=2)
    reserva_b = reservar(client, mundo["b"], cantidad=3)
    for empresa, reserva in ((dos_empresas.a, reserva_a), (dos_empresas.b, reserva_b)):
        envejecer_reserva(db_session, empresa, reserva["id"])
    db_session.execute(update(Empresa).where(Empresa.id == dos_empresas.b.id).values(activo=False))
    db_session.commit()

    respuesta = client.post("/api/v1/tareas/expirar-reservas", headers=TOKEN_SERVICIO)

    assert respuesta.json() == {"expiradas": 1}  # solo la empresa A
    assert stock_de(client, mundo["a"])["cantidad_reservada"] == 0
    # B (inactiva) conserva su reserva vencida y su stock apartado. Desde la E03
    # sus tokens no valen mientras esté inactiva: se la reactiva para consultarlo.
    db_session.execute(update(Empresa).where(Empresa.id == dos_empresas.b.id).values(activo=True))
    db_session.commit()
    assert stock_de(client, mundo["b"])["cantidad_reservada"] == 3
