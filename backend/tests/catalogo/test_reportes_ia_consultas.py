"""E09, paso 2: resolución de nombres (categorías y productos) y existencias por producto para los
reportes generativos. Datos reales de `tests/comercial/ayudas_reportes_ia.py`: categorías activas
Camisas y Poleras (y "Liquidación", inactiva); productos activos "Camisa Oxford", "Polera Básica" y
"Camisa Lino" (y "Camisa Descontinuada", inactivo); stock por sucursal en esa ayuda."""

import pytest

from app.catalogo import politicas as catalogo
from app.catalogo.models import Categoria, Producto
from app.core.exceptions import DomainError
from app.core.tenant import EmpresaNoDefinidaError, fijar_empresa
from tests.comercial.ayudas_reportes_ia import mundo_reportes  # noqa: F401  (fixture)


@pytest.fixture()
def a(db_session, mundo_reportes):  # noqa: F811
    fijar_empresa(db_session, mundo_reportes[0]["empresa_id"])
    return mundo_reportes[0]


# ---- Categorías ----------------------------------------------------------------------------------


def test_categorias_igualdad_exacta_sin_mayusculas_ni_tildes_ni_espacios_de_mas(db_session, a):
    ids, sin = catalogo.resolver_categorias_por_nombres(db_session, ["  CAMISAS ", "poleras"])
    assert ids == [a["categorias"]["camisas"], a["categorias"]["poleras"]]
    assert sin == []
    # El orden pedido se respeta y no hay ids repetidos.
    ids, sin = catalogo.resolver_categorias_por_nombres(db_session, ["Poleras", "camisas", "POLERAS"])
    assert ids == [a["categorias"]["poleras"], a["categorias"]["camisas"]]


def test_categorias_sin_coincidencia_incluye_inactivas_y_parciales(db_session, a):
    ids, sin = catalogo.resolver_categorias_por_nombres(
        db_session, ["Liquidacion", "Camisa", "Cami%", "%", "Camisas_", "Zapatos", "   "]
    )
    assert ids == []
    # Las vacías se ignoran; el resto vuelve tal como las escribió (sin espacios en los extremos).
    assert sin == ["Liquidacion", "Camisa", "Cami%", "%", "Camisas_", "Zapatos"]


def test_categorias_mezcla_de_encontradas_y_no(db_session, a):
    ids, sin = catalogo.resolver_categorias_por_nombres(db_session, ["camisas", "Faldas"])
    assert (ids, sin) == ([a["categorias"]["camisas"]], ["Faldas"])
    assert catalogo.resolver_categorias_por_nombres(db_session, []) == ([], [])


def test_categorias_no_incluye_subcategorias(db_session, a):
    hija = Categoria(nombre="Camisas Manga Larga", categoria_padre_id=a["categorias"]["camisas"])
    db_session.add(hija)
    db_session.commit()
    ids, sin = catalogo.resolver_categorias_por_nombres(db_session, ["Camisas"])
    assert ids == [a["categorias"]["camisas"]] and hija.id not in ids
    assert catalogo.resolver_categorias_por_nombres(db_session, ["Camisas Manga Larga"]) == ([hija.id], [])


def test_nombres_de_categorias_activas(db_session, a):
    assert sorted(catalogo.listar_nombres_categorias_activas(db_session)) == ["Camisas", "Poleras"]


# ---- Productos --------------------------------------------------------------------------------------


def test_productos_por_contiene_sin_tildes_ni_mayusculas(db_session, a):
    p = a["productos"]
    assert catalogo.resolver_productos_por_nombres(db_session, ["polera basica"]) == ([p["p2"]], [], [])
    assert catalogo.resolver_productos_por_nombres(db_session, ["  OXFORD "]) == ([p["p1"]], [], [])
    # "camisa" está en P1 y P3; P4 (inactivo) no cuenta.
    assert catalogo.resolver_productos_por_nombres(db_session, ["camisa"]) == ([p["p1"], p["p3"]], [], [])


def test_productos_ambiguo_cuando_supera_el_tope(db_session, a):
    p = a["productos"]
    ids, ambiguos, sin = catalogo.resolver_productos_por_nombres(db_session, ["camisa", "polera"], tope=1)
    assert (ids, ambiguos, sin) == ([p["p2"]], ["camisa"], [])
    # Con el tope por defecto (10) dos coincidencias no son ambiguas.
    assert catalogo.resolver_productos_por_nombres(db_session, ["camisa"])[1] == []


def test_productos_mas_de_diez_coincidencias_es_ambiguo_por_defecto(db_session, a):
    categoria_id = a["categorias"]["camisas"]
    from decimal import Decimal

    for n in range(10):
        db_session.add(Producto(codigo=f"X-{n}", nombre=f"Remera Lisa {n}", categoria_id=categoria_id, precio_base=Decimal("10")))
    db_session.commit()
    # 10 coincidencias todavía se aceptan; con una más pasa a ambiguo.
    ids, ambiguos, _ = catalogo.resolver_productos_por_nombres(db_session, ["remera lisa"])
    assert len(ids) == 10 and ambiguos == []
    db_session.add(Producto(codigo="X-10", nombre="Remera Lisa 10", categoria_id=categoria_id, precio_base=Decimal("10")))
    db_session.commit()
    assert catalogo.resolver_productos_por_nombres(db_session, ["remera lisa"]) == ([], ["remera lisa"], [])


def test_productos_sin_coincidencia_vacios_y_patrones(db_session, a):
    ids, ambiguos, sin = catalogo.resolver_productos_por_nombres(
        db_session, ["Descontinuada", "%", "_", "zzz", "", "  "]
    )
    # "%" y "_" no son comodines: se buscan como texto y no están en ningún nombre.
    assert (ids, ambiguos) == ([], [])
    assert sin == ["Descontinuada", "%", "_", "zzz"]


def test_productos_no_repite_ids(db_session, a):
    p = a["productos"]
    ids, _, _ = catalogo.resolver_productos_por_nombres(db_session, ["camisa lino", "lino", "camisa"])
    assert ids == [p["p3"], p["p1"]]


# ---- Existencias por producto -------------------------------------------------------------------------


def _resumen(filas):
    return [(f["producto"], f["categoria"], f["disponible"], f["stock_minimo"], f["bajo_minimo"]) for f in filas]


def test_existencias_de_todas_las_sucursales_de_menor_a_mayor(db_session, a):
    filas = catalogo.reporte_existencias_por_producto(db_session, None, None, None, 10)
    # P3: 6+2 = 8 (mín 4); P2: 3+8 = 11 (mín 7); P1: 10+4 = 14 (mín 4). La variante inactiva de P1
    # (100 en Centro) y el producto inactivo P4 (1 en Centro) no cuentan.
    assert _resumen(filas) == [
        ("Camisa Lino", "Camisas", 8, 4, False),
        ("Polera Básica", "Poleras", 11, 7, False),
        ("Camisa Oxford", "Camisas", 14, 4, False),
    ]
    assert [f["producto_id"] for f in filas] == [a["productos"]["p3"], a["productos"]["p2"], a["productos"]["p1"]]
    assert all(type(f["disponible"]) is int and type(f["bajo_minimo"]) is bool for f in filas)


def test_existencias_por_sucursal_y_bajo_minimo(db_session, a):
    centro, norte = a["sucursales"]["centro"], a["sucursales"]["norte"]
    en_centro = catalogo.reporte_existencias_por_producto(db_session, [centro], None, None, 10)
    # En Centro P2 tiene 3 con mínimo 5: bajo el mínimo.
    assert _resumen(en_centro) == [
        ("Polera Básica", "Poleras", 3, 5, True),
        ("Camisa Lino", "Camisas", 6, 2, False),
        ("Camisa Oxford", "Camisas", 10, 2, False),
    ]
    # En Norte P3 tiene 2 con mínimo 2: igual al mínimo cuenta como bajo (mismo criterio de las alertas).
    en_norte = catalogo.reporte_existencias_por_producto(db_session, [norte], None, None, 10)
    assert _resumen(en_norte) == [
        ("Camisa Lino", "Camisas", 2, 2, True),
        ("Camisa Oxford", "Camisas", 4, 2, False),
        ("Polera Básica", "Poleras", 8, 2, False),
    ]


def test_existencias_con_filtros_de_categoria_y_producto_y_limite(db_session, a):
    p, c = a["productos"], a["categorias"]
    camisas = catalogo.reporte_existencias_por_producto(db_session, None, [c["camisas"]], None, 10)
    assert [f["producto"] for f in camisas] == ["Camisa Lino", "Camisa Oxford"]
    uno = catalogo.reporte_existencias_por_producto(db_session, None, None, [p["p1"], p["p2"]], 10)
    assert [f["producto"] for f in uno] == ["Polera Básica", "Camisa Oxford"]
    assert [f["producto"] for f in catalogo.reporte_existencias_por_producto(db_session, None, None, None, 2)] == [
        "Camisa Lino",
        "Polera Básica",
    ]
    combinado = catalogo.reporte_existencias_por_producto(db_session, [a["sucursales"]["norte"]], [c["poleras"]], [p["p2"]], 5)
    assert _resumen(combinado) == [("Polera Básica", "Poleras", 8, 2, False)]


def test_existencias_listas_vacias_y_limite_invalido(db_session, a):
    for argumentos in (([], None, None), (None, [], None), (None, None, [])):
        assert catalogo.reporte_existencias_por_producto(db_session, *argumentos, 10) == []
    with pytest.raises(DomainError):
        catalogo.reporte_existencias_por_producto(db_session, None, None, None, 0)


def test_existencias_excluye_inactivos_aunque_se_pidan_por_id(db_session, a):
    # Pedir el producto inactivo por id no lo trae; tampoco la categoría inactiva.
    assert catalogo.reporte_existencias_por_producto(db_session, None, None, [a["productos"]["p4"]], 10) == []
    assert catalogo.reporte_existencias_por_producto(db_session, None, [a["categorias"]["liquidacion"]], None, 10) == []


# ---- Aislamiento por empresa -----------------------------------------------------------------------------


def test_los_nombres_se_resuelven_solo_dentro_de_la_empresa(db_session, mundo_reportes):  # noqa: F811
    a, b = mundo_reportes
    fijar_empresa(db_session, b["empresa_id"])
    db_session.add(Categoria(nombre="Solo B"))
    db_session.commit()

    fijar_empresa(db_session, a["empresa_id"])
    assert catalogo.resolver_categorias_por_nombres(db_session, ["Camisas", "Solo B"]) == (
        [a["categorias"]["camisas"]],
        ["Solo B"],
    )
    assert catalogo.resolver_productos_por_nombres(db_session, ["oxford"]) == ([a["productos"]["p1"]], [], [])
    assert "Solo B" not in catalogo.listar_nombres_categorias_activas(db_session)

    # Mismos nombres, ids de la otra empresa.
    fijar_empresa(db_session, b["empresa_id"])
    assert catalogo.resolver_categorias_por_nombres(db_session, ["Camisas"]) == ([b["categorias"]["camisas"]], [])
    assert catalogo.resolver_productos_por_nombres(db_session, ["oxford"]) == ([b["productos"]["p1"]], [], [])
    assert "Solo B" in catalogo.listar_nombres_categorias_activas(db_session)


def test_existencias_cada_empresa_ve_solo_las_suyas(db_session, mundo_reportes):  # noqa: F811
    a, b = mundo_reportes
    fijar_empresa(db_session, a["empresa_id"])
    filas_a = catalogo.reporte_existencias_por_producto(db_session, None, None, None, 10)
    assert {f["producto_id"] for f in filas_a} == {a["productos"][k] for k in ("p1", "p2", "p3")}
    assert [f["disponible"] for f in filas_a] == [8, 11, 14]

    fijar_empresa(db_session, b["empresa_id"])
    filas_b = catalogo.reporte_existencias_por_producto(db_session, None, None, None, 10)
    # B tiene el triple de stock físico (los mismos mínimos): 24, 33 y 42.
    assert {f["producto_id"] for f in filas_b} == {b["productos"][k] for k in ("p1", "p2", "p3")}
    assert [f["disponible"] for f in filas_b] == [24, 33, 42]

    # Los ids de A, vistos desde B, no traen nada (sucursales, categorías o productos).
    assert catalogo.reporte_existencias_por_producto(db_session, list(a["sucursales"].values()), None, None, 10) == []
    assert catalogo.reporte_existencias_por_producto(db_session, None, list(a["categorias"].values()), None, 10) == []
    assert catalogo.reporte_existencias_por_producto(db_session, None, None, list(a["productos"].values()), 10) == []


def test_las_consultas_de_catalogo_fallan_cerrado_sin_empresa(db_session, mundo_reportes):  # noqa: F811
    fijar_empresa(db_session, None)
    with pytest.raises(EmpresaNoDefinidaError):
        catalogo.reporte_existencias_por_producto(db_session, None, None, None, 10)
    with pytest.raises(EmpresaNoDefinidaError):
        catalogo.resolver_categorias_por_nombres(db_session, ["Camisas"])
    with pytest.raises(EmpresaNoDefinidaError):
        catalogo.resolver_productos_por_nombres(db_session, ["oxford"])
