"""Webhook de pasarela y pantalla QR: no traen usuario ni token, así que la
empresa sale de la transacción (verificada antes la firma). Se prueban con
`client_por_peticion`: sesión nueva y sin empresa por petición, como en
producción."""

import hashlib
import hmac
import json

import pytest

from app.core.config import get_settings
from tests.comercial._datos_empresa import iniciar_pago, sembrar_empresa, stock_de

SECRETO_LIBELULA = get_settings().libelula_webhook_secret


def _firmado(id_transaccion: str, estado: str = "aprobado") -> tuple[bytes, dict]:
    cuerpo = json.dumps({"id_transaccion": id_transaccion, "estado": estado}).encode("utf-8")
    firma = hmac.new(SECRETO_LIBELULA.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()
    return cuerpo, {"Content-Type": "application/json", "x-signature": firma}


def _webhook(client, id_transaccion: str, estado: str = "aprobado"):
    cuerpo, cabeceras = _firmado(id_transaccion, estado)
    return client.post("/api/v1/pagos/webhook/libelula", content=cuerpo, headers=cabeceras)


@pytest.fixture()
def mundo(client_por_peticion, dos_empresas, db_session):
    return {
        "a": sembrar_empresa(client_por_peticion, db_session, dos_empresas.a),
        "b": sembrar_empresa(client_por_peticion, db_session, dos_empresas.b),
    }


def _estado_venta(client, datos, venta_id):
    return client.get(f"/api/v1/ventas/{venta_id}/comprobante", headers=datos["admin"]).json()["estado"]


def test_el_webhook_resuelve_la_empresa_por_la_transaccion(client_por_peticion, mundo):
    client = client_por_peticion
    venta_a, pago_a = iniciar_pago(client, mundo["a"], cantidad=2)
    venta_b, pago_b = iniciar_pago(client, mundo["b"], cantidad=3)
    fisica_a = stock_de(client, mundo["a"])["cantidad_fisica"]
    fisica_b = stock_de(client, mundo["b"])["cantidad_fisica"]

    # Sin token ni empresa en la petición: solo la transacción dice de quién es.
    respuesta = _webhook(client, pago_a["referencia_externa"])

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == "aprobado"
    assert _estado_venta(client, mundo["a"], venta_a["id"]) == "pagada"
    assert stock_de(client, mundo["a"])["cantidad_fisica"] == fisica_a - 2
    # La otra empresa no se enteró de nada.
    assert _estado_venta(client, mundo["b"], venta_b["id"]) == "pendiente_pago"
    assert stock_de(client, mundo["b"])["cantidad_fisica"] == fisica_b

    # Y la de B se resuelve por su propia transacción.
    assert _webhook(client, pago_b["referencia_externa"]).status_code == 200
    assert _estado_venta(client, mundo["b"], venta_b["id"]) == "pagada"
    assert stock_de(client, mundo["b"])["cantidad_fisica"] == fisica_b - 3


def test_firma_invalida_no_filtra_informacion(client_por_peticion, mundo):
    client = client_por_peticion
    venta, pago = iniciar_pago(client, mundo["a"])
    cuerpo_real, _ = _firmado(pago["referencia_externa"])
    cuerpo_falso, _ = _firmado("LIB-QUE-NO-EXISTE")
    cabeceras = {"Content-Type": "application/json", "x-signature": "firma-trucha"}

    con_id_real = client.post("/api/v1/pagos/webhook/libelula", content=cuerpo_real, headers=cabeceras)
    con_id_falso = client.post("/api/v1/pagos/webhook/libelula", content=cuerpo_falso, headers=cabeceras)

    # La firma se valida ANTES de buscar la transacción: un id real y uno
    # inventado responden exactamente igual, así no se puede sondear ids.
    assert con_id_real.status_code == con_id_falso.status_code == 403
    assert con_id_real.json() == con_id_falso.json()
    assert _estado_venta(client, mundo["a"], venta["id"]) == "pendiente_pago"


def test_id_de_transaccion_desconocido_responde_404(client_por_peticion, mundo):
    cuerpo, cabeceras = _firmado("LIB-DESCONOCIDO")

    respuesta = client_por_peticion.post("/api/v1/pagos/webhook/libelula", content=cuerpo, headers=cabeceras)

    assert respuesta.status_code == 404
    assert "LIB-DESCONOCIDO" in respuesta.json()["detail"]
    assert client_por_peticion.post("/api/v1/pagos/qr/QR-DESCONOCIDO/confirmar").status_code == 404


def test_la_pantalla_qr_de_una_empresa_no_abre_la_transaccion_de_otra(client_por_peticion, dos_empresas, mundo):
    client = client_por_peticion
    venta_a, pago_a = iniciar_pago(client, mundo["a"], metodo="qr_online")
    venta_b, pago_b = iniciar_pago(client, mundo["b"], metodo="qr_online", cantidad=3)
    id_a, id_b = pago_a["referencia_externa"], pago_b["referencia_externa"]

    # Cada pantalla se abre con SU id (sin sesión), y muestra solo su monto.
    pantalla_a = client.get(f"/api/v1/pagos/qr/{id_a}")
    assert pantalla_a.status_code == 200 and "100.00" in pantalla_a.text
    pantalla_b = client.get(f"/api/v1/pagos/qr/{id_b}")
    assert pantalla_b.status_code == 200 and "300.00" in pantalla_b.text

    # Un usuario de A sin conocer el id de B no llega a su transacción: un id
    # que no es de nadie es 404, también con el token de A.
    for adivinado in ("QR-" + id_a[3:][::-1], "QR-0000", id_b[:-1] + "x"):
        assert client.get(f"/api/v1/pagos/qr/{adivinado}", headers=dos_empresas.a.headers).status_code == 404
        assert client.post(f"/api/v1/pagos/qr/{adivinado}/confirmar", headers=dos_empresas.a.headers).status_code == 404

    # Confirmar el QR de A es de A: no mueve nada de B.
    confirmacion = client.post(f"/api/v1/pagos/qr/{id_a}/confirmar", headers=dos_empresas.a.headers)
    assert confirmacion.status_code == 200
    assert confirmacion.json()["estado"] == "aprobado"
    assert _estado_venta(client, mundo["a"], venta_a["id"]) == "pagada"
    assert _estado_venta(client, mundo["b"], venta_b["id"]) == "pendiente_pago"
    assert "btn-confirmar" in client.get(f"/api/v1/pagos/qr/{id_b}").text  # el de B sigue sin resolver
