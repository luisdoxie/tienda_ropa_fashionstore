"""E07: el contrato JSON v1 de la sincronización (sección 4.2 de la especificación), compartido por
la PWA (E14) y Flutter (E20). Los ejemplos de la especificación validan contra los schemas, una
respuesta real respeta el contrato (montos como TEXTO decimal, fechas en UTC con "Z", claves
exactas) y el JSON Schema queda CONGELADO en `contrato_v1.json`: cambiar el contrato sin subir
`version_contrato` y regenerar ese archivo hace fallar la prueba."""

import json
import re
from pathlib import Path

from app.sincronizacion.schemas import (
    PAYLOAD_POR_TIPO,
    VERSION_CONTRATO,
    LoteEntrada,
    LoteRespuesta,
)
from tests.sincronizacion.ayudas import armar_reserva, armar_venta, enviar

ARCHIVO_CONTRATO = Path(__file__).with_name("contrato_v1.json")
FECHA_UTC_CON_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MONTO_TEXTO = re.compile(r"^-?\d+\.\d{2}$")

# ---- Ejemplos de la sección 4.2 (los "...." del texto se completan con UUID válidos) ----------------

PETICION_EJEMPLO = {
    "version_contrato": "1.0",
    "empresa_id": 3,
    "dispositivo": "pwa-chrome-3f2a",
    "operaciones": [
        {
            "operacion_id": "0d6b6c1e-4f2a-4b8e-9c1d-7a5e3f2b1c90",
            "tipo": "venta_contado",
            "sucursal_id": 2,
            "fecha_operacion": "2026-10-20T14:05:00-04:00",
            "payload": {
                "cliente_id": 15,
                "lineas": [
                    {"variante_id": 41, "cantidad": 2, "precio_unitario": "120.00", "descuento_unitario": "10.00"}
                ],
                "total": "220.00",
                "pago": {"metodo": "efectivo", "monto_recibido": "250.00"},
            },
        },
        {
            "operacion_id": "7c1e9a52-0b3d-4e6f-8a21-5d4c3b2a1f00",
            "tipo": "reserva",
            "sucursal_id": 2,
            "fecha_operacion": "2026-10-20T14:10:00Z",
            "payload": {
                "cliente_id": 15,
                "fecha_visita": "2026-10-22",
                "hora_visita_desde": "10:00",
                "hora_visita_hasta": "11:00",
                "observacion": "Viene por la camisa azul",
                "lineas": [{"variante_id": 41, "cantidad": 1}],
            },
        },
    ],
}

RESPUESTA_EJEMPLO = {
    "version_contrato": "1.0",
    "procesado_en": "2026-10-20T18:07:11Z",
    "resumen": {"total": 4, "confirmadas": 2, "rechazadas": 1, "en_conflicto": 1, "errores_temporales": 0, "duplicadas": 1},
    "resultados": [
        {
            "operacion_id": "0d6b6c1e-4f2a-4b8e-9c1d-7a5e3f2b1c90",
            "estado": "confirmada",
            "motivo": None,
            "mensaje": None,
            "duplicada": False,
            "procesada_en": "2026-10-20T18:07:11Z",
            "recurso": {"tipo": "venta", "id": 88, "codigo": "VTA-1A2B3C4D", "total": "220.00", "fecha_expiracion": None},
            "cambio": "30.00",
            "avisos": [
                {"codigo": "precio_distinto", "variante_id": 41, "precio_operacion": "110.00", "precio_actual": "120.00"}
            ],
            "faltantes": [],
        },
        {
            "operacion_id": "7c1e9a52-0b3d-4e6f-8a21-5d4c3b2a1f00",
            "estado": "confirmada",
            "motivo": None,
            "mensaje": None,
            "duplicada": True,
            "procesada_en": "2026-10-20T18:05:00Z",
            "recurso": {
                "tipo": "reserva", "id": 31, "codigo": "RES-9F8E7D6C", "total": None,
                "fecha_expiracion": "2026-10-22T11:00:00Z",
            },  # fmt: skip
            "cambio": None,
            "avisos": [],
            "faltantes": [],
        },
        {
            "operacion_id": "3b9d7f10-6a4c-4d2e-b5f8-1c0e9a8b7d60",
            "estado": "rechazada",
            "motivo": "variante_inexistente",
            "mensaje": "La variante 999 no existe",
            "duplicada": False,
            "procesada_en": "2026-10-20T18:07:11Z",
            "recurso": None,
            "cambio": None,
            "avisos": [],
            "faltantes": [],
        },
        {
            "operacion_id": "e5a4c3b2-9d8f-4a7b-8c6d-0f1e2d3c4b5a",
            "estado": "en_conflicto",
            "motivo": "stock_insuficiente",
            "mensaje": "No hay stock disponible suficiente de la variante 41",
            "duplicada": False,
            "procesada_en": "2026-10-20T18:07:11Z",
            "recurso": None,
            "cambio": None,
            "avisos": [],
            "faltantes": [{"variante_id": 41, "solicitado": 2, "disponible": 1}],
        },
    ],
}

CLAVES_RESUMEN = {"total", "confirmadas", "rechazadas", "en_conflicto", "errores_temporales", "duplicadas"}
CLAVES_RESULTADO = {
    "operacion_id", "estado", "motivo", "mensaje", "duplicada", "procesada_en", "recurso", "cambio", "avisos", "faltantes",
}  # fmt: skip


# ---- Los ejemplos de la especificación -------------------------------------------------------------


def test_la_peticion_de_ejemplo_de_la_especificacion_valida_contra_lote_entrada():
    lote = LoteEntrada.model_validate(PETICION_EJEMPLO)

    assert lote.version_contrato == "1.0" and lote.empresa_id == 3 and lote.dispositivo == "pwa-chrome-3f2a"
    assert [o.tipo for o in lote.operaciones] == ["venta_contado", "reserva"]
    # Las fechas llevan zona y se pueden normalizar a UTC.
    assert all(o.fecha_operacion.utcoffset() is not None for o in lote.operaciones)
    # Cada payload valida contra el modelo de su tipo, y los montos quedan como Decimal exacto.
    venta = PAYLOAD_POR_TIPO["venta_contado"].model_validate(lote.operaciones[0].payload)
    reserva = PAYLOAD_POR_TIPO["reserva"].model_validate(lote.operaciones[1].payload)
    assert str(venta.total) == "220.00" and str(venta.lineas[0].descuento_unitario) == "10.00"
    assert str(venta.pago.monto_recibido) == "250.00"
    assert reserva.fecha_visita.isoformat() == "2026-10-22" and reserva.lineas[0].cantidad == 1


def test_la_respuesta_de_ejemplo_de_la_especificacion_valida_y_se_serializa_igual():
    respuesta = LoteRespuesta.model_validate(RESPUESTA_EJEMPLO)

    assert respuesta.resumen.model_dump().keys() == CLAVES_RESUMEN
    # Ida y vuelta: lo que sale es EXACTAMENTE el contrato (montos como texto, fechas con "Z", claves).
    assert respuesta.model_dump(mode="json") == RESPUESTA_EJEMPLO


# ---- Una respuesta real ---------------------------------------------------------------------------


def test_una_respuesta_real_del_endpoint_respeta_el_contrato(client, escenario):
    precio_distinto = [{"variante_id": escenario.v1, "cantidad": 2, "precio_unitario": "90.00", "descuento_unitario": "0.00"}]
    sin_variante = [{"variante_id": 999999, "cantidad": 1, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    sin_stock = [{"variante_id": escenario.v2, "cantidad": 5, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    venta = armar_venta(escenario, lineas=precio_distinto, total="180.00", monto_recibido="200.00")
    operaciones = [
        venta,
        armar_reserva(escenario),
        armar_venta(escenario, lineas=sin_variante, monto_recibido="100.00"),
        armar_venta(escenario, lineas=sin_stock, monto_recibido="500.00"),
    ]
    enviar(client, escenario.cajero, [venta])  # la venta ya existe: en el lote real es un reenvío
    http = enviar(client, escenario.cajero, operaciones, dispositivo="pwa-chrome-3f2a")

    assert http.status_code == 200, http.text
    cuerpo = http.json()
    respuesta = LoteRespuesta.model_validate(cuerpo)  # valida contra el schema del contrato
    assert respuesta.model_dump(mode="json") == cuerpo  # y no sobra ni falta nada

    assert cuerpo["version_contrato"] == VERSION_CONTRATO == "1.0"
    assert FECHA_UTC_CON_Z.match(cuerpo["procesado_en"])
    assert set(cuerpo) == {"version_contrato", "procesado_en", "resumen", "resultados"}
    assert set(cuerpo["resumen"]) == CLAVES_RESUMEN
    assert cuerpo["resumen"] == {
        "total": 4, "confirmadas": 2, "rechazadas": 1, "en_conflicto": 1, "errores_temporales": 0, "duplicadas": 1,
    }
    assert [r["operacion_id"] for r in cuerpo["resultados"]] == [o["operacion_id"] for o in operaciones]  # mismo orden
    venta_r, reserva_r, rechazada_r, conflicto_r = cuerpo["resultados"]

    for resultado in cuerpo["resultados"]:
        assert set(resultado) == CLAVES_RESULTADO
        assert FECHA_UTC_CON_Z.match(resultado["procesada_en"])
        assert isinstance(resultado["duplicada"], bool) and isinstance(resultado["avisos"], list)

    # Montos como TEXTO decimal, nunca número.
    assert venta_r["duplicada"] is True and venta_r["estado"] == "confirmada"
    assert venta_r["recurso"]["total"] == "180.00" and isinstance(venta_r["recurso"]["total"], str)
    assert venta_r["cambio"] == "20.00" and isinstance(venta_r["cambio"], str)
    assert set(venta_r["recurso"]) == {"tipo", "id", "codigo", "total", "fecha_expiracion"}
    aviso = venta_r["avisos"][0]
    assert set(aviso) == {"codigo", "variante_id", "precio_operacion", "precio_actual"}
    assert aviso["codigo"] == "precio_distinto"
    assert (aviso["precio_operacion"], aviso["precio_actual"]) == ("90.00", "100.00")
    assert all(MONTO_TEXTO.match(v) for v in (aviso["precio_operacion"], aviso["precio_actual"], venta_r["cambio"]))

    assert reserva_r["recurso"]["tipo"] == "reserva" and reserva_r["cambio"] is None
    assert FECHA_UTC_CON_Z.match(reserva_r["recurso"]["fecha_expiracion"])
    assert reserva_r["recurso"]["total"] is None

    assert (rechazada_r["estado"], rechazada_r["motivo"]) == ("rechazada", "variante_inexistente")
    assert rechazada_r["recurso"] is None and rechazada_r["mensaje"]
    assert (conflicto_r["estado"], conflicto_r["motivo"]) == ("en_conflicto", "stock_insuficiente")
    assert conflicto_r["faltantes"] == [{"variante_id": escenario.v2, "solicitado": 5, "disponible": 3}]
    assert set(conflicto_r["faltantes"][0]) == {"variante_id", "solicitado", "disponible"}


# ---- El contrato congelado --------------------------------------------------------------------------


def _sin_descripciones(valor):
    """Quita los textos `description` (salen de los docstrings): corregir un comentario no es
    cambiar el contrato."""
    if isinstance(valor, dict):
        return {k: _sin_descripciones(v) for k, v in valor.items() if not (k == "description" and isinstance(v, str))}
    if isinstance(valor, list):
        return [_sin_descripciones(v) for v in valor]
    return valor


def _contrato_actual() -> dict:
    return {
        "version_contrato": VERSION_CONTRATO,
        "LoteEntrada": _sin_descripciones(LoteEntrada.model_json_schema()),
        "LoteRespuesta": _sin_descripciones(LoteRespuesta.model_json_schema()),
    }


def test_el_json_schema_coincide_con_contrato_v1_json():
    guardado = json.loads(ARCHIVO_CONTRATO.read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(_contrato_actual()))  # pasa por JSON, como el archivo

    for parte in ("LoteEntrada", "LoteRespuesta"):
        assert actual[parte] == guardado[parte], (
            f"El contrato {parte} cambió respecto de contrato_v1.json. Si el cambio es intencional: "
            "subir version_contrato y regenerar contrato_v1.json (VERSION_CONTRATO está en app/sincronizacion/schemas.py): "
            "json.dumps(_contrato_actual(), sort_keys=True, indent=2, ensure_ascii=False) de este módulo "
            "(LoteEntrada.model_json_schema() y LoteRespuesta.model_json_schema() sin las descripciones). "
            "Un cambio de contrato sin nueva versión rompe a la PWA y a la app móvil."
        )
    assert actual["version_contrato"] == guardado["version_contrato"], (
        "version_contrato cambió sin regenerar contrato_v1.json: subir version_contrato y regenerar contrato_v1.json"
    )
    assert actual == guardado


def test_la_version_del_contrato_es_1_0_en_la_peticion_y_en_la_respuesta():
    assert VERSION_CONTRATO == "1.0"
    assert json.loads(ARCHIVO_CONTRATO.read_text(encoding="utf-8"))["version_contrato"] == "1.0"
    respuesta = LoteRespuesta.model_validate({**RESPUESTA_EJEMPLO, "version_contrato": "1.0"})
    assert respuesta.version_contrato == "1.0"
    # El valor por defecto de la respuesta es la versión vigente (la usa el servidor al responder).
    omitida = {k: v for k, v in RESPUESTA_EJEMPLO.items() if k != "version_contrato"}
    assert LoteRespuesta.model_validate(omitida).version_contrato == VERSION_CONTRATO
