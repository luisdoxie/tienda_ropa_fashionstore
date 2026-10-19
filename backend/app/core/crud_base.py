from collections.abc import Callable
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, NoEncontradoError
from app.core.repository import confirmar, obtener_por_clave

ModeloT = TypeVar("ModeloT", bound=Base)
CrearSchemaT = TypeVar("CrearSchemaT", bound=BaseModel)
ActualizarSchemaT = TypeVar("ActualizarSchemaT", bound=BaseModel)


def _guardar(
    db: Session,
    modelo: type[Base],
    cambios: Callable[[], None],
    commit: bool,
    mensaje: str | None = None,
) -> None:
    """Aplica `cambios` (add/setattr/delete sobre la sesión) y los confirma.

    `commit=True`: aplica los cambios y hace commit; una violación de UNIQUE,
    NOT NULL o FK de la base se convierte en ConflictoError (409) en vez de
    escapar como 500, tras un rollback de la sesión (comportamiento de
    siempre). El mensaje no incluye el detalle de la base (tabla, columna,
    SQL).

    `commit=False`: la transacción es de quien llama (varias operaciones en
    una sola unidad de trabajo). Un `rollback()` acá tiraría también lo que
    el llamador ya había hecho, y un flush que falla deja la sesión inservible
    ("needs rollback"), así que los cambios y el flush van dentro de un
    SAVEPOINT (`begin_nested`): si la base rechaza el cambio, solo se revierte
    esta operación, la sesión sigue usable y se lanza el mismo ConflictoError.
    Los cambios se aplican DENTRO del savepoint porque `begin_nested()` hace
    flush de lo pendiente antes de abrirlo."""
    texto = mensaje or (
        f"No se pudo guardar {modelo.__name__}: choca con un registro existente o tiene datos inválidos"
    )
    if commit:
        cambios()
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ConflictoError(texto) from exc
        return
    try:
        with db.begin_nested():
            cambios()
            db.flush()
    except IntegrityError as exc:
        raise ConflictoError(texto) from exc


def _aplicar(instancia: Base, datos: BaseModel) -> None:
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(instancia, campo, valor)


class _CRUDComun(Generic[ModeloT, CrearSchemaT, ActualizarSchemaT]):
    """Lo que comparten CRUDBase y CRUDBaseSinActivo. Toda lectura parte de
    `_consulta_base()` y pasa por `_aplicar_alcance()`: ese es el único lugar
    donde se inyectará el alcance (la empresa, en el multitenant)."""

    def __init__(self, modelo: type[ModeloT]) -> None:
        self.modelo = modelo

    def _consulta_base(self) -> Select:
        return select(self.modelo)

    def _aplicar_alcance(self, consulta: Select) -> Select:
        """Gancho de alcance: hoy no restringe nada."""
        return consulta

    def _antes_de_crear(self, instancia: ModeloT) -> None:
        """Gancho previo al INSERT (p. ej. asignar la empresa): hoy no hace nada."""

    def _consulta_listado(self) -> Select:
        return self._consulta_base()

    def buscar(self, db: Session, id_: Any) -> ModeloT | None:
        """La fila por clave primaria dentro del alcance, activa o no, o None
        (a diferencia de `obtener`, que lanza y no devuelve las inactivas)."""
        return obtener_por_clave(db, self.modelo, id_, self._aplicar_alcance(self._consulta_base()))

    def listar(
        self,
        db: Session,
        paginacion: ParametrosPaginacion,
        filtros: dict[str, Any] | None = None,
    ) -> list[ModeloT]:
        consulta = self._aplicar_alcance(self._consulta_listado())
        for campo, valor in (filtros or {}).items():
            columna = getattr(self.modelo, campo, None)
            if columna is not None and valor is not None:
                consulta = consulta.where(columna == valor)
        # Orden determinista por la clave primaria: sin ORDER BY las páginas
        # de offset/limit pueden repetir o saltar filas en Postgres.
        consulta = (
            consulta.order_by(*self.modelo.__mapper__.primary_key)
            .offset(paginacion.offset)
            .limit(paginacion.tamanio)
        )
        return list(db.scalars(consulta).all())

    def crear(self, db: Session, datos: CrearSchemaT, commit: bool = True) -> ModeloT:
        instancia = self.modelo(**datos.model_dump())
        self._antes_de_crear(instancia)
        _guardar(db, self.modelo, lambda: db.add(instancia), commit)
        db.refresh(instancia)
        return instancia


class CRUDBase(_CRUDComun[ModeloT, CrearSchemaT, ActualizarSchemaT]):
    """CRUD genérico. Cada paquete lo hereda en su repository.py.

    Asume que el modelo tiene una columna booleana `activo` para borrado
    lógico. `listar` nunca devuelve registros con `activo = False`.
    """

    def _consulta_listado(self) -> Select:
        return self._consulta_base().where(self.modelo.activo.is_(True))

    def obtener(self, db: Session, id_: Any) -> ModeloT:
        instancia = self.buscar(db, id_)
        if instancia is None or not instancia.activo:
            raise NoEncontradoError(f"{self.modelo.__name__} no encontrado")
        return instancia

    def actualizar(self, db: Session, id_: Any, datos: ActualizarSchemaT, commit: bool = True) -> ModeloT:
        # No usa self.obtener(): ese filtra activo=True, y bloquearía acá
        # la única vía genérica para reactivar una fila (PUT con
        # {"activo": true}) antes de que el propio cambio se aplique.
        instancia = self.buscar(db, id_)
        if instancia is None:
            raise NoEncontradoError(f"{self.modelo.__name__} no encontrado")
        _guardar(db, self.modelo, lambda: _aplicar(instancia, datos), commit)
        db.refresh(instancia)
        return instancia

    def desactivar(self, db: Session, id_: Any, commit: bool = True) -> ModeloT:
        instancia = self.obtener(db, id_)
        instancia.activo = False
        confirmar(db, commit)
        db.refresh(instancia)
        return instancia


class CRUDBaseSinActivo(_CRUDComun[ModeloT, CrearSchemaT, ActualizarSchemaT]):
    """Variante de CRUDBase para catálogos sin columna `activo` (talla,
    color, material): no existe borrado lógico posible ahí, así que
    `eliminar` es un DELETE físico. Si la fila está referenciada por otra
    tabla (FK sin ON DELETE CASCADE), Postgres lo rechaza con
    IntegrityError; acá se convierte en un error de dominio legible en vez
    de dejar pasar el error crudo de la base.
    """

    def obtener(self, db: Session, id_: Any) -> ModeloT:
        instancia = self.buscar(db, id_)
        if instancia is None:
            raise NoEncontradoError(f"{self.modelo.__name__} no encontrado")
        return instancia

    def actualizar(self, db: Session, id_: Any, datos: ActualizarSchemaT, commit: bool = True) -> ModeloT:
        instancia = self.obtener(db, id_)
        _guardar(db, self.modelo, lambda: _aplicar(instancia, datos), commit)
        db.refresh(instancia)
        return instancia

    def eliminar(self, db: Session, id_: Any, commit: bool = True) -> None:
        instancia = self.obtener(db, id_)
        _guardar(
            db,
            self.modelo,
            lambda: db.delete(instancia),
            commit,
            mensaje=f"{self.modelo.__name__} está en uso, no se puede eliminar",
        )
