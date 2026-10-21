"""core/tenant.py: el filtro automático por empresa (E02).

Cada prueba arma dos empresas con filas propias y comprueba que la empresa de
la sesión es lo único que se ve. Los datos de prueba llevan el prefijo "zz-"
para no mezclarse con los de las semillas de la empresa 1."""

import re
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import aliased, selectinload

from app.catalogo.models import Categoria, Color, Producto, ProductoVariante, Talla
from app.comercial.models import Venta
from app.core.tenant import (
    EmpresaNoDefinidaError,
    ModoPlataformaError,
    condicion_empresa,
    empresa_de,
    exigir_empresa,
    fijar_empresa,
    fijar_plataforma,
    por_cada_empresa,
    sin_filtro,
)
from app.plataforma.models import Permiso, Rol, Usuario
from tests.conftest import crear_empresa

EMPRESA_A = 1  # la empresa de las semillas, ya fijada por db_session


@pytest.fixture()
def dos_empresas_con_datos(db_session):
    """A (empresa 1): 3 categorías "zz-"; B: 2. Cada una con un producto de
    código "ZZ-P" (el mismo código en las dos: la unicidad es por empresa) y
    una variante. Devuelve los ids y deja la sesión fijada en A."""
    b = crear_empresa(db_session, "zz-tienda-b").id
    ids: dict = {"a": EMPRESA_A, "b": b}
    for clave, empresa_id, cantidad in (("a", EMPRESA_A, 3), ("b", b, 2)):
        fijar_empresa(db_session, empresa_id)
        categorias = [Categoria(nombre=f"zz-cat-{clave}-{i}") for i in range(cantidad)]
        talla = Talla(codigo="ZZ")
        color = Color(nombre="zz-color")
        db_session.add_all([*categorias, talla, color])
        db_session.flush()
        producto = Producto(
            codigo="ZZ-P", nombre=f"zz-producto-{clave}", categoria_id=categorias[0].id, precio_base=10
        )
        db_session.add(producto)
        db_session.flush()
        variante = ProductoVariante(producto_id=producto.id, talla_id=talla.id, color_id=color.id, sku=f"ZZ-SKU-{clave}")
        db_session.add(variante)
        db_session.commit()
        ids[f"categorias_{clave}"] = [c.id for c in categorias]
        ids[f"producto_{clave}"] = producto.id
        ids[f"variante_{clave}"] = variante.id
    fijar_empresa(db_session, EMPRESA_A)
    return ids


def _nombres_zz(db):
    return sorted(db.scalars(select(Categoria.nombre).where(Categoria.nombre.like("zz-cat-%"))))


def test_select_por_entidad_por_columna_y_count_filtran(db_session, dos_empresas_con_datos):
    solo_a = [c.nombre for c in db_session.scalars(select(Categoria).where(Categoria.nombre.like("zz-cat-%")))]
    assert sorted(solo_a) == ["zz-cat-a-0", "zz-cat-a-1", "zz-cat-a-2"]
    assert _nombres_zz(db_session) == ["zz-cat-a-0", "zz-cat-a-1", "zz-cat-a-2"]
    assert db_session.scalar(select(func.count()).select_from(Categoria).where(Categoria.nombre.like("zz-cat-%"))) == 3

    fijar_empresa(db_session, dos_empresas_con_datos["b"])
    assert _nombres_zz(db_session) == ["zz-cat-b-0", "zz-cat-b-1"]
    assert db_session.scalar(select(func.count()).select_from(Categoria).where(Categoria.nombre.like("zz-cat-%"))) == 2


def test_get_que_va_a_la_base_devuelve_none_para_una_fila_ajena(db_session, dos_empresas_con_datos):
    id_de_b = dos_empresas_con_datos["categorias_b"][0]
    assert db_session.get(Categoria, id_de_b) is None
    assert db_session.get(Categoria, dos_empresas_con_datos["categorias_a"][0]) is not None


def test_lazy_load_selectinload_y_refresh_se_quedan_en_la_empresa(db_session, dos_empresas_con_datos):
    producto = db_session.get(Producto, dos_empresas_con_datos["producto_a"])
    assert [v.sku for v in producto.variantes] == ["ZZ-SKU-a"]  # lazy load

    db_session.expunge_all()
    producto = db_session.scalar(
        select(Producto).where(Producto.id == dos_empresas_con_datos["producto_a"]).options(selectinload(Producto.variantes))
    )
    assert [v.sku for v in producto.variantes] == ["ZZ-SKU-a"]

    db_session.refresh(producto)  # una fila propia se refresca sin problema
    assert producto.nombre == "zz-producto-a"


def test_join_alias_y_subconsulta_filtran(db_session, dos_empresas_con_datos):
    con_join = db_session.scalars(
        select(ProductoVariante.sku).join(Producto, Producto.id == ProductoVariante.producto_id).where(Producto.codigo == "ZZ-P")
    ).all()
    assert con_join == ["ZZ-SKU-a"]

    otro = aliased(Producto)
    con_alias = db_session.scalars(select(otro.nombre).where(otro.codigo == "ZZ-P")).all()
    assert con_alias == ["zz-producto-a"]

    con_subconsulta = db_session.scalars(
        select(Categoria.nombre).where(Categoria.id.in_(select(Producto.categoria_id).where(Producto.codigo == "ZZ-P")))
    ).all()
    assert con_subconsulta == ["zz-cat-a-0"]


def test_update_y_delete_masivos_solo_afectan_filas_propias(db_session, dos_empresas_con_datos):
    afectadas = db_session.execute(
        update(Categoria).where(Categoria.nombre.like("zz-cat-%")).values(descripcion="tocada")
    ).rowcount
    assert afectadas == 3

    fijar_empresa(db_session, dos_empresas_con_datos["b"])
    assert db_session.scalars(select(Categoria.descripcion).where(Categoria.nombre.like("zz-cat-%"))).all() == [None, None]

    # El delete masivo de B tampoco toca a A.
    producto_b = dos_empresas_con_datos["producto_b"]
    borradas = db_session.execute(delete(ProductoVariante).where(ProductoVariante.producto_id == producto_b)).rowcount
    assert borradas == 1
    fijar_empresa(db_session, EMPRESA_A)
    assert db_session.scalar(select(func.count()).select_from(ProductoVariante).where(ProductoVariante.sku == "ZZ-SKU-a")) == 1


def test_las_tablas_globales_se_leen_sin_empresa(db_session):
    fijar_empresa(db_session, None)
    assert db_session.scalars(select(Rol)).all()
    assert db_session.scalars(select(Permiso)).all()


def test_tabla_de_empresa_sin_empresa_lanza_error_de_dominio_401(db_session):
    fijar_empresa(db_session, None)
    with pytest.raises(EmpresaNoDefinidaError) as error:
        db_session.scalars(select(Categoria)).all()
    assert error.value.status_code == 401
    assert "empresa" in error.value.mensaje.lower()


def test_modo_plataforma_cierra_los_datos_de_negocio(db_session):
    fijar_plataforma(db_session)
    assert empresa_de(db_session) is None
    with pytest.raises(ModoPlataformaError) as error:
        db_session.scalars(select(Venta)).all()
    assert error.value.status_code == 403
    with pytest.raises(ModoPlataformaError):
        exigir_empresa(db_session)
    # Las tablas globales siguen disponibles, y fijar una empresa lo cierra.
    assert db_session.scalars(select(Rol)).all()
    fijar_empresa(db_session, EMPRESA_A)
    assert db_session.scalars(select(Categoria)).all() is not None


def test_sin_filtro_vale_para_usuario_y_se_rechaza_para_negocio(db_session):
    b = crear_empresa(db_session, "zz-tienda-b").id
    fijar_empresa(db_session, b)
    db_session.add(Usuario(nombre="Be", apellido="Be", email="zz-be@example.com", password_hash="x"))
    db_session.commit()
    fijar_empresa(db_session, None)

    todos = db_session.scalars(sin_filtro(select(Usuario).where(Usuario.email == "zz-be@example.com"))).all()
    assert len(todos) == 1 and todos[0].empresa_id == b

    for modelo in (Producto, Venta):
        with pytest.raises(EmpresaNoDefinidaError, match="sin_filtro"):
            db_session.scalars(sin_filtro(select(modelo))).all()
    # Y aunque la sesión tenga empresa, no se puede saltar el filtro del negocio.
    fijar_empresa(db_session, EMPRESA_A)
    with pytest.raises(EmpresaNoDefinidaError, match="sin_filtro"):
        db_session.scalars(sin_filtro(select(Producto))).all()


def test_el_usuario_tambien_queda_filtrado_por_empresa(db_session):
    b = crear_empresa(db_session, "zz-tienda-b").id
    fijar_empresa(db_session, b)
    db_session.add(Usuario(nombre="Be", apellido="Be", email="zz-be@example.com", password_hash="x"))
    db_session.commit()
    fijar_empresa(db_session, EMPRESA_A)
    assert db_session.scalars(select(Usuario).where(Usuario.email == "zz-be@example.com")).all() == []


def test_cambiar_de_empresa_expulsa_el_mapa_de_identidad(db_session, dos_empresas_con_datos):
    categoria_a = db_session.get(Categoria, dos_empresas_con_datos["categorias_a"][0])
    assert categoria_a in db_session

    fijar_empresa(db_session, dos_empresas_con_datos["b"])
    assert categoria_a not in db_session
    # El objeto de A no reaparece por get(): ya no está en el mapa y la base no lo devuelve.
    assert db_session.get(Categoria, dos_empresas_con_datos["categorias_a"][0]) is None


def test_condicion_empresa_devuelve_el_fragmento_y_falla_sin_empresa(db_session):
    fragmento, parametros = condicion_empresa(db_session)
    assert fragmento == "empresa_id = :empresa_id"
    assert parametros == {"empresa_id": EMPRESA_A}

    fijar_empresa(db_session, None)
    with pytest.raises(EmpresaNoDefinidaError):
        condicion_empresa(db_session)


def test_por_cada_empresa_sigue_con_la_siguiente_si_una_falla(db_session, dos_empresas_con_datos):
    b = dos_empresas_con_datos["b"]
    visitadas: list[int] = []

    def tarea(db):
        empresa_id = exigir_empresa(db)
        visitadas.append(empresa_id)
        if empresa_id == EMPRESA_A:
            raise RuntimeError("falla la empresa A")
        return db.scalar(select(func.count()).select_from(Categoria).where(Categoria.nombre.like("zz-cat-%")))

    resultados = por_cada_empresa(db_session, [EMPRESA_A, b], tarea)

    assert visitadas == [EMPRESA_A, b]
    assert resultados == [None, 2]  # A falló y B siguió, con SU conteo
    assert empresa_de(db_session) is None  # la sesión queda sin empresa


def test_guarda_no_hay_sql_en_texto_fuera_de_las_consultas_conocidas():
    """`text()` no pasa por el filtro del ORM. Solo se admiten el health check
    y las consultas sobre las vistas, y éstas deben usar `condicion_empresa`.
    Una consulta nueva en texto hace fallar esta prueba."""
    raiz = Path(__file__).resolve().parents[2] / "app"
    con_text: dict[str, int] = {}
    for ruta in raiz.rglob("*.py"):
        relativa = ruta.relative_to(raiz).as_posix()
        if relativa == "core/tenant.py" or relativa.endswith("models.py"):
            continue
        usos = len(re.findall(r"(?<![\w.])text\(|\.execute\(\s*[\"']", ruta.read_text(encoding="utf-8")))
        if usos:
            con_text[relativa] = usos

    assert set(con_text) == {"main.py", "catalogo/repository.py", "comercial/repository.py"}
    for relativa in ("catalogo/repository.py", "comercial/repository.py"):
        fuente = (raiz / relativa).read_text(encoding="utf-8")
        assert "condicion_empresa" in fuente, f"{relativa} tiene SQL en texto sin condicion_empresa"
