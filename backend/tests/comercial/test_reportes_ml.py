"""E11, paso 4: las dos consultas de `comercial` que alimentan el ML.

- `reporte_ventas_serie_diaria` ahora trae también `ventas_brutas` (lo vendido a precio de lista, antes
  del descuento). Es aditivo: las claves y el orden de antes no cambian.
- `reporte_rfm_clientes`: recencia, frecuencia y monto por cliente con compras efectivas.

Todo sobre SQLite en memoria (la fixture `db_session`). La serie diaria lee la vista `vw_ventas_detalle`,
que esta prueba crea con la misma fixture que usan las de E09 (`mundo_reportes`).
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.catalogo.models import ProductoVariante
from app.comercial import politicas as comercial
from app.comercial.models import EstadoVenta, Venta, VentaDetalle
from app.core.deps import ParametrosPeriodo
from app.core.exceptions import DomainError
from app.core.tenant import CLAVE_EMPRESA, EmpresaNoDefinidaError, empresa_de, fijar_empresa
from app.plataforma.models import Ciudad, Cliente, Sucursal, Usuario
from tests.comercial.ayudas_reportes_ia import PERIODO, mundo_reportes  # noqa: F401  (fixture)

HASTA = dt.date(2026, 9, 30)


# ---- ventas_brutas en la serie diaria ---------------------------------------------------------------


@pytest.fixture()
def a(db_session, mundo_reportes):  # noqa: F811
    fijar_empresa(db_session, mundo_reportes[0]["empresa_id"])
    return mundo_reportes[0]


def test_la_serie_diaria_trae_ventas_brutas_sin_cambiar_lo_demas(db_session, a):
    filas = comercial.reporte_ventas_serie_diaria(db_session, PERIODO, desglose=("categoria",))
    assert filas
    # Las claves de antes siguen, en su orden, y la nueva va al final.
    assert list(filas[0]) == [
        "dia", "categoria_id", "categoria", "transacciones", "unidades", "total_ventas", "ventas_brutas"
    ]
    # Sin descuentos en el mundo de E09, lo bruto es igual a lo vendido: 740 en total (cifras de E09).
    assert sum(f["total_ventas"] for f in filas) == Decimal("740.00")
    assert sum(f["ventas_brutas"] for f in filas) == Decimal("740.00")
    assert all(isinstance(f["ventas_brutas"], Decimal) for f in filas)
    sin_desglose = comercial.reporte_ventas_serie_diaria(db_session, PERIODO)
    assert list(sin_desglose[0])[-2:] == ["total_ventas", "ventas_brutas"]


def test_ventas_brutas_es_el_precio_de_lista_y_el_descuento_es_la_diferencia(db_session, a):
    """Una venta de 2 prendas de 100 con 20 de descuento: bruto 200, total 180."""
    variante = db_session.scalar(
        select(ProductoVariante).where(ProductoVariante.producto_id == a["productos"]["p1"])
    )
    estado_id = db_session.scalar(select(EstadoVenta.id).where(EstadoVenta.codigo == "pagada"))
    sucursal_id = a["sucursales"]["centro"]
    # Un día aparte (el 18) para aislar la cifra; digital, así no necesita cajero.
    db_session.add(
        Venta(
            codigo="DESC-1",
            canal="digital",
            sucursal_id=sucursal_id,
            estado_id=estado_id,
            fecha=dt.datetime(2026, 9, 18, 11, 0),
            subtotal=Decimal("180"),
            total=Decimal("180"),
            detalle=[
                VentaDetalle(
                    variante_id=variante.id,
                    cantidad=2,
                    precio_unitario=Decimal("100.00"),
                    descuento_unitario=Decimal("10.00"),
                    costo_unitario=Decimal("60.0000"),
                    subtotal=Decimal("180.00"),
                )
            ],
        )
    )
    db_session.commit()
    dia = dt.date(2026, 9, 18)
    filas = comercial.reporte_ventas_serie_diaria(
        db_session, ParametrosPeriodo(desde=dia, hasta=dia), desglose=("categoria",)
    )
    assert len(filas) == 1
    assert filas[0]["total_ventas"] == Decimal("180.00")
    assert filas[0]["ventas_brutas"] == Decimal("200.00")
    assert filas[0]["ventas_brutas"] - filas[0]["total_ventas"] == Decimal("20.00")


def test_ventas_brutas_no_mezcla_empresas(db_session, mundo_reportes):  # noqa: F811
    a, b = mundo_reportes  # b vende el triple en las mismas fechas
    fijar_empresa(db_session, a["empresa_id"])
    de_a = comercial.reporte_ventas_serie_diaria(db_session, PERIODO)
    fijar_empresa(db_session, b["empresa_id"])
    de_b = comercial.reporte_ventas_serie_diaria(db_session, PERIODO)
    assert sum(f["ventas_brutas"] for f in de_a) == Decimal("740.00")
    assert sum(f["ventas_brutas"] for f in de_b) == Decimal("2220.00")


# ---- reporte_rfm_clientes -------------------------------------------------------------------------------


def _infraestructura(db, empresa_id: int) -> dict:
    """Sucursal y estados de venta de la empresa. Deja la sesión en esa empresa."""
    fijar_empresa(db, empresa_id)
    ciudad = Ciudad(nombre="Ciudad RFM", departamento="Santa Cruz")
    db.add(ciudad)
    db.flush()
    sucursal = Sucursal(ciudad_id=ciudad.id, codigo="RFM", nombre="Sucursal RFM", direccion="Calle 1")
    db.add(sucursal)
    db.flush()
    return {"sucursal_id": sucursal.id, "estados": {e.codigo: e.id for e in db.scalars(select(EstadoVenta))}}


def _cliente(db, correo: str) -> int:
    usuario = Usuario(nombre="Cli", apellido="RFM", email=correo, password_hash="x")
    db.add(usuario)
    db.flush()
    cliente = Cliente(usuario_id=usuario.id)
    db.add(cliente)
    db.flush()
    return cliente.id


_contador = {"n": 0}


def _venta(db, infra, cliente_id, fecha, total, estado="pagada") -> None:
    _contador["n"] += 1
    db.add(
        Venta(
            codigo=f"RFM-{_contador['n']:05d}",
            canal="digital",
            cliente_id=cliente_id,
            sucursal_id=infra["sucursal_id"],
            estado_id=infra["estados"][estado],
            fecha=fecha,
            subtotal=Decimal(total),
            total=Decimal(total),
        )
    )


@pytest.fixture()
def rfm(db_session, dos_empresas):
    """Empresa A: tres clientes con compras (y ruido que NO debe contar); empresa B: un cliente con una
    compra enorme. Devuelve los ids de los clientes de A. La sesión queda en A."""
    infra_b = _infraestructura(db_session, dos_empresas.b.id)
    cliente_b = _cliente(db_session, "b1@rfm.example.com")
    _venta(db_session, infra_b, cliente_b, dt.datetime(2026, 9, 29, 10), "99999")
    db_session.commit()

    infra = _infraestructura(db_session, dos_empresas.a.id)
    c1, c2, c3 = (_cliente(db_session, f"a{i}@rfm.example.com") for i in (1, 2, 3))
    # c1: tres compras efectivas (pagada, entregada, pagada) + una pendiente y una anulada que no cuentan.
    _venta(db_session, infra, c1, dt.datetime(2026, 9, 1, 9), "100.50")
    _venta(db_session, infra, c1, dt.datetime(2026, 9, 10, 18), "200", estado="entregada")
    _venta(db_session, infra, c1, dt.datetime(2026, 9, 30, 23, 59), "50")  # último segundo del día `hasta`
    _venta(db_session, infra, c1, dt.datetime(2026, 9, 20, 12), "7000", estado="pendiente_pago")
    _venta(db_session, infra, c1, dt.datetime(2026, 9, 21, 12), "8000", estado="anulada")
    # c2: una compra, y una anterior a la ventana de 30 días.
    _venta(db_session, infra, c2, dt.datetime(2026, 9, 15, 12), "300")
    _venta(db_session, infra, c2, dt.datetime(2026, 8, 31, 23, 59), "10")  # fuera de (hasta-30, hasta]
    # c3: solo una anulada, una de después de `hasta` y solo una vieja: no debe salir con la ventana corta.
    _venta(db_session, infra, c3, dt.datetime(2026, 9, 25, 12), "500", estado="anulada")
    _venta(db_session, infra, c3, dt.datetime(2026, 10, 1, 0, 0), "600")  # el día siguiente a `hasta`
    _venta(db_session, infra, c3, dt.datetime(2025, 10, 5, 12), "40")  # hace casi un año
    # Una venta anónima (sin cliente) que no entra.
    _venta(db_session, infra, None, dt.datetime(2026, 9, 12, 12), "900")
    db_session.commit()
    return {"c1": c1, "c2": c2, "c3": c3, "empresa_b": cliente_b}


def test_rfm_solo_cuenta_ventas_efectivas_con_cliente(db_session, rfm):
    filas = comercial.reporte_rfm_clientes(db_session, HASTA, dias=30)
    assert [f["cliente_id"] for f in filas] == [rfm["c1"], rfm["c2"]]
    c1, c2 = filas
    # c1: 100,50 + 200 + 50 (pagada, entregada, pagada); la pendiente y la anulada no suman.
    assert (c1["frecuencia"], c1["monto_total"]) == (3, Decimal("350.50"))
    assert c1["ultima_compra"] == dt.date(2026, 9, 30)  # el último segundo del día `hasta` entra
    # c2: solo la de septiembre; la del 31 de agosto queda fuera de (hasta - 30, hasta].
    assert (c2["frecuencia"], c2["monto_total"], c2["ultima_compra"]) == (1, Decimal("300.00"), dt.date(2026, 9, 15))
    # c3 solo tiene una anulada y una posterior a `hasta`: no aparece. Tampoco la venta anónima (900).
    assert all(f["cliente_id"] != rfm["c3"] for f in filas)
    assert sum(f["monto_total"] for f in filas) == Decimal("650.50")


def test_rfm_tipos_y_claves(db_session, rfm):
    fila = comercial.reporte_rfm_clientes(db_session, HASTA, dias=30)[0]
    assert list(fila) == ["cliente_id", "ultima_compra", "frecuencia", "monto_total"]
    assert isinstance(fila["cliente_id"], int) and isinstance(fila["frecuencia"], int)
    assert type(fila["ultima_compra"]) is dt.date
    assert isinstance(fila["monto_total"], Decimal) and fila["monto_total"].as_tuple().exponent == -2


def test_rfm_la_ventana_es_abierta_por_la_izquierda_y_cerrada_por_la_derecha(db_session, rfm):
    # (hasta - 30, hasta] = del 1 de septiembre al 30: la compra de c2 del 31 de agosto a las 23:59 no entra...
    ventana_30 = comercial.reporte_rfm_clientes(db_session, HASTA, dias=30)
    assert {f["cliente_id"]: f["frecuencia"] for f in ventana_30} == {rfm["c1"]: 3, rfm["c2"]: 1}
    # ...pero con 31 días (desde el 31 de agosto) sí, y la de c1 del 1 de septiembre sigue dentro.
    ventana_31 = comercial.reporte_rfm_clientes(db_session, HASTA, dias=31)
    assert {f["cliente_id"]: f["frecuencia"] for f in ventana_31} == {rfm["c1"]: 3, rfm["c2"]: 2}
    # `hasta` en medio de septiembre deja fuera lo posterior: c1 pierde la del 30 y c2 gana la del 31 de agosto.
    al_15 = comercial.reporte_rfm_clientes(db_session, dt.date(2026, 9, 15), dias=30)
    assert {f["cliente_id"]: f["frecuencia"] for f in al_15} == {rfm["c1"]: 2, rfm["c2"]: 2}
    # El día siguiente a `hasta` (c3, 1 de octubre 00:00) no entra con hasta = 30 de septiembre.
    assert rfm["c3"] not in {f["cliente_id"] for f in ventana_31}
    # Con la ventana por defecto (365 días) c3 tampoco aparece: sus dos ventas efectivas son del 1 de octubre y
    # de hace casi un año (5 de octubre de 2025 está dentro de los 365 días que terminan el 30/9/2026).
    por_defecto = comercial.reporte_rfm_clientes(db_session, HASTA)
    assert {f["cliente_id"]: f["frecuencia"] for f in por_defecto} == {
        rfm["c1"]: 3, rfm["c2"]: 2, rfm["c3"]: 1
    }


def test_rfm_orden_por_cliente_y_tope(db_session, rfm):
    filas = comercial.reporte_rfm_clientes(db_session, HASTA, dias=365)
    ids = [f["cliente_id"] for f in filas]
    assert ids == sorted(ids) and len(ids) == 3
    # Con tope, quedan los de id menor (determinismo), nunca uno al azar.
    assert [f["cliente_id"] for f in comercial.reporte_rfm_clientes(db_session, HASTA, dias=365, tope=2)] == ids[:2]
    assert len(comercial.reporte_rfm_clientes(db_session, HASTA, dias=365, tope=1)) == 1
    # Lo que devuelve una corrida es exactamente lo de la siguiente.
    assert filas == comercial.reporte_rfm_clientes(db_session, HASTA, dias=365)


def test_rfm_no_mezcla_empresas(db_session, rfm, dos_empresas):
    de_a = comercial.reporte_rfm_clientes(db_session, HASTA, dias=30)
    assert rfm["empresa_b"] not in {f["cliente_id"] for f in de_a}
    assert Decimal("99999") not in {f["monto_total"] for f in de_a}
    fijar_empresa(db_session, dos_empresas.b.id)
    de_b = comercial.reporte_rfm_clientes(db_session, HASTA, dias=30)
    assert [(f["cliente_id"], f["monto_total"]) for f in de_b] == [(rfm["empresa_b"], Decimal("99999.00"))]


def test_rfm_sin_empresa_en_la_sesion_falla_cerrado(db_session, rfm):
    original = empresa_de(db_session)
    db_session.info.pop(CLAVE_EMPRESA, None)
    with pytest.raises(EmpresaNoDefinidaError):
        comercial.reporte_rfm_clientes(db_session, HASTA)
    fijar_empresa(db_session, original)


def test_rfm_rechaza_ventana_y_tope_invalidos(db_session, rfm):
    with pytest.raises(DomainError):
        comercial.reporte_rfm_clientes(db_session, HASTA, dias=0)
    with pytest.raises(DomainError):
        comercial.reporte_rfm_clientes(db_session, HASTA, tope=0)
