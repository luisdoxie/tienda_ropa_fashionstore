"""CRUDBase y CRUDBaseSinActivo (core/crud_base.py): comportamiento actual,
fijado antes del refactor (puntos 1, 3 y 4 de 2.1 del análisis).

Se usan modelos reales simples pero con la clase genérica directa (no la
subclase del paquete, que puede sobrescribir métodos): `Categoria` para
CRUDBase (tiene `activo`) y `Color` para CRUDBaseSinActivo. Como el esquema
de actualizar de Categoria no trae `activo`, las pruebas declaran sus propios
schemas mínimos para poder ejercitar la reactivación genérica.
"""

import pytest
from pydantic import BaseModel

from app.catalogo.models import Categoria, Color, Material, Producto
from app.core.crud_base import CRUDBase, CRUDBaseSinActivo
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, NoEncontradoError
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
def colores():
    return CRUDBaseSinActivo[Color, _ColorCrear, _ColorActualizar](Color)


def _pagina(pagina: int, tamanio: int) -> ParametrosPaginacion:
    return ParametrosPaginacion(pagina=pagina, tamanio=tamanio)


def _todas(repo, db) -> list:
    return repo.listar(db, _pagina(1, 100))


def _recorrer_paginas(repo, db, tamanio: int) -> list:
    """Pide páginas sucesivas hasta que una venga vacía; devuelve las filas
    en el orden en que llegaron."""
    acumulado: list = []
    pagina = 1
    while True:
        lote = repo.listar(db, _pagina(pagina, tamanio))
        if not lote:
            return acumulado
        assert len(lote) <= tamanio
        acumulado.extend(lote)
        pagina += 1


# ---- listar (CRUDBase) ------------------------------------------------------------------


def test_listar_pagina_sin_solapar_ni_saltar_filas(db_session, categorias):
    for i in range(7):
        categorias.crear(db_session, _CategoriaCrear(nombre=f"Pag-{i}"))
    completo = [c.id for c in _todas(categorias, db_session)]

    recorrido = [c.id for c in _recorrer_paginas(categorias, db_session, tamanio=3)]

    assert recorrido == completo  # ni repetidas, ni faltantes, mismo orden
    assert len(set(recorrido)) == len(recorrido)
    assert len(completo) >= 7


def test_listar_ordena_por_id_ascendente(db_session, categorias):
    # listar aplica order_by(clave primaria) (2.1 punto 3): orden determinista.
    for i in range(5):
        categorias.crear(db_session, _CategoriaCrear(nombre=f"Orden-{i}"))

    ids = [c.id for c in _todas(categorias, db_session)]

    assert ids == sorted(ids)


def test_listar_respeta_tamanio_y_pagina_fuera_de_rango_devuelve_vacio(db_session, categorias):
    for i in range(4):
        categorias.crear(db_session, _CategoriaCrear(nombre=f"Tam-{i}"))
    total = len(_todas(categorias, db_session))

    assert len(categorias.listar(db_session, _pagina(1, 2))) == 2
    assert categorias.listar(db_session, _pagina(total + 1, 1)) == []


def test_listar_no_incluye_inactivos_y_la_paginacion_sigue_consistente(db_session, categorias):
    creadas = [categorias.crear(db_session, _CategoriaCrear(nombre=f"Act-{i}")) for i in range(6)]
    categorias.desactivar(db_session, creadas[1].id)
    categorias.desactivar(db_session, creadas[4].id)

    ids = [c.id for c in _recorrer_paginas(categorias, db_session, tamanio=2)]

    assert creadas[1].id not in ids
    assert creadas[4].id not in ids
    assert {creadas[0].id, creadas[2].id, creadas[3].id, creadas[5].id} <= set(ids)
    assert len(set(ids)) == len(ids)


def test_listar_filtros_igualdad_ignora_none_y_campos_inexistentes(db_session, categorias):
    categorias.crear(db_session, _CategoriaCrear(nombre="Filtro-A", descripcion="uno"))
    categorias.crear(db_session, _CategoriaCrear(nombre="Filtro-B", descripcion="dos"))

    por_nombre = categorias.listar(db_session, _pagina(1, 100), {"nombre": "Filtro-A"})
    assert [c.nombre for c in por_nombre] == ["Filtro-A"]

    # valor None: el filtro se ignora (no filtra por IS NULL)
    sin_filtro = categorias.listar(db_session, _pagina(1, 100), {"nombre": None})
    assert len(sin_filtro) == len(_todas(categorias, db_session))

    # campo que el modelo no tiene: se ignora en silencio
    inexistente = categorias.listar(db_session, _pagina(1, 100), {"no_existe": "x"})
    assert len(inexistente) == len(_todas(categorias, db_session))


# ---- obtener / crear / actualizar / desactivar (CRUDBase) -----------------------------------


def test_obtener_inexistente_lanza_no_encontrado(db_session, categorias):
    with pytest.raises(NoEncontradoError, match="Categoria no encontrado"):
        categorias.obtener(db_session, 999_999)


def test_obtener_inactivo_lanza_no_encontrado(db_session, categorias):
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="Inactiva"))
    categorias.desactivar(db_session, creada.id)

    with pytest.raises(NoEncontradoError):
        categorias.obtener(db_session, creada.id)


def test_crear_persiste_y_devuelve_la_fila_con_id_y_activo(db_session, categorias):
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="Nueva", descripcion="desc"))

    assert creada.id is not None
    assert creada.activo is True
    assert categorias.obtener(db_session, creada.id).descripcion == "desc"


def test_actualizar_parcial_solo_toca_los_campos_enviados(db_session, categorias):
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="Original", descripcion="conservar"))

    actualizada = categorias.actualizar(db_session, creada.id, _CategoriaActualizar(nombre="Cambiada"))

    assert actualizada.nombre == "Cambiada"
    assert actualizada.descripcion == "conservar"
    assert actualizada.activo is True


def test_actualizar_con_none_explicito_si_se_aplica_pero_omitido_no(db_session, categorias):
    # exclude_unset: un campo enviado como null SÍ se escribe (anula la
    # descripción); uno no enviado queda igual.
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="Nulable", descripcion="borrar"))

    actualizada = categorias.actualizar(db_session, creada.id, _CategoriaActualizar(descripcion=None))

    assert actualizada.descripcion is None
    assert actualizada.nombre == "Nulable"


def test_actualizar_inexistente_lanza_no_encontrado(db_session, categorias):
    with pytest.raises(NoEncontradoError):
        categorias.actualizar(db_session, 999_999, _CategoriaActualizar(nombre="x"))


def test_nombre_none_en_campo_no_nulo_lanza_conflicto(db_session, categorias):
    # CRUDBase.actualizar escribe el None tal cual, la base rechaza el NOT NULL
    # y el IntegrityError se convierte en ConflictoError (2.1 punto 4).
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="NoNulo"))

    with pytest.raises(ConflictoError, match="No se pudo guardar Categoria"):
        categorias.actualizar(db_session, creada.id, _CategoriaActualizar(nombre=None))
    # el rollback interno deja la sesión usable y la fila intacta
    assert categorias.obtener(db_session, creada.id).nombre == "NoNulo"


def test_desactivar_hace_borrado_logico(db_session, categorias):
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="A desactivar"))

    devuelta = categorias.desactivar(db_session, creada.id)

    assert devuelta.activo is False
    # la fila sigue en la tabla (no hay DELETE físico)
    assert db_session.get(Categoria, creada.id) is not None
    assert creada.id not in [c.id for c in _todas(categorias, db_session)]


def test_desactivar_dos_veces_la_segunda_es_no_encontrado(db_session, categorias):
    # comportamiento actual: desactivar usa obtener(), que filtra inactivos.
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="Dos veces"))
    categorias.desactivar(db_session, creada.id)

    with pytest.raises(NoEncontradoError):
        categorias.desactivar(db_session, creada.id)


def test_desactivar_inexistente_lanza_no_encontrado(db_session, categorias):
    with pytest.raises(NoEncontradoError):
        categorias.desactivar(db_session, 999_999)


def test_reactivar_via_actualizar_activo_true(db_session, categorias):
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="Reactivable"))
    categorias.desactivar(db_session, creada.id)

    reactivada = categorias.actualizar(db_session, creada.id, _CategoriaActualizar(activo=True))

    assert reactivada.activo is True
    assert categorias.obtener(db_session, creada.id).nombre == "Reactivable"
    assert creada.id in [c.id for c in _todas(categorias, db_session)]


def test_actualizar_una_fila_inactiva_sin_reactivarla_la_deja_inactiva(db_session, categorias):
    # comportamiento actual: actualizar usa db.get (no filtra activo), así que
    # edita filas dadas de baja sin reactivarlas.
    creada = categorias.crear(db_session, _CategoriaCrear(nombre="Baja editable"))
    categorias.desactivar(db_session, creada.id)

    editada = categorias.actualizar(db_session, creada.id, _CategoriaActualizar(nombre="Editada en baja"))

    assert editada.nombre == "Editada en baja"
    assert editada.activo is False


# ---- CRUDBaseSinActivo ----------------------------------------------------------------------


def test_sin_activo_listar_pagina_sin_solapar_ni_saltar_filas(db_session, colores):
    for i in range(7):
        colores.crear(db_session, _ColorCrear(nombre=f"Col-{i}"))
    completo = [c.id for c in _todas(colores, db_session)]

    recorrido = [c.id for c in _recorrer_paginas(colores, db_session, tamanio=3)]

    assert recorrido == completo
    assert recorrido == sorted(recorrido)  # orden explícito: por id ascendente
    assert len(completo) >= 7


def test_sin_activo_listar_filtros(db_session, colores):
    colores.crear(db_session, _ColorCrear(nombre="Rojo prueba", codigo_hex="#FF0000"))
    colores.crear(db_session, _ColorCrear(nombre="Azul prueba", codigo_hex="#0000FF"))

    encontrados = colores.listar(db_session, _pagina(1, 100), {"codigo_hex": "#FF0000"})

    assert [c.nombre for c in encontrados] == ["Rojo prueba"]


def test_sin_activo_obtener_crear_y_actualizar_parcial(db_session, colores):
    creado = colores.crear(db_session, _ColorCrear(nombre="Verde prueba", codigo_hex="#00FF00"))
    assert colores.obtener(db_session, creado.id).codigo_hex == "#00FF00"

    actualizado = colores.actualizar(db_session, creado.id, _ColorActualizar(nombre="Verde oscuro"))

    assert actualizado.nombre == "Verde oscuro"
    assert actualizado.codigo_hex == "#00FF00"


def test_sin_activo_obtener_actualizar_y_eliminar_inexistente(db_session, colores):
    with pytest.raises(NoEncontradoError):
        colores.obtener(db_session, 999_999)
    with pytest.raises(NoEncontradoError):
        colores.actualizar(db_session, 999_999, _ColorActualizar(nombre="x"))
    with pytest.raises(NoEncontradoError):
        colores.eliminar(db_session, 999_999)


def test_sin_activo_actualizar_a_nombre_duplicado_lanza_conflicto(db_session, colores):
    # actualizar traduce el IntegrityError (UNIQUE) a ConflictoError, igual que
    # eliminar() (2.1 punto 4).
    colores.crear(db_session, _ColorCrear(nombre="Repetido"))
    otro = colores.crear(db_session, _ColorCrear(nombre="Distinto"))

    with pytest.raises(ConflictoError, match="No se pudo guardar Color"):
        colores.actualizar(db_session, otro.id, _ColorActualizar(nombre="Repetido"))
    assert colores.obtener(db_session, otro.id).nombre == "Distinto"


def test_crear_duplicado_lanza_conflicto_en_ambas_variantes(db_session, colores):
    # crear() también traduce el IntegrityError (UNIQUE) y la sesión sigue
    # usable. CRUDBase con Rol (nombre UNIQUE) y CRUDBaseSinActivo con Color.
    roles = CRUDBase[Rol, _RolCrear, _RolCrear](Rol)
    roles.crear(db_session, _RolCrear(nombre="rol-crear-dup"))
    colores.crear(db_session, _ColorCrear(nombre="Unico-crear"))

    with pytest.raises(ConflictoError, match="No se pudo guardar Rol"):
        roles.crear(db_session, _RolCrear(nombre="rol-crear-dup"))
    with pytest.raises(ConflictoError, match="No se pudo guardar Color"):
        colores.crear(db_session, _ColorCrear(nombre="Unico-crear"))
    assert colores.crear(db_session, _ColorCrear(nombre="Otro-crear")).id is not None


def test_sin_activo_eliminar_es_delete_fisico(db_session, colores):
    creado = colores.crear(db_session, _ColorCrear(nombre="Efimero"))

    resultado = colores.eliminar(db_session, creado.id)

    assert resultado is None
    assert db_session.get(Color, creado.id) is None
    with pytest.raises(NoEncontradoError):
        colores.obtener(db_session, creado.id)


def test_sin_activo_eliminar_con_referencias_lanza_conflicto_y_deja_la_fila(db_session):
    """SQLite no aplica FKs salvo que se active el pragma; se activa solo para
    esta prueba para que `eliminar` vea el mismo IntegrityError que Postgres."""
    material = Material(nombre="Material en uso")
    categoria = Categoria(nombre="Categoria del producto")
    db_session.add_all([material, categoria])
    db_session.commit()
    db_session.add(
        Producto(
            codigo="CRUD-FK-1", nombre="Prod", categoria_id=categoria.id,
            material_id=material.id, precio_base=10,
        )
    )
    db_session.commit()

    repo_material = CRUDBaseSinActivo[Material, BaseModel, BaseModel](Material)
    # El pragma se ignora dentro de una transacción, y el engine de pruebas emite
    # BEGIN explícito (ver conftest): se fija sobre la conexión cruda, sin
    # transacción abierta (la StaticPool devuelve siempre esa misma conexión).
    conexion_cruda = db_session.get_bind().raw_connection()
    conexion_cruda.driver_connection.execute("PRAGMA foreign_keys=ON")
    try:
        with pytest.raises(ConflictoError, match="Material está en uso"):
            repo_material.eliminar(db_session, material.id)
        # tras el rollback interno la sesión sigue usable y la fila sigue ahí
        assert db_session.get(Material, material.id) is not None
    finally:
        db_session.rollback()
        conexion_cruda.driver_connection.execute("PRAGMA foreign_keys=OFF")
        conexion_cruda.close()
