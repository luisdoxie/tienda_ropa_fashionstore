"""E07: el lote como unidad (mezcla de resultados, orden de proceso por fecha de ocurrencia) y
los errores que tumban el lote ENTERO (422 y 400, 403 por empresa ajena)."""

import datetime as dt

from sqlalchemy import func, select

from app.comercial.models import Reserva, Venta
from app.plataforma.models import Empresa
from app.sincronizacion.models import OperacionSync
from tests.sincronizacion.ayudas import (
    STOCK_V1,
    STOCK_V2,
    armar_lote,
    armar_reserva,
    armar_venta,
    enviar,
    hace,
    stock_de,
)

LINEA_V2_X2 = [{"variante_id": 0, "cantidad": 2, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]


def _contar(db, modelo) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(modelo))


def _en_el_futuro(minutos: int) -> str:
    """Un instante futuro, ISO-8601 en UTC con 'Z'."""
    ahora = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutos)
    return ahora.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _venta_de_v2_x2(escenario, **extra) -> dict:
    lineas = [{**LINEA_V2_X2[0], "variante_id": escenario.v2}]
    return armar_venta(escenario, lineas=lineas, monto_recibido="200.00", **extra)


# ---- Lote mixto ----


def test_un_lote_mixto_responde_200_con_el_resumen_y_los_resultados_en_el_orden_de_la_peticion(
    client, db_session, escenario
):
    lineas_inexistente = [{"variante_id": 999999, "cantidad": 1, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    lineas_sin_stock = [{"variante_id": escenario.v2, "cantidad": 5, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    # Las fechas NO siguen el orden de la petición: así se prueba que el orden de salida es el de entrada.
    venta = armar_venta(escenario, fecha_operacion=hace(5))
    rechazada = armar_venta(escenario, lineas=lineas_inexistente, monto_recibido="100.00", fecha_operacion=hace(40))
    conflicto = armar_venta(escenario, lineas=lineas_sin_stock, monto_recibido="500.00", fecha_operacion=hace(30))
    reserva = armar_reserva(escenario, fecha_operacion=hace(20))
    operaciones = [venta, rechazada, conflicto, reserva]

    respuesta = enviar(client, escenario.cajero, operaciones)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["version_contrato"] == "1.0"
    assert cuerpo["resumen"] == {
        "total": 4, "confirmadas": 2, "rechazadas": 1, "en_conflicto": 1, "errores_temporales": 0, "duplicadas": 0,
    }
    assert [r["operacion_id"] for r in cuerpo["resultados"]] == [o["operacion_id"] for o in operaciones]
    assert [r["estado"] for r in cuerpo["resultados"]] == ["confirmada", "rechazada", "en_conflicto", "confirmada"]
    assert [r["motivo"] for r in cuerpo["resultados"]] == [None, "variante_inexistente", "stock_insuficiente", None]
    assert [(r["recurso"] or {}).get("tipo") for r in cuerpo["resultados"]] == ["venta", None, None, "reserva"]
    assert cuerpo["resultados"][2]["faltantes"] == [{"variante_id": escenario.v2, "solicitado": 5, "disponible": STOCK_V2}]


def test_una_operacion_mala_no_tumba_a_las_demas_y_las_buenas_quedan_guardadas(client, db_session, escenario):
    lineas_inexistente = [{"variante_id": 999999, "cantidad": 1, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    lineas_sin_stock = [{"variante_id": escenario.v2, "cantidad": 5, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    buena_1 = armar_venta(escenario, fecha_operacion=hace(50))
    mala = armar_venta(escenario, lineas=lineas_inexistente, monto_recibido="100.00", fecha_operacion=hace(40))
    conflicto = armar_venta(escenario, lineas=lineas_sin_stock, monto_recibido="500.00", fecha_operacion=hace(30))
    buena_2 = armar_reserva(escenario, fecha_operacion=hace(20))
    buena_3 = armar_venta(escenario, fecha_operacion=hace(10))

    respuesta = enviar(client, escenario.cajero, [buena_1, mala, conflicto, buena_2, buena_3])
    assert respuesta.status_code == 200, respuesta.text

    db_session.expire_all()
    guardadas = {f.operacion_id: f for f in db_session.scalars(select(OperacionSync))}
    assert len(guardadas) == 5  # las cinco quedan guardadas, también las malas
    estados = {str(clave): (fila.estado, fila.motivo) for clave, fila in guardadas.items()}
    assert estados[buena_1["operacion_id"]] == ("confirmada", None)
    assert estados[mala["operacion_id"]] == ("rechazada", "variante_inexistente")
    assert estados[conflicto["operacion_id"]] == ("en_conflicto", "stock_insuficiente")
    assert estados[buena_2["operacion_id"]] == ("confirmada", None)
    assert estados[buena_3["operacion_id"]] == ("confirmada", None)
    # Lo de las buenas quedó aplicado; lo de las malas, no.
    assert _contar(db_session, Venta) == 2 and _contar(db_session, Reserva) == 1
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 4, 1)
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2, 0)


# ---- Orden por fecha de ocurrencia ----


def test_con_la_ultima_unidad_en_juego_gana_la_operacion_mas_antigua_aunque_llegue_al_final_del_lote(
    client, db_session, escenario
):
    # v2 tiene 3 unidades y cada venta pide 2: solo una cabe.
    reciente = _venta_de_v2_x2(escenario, fecha_operacion=hace(5))
    antigua = _venta_de_v2_x2(escenario, fecha_operacion=hace(60))

    respuesta = enviar(client, escenario.cajero, [reciente, antigua])  # la antigua va al FINAL

    assert respuesta.status_code == 200, respuesta.text
    primero, segundo = respuesta.json()["resultados"]  # en el orden de la petición
    assert primero["operacion_id"] == reciente["operacion_id"]
    assert primero["estado"] == "en_conflicto" and primero["motivo"] == "stock_insuficiente"
    assert primero["faltantes"] == [{"variante_id": escenario.v2, "solicitado": 2, "disponible": 1}]
    assert segundo["operacion_id"] == antigua["operacion_id"]
    assert segundo["estado"] == "confirmada"

    db_session.expire_all()
    venta = db_session.scalars(select(Venta)).one()
    assert venta.id == segundo["recurso"]["id"]
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2 - 2, 0)


def test_con_la_misma_fecha_gana_la_que_va_primero_en_la_peticion(client, db_session, escenario):
    fecha = hace(15)
    primera = _venta_de_v2_x2(escenario, fecha_operacion=fecha)
    segunda = _venta_de_v2_x2(escenario, fecha_operacion=fecha)

    respuesta = enviar(client, escenario.cajero, [primera, segunda])

    resultados = respuesta.json()["resultados"]
    assert [r["estado"] for r in resultados] == ["confirmada", "en_conflicto"]
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2 - 2, 0)


def test_la_fecha_se_compara_en_utc_aunque_cada_una_traiga_otro_desfase_horario(client, db_session, escenario):
    # Ordenadas como TEXTO saldrían al revés: la más tardía lleva un desfase -04:00 (su hora local, p. ej.
    # 08:30-04:00, "parece" anterior a 12:00+00:00 aunque ocurrió después). Debe ganar la más temprana en UTC.
    base = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).replace(microsecond=0)
    mas_tarde_en_bolivia = (base + dt.timedelta(minutes=30)).astimezone(dt.timezone(dt.timedelta(hours=-4)))
    mas_temprano_en_utc = base
    tarde = _venta_de_v2_x2(escenario, fecha_operacion=mas_tarde_en_bolivia.isoformat())
    temprano = _venta_de_v2_x2(escenario, fecha_operacion=mas_temprano_en_utc.isoformat())

    resultados = enviar(client, escenario.cajero, [tarde, temprano]).json()["resultados"]

    assert [r["estado"] for r in resultados] == ["en_conflicto", "confirmada"]


# ---- Errores del lote completo ----


def test_mas_de_50_operaciones_es_un_422_y_no_se_procesa_ninguna(client, db_session, escenario):
    operaciones = [armar_venta(escenario) for _ in range(51)]
    respuesta = enviar(client, escenario.cajero, operaciones)

    assert respuesta.status_code == 422, respuesta.text
    assert _contar(db_session, OperacionSync) == 0 and _contar(db_session, Venta) == 0


def test_un_lote_de_exactamente_50_operaciones_si_se_acepta(client, db_session, escenario):
    # Tipo desconocido: se rechazan sin tocar stock, así el lote lleno es barato.
    operaciones = [{**armar_venta(escenario), "tipo": "transferencia"} for _ in range(50)]
    respuesta = enviar(client, escenario.cajero, operaciones)

    assert respuesta.status_code == 200, respuesta.text
    resumen = respuesta.json()["resumen"]
    assert resumen["total"] == 50 and resumen["rechazadas"] == 50
    assert len(respuesta.json()["resultados"]) == 50


def test_un_lote_vacio_es_un_422(client, escenario):
    respuesta = enviar(client, escenario.cajero, [])
    assert respuesta.status_code == 422, respuesta.text


def test_una_operacion_id_que_no_es_uuid_tumba_el_lote_con_422(client, db_session, escenario):
    buena = armar_venta(escenario)
    mala = armar_venta(escenario, operacion_id="esto-no-es-un-uuid")

    respuesta = enviar(client, escenario.cajero, [buena, mala])

    assert respuesta.status_code == 422, respuesta.text
    assert _contar(db_session, OperacionSync) == 0  # ni siquiera la buena
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 0)


def test_una_fecha_sin_zona_horaria_tumba_el_lote_con_422(client, db_session, escenario):
    sin_zona = armar_venta(escenario, fecha_operacion="2026-10-20T14:05:00")
    respuesta = enviar(client, escenario.cajero, [sin_zona])

    assert respuesta.status_code == 422, respuesta.text
    assert _contar(db_session, OperacionSync) == 0


def test_una_version_de_contrato_desconocida_es_un_400_y_no_procesa_nada(client, db_session, escenario):
    respuesta = enviar(client, escenario.cajero, [armar_venta(escenario)], version_contrato="2.0")

    assert respuesta.status_code == 400, respuesta.text
    assert _contar(db_session, OperacionSync) == 0 and _contar(db_session, Venta) == 0
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 0)


# ---- Fecha futura ----


def test_una_fecha_en_el_futuro_se_rechaza_y_queda_guardada(client, db_session, escenario):
    operacion = armar_venta(escenario, fecha_operacion=_en_el_futuro(60))
    resultado = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "fecha_futura", resultado
    assert _contar(db_session, Venta) == 0
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 0)
    assert db_session.scalars(select(OperacionSync)).one().motivo == "fecha_futura"


def test_una_fecha_4_minutos_en_el_futuro_entra_dentro_de_la_tolerancia(client, db_session, escenario):
    operacion = armar_venta(escenario, fecha_operacion=_en_el_futuro(4))
    resultado = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]

    assert resultado["estado"] == "confirmada", resultado
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)


# ---- Empresa del cuerpo ----


def test_una_empresa_en_el_cuerpo_distinta_a_la_de_la_sesion_da_403_para_todo_el_lote(client, db_session, escenario):
    empresa_id = db_session.scalar(select(Empresa.id).where(Empresa.codigo == "fashionstore"))
    respuesta = client.post(
        "/api/v1/sincronizacion/lote",
        json=armar_lote([armar_venta(escenario), armar_reserva(escenario)], empresa_id=empresa_id + 999),
        headers=escenario.cajero,
    )

    assert respuesta.status_code == 403, respuesta.text
    assert _contar(db_session, OperacionSync) == 0
    assert _contar(db_session, Venta) == 0 and _contar(db_session, Reserva) == 0
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1, 0)


def test_una_empresa_en_el_cuerpo_igual_a_la_de_la_sesion_es_solo_informativa(client, db_session, escenario):
    empresa_id = db_session.scalar(select(Empresa.id).where(Empresa.codigo == "fashionstore"))
    respuesta = enviar(client, escenario.cajero, [armar_venta(escenario)], empresa_id=empresa_id, dispositivo="pwa-prueba")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["resultados"][0]["estado"] == "confirmada"
    db_session.expire_all()
    assert db_session.scalars(select(OperacionSync)).one().dispositivo == "pwa-prueba"


# ---- Tipo desconocido ----


def test_un_tipo_desconocido_se_rechaza_sin_guardarse_y_sin_tumbar_a_las_demas(client, db_session, escenario):
    desconocida = {**armar_venta(escenario), "tipo": "transferencia"}
    antes = armar_venta(escenario, fecha_operacion=hace(30))
    despues = armar_venta(escenario, fecha_operacion=hace(5))

    respuesta = enviar(client, escenario.cajero, [antes, desconocida, despues])

    assert respuesta.status_code == 200, respuesta.text
    resultados = respuesta.json()["resultados"]
    assert [r["estado"] for r in resultados] == ["confirmada", "rechazada", "confirmada"]
    assert resultados[1]["motivo"] == "tipo_no_soportado" and resultados[1]["mensaje"]
    assert resultados[1]["operacion_id"] == desconocida["operacion_id"]
    assert respuesta.json()["resumen"]["confirmadas"] == 2 and respuesta.json()["resumen"]["rechazadas"] == 1

    db_session.expire_all()
    guardadas = {str(f.operacion_id) for f in db_session.scalars(select(OperacionSync))}
    assert guardadas == {antes["operacion_id"], despues["operacion_id"]}  # la desconocida NO tiene fila
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 4, 0)

    # Reenviarla da lo mismo: no hay fila que la haga duplicada.
    otra_vez = enviar(client, escenario.cajero, [desconocida]).json()["resultados"][0]
    assert otra_vez["estado"] == "rechazada" and otra_vez["motivo"] == "tipo_no_soportado"
    assert otra_vez["duplicada"] is False
