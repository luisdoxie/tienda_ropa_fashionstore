"""E07: observabilidad (RNF10). El log del paquete (`app.sincronizacion`) tiene una línea por evento
en formato clave=valor y NUNCA payloads, montos, clientes, nombres, correos ni tokens; la bitácora
guarda UNA fila por lote con el resumen y sin payloads."""

import logging
import re

import pytest

from tests.ayudas_bitacora import exigir_datos_sin_sensibles, filas_de
from tests.sincronizacion.ayudas import armar_reserva, armar_venta, enviar

LOGGER = "app.sincronizacion"
CLAVE_VALOR = re.compile(r"(\w+)=(\S*)")

# Montos reconocibles: si aparecen en el log, alguien está volcando el payload.
PRECIO = "187.35"
TOTAL = "374.70"
RECIBIDO = "999.99"
CAMBIO = "625.29"
OBSERVACION = "Viene por la camisa azul"


@pytest.fixture()
def log(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    return caplog


def _lineas(caplog, evento: str | None = None) -> list[str]:
    """Los mensajes del paquete (con su traza si la hubiera), opcionalmente de un evento."""
    mensajes = []
    for registro in caplog.records:
        if registro.name.startswith(LOGGER):
            mensajes.append(registro.getMessage() + (f"\n{registro.exc_text}" if registro.exc_text else ""))
    return [m for m in mensajes if evento is None or m.startswith(evento + " ")]


def _campos(linea: str) -> dict[str, str]:
    return dict(CLAVE_VALOR.findall(linea))


def _lote_de_prueba(escenario):
    """Una venta confirmada (con montos reconocibles), una rechazada, un conflicto de stock y una reserva."""
    linea = [{"variante_id": escenario.v1, "cantidad": 2, "precio_unitario": PRECIO, "descuento_unitario": "0.00"}]
    sin_variante = [{"variante_id": 999999, "cantidad": 1, "precio_unitario": PRECIO, "descuento_unitario": "0.00"}]
    sin_stock = [{"variante_id": escenario.v2, "cantidad": 5, "precio_unitario": PRECIO, "descuento_unitario": "0.00"}]
    return {
        "confirmada": armar_venta(escenario, lineas=linea, total=TOTAL, monto_recibido=RECIBIDO),
        "rechazada": armar_venta(escenario, lineas=sin_variante, total=PRECIO, monto_recibido=RECIBIDO),
        "en_conflicto": armar_venta(escenario, lineas=sin_stock, total="936.75", monto_recibido=RECIBIDO),
        "reserva": armar_reserva(escenario, observacion=OBSERVACION),
    }


def test_hay_una_linea_sync_operacion_por_operacion_con_sus_campos(client, escenario, log):
    operaciones = _lote_de_prueba(escenario)
    respuesta = enviar(client, escenario.cajero, list(operaciones.values()))
    assert respuesta.status_code == 200, respuesta.text

    lineas = _lineas(log, "sync_operacion")
    assert len(lineas) == 4
    por_operacion = {_campos(l)["op"]: _campos(l) for l in lineas}
    esperado = {
        "confirmada": ("venta_contado", "confirmada", "-"),
        "rechazada": ("venta_contado", "rechazada", "variante_inexistente"),
        "en_conflicto": ("venta_contado", "en_conflicto", "stock_insuficiente"),
        "reserva": ("reserva", "confirmada", "-"),
    }
    lotes = set()
    for clave, (tipo, estado, motivo) in esperado.items():
        campos = por_operacion[operaciones[clave]["operacion_id"][:8]]
        assert (campos["tipo"], campos["estado"], campos["motivo"]) == (tipo, estado, motivo), campos
        assert re.fullmatch(r"\d+", campos["ms"]), campos  # milisegundos
        assert re.fullmatch(r"[0-9a-f]{8}", campos["lote"]), campos
        lotes.add(campos["lote"])
    assert len(lotes) == 1  # el mismo identificador de lote en todas las líneas


def test_hay_una_linea_de_inicio_y_otra_de_fin_del_lote_con_el_mismo_identificador(client, escenario, log):
    operaciones = _lote_de_prueba(escenario)
    enviar(client, escenario.cajero, list(operaciones.values()), dispositivo="pwa-chrome-3f2a")

    inicio, fin = _lineas(log, "sync_lote_recibido"), _lineas(log, "sync_lote_fin")
    assert len(inicio) == 1 and len(fin) == 1
    recibido, final = _campos(inicio[0]), _campos(fin[0])
    assert recibido["ops"] == "4" and recibido["disp"] == "pwa-chrome-3f2a"
    assert recibido["usuario"] == str(escenario.cajero_usuario_id) and recibido["empresa"].isdigit()
    assert recibido["lote"] == final["lote"] == _campos(_lineas(log, "sync_operacion")[0])["lote"]
    assert (final["conf"], final["rech"], final["confl"], final["dup"]) == ("2", "1", "1", "0")
    assert re.fullmatch(r"\d+", final["ms"])
    # El orden del log: inicio, las operaciones, fin.
    mensajes = _lineas(log)
    assert mensajes[0].startswith("sync_lote_recibido") and mensajes[-1].startswith("sync_lote_fin")


def test_ninguna_linea_del_log_trae_montos_clientes_nombres_correos_tokens_ni_el_payload(
    client, escenario, log
):
    operaciones = _lote_de_prueba(escenario)
    token = escenario.cajero["Authorization"].removeprefix("Bearer ")
    respuesta = enviar(client, escenario.cajero, list(operaciones.values()), dispositivo="pwa-chrome-3f2a")
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["resultados"][0]["cambio"] == CAMBIO  # el cambio existe en la respuesta, pero no en el log

    texto = "\n".join(_lineas(log))
    assert texto  # hay algo que revisar
    prohibido = [
        PRECIO, TOTAL, RECIBIDO, CAMBIO, "936.75",  # montos
        OBSERVACION, "camisa", "Cli Sync", "Sync ", "cliente@example.com", "cajero-sync", "encargado-sync",  # texto libre y personas
        token, "Bearer", "eyJ",  # credenciales
    ]  # fmt: skip
    for dato in prohibido:
        assert dato not in texto, f"el log del paquete contiene {dato!r}:\n{texto}"
    for palabra in ("payload", "cliente", "cliente_id", "monto", "total=", "precio", "lineas", "pago", "@", "password", "{", "["):
        assert palabra not in texto.lower(), f"el log del paquete contiene {palabra!r}:\n{texto}"


def test_la_bitacora_guarda_una_fila_por_lote_con_el_resumen_y_sin_payloads(client, db_session, escenario, log):
    operaciones = _lote_de_prueba(escenario)
    enviar(client, escenario.cajero, list(operaciones.values()), dispositivo="pwa-chrome-3f2a")
    enviar(client, escenario.cajero, [armar_venta(escenario)])  # un segundo lote: otra fila

    filas = filas_de(db_session, "lote_sync", "sincronizar_lote")
    assert len(filas) == 2  # UNA por lote, no una por operación
    primera = filas[0]
    assert primera.entidad_id is None and primera.usuario_id == escenario.cajero_usuario_id
    datos = primera.datos
    assert set(datos) == {"lote", "dispositivo", "resumen", "no_confirmadas"}
    assert datos["dispositivo"] == "pwa-chrome-3f2a"
    assert datos["lote"] == _campos(_lineas(log, "sync_lote_recibido")[0])["lote"]
    assert datos["resumen"] == {
        "total": 4, "confirmadas": 2, "rechazadas": 1, "en_conflicto": 1, "errores_temporales": 0, "duplicadas": 0,
    }
    assert sorted(datos["no_confirmadas"], key=lambda n: n["estado"]) == sorted(
        [
            {"operacion_id": operaciones["rechazada"]["operacion_id"], "estado": "rechazada", "motivo": "variante_inexistente"},
            {"operacion_id": operaciones["en_conflicto"]["operacion_id"], "estado": "en_conflicto", "motivo": "stock_insuficiente"},
        ],
        key=lambda n: n["estado"],
    )  # las confirmadas no se repiten: ya están en operacion_sync

    for fila in filas:
        exigir_datos_sin_sensibles(fila)
        texto = str(fila.datos)
        for dato in (PRECIO, TOTAL, RECIBIDO, OBSERVACION, "payload", "lineas", "cliente", "monto"):
            assert dato not in texto, f"la bitácora contiene {dato!r}: {texto}"
    assert filas[1].datos["resumen"]["total"] == 1 and filas[1].datos["no_confirmadas"] == []


def test_un_lote_de_solo_duplicadas_registra_dup_en_el_log_y_en_la_bitacora(client, db_session, escenario, log):
    operaciones = list(_lote_de_prueba(escenario).values())
    enviar(client, escenario.cajero, operaciones)
    log.clear()

    respuesta = enviar(client, escenario.cajero, operaciones)
    assert respuesta.json()["resumen"]["duplicadas"] == 4

    fin = _campos(_lineas(log, "sync_lote_fin")[0])
    assert fin["dup"] == "4" and fin["conf"] == "2" and fin["rech"] == "1" and fin["confl"] == "1"
    operaciones_log = [_campos(l) for l in _lineas(log, "sync_operacion")]
    assert len(operaciones_log) == 4 and all(o["dup"] == "1" for o in operaciones_log)
    # Lo devuelto es lo guardado: mismo estado y motivo que la primera vez.
    assert sorted((o["estado"], o["motivo"]) for o in operaciones_log) == sorted(
        [("confirmada", "-"), ("confirmada", "-"), ("rechazada", "variante_inexistente"), ("en_conflicto", "stock_insuficiente")]
    )

    filas = filas_de(db_session, "lote_sync", "sincronizar_lote")
    assert len(filas) == 2
    assert filas[1].datos["resumen"]["duplicadas"] == 4
    assert len(filas[1].datos["no_confirmadas"]) == 2  # las no confirmadas se listan también al reenviar


def test_el_dispositivo_con_un_correo_adentro_se_sanea_en_el_log(client, db_session, escenario, log):
    dispositivo = "Juan Perez <juan.perez@correo.com> tel 70012345"
    respuesta = enviar(client, escenario.cajero, [armar_venta(escenario)], dispositivo=dispositivo)
    assert respuesta.status_code == 200, respuesta.text

    texto = "\n".join(_lineas(log))
    for dato in ("@", "juan.perez@correo.com", "<", ">", " tel "):
        assert dato not in texto, f"el log contiene {dato!r}:\n{texto}"
    disp = _campos(_lineas(log, "sync_lote_recibido")[0])["disp"]
    assert re.fullmatch(r"[\w.\-]+", disp), disp  # una sola palabra, sin espacios ni símbolos
    assert len(_lineas(log, "sync_lote_recibido")) == 1  # el valor no partió la línea
    # La bitácora tampoco guarda el correo (la auditoría lo omite).
    fila = filas_de(db_session, "lote_sync", "sincronizar_lote")[0]
    exigir_datos_sin_sensibles(fila)
    assert "juan.perez" not in str(fila.datos)
