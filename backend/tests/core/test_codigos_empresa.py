"""E02 (multitenant), PASO 3.5: `generar_codigo` no cambia. Su chequeo de
unicidad (`existe_codigo`) es una consulta ORM, así que el filtro de empresa
la acota: dos empresas pueden tener el mismo código de venta (la restricción
única es POR empresa, no global)."""

import itertools

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.comercial.models import EstadoVenta, Venta
from app.comercial.politicas import venta_repo
from app.core import codigos
from app.core.codigos import generar_codigo
from app.core.tenant import fijar_empresa
from tests.catalogo.test_consolidado_empresa import sembrar_negocio


def _fijar_aleatorio(monkeypatch, *valores: str) -> None:
    """Hace que `secrets.token_hex(4)` devuelva, en orden, esos valores
    (y vuelva a repetir el último)."""
    secuencia = itertools.chain(valores, itertools.repeat(valores[-1]))
    monkeypatch.setattr(codigos.secrets, "token_hex", lambda _n: next(secuencia))


def _nueva_venta(db, codigo: str, sucursal_id: int) -> Venta:
    estado = db.scalar(select(EstadoVenta).where(EstadoVenta.codigo == "pendiente_pago"))
    venta = Venta(codigo=codigo, canal="digital", sucursal_id=sucursal_id, estado_id=estado.id)
    db.add(venta)
    db.flush()
    return venta


def test_dos_empresas_pueden_tener_el_mismo_codigo_de_venta(db_session, dos_empresas, monkeypatch):
    a = sembrar_negocio(db_session, dos_empresas.a.id, "A")
    b = sembrar_negocio(db_session, dos_empresas.b.id, "B")
    _fijar_aleatorio(monkeypatch, "deadbeef")

    fijar_empresa(db_session, a["empresa_id"])
    codigo_a = generar_codigo(db_session, "VTA", venta_repo.obtener_por_codigo)
    _nueva_venta(db_session, codigo_a, a["sucursal_id"])
    db_session.commit()

    # En A el código ya existe: se descarta y se reintenta con otro.
    _fijar_aleatorio(monkeypatch, "deadbeef", "cafecafe")
    assert generar_codigo(db_session, "VTA", venta_repo.obtener_por_codigo) == "VTA-CAFECAFE"

    # En B, "VTA-DEADBEEF" está libre aunque A ya lo use: sale a la primera
    # y se puede guardar sin chocar con la restricción única.
    fijar_empresa(db_session, b["empresa_id"])
    _fijar_aleatorio(monkeypatch, "deadbeef", "cafecafe")
    codigo_b = generar_codigo(db_session, "VTA", venta_repo.obtener_por_codigo)
    assert codigo_a == codigo_b == "VTA-DEADBEEF"
    _nueva_venta(db_session, codigo_b, b["sucursal_id"])
    db_session.commit()

    for empresa_id in (a["empresa_id"], b["empresa_id"]):
        fijar_empresa(db_session, empresa_id)
        assert [v.codigo for v in db_session.scalars(select(Venta))] == ["VTA-DEADBEEF"]


def test_el_mismo_codigo_en_la_misma_empresa_sigue_siendo_unico(db_session, dos_empresas, monkeypatch):
    """La unicidad no se perdió: dentro de una empresa el código no se repite
    (ni lo genera `generar_codigo`, ni lo acepta la base)."""
    a = sembrar_negocio(db_session, dos_empresas.a.id, "A")
    fijar_empresa(db_session, a["empresa_id"])
    _nueva_venta(db_session, "VTA-DEADBEEF", a["sucursal_id"])
    db_session.commit()

    _fijar_aleatorio(monkeypatch, "deadbeef", "deadbeef", "0badf00d")
    assert generar_codigo(db_session, "VTA", venta_repo.obtener_por_codigo) == "VTA-0BADF00D"

    with pytest.raises(IntegrityError):
        _nueva_venta(db_session, "VTA-DEADBEEF", a["sucursal_id"])
    db_session.rollback()
