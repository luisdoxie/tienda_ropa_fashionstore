"""Unidad de trabajo (G1) en catalogo: crear un producto y sus variantes es
UNA sola transacción (un solo commit al final).

Antes `GestionarProductos.crear` hacía commit del producto y luego otro de las
variantes: si fallaban las variantes quedaba un producto sin variantes.
"""

import pytest
from sqlalchemy import func, select

from app.catalogo.casos_uso.cu05_gestionar_catalogo import GestionarProductos
from app.catalogo.models import Producto, ProductoVariante
from app.catalogo.repository import ProductoRepository, VarianteRepository
from app.catalogo.schemas import ProductoCrear
from app.core.exceptions import NoEncontradoError


@pytest.fixture()
def contexto(client, admin_headers):
    categoria = client.post("/api/v1/categorias", json={"nombre": "Camisas UoW"}, headers=admin_headers).json()
    talla_m = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    talla_l = client.post("/api/v1/tallas", json={"codigo": "L", "orden": 2}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul UoW"}, headers=admin_headers).json()
    return {
        "categoria_id": categoria["id"],
        "tallas_ids": [talla_m["id"], talla_l["id"]],
        "colores_ids": [color["id"]],
    }


def _datos(contexto, codigo="UOW-1", tallas_ids=None) -> ProductoCrear:
    return ProductoCrear(
        codigo=codigo,
        nombre="Camisa UoW",
        categoria_id=contexto["categoria_id"],
        precio_base="100.00",
        tallas_ids=tallas_ids if tallas_ids is not None else contexto["tallas_ids"],
        colores_ids=contexto["colores_ids"],
    )


def _productos_con_codigo(db, codigo: str) -> int:
    return db.scalar(select(func.count()).select_from(Producto).where(Producto.codigo == codigo))


def _variantes_de(db, producto_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(ProductoVariante).where(ProductoVariante.producto_id == producto_id)
    )


def test_crear_producto_con_variantes_hace_un_solo_commit(db_session, contexto, monkeypatch):
    commits: list[int] = []
    commit_original = db_session.commit

    def commit_contado():
        commits.append(1)
        commit_original()

    monkeypatch.setattr(db_session, "commit", commit_contado)

    producto = GestionarProductos().crear(db_session, _datos(contexto), creado_por=None)

    assert len(commits) == 1
    db_session.rollback()  # lo confirmado sobrevive
    assert _productos_con_codigo(db_session, "UOW-1") == 1
    assert _variantes_de(db_session, producto.id) == 2  # 2 tallas x 1 color
    assert producto.id is not None


def test_crear_producto_con_talla_inexistente_no_deja_producto(db_session, contexto):
    """El fallo ocurre DESPUÉS de insertar el producto: el producto también se revierte."""
    with pytest.raises(NoEncontradoError, match="tallas"):
        GestionarProductos().crear(db_session, _datos(contexto, tallas_ids=[999_999]), creado_por=None)

    assert _productos_con_codigo(db_session, "UOW-1") == 0
    db_session.rollback()
    assert _productos_con_codigo(db_session, "UOW-1") == 0


def test_crear_producto_con_fallo_inesperado_en_variantes_no_deja_producto(db_session, contexto, monkeypatch):
    def falla(self, db, producto_id, talla_id, color_id):
        raise RuntimeError("fallo simulado al generar variantes")

    monkeypatch.setattr(VarianteRepository, "obtener_por_combinacion", falla)

    with pytest.raises(RuntimeError, match="fallo simulado"):
        GestionarProductos().crear(db_session, _datos(contexto), creado_por=None)

    assert _productos_con_codigo(db_session, "UOW-1") == 0
    db_session.rollback()
    assert _productos_con_codigo(db_session, "UOW-1") == 0


def test_crear_producto_dado_de_baja_con_fallo_en_variantes_no_lo_reactiva(db_session, contexto):
    gestion = GestionarProductos()
    producto = gestion.crear(db_session, _datos(contexto), creado_por=None)
    gestion.desactivar(db_session, producto.id)

    with pytest.raises(NoEncontradoError):
        gestion.crear(db_session, _datos(contexto, tallas_ids=[999_999]), creado_por=None)

    db_session.rollback()
    assert db_session.get(Producto, producto.id).activo is False


def test_producto_repository_crear_commit_false_mas_rollback(db_session, contexto):
    producto = ProductoRepository().crear(db_session, _datos(contexto, codigo="UOW-2"), None, commit=False)
    assert producto.id is not None

    db_session.rollback()
    assert _productos_con_codigo(db_session, "UOW-2") == 0


def test_generar_variantes_commit_false_mas_rollback_no_deja_variantes(db_session, contexto):
    gestion = GestionarProductos()
    producto = gestion.crear(db_session, _datos(contexto, tallas_ids=contexto["tallas_ids"][:1]), creado_por=None)
    assert _variantes_de(db_session, producto.id) == 1

    creadas = gestion.generar_variantes(
        db_session, producto, contexto["tallas_ids"], contexto["colores_ids"], commit=False
    )
    assert len(creadas) == 1  # solo la talla nueva
    assert _variantes_de(db_session, producto.id) == 2

    db_session.rollback()
    assert _variantes_de(db_session, producto.id) == 1
