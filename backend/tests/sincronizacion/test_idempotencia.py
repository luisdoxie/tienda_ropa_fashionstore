"""E07: idempotencia. Reenviar una `operacion_id` ya guardada devuelve lo guardado (duplicada=true),
suma un intento e IGNORA el payload nuevo; nunca repite la venta ni la reserva. La clave única es
(empresa, operacion_id): la misma id en otra empresa es otra operación."""

import uuid

from sqlalchemy import func, select

from app.comercial.models import Venta
from app.core.tenant import empresa_de, fijar_empresa
from app.sincronizacion.models import OperacionSync
from tests.sincronizacion.ayudas import (
    STOCK_V1,
    STOCK_V2,
    armar_venta,
    construir_escenario,
    enviar,
    hace,
    nuevo_uuid,
    stock_de,
)


def _contar(db, modelo) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(modelo))


def _fila(db, operacion_id: str) -> OperacionSync:
    db.expire_all()
    return db.scalars(select(OperacionSync).where(OperacionSync.operacion_id == uuid.UUID(operacion_id))).one()


def _resultado(respuesta) -> dict:
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["resultados"][0]


def _linea_v2(escenario, cantidad: int) -> list[dict]:
    return [{"variante_id": escenario.v2, "cantidad": cantidad, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]


# ---- Reenvío de cada estado guardado ----


def test_reenviar_una_confirmada_devuelve_la_misma_venta_sin_repetir_nada(client, db_session, escenario):
    operacion = armar_venta(escenario)
    primera = _resultado(enviar(client, escenario.cajero, [operacion]))
    assert primera["estado"] == "confirmada" and primera["duplicada"] is False

    segunda = _resultado(enviar(client, escenario.cajero, [operacion]))

    assert segunda["duplicada"] is True and segunda["estado"] == "confirmada"
    assert segunda["recurso"]["id"] == primera["recurso"]["id"]  # la MISMA venta
    assert segunda["recurso"] == primera["recurso"] and segunda["cambio"] == primera["cambio"]
    assert segunda["procesada_en"] == primera["procesada_en"]  # lo guardado, no una hora nueva
    assert _contar(db_session, Venta) == 1
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)  # descontado UNA vez
    assert _fila(db_session, operacion["operacion_id"]).intentos == 2


def test_reenviar_una_rechazada_devuelve_el_mismo_rechazo(client, db_session, escenario):
    lineas = [{"variante_id": 999999, "cantidad": 1, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    operacion = armar_venta(escenario, lineas=lineas, monto_recibido="100.00")
    primera = _resultado(enviar(client, escenario.cajero, [operacion]))
    assert primera["estado"] == "rechazada" and primera["duplicada"] is False

    segunda = _resultado(enviar(client, escenario.cajero, [operacion]))

    assert segunda["duplicada"] is True
    assert (segunda["estado"], segunda["motivo"], segunda["mensaje"]) == (
        primera["estado"], primera["motivo"], primera["mensaje"],
    )
    assert _contar(db_session, OperacionSync) == 1
    assert _fila(db_session, operacion["operacion_id"]).intentos == 2


def test_reenviar_una_en_conflicto_devuelve_el_conflicto_guardado_aunque_ya_haya_stock(client, db_session, escenario):
    operacion = armar_venta(escenario, lineas=_linea_v2(escenario, 5), monto_recibido="500.00")
    primera = _resultado(enviar(client, escenario.cajero, [operacion]))
    assert primera["estado"] == "en_conflicto"

    # Llega mercadería: ahora la venta SÍ cabría. Pero el reenvío no se vuelve a procesar.
    recepcion = client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": escenario.v2,
            "sucursal_id": escenario.sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 10,
            "costo_unitario": "40.00",
        },
        headers=escenario.admin,
    )
    assert recepcion.status_code in (200, 201), recepcion.text

    segunda = _resultado(enviar(client, escenario.cajero, [operacion]))

    assert segunda["duplicada"] is True
    assert (segunda["estado"], segunda["motivo"]) == ("en_conflicto", "stock_insuficiente")
    assert segunda["faltantes"] == primera["faltantes"]
    assert _contar(db_session, Venta) == 0
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2 + 10, 0)


# ---- El payload nuevo se ignora ----


def test_reenviar_con_un_payload_distinto_devuelve_el_resultado_original_sin_procesar_el_nuevo(
    client, db_session, escenario
):
    original = armar_venta(escenario)  # 2 de v1
    primera = _resultado(enviar(client, escenario.cajero, [original]))

    distinta = armar_venta(
        escenario,
        operacion_id=original["operacion_id"],
        lineas=_linea_v2(escenario, 1),
        monto_recibido="100.00",
        cliente_id=None,
    )
    segunda = _resultado(enviar(client, escenario.cajero, [distinta]))

    assert segunda["duplicada"] is True and segunda["recurso"]["id"] == primera["recurso"]["id"]
    assert segunda["recurso"]["total"] == "200.00"  # el total ORIGINAL, no el de la línea nueva
    assert _contar(db_session, Venta) == 1
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2, 0)  # lo nuevo NO se aplicó
    assert _fila(db_session, original["operacion_id"]).payload == original["payload"]  # el guardado no cambia


def test_un_rechazo_es_final_aunque_el_reenvio_traiga_un_payload_ahora_valido(client, db_session, escenario):
    malas = [{"variante_id": 999999, "cantidad": 1, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    original = armar_venta(escenario, lineas=malas, monto_recibido="100.00")
    assert _resultado(enviar(client, escenario.cajero, [original]))["estado"] == "rechazada"

    corregida = armar_venta(escenario, operacion_id=original["operacion_id"])  # ahora sí es válida
    segunda = _resultado(enviar(client, escenario.cajero, [corregida]))

    assert segunda["duplicada"] is True
    assert (segunda["estado"], segunda["motivo"]) == ("rechazada", "variante_inexistente")
    assert _contar(db_session, Venta) == 0
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 0)


# ---- Duplicadas en el mismo lote y reenvíos repetidos ----


def test_la_misma_operacion_dos_veces_en_un_lote_se_procesa_una_vez_y_la_otra_es_duplicada(
    client, db_session, escenario
):
    operacion = armar_venta(escenario)
    respuesta = enviar(client, escenario.cajero, [operacion, operacion])

    assert respuesta.status_code == 200, respuesta.text
    primera, segunda = respuesta.json()["resultados"]
    assert primera["estado"] == "confirmada" and primera["duplicada"] is False
    assert segunda["estado"] == "confirmada" and segunda["duplicada"] is True
    assert segunda["recurso"]["id"] == primera["recurso"]["id"]
    assert respuesta.json()["resumen"]["duplicadas"] == 1
    assert _contar(db_session, Venta) == 1 and _contar(db_session, OperacionSync) == 1
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)
    assert _fila(db_session, operacion["operacion_id"]).intentos == 2


def test_cinco_reenvios_seguidos_dejan_intentos_en_6_y_una_sola_venta(client, db_session, escenario):
    operacion = armar_venta(escenario)
    original = _resultado(enviar(client, escenario.cajero, [operacion]))

    for _ in range(5):
        otra = _resultado(enviar(client, escenario.cajero, [operacion]))
        assert otra["duplicada"] is True and otra["recurso"]["id"] == original["recurso"]["id"]

    assert _fila(db_session, operacion["operacion_id"]).intentos == 6
    assert _contar(db_session, Venta) == 1
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)


def test_el_resumen_cuenta_las_duplicadas_aparte_ademas_de_por_estado(client, db_session, escenario):
    ya_confirmada = armar_venta(escenario, fecha_operacion=hace(30))
    ya_rechazada = armar_venta(
        escenario,
        lineas=[{"variante_id": 999999, "cantidad": 1, "precio_unitario": "100.00", "descuento_unitario": "0.00"}],
        monto_recibido="100.00",
        fecha_operacion=hace(20),
    )
    enviar(client, escenario.cajero, [ya_confirmada, ya_rechazada])
    nueva = armar_venta(escenario, fecha_operacion=hace(5))

    respuesta = enviar(client, escenario.cajero, [ya_confirmada, nueva, ya_rechazada])

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["resumen"] == {
        "total": 3, "confirmadas": 2, "rechazadas": 1, "en_conflicto": 0, "errores_temporales": 0, "duplicadas": 2,
    }
    assert [r["duplicada"] for r in respuesta.json()["resultados"]] == [True, False, True]

    solo_duplicadas = enviar(client, escenario.cajero, [ya_confirmada, ya_rechazada]).json()["resumen"]
    assert solo_duplicadas["duplicadas"] == solo_duplicadas["total"] == 2
    assert _contar(db_session, Venta) == 2  # la primera y la nueva


# ---- Quién reenvía y en qué empresa ----


def test_otro_usuario_que_reenvia_la_misma_operacion_recibe_lo_guardado_sin_duplicar(client, db_session, escenario):
    operacion = armar_venta(escenario)
    primera = _resultado(enviar(client, escenario.cajero, [operacion]))

    segunda = _resultado(enviar(client, escenario.encargado, [operacion]))  # el encargado también puede operar

    assert segunda["duplicada"] is True and segunda["estado"] == "confirmada"
    assert segunda["recurso"]["id"] == primera["recurso"]["id"]
    assert _contar(db_session, Venta) == 1
    fila = _fila(db_session, operacion["operacion_id"])
    assert fila.usuario_id == escenario.cajero_usuario_id  # sigue siendo del cajero que la hizo
    assert fila.intentos == 2
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)


def _filas_de_empresa(db, empresa_id: int) -> list[OperacionSync]:
    original = empresa_de(db)
    try:
        fijar_empresa(db, empresa_id)
        db.expire_all()
        return list(db.scalars(select(OperacionSync)))
    finally:
        fijar_empresa(db, original)


def test_la_misma_operacion_id_en_dos_empresas_son_dos_operaciones_y_ninguna_es_duplicada(
    client_por_peticion, dos_empresas, db_session
):
    client = client_por_peticion
    esc_a = construir_escenario(client, dos_empresas.a.headers, db_session, sufijo="-a", codigo_empresa="tienda-a")
    esc_b = construir_escenario(client, dos_empresas.b.headers, db_session, sufijo="-b", codigo_empresa="tienda-b")
    operacion_id = nuevo_uuid()

    en_a = _resultado(enviar(client, esc_a.cajero, [armar_venta(esc_a, operacion_id=operacion_id)]))
    en_b = _resultado(enviar(client, esc_b.cajero, [armar_venta(esc_b, operacion_id=operacion_id)]))

    assert en_a["estado"] == "confirmada" and en_a["duplicada"] is False
    assert en_b["estado"] == "confirmada" and en_b["duplicada"] is False  # NO choca con la de A
    filas_a, filas_b = _filas_de_empresa(db_session, dos_empresas.a.id), _filas_de_empresa(db_session, dos_empresas.b.id)
    assert len(filas_a) == 1 and len(filas_b) == 1
    assert filas_a[0].operacion_id == filas_b[0].operacion_id
    assert filas_a[0].empresa_id == dos_empresas.a.id and filas_b[0].empresa_id == dos_empresas.b.id

    # Reenviar en A es duplicada de A y no toca la de B.
    otra_vez = _resultado(enviar(client, esc_a.cajero, [armar_venta(esc_a, operacion_id=operacion_id)]))
    assert otra_vez["duplicada"] is True and otra_vez["recurso"]["id"] == en_a["recurso"]["id"]
    assert [f.intentos for f in _filas_de_empresa(db_session, dos_empresas.a.id)] == [2]
    assert [f.intentos for f in _filas_de_empresa(db_session, dos_empresas.b.id)] == [1]


def test_el_resultado_duplicado_conserva_el_cambio_y_los_avisos_guardados(client, db_session, escenario):
    # Precio distinto al actual (100.00): se acepta y sale un aviso; el reenvío debe devolver el mismo aviso.
    lineas = [{"variante_id": escenario.v1, "cantidad": 1, "precio_unitario": "90.00", "descuento_unitario": "0.00"}]
    operacion = armar_venta(escenario, lineas=lineas, monto_recibido="100.00")
    primera = _resultado(enviar(client, escenario.cajero, [operacion]))
    assert primera["estado"] == "confirmada" and primera["cambio"] == "10.00"
    assert [a["codigo"] for a in primera["avisos"]] == ["precio_distinto"]

    otra = _resultado(enviar(client, escenario.cajero, [operacion]))
    assert otra["duplicada"] is True
    assert otra["cambio"] == primera["cambio"] and otra["avisos"] == primera["avisos"]
