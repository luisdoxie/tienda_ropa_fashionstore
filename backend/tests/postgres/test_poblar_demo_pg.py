"""`scripts.poblar_demo` sobre PostgreSQL real (fashionstore_test): lo que SQLite no comprueba, o sea la
columna generada `stock.cantidad_disponible`, el `FOR UPDATE` del límite de sucursales del plan y las
restricciones únicas por empresa, con dos organizaciones (una existente y otra registrada)."""

import dataclasses

from sqlalchemy import func, select

from app.catalogo.models import MovimientoInventario, Producto, ProductoImagen, Stock
from app.core.tenant import en_empresa
from app.plataforma import politicas
from app.plataforma.models import Plan, Sucursal, Usuario
from scripts import demo_organizaciones as demo
from scripts.demo_organizaciones import por_codigo
from scripts.poblar_demo import cantidad_stock, planes_de_prendas, seed
from tests.scripts._prendas_falsas import crear_carpeta, simular_cloudinary

CLAVE = "claveSegura123"


def _reducida(codigo: str, prendas: tuple[int, ...]) -> demo.OrganizacionDemo:
    return dataclasses.replace(por_codigo(codigo), prendas=prendas)


def test_poblar_dos_organizaciones_y_repetir_no_duplica(fabrica_pg, tmp_path, monkeypatch):
    subidos = simular_cloudinary(monkeypatch)
    carpeta = crear_carpeta(tmp_path)
    organizaciones = (
        _reducida("fashionstore", (10005, 10003, 10017, 14006)),
        _reducida("chaski-sport", (10005, 10010, 10019, 10022)),
    )

    with fabrica_pg() as db:
        primera = seed(db, ejecutar=True, password=CLAVE, origen=carpeta, organizaciones=organizaciones)
        assert all(sum(r.creados.values()) > 0 for r in primera.values())

        fashionstore = politicas.obtener_empresa_por_codigo(db, "fashionstore").id
        chaski = politicas.obtener_empresa_por_codigo(db, "chaski-sport").id
        assert db.scalar(select(Plan.max_sucursales).where(Plan.codigo == "estandar")) == 5

        for org, empresa_id in zip(organizaciones, (fashionstore, chaski)):
            planes = planes_de_prendas(org, carpeta)
            esperadas = sum(
                cantidad_stock(org.codigo, s, p.codigo, t) > 0 for s in org.sucursales for p in planes for t in demo.TALLAS_DEMO
            )
            with en_empresa(db, empresa_id):
                assert db.scalar(select(func.count()).select_from(Sucursal)) == len(org.sucursales)
                assert db.scalar(select(func.count()).select_from(Producto)) == len(org.prendas)
                assert db.scalar(select(func.count()).select_from(ProductoImagen)) == len(org.prendas)
                # El stock inicial entró por recepciones: una fila de stock y un movimiento por variante y sucursal.
                assert db.scalar(select(func.count()).select_from(Stock)) == esperadas
                assert db.scalar(select(func.count()).select_from(MovimientoInventario)) == esperadas
                # La columna generada por la base: disponible = físico - reservado.
                assert (
                    db.scalar(
                        select(func.count()).select_from(Stock).where(
                            Stock.cantidad_disponible != Stock.cantidad_fisica - Stock.cantidad_reservada
                        )
                    )
                    == 0
                )
                assert db.scalar(select(func.min(Stock.cantidad_fisica))) >= 1
                correos = set(db.scalars(select(Usuario.email)))
            dominio = org.dominio
            # Personal con @<dominio> y clientes con @demo.<dominio>: ningún correo de otra organización.
            assert f"admin@{dominio}" in correos and all(c.endswith(dominio) for c in correos)
        fotos = len(subidos)

        # Repetir no cambia nada ni vuelve a subir fotos.
        segunda = seed(db, ejecutar=True, password=CLAVE, origen=carpeta, organizaciones=organizaciones)
        assert {codigo: sum(r.creados.values()) for codigo, r in segunda.items()} == dict.fromkeys(segunda, 0)
        assert len(subidos) == fotos
        with en_empresa(db, chaski):
            assert db.scalar(select(func.count()).select_from(Producto)) == 4
            assert db.scalar(select(func.count()).select_from(Stock)) > 0
