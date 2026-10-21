"""E01 (multitenant): las vistas V2 conocen la empresa.

vw_ventas_detalle y vw_inventario_consolidado traen `empresa_id` al final de
la lista de columnas y cada JOIN exige la misma empresa. El SQL V2 vive en
los repositorios (constantes) y la migración multitenant lleva una copia
embebida; estas pruebas detectan cualquier desvío entre ambos. El FILTRADO
por empresa de las consultas es de la etapa E02: aquí solo se comprueba que la
columna existe y que sirve para filtrar.
"""

import datetime as dt
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text

from app.catalogo import repository as catalogo_repository
from app.catalogo.models import Categoria, Color, Producto, ProductoVariante, Stock, Talla
from app.catalogo.repository import VW_INVENTARIO_CONSOLIDADO_V2_SQL
from app.catalogo.schemas import ConsolidadoRespuesta, ValuacionRespuesta
from app.comercial import repository as comercial_repository
from app.comercial.models import EstadoVenta, Venta, VentaDetalle
from app.comercial.repository import VW_VENTAS_DETALLE_V2_SQL
from app.core.tenant import CLAVE_EMPRESA, fijar_empresa
from app.inteligencia.schemas import FilaVentasDetalle
from app.plataforma.models import Ciudad, Empresa, Sucursal
from tests.conftest import crear_empresa

MIGRACIONES = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _crear_vistas_v2(db) -> None:
    """conftest solo crea la vista de inventario V2; la de ventas la crea
    quien la necesita."""
    db.execute(text("DROP VIEW IF EXISTS vw_ventas_detalle"))
    db.execute(text(VW_VENTAS_DETALLE_V2_SQL))
    db.commit()


def _sembrar_venta(db, empresa_id: int, sufijo: str, cantidad: int = 2) -> dict:
    """Una venta con su detalle, su producto, su variante y su stock, todo en
    `empresa_id`. Deja la empresa fijada en la sesión (el llamador la restaura)."""
    fijar_empresa(db, empresa_id)
    ciudad = Ciudad(nombre=f"Ciudad {sufijo}", departamento="Santa Cruz")
    categoria = Categoria(nombre=f"Categoria {sufijo}")
    talla = Talla(codigo="M")
    color = Color(nombre="Negro")
    db.add_all([ciudad, categoria, talla, color])
    db.flush()
    sucursal = Sucursal(ciudad_id=ciudad.id, codigo=f"S-{sufijo}", nombre=f"Sucursal {sufijo}", direccion="Calle 1")
    producto = Producto(
        codigo=f"P-{sufijo}", nombre=f"Producto {sufijo}", categoria_id=categoria.id, precio_base=Decimal("100.00")
    )
    db.add_all([sucursal, producto])
    db.flush()
    variante = ProductoVariante(producto_id=producto.id, talla_id=talla.id, color_id=color.id, sku=f"SKU-{sufijo}")
    db.add(variante)
    db.flush()
    db.add(
        Stock(
            variante_id=variante.id,
            sucursal_id=sucursal.id,
            cantidad_fisica=10,
            cantidad_reservada=0,
            costo_promedio=Decimal("10.0000"),
        )
    )
    estado = db.scalar(select(EstadoVenta).where(EstadoVenta.codigo == "pagada"))
    venta = Venta(
        codigo=f"V-{sufijo}",
        canal="digital",
        sucursal_id=sucursal.id,
        estado_id=estado.id,
        subtotal=Decimal("100.00") * cantidad,
        total=Decimal("100.00") * cantidad,
    )
    db.add(venta)
    db.flush()
    db.add(
        VentaDetalle(
            venta_id=venta.id,
            variante_id=variante.id,
            cantidad=cantidad,
            precio_unitario=Decimal("100.00"),
            costo_unitario=Decimal("10.0000"),
            subtotal=Decimal("100.00") * cantidad,
        )
    )
    db.commit()
    return {"venta": f"V-{sufijo}", "producto": f"Producto {sufijo}", "sucursal": f"Sucursal {sufijo}"}


def _dos_empresas_con_venta(db) -> tuple[dict, dict]:
    """Empresa 'fashionstore' (fijada en la sesión) y 'tienda-b', cada una con
    una venta. Devuelve ids y datos de cada una."""
    id_a = db.scalar(select(Empresa.id).where(Empresa.codigo == "fashionstore"))
    # Ids antes de cambiar de empresa: fijar_empresa vacía el mapa de identidad.
    id_b = crear_empresa(db, "tienda-b", plan="basico").id
    datos_a = _sembrar_venta(db, id_a, "A", cantidad=2)
    datos_b = _sembrar_venta(db, id_b, "B", cantidad=3)
    fijar_empresa(db, id_a)
    return {"empresa_id": id_a, **datos_a}, {"empresa_id": id_b, **datos_b}


def test_vistas_v2_exponen_empresa_id_al_final(db_session):
    _crear_vistas_v2(db_session)
    for vista in ("vw_ventas_detalle", "vw_inventario_consolidado"):
        columnas = list(db_session.execute(text(f"SELECT * FROM {vista}")).keys())
        assert columnas[-1] == "empresa_id", f"{vista} debe traer empresa_id al final: {columnas}"
        assert columnas.count("empresa_id") == 1


def test_vistas_se_filtran_por_empresa(db_session):
    _crear_vistas_v2(db_session)
    a, b = _dos_empresas_con_venta(db_session)

    for datos, otro in ((a, b), (b, a)):
        ventas = db_session.execute(
            text("SELECT codigo, producto, sucursal, empresa_id FROM vw_ventas_detalle WHERE empresa_id = :e"),
            {"e": datos["empresa_id"]},
        ).mappings().all()
        assert [fila["codigo"] for fila in ventas] == [datos["venta"]]
        assert ventas[0]["producto"] == datos["producto"]
        assert ventas[0]["empresa_id"] == datos["empresa_id"]
        assert otro["venta"] not in {fila["codigo"] for fila in ventas}

        inventario = db_session.execute(
            text("SELECT sucursal, cantidad_disponible, empresa_id FROM vw_inventario_consolidado WHERE empresa_id = :e"),
            {"e": datos["empresa_id"]},
        ).mappings().all()
        assert [fila["sucursal"] for fila in inventario] == [datos["sucursal"]]
        assert inventario[0]["cantidad_disponible"] == 10

    # Sin filtro aparecen las dos empresas (el filtrado de lecturas es de E02).
    todas = db_session.execute(text("SELECT DISTINCT empresa_id FROM vw_ventas_detalle")).scalars().all()
    assert sorted(todas) == sorted([a["empresa_id"], b["empresa_id"]])


def test_sql_embebido_en_la_migracion_es_igual_a_la_constante_v2():
    archivos = list(MIGRACIONES.glob("*_multitenant_empresa_plan_suscripcion.py"))
    assert len(archivos) == 1, "Debe existir exactamente una migración multitenant"
    contenido = archivos[0].read_text(encoding="utf-8").replace("\r\n", "\n")
    for constante in (VW_VENTAS_DETALLE_V2_SQL, VW_INVENTARIO_CONSOLIDADO_V2_SQL):
        assert constante.replace("\r\n", "\n") in contenido, (
            "El SQL V2 embebido en la migración se desvió de la constante del repositorio"
        )
    # Las constantes V1 siguen congeladas: sin empresa_id.
    assert "empresa_id" not in comercial_repository.VW_VENTAS_DETALLE_SQL
    assert "empresa_id" not in catalogo_repository.VW_INVENTARIO_CONSOLIDADO_SQL


def test_schemas_toleran_la_columna_extra_empresa_id(db_session):
    _crear_vistas_v2(db_session)
    a, _b = _dos_empresas_con_venta(db_session)

    hoy = dt.date.today()
    filas_ventas = comercial_repository.detalle(db_session, hoy - dt.timedelta(days=1), hoy + dt.timedelta(days=1))
    assert filas_ventas, "las ventas sembradas deben aparecer en el rango"
    assert all("empresa_id" in fila for fila in filas_ventas)
    for fila in filas_ventas:
        parseada = FilaVentasDetalle(**fila)
        assert not hasattr(parseada, "empresa_id")

    for fila in catalogo_repository.consolidado(db_session) + catalogo_repository.alertas(db_session):
        assert "empresa_id" in fila
        ConsolidadoRespuesta(**fila)
    valuaciones = catalogo_repository.valuacion(db_session)
    assert valuaciones
    for fila in valuaciones:
        ValuacionRespuesta(**fila)

    assert db_session.info[CLAVE_EMPRESA] == a["empresa_id"]
