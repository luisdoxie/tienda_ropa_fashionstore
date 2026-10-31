"""E22: prueba de humo del flujo completo por HTTP (crear, listar, detalle y tablas). Las pruebas detalladas (C1-C13)
viven en test_copias_seguridad.py."""

import hashlib
import json
import zipfile
from io import BytesIO

API = "/api/v1/copias-seguridad"


def test_el_administrador_crea_y_descarga_una_copia(client, admin_headers):
    respuesta = client.post(API, headers=admin_headers)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"] == "application/zip"
    assert respuesta.headers["content-disposition"].startswith('attachment; filename="fashionstore-fashionstore-')
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.headers["x-checksum-sha256"] == hashlib.sha256(respuesta.content).hexdigest()
    zf = zipfile.ZipFile(BytesIO(respuesta.content))
    assert zf.testzip() is None
    manifiesto = json.loads(zf.read("manifest.json"))
    assert manifiesto["formato"] == "fashionstore-copia-1"

    historial = client.get(API, headers=admin_headers).json()
    assert historial["total"] == 1
    copia = historial["items"][0]
    assert copia["id"] == int(respuesta.headers["x-copia-id"])
    assert copia["estado"] == "completada"
    assert copia["checksum"] == respuesta.headers["x-checksum-sha256"]
    assert copia["tamano_bytes"] == len(respuesta.content)
    assert copia["total_filas"] == sum(manifiesto["tablas"][t]["filas"] for t in manifiesto["tablas"])

    detalle = client.get(f"{API}/{copia['id']}", headers=admin_headers)
    assert detalle.status_code == 200 and detalle.json()["id"] == copia["id"]


def test_tablas_devuelve_lo_que_incluye_y_lo_que_no(client, admin_headers):
    cuerpo = client.get(f"{API}/tablas", headers=admin_headers).json()
    assert "venta" in cuerpo["incluidas"] and "plan" in cuerpo["referencias"]
    assert {e["tabla"] for e in cuerpo["excluidas"]} >= {"transaccion_pasarela", "probador_generacion"}
    assert cuerpo["columnas_excluidas"]["usuario"] == ["password_hash"]


def test_sin_token_es_401(client):
    assert client.post(API).status_code == 401
