"""Stock bajo concurrencia real. En SQLite estas pruebas no significan nada
(sin FOR UPDATE, los hilos se pisan o no corren en paralelo): acá cada hilo es
una transacción distinta sobre la misma fila de `stock`.
"""

from sqlalchemy import func, select

from app.catalogo.models import MovimientoInventario, Stock
from app.catalogo.politicas import actualizar_stock_operacion, reservar_stock
from app.core.exceptions import ConflictoError

from .paralelo import ejecutar_en_paralelo


def _stock(fabrica, variante_id: int, sucursal_id: int) -> Stock:
    with fabrica() as db:
        return db.scalars(
            select(Stock).where(Stock.variante_id == variante_id, Stock.sucursal_id == sucursal_id)
        ).one()


def test_reservas_simultaneas_no_apartan_mas_de_lo_que_hay(fabrica_pg, escenario):
    variante_id, sucursal_id = escenario["variantes"][0], escenario["sucursal_id"]
    intentos = 25  # hay 10 unidades: solo 10 reservas de 1 pueden salir bien

    resultados = ejecutar_en_paralelo(
        fabrica_pg, [lambda db: reservar_stock(db, variante_id, sucursal_id, 1)] * intentos
    )

    exitosas = [r for r in resultados if r.ok]
    rechazadas = [r for r in resultados if not r.ok]
    assert len(exitosas) == 10
    assert all(isinstance(r.error, ConflictoError) for r in rechazadas), [r.error for r in rechazadas]
    stock = _stock(fabrica_pg, variante_id, sucursal_id)
    assert (stock.cantidad_fisica, stock.cantidad_reservada, stock.cantidad_disponible) == (10, 10, 0)


def test_salidas_simultaneas_no_dejan_el_stock_negativo(fabrica_pg, escenario):
    variante_id, sucursal_id = escenario["variantes"][1], escenario["sucursal_id"]
    intentos = 25

    resultados = ejecutar_en_paralelo(
        fabrica_pg,
        [
            lambda db: actualizar_stock_operacion(
                db, variante_id=variante_id, sucursal_id=sucursal_id, tipo_movimiento_codigo="venta", cantidad=1
            )
        ]
        * intentos,
    )

    assert sum(r.ok for r in resultados) == 10
    assert all(isinstance(r.error, ConflictoError) for r in resultados if not r.ok)
    assert _stock(fabrica_pg, variante_id, sucursal_id).cantidad_fisica == 0
    with fabrica_pg() as db:
        saldos = sorted(
            db.scalars(
                select(MovimientoInventario.saldo_post).where(
                    MovimientoInventario.variante_id == variante_id, MovimientoInventario.cantidad < 0
                )
            )
        )
        movimientos_de_salida = db.scalar(
            select(func.count()).select_from(MovimientoInventario).where(
                MovimientoInventario.variante_id == variante_id, MovimientoInventario.cantidad < 0
            )
        )
    # Cada salida vio el saldo que dejó la anterior: 9, 8, ..., 0 sin repetidos.
    assert movimientos_de_salida == 10
    assert saldos == list(range(10))
