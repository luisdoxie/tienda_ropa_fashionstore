"""Ganchos de alcance de CRUDBase y CRUDBaseSinActivo (core/crud_base.py): el
único punto donde se inyectará la empresa (multitenant). Hoy son no-op; acá
se fija que una subclase que sobreescribe `_aplicar_alcance` filtra TODAS las
lecturas (obtener, listar, actualizar, desactivar, eliminar) y que
`_antes_de_crear` se ejecuta antes del INSERT."""

import pytest
from pydantic import BaseModel

from app.catalogo.models import Categoria, Color
from app.core.crud_base import CRUDBase, CRUDBaseSinActivo
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import NoEncontradoError


class _Crear(BaseModel):
    nombre: str
    descripcion: str | None = None


class _Actualizar(BaseModel):
    descripcion: str | None = None
    activo: bool | None = None


class _ColorCrear(BaseModel):
    nombre: str


class _ColorActualizar(BaseModel):
    nombre: str | None = None


class _CategoriasDeLaEmpresaA(CRUDBase[Categoria, _Crear, _Actualizar]):
    """Alcance de prueba: solo ve las categorías cuyo nombre empieza con 'A-'."""

    def _aplicar_alcance(self, consulta):
        return consulta.where(Categoria.nombre.like("A-%"))

    def _antes_de_crear(self, instancia):
        instancia.descripcion = "marcada antes de crear"


class _ColoresDeLaEmpresaA(CRUDBaseSinActivo[Color, _ColorCrear, _ColorActualizar]):
    def _aplicar_alcance(self, consulta):
        return consulta.where(Color.nombre.like("A-%"))


def _pagina() -> ParametrosPaginacion:
    return ParametrosPaginacion(pagina=1, tamanio=100)


@pytest.fixture()
def categorias():
    return _CategoriasDeLaEmpresaA(Categoria)


@pytest.fixture()
def libres():
    return CRUDBase[Categoria, _Crear, _Actualizar](Categoria)


@pytest.fixture()
def dos_categorias(db_session, libres):
    propia = libres.crear(db_session, _Crear(nombre="A-propia"))
    ajena = libres.crear(db_session, _Crear(nombre="B-ajena"))
    return propia, ajena


def test_sin_sobreescribir_el_alcance_no_restringe_nada(db_session, libres, dos_categorias):
    propia, ajena = dos_categorias

    assert libres.obtener(db_session, ajena.id).id == ajena.id
    assert {propia.id, ajena.id} <= {c.id for c in libres.listar(db_session, _pagina())}


def test_listar_solo_devuelve_lo_que_esta_dentro_del_alcance(db_session, categorias, dos_categorias):
    propia, ajena = dos_categorias

    ids = {c.id for c in categorias.listar(db_session, _pagina())}

    assert propia.id in ids
    assert ajena.id not in ids


def test_obtener_y_buscar_no_ven_filas_fuera_del_alcance(db_session, categorias, dos_categorias):
    propia, ajena = dos_categorias

    assert categorias.obtener(db_session, propia.id).id == propia.id
    with pytest.raises(NoEncontradoError):
        categorias.obtener(db_session, ajena.id)
    assert categorias.buscar(db_session, ajena.id) is None


def test_actualizar_no_toca_filas_fuera_del_alcance(db_session, categorias, dos_categorias):
    propia, ajena = dos_categorias

    categorias.actualizar(db_session, propia.id, _Actualizar(descripcion="nueva"))
    with pytest.raises(NoEncontradoError):
        categorias.actualizar(db_session, ajena.id, _Actualizar(descripcion="intrusa"))

    db_session.refresh(ajena)
    assert propia.descripcion == "nueva"
    assert ajena.descripcion != "intrusa"


def test_actualizar_sigue_alcanzando_filas_inactivas_dentro_del_alcance(db_session, categorias, dos_categorias):
    # El alcance no cambia el comportamiento documentado: actualizar reactiva.
    propia, _ = dos_categorias
    categorias.desactivar(db_session, propia.id)

    reactivada = categorias.actualizar(db_session, propia.id, _Actualizar(activo=True))

    assert reactivada.activo is True


def test_desactivar_no_toca_filas_fuera_del_alcance(db_session, categorias, dos_categorias):
    propia, ajena = dos_categorias

    categorias.desactivar(db_session, propia.id)
    with pytest.raises(NoEncontradoError):
        categorias.desactivar(db_session, ajena.id)

    db_session.refresh(ajena)
    assert propia.activo is False
    assert ajena.activo is True


def test_antes_de_crear_se_ejecuta_antes_del_insert(db_session, categorias):
    creada = categorias.crear(db_session, _Crear(nombre="A-nueva", descripcion="del cliente"))

    assert creada.descripcion == "marcada antes de crear"


def test_sin_activo_aplica_el_mismo_alcance_a_listar_obtener_actualizar_y_eliminar(db_session):
    libres = CRUDBaseSinActivo[Color, _ColorCrear, _ColorActualizar](Color)
    colores = _ColoresDeLaEmpresaA(Color)
    propio = libres.crear(db_session, _ColorCrear(nombre="A-rojo"))
    ajeno = libres.crear(db_session, _ColorCrear(nombre="B-azul"))

    ids = {c.id for c in colores.listar(db_session, _pagina())}
    assert propio.id in ids and ajeno.id not in ids
    assert colores.obtener(db_session, propio.id).id == propio.id
    for operacion in (
        lambda: colores.obtener(db_session, ajeno.id),
        lambda: colores.actualizar(db_session, ajeno.id, _ColorActualizar(nombre="A-robado")),
        lambda: colores.eliminar(db_session, ajeno.id),
    ):
        with pytest.raises(NoEncontradoError):
            operacion()

    colores.eliminar(db_session, propio.id)
    assert libres.buscar(db_session, propio.id) is None
    assert libres.buscar(db_session, ajeno.id) is not None
