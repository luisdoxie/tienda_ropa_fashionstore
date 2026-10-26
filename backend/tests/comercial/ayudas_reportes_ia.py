"""E09, paso 2: el mundo de datos de las consultas de los reportes generativos (ventas por
día, por categoría, top de productos, existencias y resolución de nombres).

`sembrar_mundo_reportes(db, empresa_id, m)` crea en UNA empresa (con la misma estructura y los
mismos nombres en todas: así se prueba que los nombres iguales no se mezclan) y deja la empresa de
la sesión como estaba:

  Sucursales activas: Centro y Norte (más "Sucursal Vieja", inactiva). Categorías: Camisas y
  Poleras (más "Liquidación", inactiva). Productos: P1 "Camisa Oxford" (Camisas, 100.00, costo 60),
  P2 "Polera Básica" (Poleras, 50.00, costo 30), P3 "Camisa Lino" (Camisas, 80.00, costo 50) y
  P4 "Camisa Descontinuada" (inactivo).

Ventas (las cantidades se multiplican por `m`; fechas fijas de septiembre de 2026). Las cuentan
las pagadas y entregadas:

  V1 pagada     presencial Centro 14/09 10:00   P1 x2, P2 x1            = 250   (margen 100)
  V2 entregada  digital    Centro 15/09 15:30   P1 x1                   = 100   (margen  40)
  V3 pagada     presencial Norte  15/09 09:00   P2 x3, P3 x1            = 230   (margen  90)
  V4 pagada     presencial Norte  20/09 23:30   P3 x2                   = 160   (margen  60)
  V5 pendiente_pago Centro 14/09                P1 x5   (NO cuenta)
  V6 anulada        Norte  15/09                P2 x4   (NO cuenta)
  V7 pagada     presencial Centro 01/08         P1 x1   (fuera del período)
  V8 pagada     presencial Centro 21/09 00:00   P1 x1   (fuera: el período termina el 20)

Período del 14 al 20 de septiembre con m=1: 4 ventas, 10 unidades, 740.00 vendidos, 290.00 de margen.

Stock (cantidad física / mínimo, multiplicada la física por `m`): Centro P1 10/2, P2 3/5, P3 6/2;
Norte P1 4/2, P2 8/2, P3 2/2; más una variante inactiva de P1 (talla L) con 100 en Centro y 1 de
P4 en Centro, que NO deben contarse.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.catalogo.models import Categoria, Color, Producto, ProductoVariante, Stock, Talla
from app.comercial.models import EstadoVenta, Venta, VentaDetalle
from app.comercial.repository import VW_VENTAS_DETALLE_V2_SQL
from app.core.deps import ParametrosPeriodo
from app.core.tenant import empresa_de, fijar_empresa
from app.plataforma.models import Ciudad, Empleado, Sucursal, Usuario

PERIODO = ParametrosPeriodo(desde=dt.date(2026, 9, 14), hasta=dt.date(2026, 9, 20))

# (producto, categoría, precio, costo)
_PRODUCTOS = {
    "p1": ("Camisa Oxford", "camisas", Decimal("100.00"), Decimal("60.0000")),
    "p2": ("Polera Básica", "poleras", Decimal("50.00"), Decimal("30.0000")),
    "p3": ("Camisa Lino", "camisas", Decimal("80.00"), Decimal("50.0000")),
}

# (código, estado, canal, sucursal, fecha, [(producto, cantidad)])
_VENTAS = [
    ("V1", "pagada", "presencial", "centro", dt.datetime(2026, 9, 14, 10, 0), [("p1", 2), ("p2", 1)]),
    ("V2", "entregada", "digital", "centro", dt.datetime(2026, 9, 15, 15, 30), [("p1", 1)]),
    ("V3", "pagada", "presencial", "norte", dt.datetime(2026, 9, 15, 9, 0), [("p2", 3), ("p3", 1)]),
    ("V4", "pagada", "presencial", "norte", dt.datetime(2026, 9, 20, 23, 30), [("p3", 2)]),
    ("V5", "pendiente_pago", "presencial", "centro", dt.datetime(2026, 9, 14, 11, 0), [("p1", 5)]),
    ("V6", "anulada", "presencial", "norte", dt.datetime(2026, 9, 15, 12, 0), [("p2", 4)]),
    ("V7", "pagada", "presencial", "centro", dt.datetime(2026, 8, 1, 10, 0), [("p1", 1)]),
    ("V8", "pagada", "presencial", "centro", dt.datetime(2026, 9, 21, 0, 0), [("p1", 1)]),
]

# (sucursal, producto, física, mínimo)
_STOCK = [
    ("centro", "p1", 10, 2),
    ("centro", "p2", 3, 5),
    ("centro", "p3", 6, 2),
    ("norte", "p1", 4, 2),
    ("norte", "p2", 8, 2),
    ("norte", "p3", 2, 2),
]


def sembrar_mundo_reportes(db, empresa_id: int, m: int = 1) -> dict:
    original = empresa_de(db)
    fijar_empresa(db, empresa_id)
    try:
        ciudad = Ciudad(nombre="Ciudad Reportes", departamento="Santa Cruz")
        categorias = {
            "camisas": Categoria(nombre="Camisas"),
            "poleras": Categoria(nombre="Poleras"),
            "liquidacion": Categoria(nombre="Liquidación", activo=False),
        }
        talla_m, talla_l, color = Talla(codigo="M"), Talla(codigo="L"), Color(nombre="Negro")
        db.add_all([ciudad, talla_m, talla_l, color, *categorias.values()])
        db.flush()
        sucursales = {
            "centro": Sucursal(ciudad_id=ciudad.id, codigo="CEN", nombre="Centro", direccion="Calle 1"),
            "norte": Sucursal(ciudad_id=ciudad.id, codigo="NOR", nombre="Norte", direccion="Calle 2"),
            "vieja": Sucursal(ciudad_id=ciudad.id, codigo="VIE", nombre="Sucursal Vieja", direccion="Calle 3", activo=False),
        }
        db.add_all(sucursales.values())
        usuario = Usuario(nombre="Caja", apellido="Reportes", email="cajero@reportes.example.com", password_hash="x")
        db.add(usuario)
        db.flush()
        cajero = Empleado(usuario_id=usuario.id, sucursal_id=sucursales["centro"].id, cargo="Cajero")
        db.add(cajero)

        productos: dict[str, Producto] = {}
        variantes: dict[str, ProductoVariante] = {}
        for clave, (nombre, categoria, precio, _costo) in _PRODUCTOS.items():
            producto = Producto(
                codigo=f"P-{clave.upper()}", nombre=nombre, categoria_id=categorias[categoria].id, precio_base=precio
            )
            db.add(producto)
            db.flush()
            productos[clave] = producto
            variante = ProductoVariante(
                producto_id=producto.id, talla_id=talla_m.id, color_id=color.id, sku=f"SKU-{clave.upper()}-M"
            )
            db.add(variante)
            variantes[clave] = variante
        descontinuado = Producto(
            codigo="P-P4",
            nombre="Camisa Descontinuada",
            categoria_id=categorias["camisas"].id,
            precio_base=Decimal("10.00"),
            activo=False,
        )
        db.add(descontinuado)
        db.flush()
        variante_p4 = ProductoVariante(
            producto_id=descontinuado.id, talla_id=talla_m.id, color_id=color.id, sku="SKU-P4-M"
        )
        variante_inactiva = ProductoVariante(
            producto_id=productos["p1"].id, talla_id=talla_l.id, color_id=color.id, sku="SKU-P1-L", activo=False
        )
        db.add_all([variante_p4, variante_inactiva])
        db.flush()

        for sucursal, producto, fisica, minimo in _STOCK:
            db.add(
                Stock(
                    variante_id=variantes[producto].id,
                    sucursal_id=sucursales[sucursal].id,
                    cantidad_fisica=fisica * m,
                    cantidad_reservada=0,
                    stock_minimo=minimo,
                    costo_promedio=_PRODUCTOS[producto][3],
                )
            )
        for variante, fisica in ((variante_inactiva, 100), (variante_p4, 1)):
            db.add(
                Stock(
                    variante_id=variante.id,
                    sucursal_id=sucursales["centro"].id,
                    cantidad_fisica=fisica,
                    cantidad_reservada=0,
                    stock_minimo=0,
                    costo_promedio=Decimal("1.0000"),
                )
            )

        estados = {e.codigo: e.id for e in db.scalars(select(EstadoVenta))}
        for codigo, estado, canal, sucursal, fecha, lineas in _VENTAS:
            detalle = []
            for producto, cantidad in lineas:
                _nombre, _cat, precio, costo = _PRODUCTOS[producto]
                detalle.append(
                    VentaDetalle(
                        variante_id=variantes[producto].id,
                        cantidad=cantidad * m,
                        precio_unitario=precio,
                        costo_unitario=costo,
                        subtotal=precio * cantidad * m,
                    )
                )
            total = sum((linea.subtotal for linea in detalle), Decimal("0"))
            db.add(
                Venta(
                    codigo=codigo,
                    canal=canal,
                    sucursal_id=sucursales[sucursal].id,
                    cajero_id=cajero.id if canal == "presencial" else None,
                    estado_id=estados[estado],
                    fecha=fecha,
                    subtotal=total,
                    total=total,
                    detalle=detalle,
                )
            )
        db.commit()
        return {
            "empresa_id": empresa_id,
            "m": m,
            "sucursales": {clave: s.id for clave, s in sucursales.items()},
            "categorias": {clave: c.id for clave, c in categorias.items()},
            "productos": {clave: p.id for clave, p in productos.items()} | {"p4": descontinuado.id},
        }
    finally:
        fijar_empresa(db, original)


@pytest.fixture()
def mundo_reportes(db_session, dos_empresas):
    """(A, B): la empresa A con m=1 y la B con m=3 (mismos nombres, cifras distintas). Crea la
    vista de ventas (conftest solo crea la de inventario) y deja la sesión como estaba."""
    db_session.execute(text(VW_VENTAS_DETALLE_V2_SQL))
    db_session.commit()
    a = sembrar_mundo_reportes(db_session, dos_empresas.a.id, m=1)
    b = sembrar_mundo_reportes(db_session, dos_empresas.b.id, m=3)
    return a, b
