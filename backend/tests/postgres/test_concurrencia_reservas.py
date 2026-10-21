"""Reservas bajo concurrencia real: cancelar contra expirar la misma reserva, y
dos reservas que piden las mismas variantes en orden contrario.
"""

import datetime as dt
import time

from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from app.catalogo import politicas as catalogo_politicas
from app.catalogo.models import Stock
from app.catalogo.repository import StockRepository
from app.comercial.casos_uso.cu12_gestionar_reservas import CancelarReserva
from app.comercial.models import EstadoReserva, Reserva, ReservaHistorial
from app.comercial.politicas import crear_reserva, expirar_reservas_vencidas
from app.comercial.schemas import ReservaCrear, ReservaDetalleCrear
from app.core.exceptions import ConflictoError, DomainError

from .conftest import registrar_cliente
from .paralelo import ejecutar_en_paralelo


def _datos_reserva(escenario, lineas: list[tuple[int, int]]) -> ReservaCrear:
    """`lineas` = [(variante_id, cantidad)] en el orden en que se piden."""
    return ReservaCrear(
        sucursal_id=escenario["sucursal_id"],
        fecha_visita=escenario["fecha_visita"],
        hora_visita_desde=dt.time(10, 0),
        hora_visita_hasta=dt.time(11, 0),
        detalle=[ReservaDetalleCrear(variante_id=v, cantidad=c) for v, c in lineas],
    )


def _reservado(fabrica, variante_id: int, sucursal_id: int) -> int:
    with fabrica() as db:
        return db.scalar(
            select(Stock.cantidad_reservada).where(Stock.variante_id == variante_id, Stock.sucursal_id == sucursal_id)
        )


# ---- cancelar contra expirar --------------------------------------------------------------


def test_cancelar_y_expirar_a_la_vez_liberan_el_stock_una_sola_vez(client_pg, fabrica_pg, escenario):
    variante_id, sucursal_id = escenario["variantes"][0], escenario["sucursal_id"]
    usuario_id = registrar_cliente(client_pg, fabrica_pg, "cancela@example.com")
    rondas = 8

    for ronda in range(rondas):
        with fabrica_pg() as db:
            # Una reserva que no se toca y con más unidades que la objetivo: si
            # la liberación se hiciera dos veces, el saldo reservado bajaría de
            # las 4 unidades del testigo sin que nada fallara.
            testigo = crear_reserva(db, usuario_id, _datos_reserva(escenario, [(variante_id, 4)]))
            objetivo = crear_reserva(db, usuario_id, _datos_reserva(escenario, [(variante_id, 3)]))
            testigo_id, objetivo_id = testigo.id, objetivo.id
            # Solo la reserva objetivo está vencida.
            db.execute(
                update(Reserva)
                .where(Reserva.id == objetivo_id)
                .values(fecha_expiracion=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))
            )
            db.commit()
        assert _reservado(fabrica_pg, variante_id, sucursal_id) == 7

        resultados = ejecutar_en_paralelo(
            fabrica_pg,
            [
                lambda db: CancelarReserva().ejecutar(db, objetivo_id, usuario_id),
                lambda db: expirar_reservas_vencidas(db),
            ],
        )

        # Ninguna debe fallar con algo distinto de "ya no se puede cancelar".
        for r in resultados:
            assert r.ok or isinstance(r.error, (ConflictoError, DomainError)), r.error

        with fabrica_pg() as db:
            estado = db.scalar(
                select(EstadoReserva.codigo).join(Reserva, Reserva.estado_id == EstadoReserva.id).where(Reserva.id == objetivo_id)
            )
            cierres = db.scalar(
                select(func.count())
                .select_from(ReservaHistorial)
                .join(EstadoReserva, ReservaHistorial.estado_id == EstadoReserva.id)
                .where(ReservaHistorial.reserva_id == objetivo_id, EstadoReserva.codigo.in_(("cancelada", "expirada")))
            )
            estado_testigo = db.scalar(
                select(EstadoReserva.codigo).join(Reserva, Reserva.estado_id == EstadoReserva.id).where(Reserva.id == testigo_id)
            )
        assert estado in ("cancelada", "expirada"), f"ronda {ronda}: estado final {estado}"
        assert cierres == 1, f"ronda {ronda}: la reserva se cerró {cierres} veces"
        assert estado_testigo == "pendiente"
        # Las 3 unidades de la objetivo se liberaron una vez; las 4 del testigo siguen apartadas.
        assert _reservado(fabrica_pg, variante_id, sucursal_id) == 4, f"ronda {ronda}"

        # Se libera también el testigo para que la ronda siguiente parta de cero.
        with fabrica_pg() as db:
            CancelarReserva().ejecutar(db, testigo_id, usuario_id)
        assert _reservado(fabrica_pg, variante_id, sucursal_id) == 0


# ---- orden de bloqueos --------------------------------------------------------------------


def test_reservas_con_las_mismas_variantes_en_orden_contrario_no_se_interbloquean(
    client_pg, fabrica_pg, escenario, monkeypatch
):
    v1, v2 = escenario["variantes"]
    cliente_a = registrar_cliente(client_pg, fabrica_pg, "a@example.com")
    cliente_b = registrar_cliente(client_pg, fabrica_pg, "b@example.com")

    # Ensancha la ventana entre una línea y la siguiente: sin el orden común de
    # bloqueos (`bloquear_stock_en_orden`), la reserva (v1, v2) y la (v2, v1)
    # se esperan una a la otra y PostgreSQL aborta una por deadlock.
    reservar_original = catalogo_politicas.reservar_stock

    def reservar_lento(*args, **kwargs):
        resultado = reservar_original(*args, **kwargs)
        time.sleep(0.15)
        return resultado

    monkeypatch.setattr(catalogo_politicas, "reservar_stock", reservar_lento)

    for ronda in range(5):
        resultados = ejecutar_en_paralelo(
            fabrica_pg,
            [
                lambda db: crear_reserva(db, cliente_a, _datos_reserva(escenario, [(v1, 1), (v2, 1)])),
                lambda db: crear_reserva(db, cliente_b, _datos_reserva(escenario, [(v2, 1), (v1, 1)])),
            ],
        )
        errores = [r.error for r in resultados if not r.ok]
        assert not errores, f"ronda {ronda}: {errores}"

    assert _reservado(fabrica_pg, v1, escenario["sucursal_id"]) == 10
    assert _reservado(fabrica_pg, v2, escenario["sucursal_id"]) == 10


def test_control_sin_orden_comun_postgres_si_detecta_el_deadlock(fabrica_pg, escenario):
    """Control de la prueba anterior: demuestra que este montaje SÍ provoca un
    deadlock cuando dos transacciones toman los mismos bloqueos en orden
    contrario. Sin este control, la prueba de arriba podría pasar sin probar
    nada."""
    v1, v2 = escenario["variantes"]
    sucursal_id = escenario["sucursal_id"]
    repo = StockRepository()
    from threading import Barrier

    ambos_con_su_primer_bloqueo = Barrier(2)

    def tomar(primero: int, segundo: int):
        def operacion(db):
            repo.obtener_o_crear_bloqueado(db, primero, sucursal_id)
            ambos_con_su_primer_bloqueo.wait(timeout=10)
            repo.obtener_o_crear_bloqueado(db, segundo, sucursal_id)
            db.commit()

        return operacion

    resultados = ejecutar_en_paralelo(fabrica_pg, [tomar(v1, v2), tomar(v2, v1)])

    errores = [r.error for r in resultados if not r.ok]
    assert len(errores) == 1, "debía abortarse exactamente una de las dos"
    assert isinstance(errores[0], OperationalError)
    assert "deadlock" in str(errores[0]).lower()
