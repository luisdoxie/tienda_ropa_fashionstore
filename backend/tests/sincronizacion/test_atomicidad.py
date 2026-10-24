"""E07: atomicidad del lote. Cada operación se aplica en su SAVEPOINT y se confirma al terminar:
lo que falla dentro no deja nada, un fallo inesperado no se guarda (el cliente reintenta con la
misma `operacion_id`) y una mala no tumba a las demás.

Los fallos se simulan sustituyendo `app.sincronizacion.politicas.cobrar_en_caja`. El sustituto
llama primero al cobro REAL (así el pago y el movimiento de stock ya están en la sesión) y
recién después falla: lo que se prueba es que el SAVEPOINT lo deshace todo."""

from sqlalchemy import func, select

from app.catalogo.models import MovimientoInventario
from app.comercial.models import Pago, Venta, VentaDetalle
from app.core.exceptions import DomainError
from app.sincronizacion import politicas
from app.sincronizacion.models import OperacionSync
from tests.sincronizacion.ayudas import STOCK_V1, STOCK_V2, armar_venta, enviar, hace, stock_de


def _linea(variante_id: int, cantidad: int = 1) -> dict:
    return {"variante_id": variante_id, "cantidad": cantidad, "precio_unitario": "100.00", "descuento_unitario": "0.00"}


def _venta(escenario, minutos: int = 10, variante_id: int | None = None, cantidad: int = 1, **extra) -> dict:
    """Una venta de `cantidad` unidades (por defecto 1 de v1) pagada justo."""
    variante_id = variante_id or escenario.v1
    return armar_venta(
        escenario,
        lineas=[_linea(variante_id, cantidad)],
        monto_recibido=f"{100 * cantidad}.00",
        fecha_operacion=hace(minutos),
        **extra,
    )


def _contar(db, modelo) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(modelo))


def _guardadas(db) -> dict[str, OperacionSync]:
    db.expire_all()
    return {str(fila.operacion_id): fila for fila in db.scalars(select(OperacionSync))}


def _sin_efectos_de_venta(db, escenario) -> None:
    assert _contar(db, Venta) == 0 and _contar(db, Pago) == 0 and _contar(db, VentaDetalle) == 0
    assert _contar(db, MovimientoInventario) == 2  # solo las dos recepciones del escenario
    assert stock_de(db, escenario, escenario.v1) == (STOCK_V1, 0)
    assert stock_de(db, escenario, escenario.v2) == (STOCK_V2, 0)


def _cobro_que_falla(monkeypatch, *, cuando, error) -> dict:
    """Sustituye `cobrar_en_caja`: ejecuta el cobro real y, si `cuando(n)` (n = nº de llamada,
    desde 1), lanza `error()`. Devuelve un contador {'llamadas': n} para las aserciones."""
    original = politicas.cobrar_en_caja
    estado = {"llamadas": 0}

    def sustituto(*args, **kwargs):
        estado["llamadas"] += 1
        resultado = original(*args, **kwargs)
        if cuando(estado["llamadas"]):
            raise error()
        return resultado

    monkeypatch.setattr(politicas, "cobrar_en_caja", sustituto)
    return estado


# ---- (a) una regla de negocio dentro del cobro deshace todo ------------------------------


def test_un_error_de_negocio_dentro_del_cobro_no_deja_venta_ni_pago_ni_stock_movido(client, db_session, escenario, monkeypatch):
    _cobro_que_falla(monkeypatch, cuando=lambda n: True, error=lambda: DomainError("La caja está cerrada"))
    operacion = _venta(escenario)

    resultado = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "regla_de_negocio"
    assert resultado["mensaje"] == "La caja está cerrada" and resultado["recurso"] is None
    _sin_efectos_de_venta(db_session, escenario)
    fila = _guardadas(db_session)[operacion["operacion_id"]]
    assert (fila.estado, fila.motivo) == ("rechazada", "regla_de_negocio")


# ---- (b) un fallo inesperado no se guarda y se puede reintentar ---------------------------


def test_un_fallo_inesperado_es_error_temporal_sin_fila_y_el_reintento_con_la_misma_operacion_funciona(
    client, db_session, escenario, monkeypatch
):
    ctrl = _cobro_que_falla(monkeypatch, cuando=lambda n: True, error=lambda: RuntimeError("se cayó la base"))
    operacion = _venta(escenario)

    respuesta = enviar(client, escenario.cajero, [operacion])
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    resultado = cuerpo["resultados"][0]
    assert resultado["estado"] == "error_temporal" and resultado["motivo"] is None
    assert resultado["operacion_id"] == operacion["operacion_id"] and resultado["procesada_en"] is None
    assert cuerpo["resumen"]["errores_temporales"] == 1 and cuerpo["resumen"]["confirmadas"] == 0
    assert "se cayó la base" not in respuesta.text  # el detalle interno no llega al cliente
    assert ctrl["llamadas"] == 1
    assert _guardadas(db_session) == {}  # ni siquiera la fila "en_proceso"
    _sin_efectos_de_venta(db_session, escenario)

    # El cliente reintenta con la MISMA operacion_id, ya sin el fallo.
    monkeypatch.undo()
    reintento = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]

    assert reintento["estado"] == "confirmada" and reintento["duplicada"] is False
    assert _contar(db_session, Venta) == 1 and _contar(db_session, Pago) == 1
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 1, 0)
    (fila,) = _guardadas(db_session).values()
    assert str(fila.operacion_id) == operacion["operacion_id"]
    assert (fila.estado, fila.intentos) == ("confirmada", 1)  # para el servidor es la primera vez que se guarda


# ---- (c) commit por operación ---------------------------------------------------------------


def test_en_un_lote_de_tres_la_segunda_falla_y_la_primera_y_la_tercera_quedan_guardadas(
    client, db_session, escenario, monkeypatch
):
    _cobro_que_falla(monkeypatch, cuando=lambda n: n == 2, error=lambda: RuntimeError("fallo a mitad del lote"))
    primera, segunda, tercera = _venta(escenario, 30), _venta(escenario, 20), _venta(escenario, 10)

    respuesta = enviar(client, escenario.cajero, [primera, segunda, tercera])

    assert respuesta.status_code == 200, respuesta.text
    resultados = respuesta.json()["resultados"]
    assert [r["operacion_id"] for r in resultados] == [o["operacion_id"] for o in (primera, segunda, tercera)]
    assert [r["estado"] for r in resultados] == ["confirmada", "error_temporal", "confirmada"]
    guardadas = _guardadas(db_session)
    assert set(guardadas) == {primera["operacion_id"], tercera["operacion_id"]}
    assert all(f.estado == "confirmada" for f in guardadas.values())
    # Dos ventas completas y solo dos unidades salidas: la segunda no dejó nada.
    assert _contar(db_session, Venta) == 2 and _contar(db_session, Pago) == 2
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)


# ---- (d) conflicto sin stock apartado -----------------------------------------------------


def test_una_operacion_en_conflicto_no_deja_stock_apartado(client, db_session, escenario):
    # v2 tiene 3. La más antigua se lleva 1; la siguiente pide 3 y solo quedan 2.
    ok = _venta(escenario, 20, variante_id=escenario.v2, cantidad=1)
    conflicto = _venta(escenario, 10, variante_id=escenario.v2, cantidad=3)

    resultados = enviar(client, escenario.cajero, [ok, conflicto]).json()["resultados"]

    assert [r["estado"] for r in resultados] == ["confirmada", "en_conflicto"]
    assert resultados[1]["motivo"] == "stock_insuficiente"
    assert resultados[1]["faltantes"] == [{"variante_id": escenario.v2, "solicitado": 3, "disponible": 2}]
    # Físico 3 - 1 = 2 y NADA apartado: el conflicto no dejó cantidad_reservada.
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2 - 1, 0)
    assert _contar(db_session, Venta) == 1 and _contar(db_session, Pago) == 1
    fila = _guardadas(db_session)[conflicto["operacion_id"]]
    assert (fila.estado, fila.motivo) == ("en_conflicto", "stock_insuficiente")


# ---- (e) rechazada: sin efectos, pero guardada --------------------------------------------


def test_una_operacion_rechazada_no_deja_efectos_pero_queda_guardada_con_su_motivo(client, db_session, escenario):
    # Segunda línea con una variante que no existe: la primera (válida) tampoco debe dejar nada.
    operacion = armar_venta(
        escenario,
        lineas=[_linea(escenario.v1, 2), _linea(999999, 1)],
        monto_recibido="300.00",
        fecha_operacion=hace(10),
    )

    resultado = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]

    assert resultado["estado"] == "rechazada" and resultado["motivo"] == "variante_inexistente"
    _sin_efectos_de_venta(db_session, escenario)
    fila = _guardadas(db_session)[operacion["operacion_id"]]
    assert (fila.estado, fila.motivo, fila.tipo) == ("rechazada", "variante_inexistente", "venta_contado")
    assert fila.procesada_en is not None and fila.payload["lineas"][1]["variante_id"] == 999999
    assert "999999" in fila.resultado["mensaje"]

    # Reenviarla devuelve el mismo rechazo guardado, sin volver a evaluarla.
    segunda = enviar(client, escenario.cajero, [operacion]).json()["resultados"][0]
    assert segunda["duplicada"] is True and segunda["estado"] == "rechazada" and segunda["motivo"] == "variante_inexistente"
    assert _guardadas(db_session)[operacion["operacion_id"]].intentos == 2


# ---- (f) resumen del lote ---------------------------------------------------------------


def test_el_resumen_cuenta_cada_estado_y_los_resultados_van_en_el_orden_de_la_peticion(
    client, db_session, escenario, monkeypatch
):
    # Se procesan por fecha: o1 (confirmada, 1ª llamada al cobro), o2 (rechazada), o3 (conflicto),
    # o4 (error: 2ª llamada al cobro) y o5 (confirmada, 3ª llamada). Se envían desordenadas.
    o1 = _venta(escenario, 50)
    o2 = _venta(escenario, 40, metodo="tarjeta")
    o3 = _venta(escenario, 30, variante_id=escenario.v2, cantidad=5)
    o4 = _venta(escenario, 20)
    o5 = _venta(escenario, 10)
    _cobro_que_falla(monkeypatch, cuando=lambda n: n == 2, error=lambda: RuntimeError("fallo inesperado"))
    peticion = [o5, o1, o4, o3, o2]

    respuesta = enviar(client, escenario.cajero, peticion)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["resumen"] == {
        "total": 5, "confirmadas": 2, "rechazadas": 1, "en_conflicto": 1, "errores_temporales": 1, "duplicadas": 0,
    }
    assert [r["operacion_id"] for r in cuerpo["resultados"]] == [o["operacion_id"] for o in peticion]
    assert [r["estado"] for r in cuerpo["resultados"]] == [
        "confirmada", "confirmada", "error_temporal", "en_conflicto", "rechazada",
    ]
    # Se guardan las cuatro que no son error temporal; la quinta se reintenta.
    assert set(_guardadas(db_session)) == {o["operacion_id"] for o in (o1, o2, o3, o5)}
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)
    assert stock_de(db_session, escenario, escenario.v2) == (STOCK_V2, 0)


def test_el_resumen_cuenta_las_duplicadas_de_un_reenvio(client, db_session, escenario):
    primera, segunda = _venta(escenario, 20), _venta(escenario, 10)
    enviar(client, escenario.cajero, [primera])

    cuerpo = enviar(client, escenario.cajero, [primera, segunda]).json()

    assert cuerpo["resumen"] == {
        "total": 2, "confirmadas": 2, "rechazadas": 0, "en_conflicto": 0, "errores_temporales": 0, "duplicadas": 1,
    }
    assert [r["duplicada"] for r in cuerpo["resultados"]] == [True, False]
    assert _contar(db_session, Venta) == 2
    assert stock_de(db_session, escenario, escenario.v1) == (STOCK_V1 - 2, 0)
