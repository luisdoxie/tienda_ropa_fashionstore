import pytest

from tests.sincronizacion.ayudas import Escenario, construir_escenario


@pytest.fixture()
def escenario(client, admin_headers, db_session, cliente_headers) -> Escenario:
    """La empresa de las semillas ('fashionstore', plan Profesional, suscripción activa) con
    catálogo, stock (v1: 10, v2: 3), sucursal abierta, cajero, encargado y cliente."""
    return construir_escenario(client, admin_headers, db_session, cliente_email="cliente@example.com")
