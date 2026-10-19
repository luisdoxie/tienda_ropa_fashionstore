from typing import Any, TypeVar

from sqlalchemy import Select, and_, select
from sqlalchemy.orm import Session

from app.core.database import Base

ModeloT = TypeVar("ModeloT", bound=Base)


def confirmar(db: Session, commit: bool = True) -> None:
    """Cierra una escritura según quién sea el dueño de la transacción.

    `commit=True` (por defecto) confirma: es el comportamiento de siempre del
    endpoint HTTP. `commit=False` solo hace flush: los cambios quedan visibles
    dentro de la sesión (ids, restricciones de la base) pero la transacción
    sigue abierta para que quien llama (un caso de uso compuesto o la
    sincronización offline, CU-25) decida el commit o el rollback de todo el
    lote. Evita repetir `if commit: db.commit() else: db.flush()`."""
    if commit:
        db.commit()
    else:
        db.flush()


def obtener_por_clave(
    db: Session, modelo: type[ModeloT], id_: Any, consulta: Select | None = None
) -> ModeloT | None:
    """La fila de `modelo` con esa clave primaria (`id_` es una tupla si la
    clave es compuesta), o None; no filtra por `activo`.

    Es el reemplazo de `db.get` en los repositorios: `db.get` no pasa por
    ninguna consulta, así que no podría recibir un filtro de alcance (la
    empresa, en el multitenant). `consulta` es la consulta de partida (los
    CRUD le pasan la suya ya con el alcance aplicado). Igual que `db.get`,
    devuelve la instancia del mapa de identidad si ya está cargada."""
    claves = modelo.__mapper__.primary_key
    valores = id_ if isinstance(id_, (tuple, list)) else (id_,)
    condicion = and_(*(columna == valor for columna, valor in zip(claves, valores)))
    base = consulta if consulta is not None else select(modelo)
    return db.scalars(base.where(condicion)).first()
