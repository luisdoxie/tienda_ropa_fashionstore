"""Unidad de trabajo (G1): CRUDBase y CRUDBaseSinActivo con `commit=False`.

Con `commit=False` el repositorio solo hace flush: la transacción es de quien
llama (un caso de uso compuesto o la sincronización offline, CU-25), que decide
el commit o el rollback de todo el lote. Con el valor por defecto (`commit=True`)
el comportamiento no cambia.

Se usan las clases genéricas directas (no las subclases del paquete), igual que
test_crud_base.py. Para saber qué quedó persistido se hace `rollback()` y se
vuelve a consultar: lo no confirmado desaparece, lo confirmado se queda.
"""

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select

from app.catalogo.models import Categoria, Color
from app.core.crud_base import CRUDBase, CRUDBaseSinActivo
from app.core.exceptions import ConflictoError
from app.core.repository import confirmar
from app.plataforma.models import Rol


class _CategoriaCrear(BaseModel):
    nombre: str
    descripcion: str | None = None


class _CategoriaActualizar(BaseModel):
    nombre: str | None = None
    descripcion: str | None = None
    activo: bool | None = None


class _RolCrear(BaseModel):
    nombre: str


class _RolActualizar(BaseModel):
    nombre: str | None = None


class _ColorCrear(BaseModel):
    nombre: str
    codigo_hex: str | None = None


class _ColorActualizar(BaseModel):
    nombre: str | None = None
    codigo_hex: str | None = None


@pytest.fixture()
def categorias():
    return CRUDBase[Categoria, _CategoriaCrear, _CategoriaActualizar](Categoria)


@pytest.fixture()
def roles():
    # Rol.nombre es UNIQUE (Categoria.nombre no lo es): sirve para los conflictos.
    return CRUDBase[Rol, _RolCrear, _RolActualizar](Rol)


@pytest.fixture()
def colores():
    return CRUDBaseSinActivo[Color, _ColorCrear, _ColorActualizar](Color)


def _existe_categoria(db, nombre: str) -> bool:
    return db.scalar(select(func.count()).select_from(Categoria).where(Categoria.nombre == nombre)) > 0


def _existe_color(db, nombre: str) -> bool:
    return db.scalar(select(func.count()).select_from(Color).where(Color.nombre == nombre)) > 0


# ---- crear ------------------------------------------------------------------------------


def test_crear_commit_false_mas_rollback_no_persiste(db_session, categorias):
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="UoW-Rollback"), commit=False)

    # flush: el id ya existe y la fila se ve dentro de la misma sesión.
    assert creada.id is not None
    assert _existe_categoria(db_session, "UoW-Rollback")

    db_session.rollback()
    assert not _existe_categoria(db_session, "UoW-Rollback")


def test_crear_commit_false_mas_commit_persiste(db_session, categorias):
    categorias.crear(db_session, _CategoriaCrear(nombre="UoW-Commit"), commit=False)
    db_session.commit()
    db_session.rollback()  # lo ya confirmado no se pierde

    assert _existe_categoria(db_session, "UoW-Commit")


def test_crear_por_defecto_hace_commit_y_sobrevive_al_rollback(db_session, categorias):
    categorias.crear(db_session, _CategoriaCrear(nombre="UoW-Defecto"))
    db_session.rollback()

    assert _existe_categoria(db_session, "UoW-Defecto")


def test_varias_operaciones_commit_false_se_revierten_juntas(db_session, categorias):
    a = categorias.crear(db_session, _CategoriaCrear(nombre="UoW-A"), commit=False)
    categorias.actualizar(db_session, a.id, _CategoriaActualizar(descripcion="x"), commit=False)
    categorias.crear(db_session, _CategoriaCrear(nombre="UoW-B"), commit=False)

    db_session.rollback()

    assert not _existe_categoria(db_session, "UoW-A")
    assert not _existe_categoria(db_session, "UoW-B")


# ---- actualizar / desactivar -------------------------------------------------------------


def test_actualizar_commit_false_mas_rollback_restaura(db_session, categorias):
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="UoW-Act", descripcion="original"))

    categorias.actualizar(db_session, creada.id, _CategoriaActualizar(descripcion="cambiada"), commit=False)
    assert db_session.get(Categoria, creada.id).descripcion == "cambiada"

    db_session.rollback()
    assert db_session.get(Categoria, creada.id).descripcion == "original"


def test_actualizar_por_defecto_persiste(db_session, categorias):
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="UoW-Act2", descripcion="original"))
    categorias.actualizar(db_session, creada.id, _CategoriaActualizar(descripcion="cambiada"))
    db_session.rollback()

    assert db_session.get(Categoria, creada.id).descripcion == "cambiada"


def test_desactivar_commit_false_mas_rollback_deja_activo(db_session, categorias):
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="UoW-Des"))

    categorias.desactivar(db_session, creada.id, commit=False)
    assert creada.activo is False

    db_session.rollback()
    assert db_session.get(Categoria, creada.id).activo is True


def test_desactivar_por_defecto_persiste(db_session, categorias):
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="UoW-Des2"))
    categorias.desactivar(db_session, creada.id)
    db_session.rollback()

    assert db_session.get(Categoria, creada.id).activo is False


# ---- conflictos con commit=False ---------------------------------------------------------


def _existe_rol(db, nombre: str) -> bool:
    return db.scalar(select(func.count()).select_from(Rol).where(Rol.nombre == nombre)) > 0


def test_crear_duplicado_commit_false_lanza_conflicto_y_no_inutiliza_la_sesion(db_session, roles):
    """El IntegrityError del flush se convierte en ConflictoError SIN hacer
    rollback de toda la sesión: lo que la unidad de trabajo ya había hecho
    antes de la operación fallida sigue ahí y la sesión sigue usable."""
    roles.crear(db_session, _RolCrear(nombre="uow_dup"))
    roles.crear(db_session, _RolCrear(nombre="uow_previa"), commit=False)

    with pytest.raises(ConflictoError, match="No se pudo guardar Rol"):
        roles.crear(db_session, _RolCrear(nombre="uow_dup"), commit=False)

    # La sesión no quedó "needs rollback": se puede seguir y confirmar lo previo.
    assert _existe_rol(db_session, "uow_previa")
    roles.crear(db_session, _RolCrear(nombre="uow_posterior"), commit=False)
    db_session.commit()
    db_session.rollback()

    assert _existe_rol(db_session, "uow_previa")
    assert _existe_rol(db_session, "uow_posterior")


def test_actualizar_a_nombre_duplicado_commit_false_lanza_conflicto(db_session, roles):
    roles.crear(db_session, _RolCrear(nombre="uow_uno"))
    otro = roles.crear(db_session, _RolCrear(nombre="uow_dos"))

    with pytest.raises(ConflictoError, match="No se pudo guardar Rol"):
        roles.actualizar(db_session, otro.id, _RolActualizar(nombre="uow_uno"), commit=False)

    # La instancia vuelve a su estado de la base y la sesión sigue usable.
    assert db_session.get(Rol, otro.id).nombre == "uow_dos"
    assert _existe_rol(db_session, "uow_uno")


def test_crear_duplicado_por_defecto_sigue_dando_conflicto(db_session, roles):
    roles.crear(db_session, _RolCrear(nombre="uow_dup_def"))
    with pytest.raises(ConflictoError, match="No se pudo guardar Rol"):
        roles.crear(db_session, _RolCrear(nombre="uow_dup_def"))


def test_sin_activo_crear_duplicado_commit_false_lanza_conflicto(db_session, colores):
    colores.crear(db_session, _ColorCrear(nombre="UoW-ColorDup"))
    with pytest.raises(ConflictoError, match="No se pudo guardar Color"):
        colores.crear(db_session, _ColorCrear(nombre="UoW-ColorDup"), commit=False)
    assert _existe_color(db_session, "UoW-ColorDup")


# ---- CRUDBaseSinActivo -------------------------------------------------------------------


def test_sin_activo_crear_y_actualizar_commit_false_mas_rollback(db_session, colores):
    creado = colores.crear(db_session, _ColorCrear(nombre="UoW-Color"), commit=False)
    colores.actualizar(db_session, creado.id, _ColorActualizar(codigo_hex="#FFFFFF"), commit=False)
    assert _existe_color(db_session, "UoW-Color")

    db_session.rollback()
    assert not _existe_color(db_session, "UoW-Color")


def test_sin_activo_crear_commit_false_mas_commit_persiste(db_session, colores):
    colores.crear(db_session, _ColorCrear(nombre="UoW-Color2"), commit=False)
    db_session.commit()
    db_session.rollback()

    assert _existe_color(db_session, "UoW-Color2")


def test_sin_activo_eliminar_commit_false_mas_rollback_conserva_la_fila(db_session, colores):
    creado = colores.crear(db_session, _ColorCrear(nombre="UoW-Color3"))

    colores.eliminar(db_session, creado.id, commit=False)
    assert not _existe_color(db_session, "UoW-Color3")

    db_session.rollback()
    assert _existe_color(db_session, "UoW-Color3")


def test_sin_activo_eliminar_por_defecto_borra(db_session, colores):
    creado = colores.crear(db_session, _ColorCrear(nombre="UoW-Color4"))
    colores.eliminar(db_session, creado.id)
    db_session.rollback()

    assert not _existe_color(db_session, "UoW-Color4")


# ---- helper confirmar --------------------------------------------------------------------


def test_confirmar_helper_commit_true_y_false(db_session):
    db_session.add(Categoria(nombre="UoW-Helper-F"))
    confirmar(db_session, commit=False)
    db_session.rollback()
    assert not _existe_categoria(db_session, "UoW-Helper-F")

    db_session.add(Categoria(nombre="UoW-Helper-T"))
    confirmar(db_session)
    db_session.rollback()
    assert _existe_categoria(db_session, "UoW-Helper-T")
