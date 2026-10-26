"""E09, paso 2: resolución de nombres de sucursal para los reportes generativos. Datos de
`tests/comercial/ayudas_reportes_ia.py`: sucursales activas Centro y Norte, y "Sucursal Vieja"
(inactiva), en las dos empresas de prueba."""

import pytest

from app.core.tenant import EmpresaNoDefinidaError, fijar_empresa
from app.plataforma import politicas as plataforma
from app.plataforma.models import Ciudad, Sucursal
from tests.comercial.ayudas_reportes_ia import mundo_reportes  # noqa: F401  (fixture)


@pytest.fixture()
def a(db_session, mundo_reportes):  # noqa: F811
    fijar_empresa(db_session, mundo_reportes[0]["empresa_id"])
    return mundo_reportes[0]


def test_igualdad_exacta_sin_mayusculas_ni_tildes_ni_espacios_de_mas(db_session, a):
    ids, sin = plataforma.resolver_sucursales_por_nombres(db_session, ["  CENTRO ", "norte"])
    assert ids == [a["sucursales"]["centro"], a["sucursales"]["norte"]]
    assert sin == []
    ids, sin = plataforma.resolver_sucursales_por_nombres(db_session, ["Norte", "centro", "NORTE"])
    assert ids == [a["sucursales"]["norte"], a["sucursales"]["centro"]]  # orden pedido, sin repetir


def test_una_sucursal_con_tilde_se_resuelve_sin_ella(db_session, a):
    ciudad = db_session.query(Ciudad).first()
    nueva = Sucursal(ciudad_id=ciudad.id, codigo="PLZ", nombre="Plaza Ñuflo   Chávez", direccion="Calle 9")
    db_session.add(nueva)
    db_session.commit()
    assert plataforma.resolver_sucursales_por_nombres(db_session, ["plaza nuflo chavez"]) == ([nueva.id], [])
    assert plataforma.resolver_sucursales_por_nombres(db_session, ["PLAZA ÑUFLO CHÁVEZ"]) == ([nueva.id], [])


def test_solo_sucursales_activas_y_nunca_patrones(db_session, a):
    ids, sin = plataforma.resolver_sucursales_por_nombres(
        db_session, ["Sucursal Vieja", "Cent", "Cen%", "%", "Norte_", "Marte", "", "   "]
    )
    assert ids == []
    assert sin == ["Sucursal Vieja", "Cent", "Cen%", "%", "Norte_", "Marte"]  # las vacías se ignoran


def test_mezcla_de_encontradas_y_no_y_lista_vacia(db_session, a):
    ids, sin = plataforma.resolver_sucursales_por_nombres(db_session, ["Centro", "Marte"])
    assert (ids, sin) == ([a["sucursales"]["centro"]], ["Marte"])
    assert plataforma.resolver_sucursales_por_nombres(db_session, []) == ([], [])


def test_nombres_de_sucursales_activas_para_sugerencias(db_session, a):
    assert plataforma.listar_nombres_sucursales_activas(db_session) == ["Centro", "Norte"]


def test_cada_empresa_resuelve_solo_sus_sucursales(db_session, mundo_reportes):  # noqa: F811
    a, b = mundo_reportes
    fijar_empresa(db_session, b["empresa_id"])
    solo_b = Sucursal(ciudad_id=db_session.query(Ciudad).first().id, codigo="SOB", nombre="Solo B", direccion="Calle 7")
    db_session.add(solo_b)
    db_session.commit()
    solo_b_id = solo_b.id

    fijar_empresa(db_session, a["empresa_id"])
    assert plataforma.resolver_sucursales_por_nombres(db_session, ["Centro", "Solo B"]) == (
        [a["sucursales"]["centro"]],
        ["Solo B"],
    )
    assert plataforma.listar_nombres_sucursales_activas(db_session) == ["Centro", "Norte"]

    fijar_empresa(db_session, b["empresa_id"])
    # Mismo nombre, id de la otra empresa; y "Solo B" existe solo aquí.
    assert plataforma.resolver_sucursales_por_nombres(db_session, ["Centro", "Solo B"]) == (
        [b["sucursales"]["centro"], solo_b_id],
        [],
    )
    assert plataforma.listar_nombres_sucursales_activas(db_session) == ["Centro", "Norte", "Solo B"]


def test_sin_empresa_falla_cerrado(db_session, mundo_reportes):  # noqa: F811
    fijar_empresa(db_session, None)
    with pytest.raises(EmpresaNoDefinidaError):
        plataforma.resolver_sucursales_por_nombres(db_session, ["Centro"])
    with pytest.raises(EmpresaNoDefinidaError):
        plataforma.listar_nombres_sucursales_activas(db_session)
