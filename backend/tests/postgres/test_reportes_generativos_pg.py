"""E09 en PostgreSQL real: las consultas de los reportes generativos agrupan por día con `date(fecha)`,
aceptan listas con `IN` y no mezclan dos empresas que usan los mismos nombres. Las cifras son las de
`sembrar_mundo_reportes` (A con m=1, B con m=3)."""

import datetime as dt
from decimal import Decimal

from app.catalogo import politicas as catalogo_politicas
from app.comercial import politicas as comercial_politicas
from app.core.deps import ParametrosPeriodo
from app.core.tenant import fijar_empresa
from app.plataforma import politicas as plataforma_politicas
from tests.comercial.ayudas_reportes_ia import PERIODO, sembrar_mundo_reportes
from tests.conftest import crear_empresa


def _dos_empresas(fabrica_pg):
    with fabrica_pg() as db:
        id_a = crear_empresa(db, "tienda-a").id  # los ids antes de que un commit expire las filas
        id_b = crear_empresa(db, "tienda-b").id
        datos_a = sembrar_mundo_reportes(db, id_a, m=1)
        datos_b = sembrar_mundo_reportes(db, id_b, m=3)
    return id_a, id_b, datos_a, datos_b


def test_las_consultas_de_los_reportes_generativos_no_mezclan_empresas(fabrica_pg):
    id_a, id_b, datos_a, datos_b = _dos_empresas(fabrica_pg)

    for empresa_id, m in ((id_a, 1), (id_b, 3)):
        with fabrica_pg() as db:
            fijar_empresa(db, empresa_id)

            serie = comercial_politicas.reporte_ventas_serie_diaria(db, PERIODO)
            assert [(f["dia"], f["total_ventas"]) for f in serie] == [
                (dt.date(2026, 9, 14), Decimal("250.00") * m),
                (dt.date(2026, 9, 15), Decimal("330.00") * m),
                (dt.date(2026, 9, 20), Decimal("160.00") * m),
            ]
            assert all(isinstance(f["total_ventas"], Decimal) for f in serie)

            por_sucursal_dia = comercial_politicas.reporte_ventas_serie_diaria(db, PERIODO, desglose=("sucursal",))
            assert {f["sucursal"] for f in por_sucursal_dia} == {"Centro", "Norte"}

            categorias = comercial_politicas.reporte_ventas_por_categoria(db, PERIODO)
            assert [(f["categoria"], f["total_vendido"]) for f in categorias] == [
                ("Camisas", Decimal("540.00") * m),
                ("Poleras", Decimal("200.00") * m),
            ]

            top = comercial_politicas.reporte_ventas_top_productos(db, PERIODO, limite=3)
            assert [f["producto"] for f in top] == ["Polera Básica", "Camisa Oxford", "Camisa Lino"]
            assert sum(int(f["cantidad_vendida"]) for f in top) == 10 * m

            existencias = catalogo_politicas.reporte_existencias_por_producto(db, None, None, None, 10)
            assert [(f["producto"], f["disponible"]) for f in existencias] == [
                ("Camisa Lino", 8 * m),
                ("Polera Básica", 11 * m),
                ("Camisa Oxford", 14 * m),
            ]


def test_los_filtros_en_lista_con_in_y_los_nombres_se_resuelven_dentro_de_la_empresa(fabrica_pg):
    id_a, id_b, datos_a, datos_b = _dos_empresas(fabrica_pg)

    with fabrica_pg() as db:
        fijar_empresa(db, id_a)
        ids, sin = plataforma_politicas.resolver_sucursales_por_nombres(db, ["centro", "NORTE", "Marte"])
        assert set(ids) == set(datos_a["sucursales"][k] for k in ("centro", "norte")) and sin == ["Marte"]
        assert not set(ids) & set(datos_b["sucursales"].values())  # nunca ids de B

        por_sucursal = comercial_politicas.reporte_ventas_por_sucursal(db, PERIODO, sucursal_ids=[datos_a["sucursales"]["centro"]])
        assert [(f["sucursal"], _dinero(f["total_ventas"])) for f in por_sucursal] == [("Centro", Decimal("350.00"))]

        # Con ids de la otra empresa no hay nada: la consulta siempre filtra por la de la sesión.
        ajenos = comercial_politicas.reporte_ventas_por_sucursal(db, PERIODO, sucursal_ids=list(datos_b["sucursales"].values()))
        assert ajenos == []


def test_un_periodo_largo_agrupa_por_dia_sin_perder_ventas(fabrica_pg):
    id_a, _id_b, _a, _b = _dos_empresas(fabrica_pg)

    with fabrica_pg() as db:
        fijar_empresa(db, id_a)
        serie = comercial_politicas.reporte_ventas_serie_diaria(
            db, ParametrosPeriodo(desde=dt.date(2026, 7, 1), hasta=dt.date(2026, 9, 20))
        )

        # Además de las 4 ventas de septiembre, V7 (1 de agosto) entra: 740 + 100.
        assert sum(f["total_ventas"] for f in serie) == Decimal("840.00")
        assert [f["dia"] for f in serie] == sorted(f["dia"] for f in serie)


def _dinero(valor) -> Decimal:
    return Decimal(str(valor)).quantize(Decimal("0.01"))
