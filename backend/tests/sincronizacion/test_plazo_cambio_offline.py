"""E08 (D19): el plazo para devolver o cambiar prendas se cuenta desde la fecha REAL de la venta.
En una venta registrada sin conexión esa fecha es la `fecha_operacion` del dispositivo, no la hora en
que se sincronizó: sincronizar tarde no regala plazo. Aplica igual a la venta forzada por un encargado
(4.B) y a la consulta `GET /ventas/{id}/plazo-cambio`. Las pruebas usan el reloj real con holgura
(minutos) respecto de cada borde; los bordes exactos al segundo están en
`tests/comercial/test_plazo_cambio.py`."""

import datetime as dt

from tests.sincronizacion.ayudas import API, armar_venta, en_utc_naive, enviar, hace

HORA = 60  # minutos
FORMATO_UTC = "%Y-%m-%dT%H:%M:%SZ"
MI_EMPRESA = "/api/v1/mi-empresa"


def _linea(variante_id: int, cantidad: int) -> dict:
    return {"variante_id": variante_id, "cantidad": cantidad, "precio_unitario": "100.00", "descuento_unitario": "0.00"}


def _sincronizar_venta(client, escenario, minutos: int) -> tuple[dict, int]:
    """Sincroniza AHORA una venta hecha sin conexión hace `minutos`. Devuelve (operación, id de la venta)."""
    operacion = armar_venta(escenario, fecha_operacion=hace(minutos))
    resultado = enviar(client, escenario.cajero, [operacion])
    assert resultado.status_code == 200, resultado.text
    fila = resultado.json()["resultados"][0]
    assert fila["estado"] == "confirmada", fila
    assert fila["recurso"]["tipo"] == "venta"
    return operacion, fila["recurso"]["id"]


def _devolver(client, headers: dict, venta_id: int):
    """Devuelve 1 unidad de la primera línea de la venta (el id de la línea sale del comprobante)."""
    comprobante = client.get(f"/api/v1/ventas/{venta_id}/comprobante", headers=headers)
    assert comprobante.status_code == 200, comprobante.text
    linea_id = comprobante.json()["detalle"][0]["id"]
    return client.post(
        "/api/v1/devoluciones",
        json={"venta_id": venta_id, "motivo": "Talle", "detalle": [{"venta_detalle_id": linea_id, "cantidad": 1}]},
        headers=headers,
    )


def _plazo(client, headers: dict, venta_id: int) -> dict:
    respuesta = client.get(f"/api/v1/ventas/{venta_id}/plazo-cambio", headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _marca(texto: str) -> dt.datetime:
    return dt.datetime.strptime(texto, FORMATO_UTC)


# ---- la fecha de la operación manda, no la de la sincronización -------------------------------------------------


def test_una_venta_offline_de_hace_25_horas_ya_no_admite_devolucion_aunque_se_sincronizo_hace_un_minuto(
    client, escenario
):
    _, venta_id = _sincronizar_venta(client, escenario, 25 * HORA)  # se sincroniza recién ahora

    respuesta = _devolver(client, escenario.cajero, venta_id)

    assert respuesta.status_code == 409, respuesta.text
    detalle = respuesta.json()["detail"]
    assert detalle.startswith("El plazo para cambiar prendas de esta venta ya venció")
    assert "25 h" in detalle and "24 horas" in detalle


def test_una_venta_offline_de_hace_2_horas_admite_la_devolucion(client, escenario):
    operacion, venta_id = _sincronizar_venta(client, escenario, 2 * HORA)

    respuesta = _devolver(client, escenario.cajero, venta_id)

    assert respuesta.status_code == 201, respuesta.text
    # Y le quedan unas 22 horas, contadas desde la fecha de la operación (no 24 desde la sincronización).
    plazo = _plazo(client, escenario.cajero, venta_id)
    assert plazo["fecha_venta"] == en_utc_naive(operacion["fecha_operacion"]).strftime(FORMATO_UTC)
    ahora = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    assert dt.timedelta(hours=21, minutes=55) < _marca(plazo["vence_en"]) - ahora < dt.timedelta(hours=22, minutes=5)


def test_bordes_del_plazo_con_ventas_offline_23_h_59_min_entra_y_24_h_5_min_no(client, escenario):
    _, justo_dentro = _sincronizar_venta(client, escenario, 23 * HORA + 59)
    _, recien_vencida = _sincronizar_venta(client, escenario, 24 * HORA + 5)

    assert _devolver(client, escenario.cajero, justo_dentro).status_code == 201
    vencida = _devolver(client, escenario.cajero, recien_vencida)

    assert vencida.status_code == 409, vencida.text
    assert "24 h" in vencida.json()["detail"] and "24 horas" in vencida.json()["detail"]


# ---- la venta forzada por el encargado conserva la fecha de la operación ----------------------------------------


def _forzar(client, escenario, minutos: int) -> tuple[dict, int]:
    """Una venta que pide 5 de v2 (hay 3) queda en conflicto; el encargado la fuerza. Devuelve (operación, id de la venta)."""
    operacion = armar_venta(
        escenario, lineas=[_linea(escenario.v2, 5)], monto_recibido="900.00", fecha_operacion=hace(minutos)
    )
    resultado = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]
    assert resultado["estado"] == "en_conflicto", resultado
    forzada = client.post(
        f"{API}/operaciones/{operacion['operacion_id']}/resolver", json={"accion": "forzar"}, headers=escenario.encargado
    )
    assert forzada.status_code == 200, forzada.text
    assert forzada.json()["estado"] == "confirmada" and forzada.json()["recurso"]["tipo"] == "venta"
    return operacion, forzada.json()["recurso"]["id"]


def test_la_venta_forzada_de_hace_30_horas_conserva_su_fecha_y_no_admite_devolucion(client, escenario):
    operacion, venta_id = _forzar(client, escenario, 30 * HORA)  # el encargado la confirma AHORA

    plazo = _plazo(client, escenario.encargado, venta_id)

    assert plazo["vigente"] is False
    assert plazo["fecha_venta"] == en_utc_naive(operacion["fecha_operacion"]).strftime(FORMATO_UTC)
    assert plazo["plazo_horas"] == 24
    respuesta = _devolver(client, escenario.cajero, venta_id)
    assert respuesta.status_code == 409, respuesta.text
    assert "30 h" in respuesta.json()["detail"] and "24 horas" in respuesta.json()["detail"]


def test_la_venta_forzada_de_hace_2_horas_sigue_vigente_y_admite_devolucion(client, escenario):
    operacion, venta_id = _forzar(client, escenario, 2 * HORA)

    plazo = _plazo(client, escenario.encargado, venta_id)

    assert plazo["vigente"] is True
    assert plazo["fecha_venta"] == en_utc_naive(operacion["fecha_operacion"]).strftime(FORMATO_UTC)
    assert _devolver(client, escenario.cajero, venta_id).status_code == 201


# ---- la venta en línea usa su fecha de creación -----------------------------------------------------------------


def test_una_venta_en_linea_normal_cuenta_el_plazo_desde_su_creacion(client, escenario):
    antes = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(seconds=2)
    venta = client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": escenario.sucursal_id, "detalle": [{"variante_id": escenario.v1, "cantidad": 2}]},
        headers=escenario.cajero,
    )
    assert venta.status_code == 201, venta.text
    venta_id = venta.json()["id"]
    pago = client.post("/api/v1/pagos/caja", json={"venta_id": venta_id, "metodo_pago": "qr"}, headers=escenario.cajero)
    assert pago.status_code in (200, 201), pago.text

    plazo = _plazo(client, escenario.cajero, venta_id)

    despues = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(seconds=2)
    assert plazo["vigente"] is True and plazo["plazo_horas"] == 24
    assert antes <= _marca(plazo["fecha_venta"]) <= despues  # la hora de la venta, no la de otra cosa
    assert _marca(plazo["vence_en"]) - _marca(plazo["fecha_venta"]) == dt.timedelta(hours=24)
    assert _devolver(client, escenario.cajero, venta_id).status_code == 201


# ---- GET /ventas/{id}/plazo-cambio de una venta offline ---------------------------------------------------------


def test_el_plazo_de_una_venta_offline_vence_24_horas_despues_de_la_fecha_de_la_operacion(client, escenario):
    operacion, venta_id = _sincronizar_venta(client, escenario, 10 * HORA)

    plazo = _plazo(client, escenario.cajero, venta_id)

    fecha_operacion = en_utc_naive(operacion["fecha_operacion"])
    assert plazo["venta_id"] == venta_id and plazo["vigente"] is True
    assert plazo["fecha_venta"] == fecha_operacion.strftime(FORMATO_UTC)
    assert plazo["vence_en"] == (fecha_operacion + dt.timedelta(hours=24)).strftime(FORMATO_UTC)
    # La hora de sincronización (ahora) está unas 10 horas después de la fecha de la venta, no al lado de ella.
    ahora = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    assert dt.timedelta(hours=9, minutes=55) < ahora - _marca(plazo["fecha_venta"]) < dt.timedelta(hours=10, minutes=5)


def test_con_un_plazo_propio_de_48_horas_una_venta_offline_de_30_horas_pasa_a_vigente(client, escenario):
    _, venta_id = _sincronizar_venta(client, escenario, 30 * HORA)
    assert _plazo(client, escenario.cajero, venta_id)["vigente"] is False
    assert _devolver(client, escenario.cajero, venta_id).status_code == 409

    cambio = client.put(MI_EMPRESA, json={"plazo_cambio_horas": 48}, headers=escenario.admin)
    assert cambio.status_code == 200, cambio.text

    plazo = _plazo(client, escenario.cajero, venta_id)
    assert plazo["plazo_horas"] == 48 and plazo["vigente"] is True
    assert _marca(plazo["vence_en"]) - _marca(plazo["fecha_venta"]) == dt.timedelta(hours=48)
    assert _devolver(client, escenario.cajero, venta_id).status_code == 201
