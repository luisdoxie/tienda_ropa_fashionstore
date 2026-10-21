"""Ayuda para las pruebas de concurrencia: lanza varias operaciones a la vez,
cada una en su propio hilo y con su propia sesión (su propia transacción), y
devuelve qué le pasó a cada una."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier

from sqlalchemy.orm import Session


@dataclass
class Resultado:
    valor: object = None
    error: BaseException | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def ejecutar_en_paralelo(fabrica, operaciones: list[Callable[[Session], object]]) -> list[Resultado]:
    """Cada operación recibe su sesión. Todas esperan en una barrera y arrancan
    juntas; un error de una operación no frena a las demás y queda en su
    `Resultado` (la sesión se revierte, como haría `get_db`)."""
    barrera = Barrier(len(operaciones))

    def correr(operacion: Callable[[Session], object]) -> Resultado:
        with fabrica() as db:
            barrera.wait(timeout=30)
            try:
                return Resultado(valor=operacion(db))
            except BaseException as error:  # noqa: BLE001 -- se informa tal cual al test
                db.rollback()
                return Resultado(error=error)

    with ThreadPoolExecutor(max_workers=len(operaciones)) as pool:
        return [futuro.result() for futuro in [pool.submit(correr, op) for op in operaciones]]
