"""E08: rendimiento y paridad del paquete de descarga offline. (1) Una página cuesta una cantidad FIJA de
consultas SQL, no una por producto, variante o cliente (nada de N+1); (2) el descuento de cada variante
del paquete es EXACTAMENTE el que calcularía el servidor al vender (`calcular_linea`), con las tres clases
de promoción (producto, categoría y temporada), porcentaje y monto, y con las que no aplican.

Una empresa Profesional con una sesión nueva por petición (como en producción); los datos masivos se
crean directo con la sesión ORM para que la prueba sea rápida."""

import datetime as dt
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from app.catalogo.models import Producto, ProductoVariante, Stock
from app.comercial.politicas import calcular_linea
from app.core.tenant import en_empresa
from app.core.tiempo import hoy_utc
from app.plataforma.models import Cliente, Usuario
from tests.sincronizacion.ayudas import API, construir_escenario
from tests.sincronizacion.test_paquete_seguridad import _crear_empresa_profesional

TALLAS_EXTRA = ("L-r", "XL-r")


# ---- Ayudas ------------------------------------------------------------------------------------


@contextmanager
def contar_consultas(db_session):
    """Las sentencias SQL que llegan a la base mientras dura el bloque (todas las sesiones del motor
    de pruebas: la de la petición incluida). Se activa justo antes de la petición y se quita después."""
    motor = db_session.get_bind()
    sentencias: list[str] = []

    def antes(_conexion, _cursor, sentencia, _parametros, _contexto, _muchas):
        sentencias.append(sentencia)

    event.listen(motor, "before_cursor_execute", antes)
    try:
        yield sentencias
    finally:
        event.remove(motor, "before_cursor_execute", antes)


def consultas_de(client, db_session, ruta: str, headers: dict, **params) -> tuple[dict, int]:
    """(JSON, número de consultas SQL) de un GET. Antes de medir se hace una petición de calentamiento
    idéntica: así no cuenta lo que se carga una sola vez por proceso."""
    calentamiento = client.get(f"{API}{ruta}", params=params, headers=headers)
    assert calentamiento.status_code == 200, calentamiento.text
    db_session.expire_all()
    with contar_consultas(db_session) as sentencias:
        respuesta = client.get(f"{API}{ruta}", params=params, headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    # Una cota inferior evita una prueba verde por un contador que no está contando.
    assert len(sentencias) >= 3, sentencias
    return respuesta.json(), len(sentencias)


def _ids_base(db, empresa_id: int, producto_id: int) -> SimpleNamespace:
    """categoria, color y tallas del escenario, y dos tallas más para tener 3 variantes por producto."""
    from app.catalogo.models import Talla

    with en_empresa(db, empresa_id):
        producto = db.get(Producto, producto_id)
        variantes = list(db.scalars(select(ProductoVariante).where(ProductoVariante.producto_id == producto_id)))
        tallas = [v.talla_id for v in sorted(variantes, key=lambda v: v.id)]
        for orden, codigo in enumerate(TALLAS_EXTRA, 10):
            talla = Talla(codigo=codigo, orden=orden)
            db.add(talla)
            db.flush()
            tallas.append(talla.id)
        db.commit()
        return SimpleNamespace(categoria_id=producto.categoria_id, color_id=variantes[0].color_id, tallas=tallas)


def crear_productos(db, empresa_id: int, base, cantidad: int, *, prefijo: str, sucursal_id: int | None = None) -> list[int]:
    """`cantidad` productos activos de 3 variantes cada uno (si hay `sucursal_id`, cada variante con
    stock en ella). Devuelve los ids de las variantes."""
    variantes_ids: list[int] = []
    with en_empresa(db, empresa_id):
        productos = [
            Producto(
                codigo=f"{prefijo}-{n}", nombre=f"Producto {prefijo} {n}", categoria_id=base.categoria_id,
                genero="hombre", precio_base=Decimal("100.00"),
            )
            for n in range(cantidad)
        ]
        db.add_all(productos)
        db.flush()
        variantes = [
            ProductoVariante(
                producto_id=producto.id, talla_id=talla_id, color_id=base.color_id, sku=f"{producto.codigo}-{i}",
                codigo_barras=f"{prefijo}{n:05d}{i}",
            )
            for n, producto in enumerate(productos)
            for i, talla_id in enumerate(base.tallas[:3])
        ]
        db.add_all(variantes)
        db.flush()
        if sucursal_id is not None:
            db.add_all(
                Stock(variante_id=v.id, sucursal_id=sucursal_id, cantidad_fisica=5, cantidad_reservada=1)
                for v in variantes
            )
        variantes_ids = [v.id for v in variantes]
        db.commit()
    db.expire_all()
    return variantes_ids


def crear_clientes(db, empresa_id: int, cantidad: int, *, prefijo: str) -> None:
    with en_empresa(db, empresa_id):
        usuarios = [
            Usuario(nombre=f"Nombre{n}", apellido=f"Apellido{n}", email=f"{prefijo}{n}@example.com", password_hash="x", telefono="7000000")
            for n in range(cantidad)
        ]
        db.add_all(usuarios)
        db.flush()
        db.add_all(Cliente(usuario_id=u.id, ci_nit=f"{prefijo}{n:06d}") for n, u in enumerate(usuarios))
        db.commit()
    db.expire_all()


@pytest.fixture()
def mundo(client_por_peticion, db_session):
    """Una empresa Profesional con su escenario (sucursal, cajero, un producto de 2 variantes, un cliente)."""
    empresa = _crear_empresa_profesional(db_session, "tienda-r")
    escenario = construir_escenario(client_por_peticion, empresa.headers, db_session, sufijo="-r", codigo_empresa="tienda-r")
    base = _ids_base(db_session, empresa.id, escenario.producto_id)
    return SimpleNamespace(client=client_por_peticion, db=db_session, empresa=empresa, e=escenario, base=base)


# ---- 1 y 2. El número de consultas no depende de cuántos productos hay ----------------------------------


def test_una_pagina_de_200_productos_cuesta_pocas_consultas(mundo):
    crear_productos(mundo.db, mundo.empresa.id, mundo.base, 200, prefijo="R")

    paquete, consultas = consultas_de(mundo.client, mundo.db, "/paquete/catalogo", mundo.e.cajero, limite=200)

    assert len(paquete["items"]) == 200
    # 3 variantes por producto, salvo el del escenario (2): sin ninguna variante perdida en la página.
    assert sum(len(p["variantes"]) for p in paquete["items"]) == 2 + 199 * 3
    assert paquete["siguiente_desde_id"] is not None and paquete["total"] == 201
    assert consultas <= 20, f"{consultas} consultas para 200 productos (¿N+1?)"


def test_las_consultas_del_catalogo_son_las_mismas_con_10_y_con_100_productos(mundo):
    crear_productos(mundo.db, mundo.empresa.id, mundo.base, 120, prefijo="R")

    chica, consultas_chica = consultas_de(mundo.client, mundo.db, "/paquete/catalogo", mundo.e.cajero, limite=10)
    grande, consultas_grande = consultas_de(mundo.client, mundo.db, "/paquete/catalogo", mundo.e.cajero, limite=100)

    assert len(chica["items"]) == 10 and len(grande["items"]) == 100
    assert chica["siguiente_desde_id"] is not None and grande["siguiente_desde_id"] is not None  # ninguna es la última
    assert consultas_chica == consultas_grande, f"10 productos: {consultas_chica}, 100 productos: {consultas_grande}"


def test_las_consultas_del_stock_son_las_mismas_con_10_y_con_200_variantes(mundo):
    # 70 productos x 3 variantes = 210 filas de stock en la sucursal, más las 2 del escenario.
    crear_productos(mundo.db, mundo.empresa.id, mundo.base, 70, prefijo="S", sucursal_id=mundo.e.sucursal_id)
    sucursal = mundo.e.sucursal_id

    chica, consultas_chica = consultas_de(
        mundo.client, mundo.db, "/paquete/stock", mundo.e.cajero, sucursal_id=sucursal, limite=10
    )
    grande, consultas_grande = consultas_de(
        mundo.client, mundo.db, "/paquete/stock", mundo.e.cajero, sucursal_id=sucursal, limite=200
    )

    assert len(chica["items"]) == 10 and len(grande["items"]) == 200
    assert {i["cantidad_disponible"] for i in grande["items"]} <= {4, 10, 3}  # 5 - 1 reservada; o las del escenario
    assert chica["siguiente_desde_variante_id"] is not None and grande["siguiente_desde_variante_id"] is not None
    assert consultas_chica == consultas_grande, f"10 variantes: {consultas_chica}, 200 variantes: {consultas_grande}"
    assert consultas_grande <= 15  # las de autenticación (~8) más el stock


def test_las_consultas_de_clientes_son_las_mismas_con_10_y_con_100_clientes(mundo):
    crear_clientes(mundo.db, mundo.empresa.id, 110, prefijo="cli")

    chica, consultas_chica = consultas_de(mundo.client, mundo.db, "/paquete/clientes", mundo.e.cajero, limite=10)
    grande, consultas_grande = consultas_de(mundo.client, mundo.db, "/paquete/clientes", mundo.e.cajero, limite=100)

    assert len(chica["items"]) == 10 and len(grande["items"]) == 100
    assert chica["total"] == grande["total"] == 111
    assert consultas_chica == consultas_grande, f"10 clientes: {consultas_chica}, 100 clientes: {consultas_grande}"
    assert consultas_grande <= 15  # las de autenticación (~8) más el total y la página


def test_el_manifiesto_tampoco_crece_con_las_promociones(mundo):
    """Las promociones y sus alcances se cargan por lote, no una consulta por promoción."""
    client, db = mundo.client, mundo.db
    hoy = hoy_utc()

    def crear_promociones(desde: int, hasta: int) -> None:
        for n in range(desde, hasta):
            creada = client.post(
                "/api/v1/promociones",
                json={
                    "nombre": f"Oferta {n}", "tipo": "monto", "valor": "5",
                    "fecha_inicio": hoy.isoformat(), "fecha_fin": (hoy + dt.timedelta(days=3)).isoformat(),
                    "alcances": [{"producto_id": mundo.e.producto_id}, {"categoria_id": mundo.base.categoria_id}],
                },
                headers=mundo.empresa.headers,
            )
            assert creada.status_code == 201, creada.text

    # (Con 0 promociones la carga de alcances ni se emite; se compara 1 contra 8.)
    crear_promociones(0, 1)
    uno, con_una = consultas_de(client, db, "/paquete", mundo.e.cajero)
    crear_promociones(1, 8)
    ocho, con_ocho = consultas_de(client, db, "/paquete", mundo.e.cajero)

    assert len(uno["promociones_vigentes"]) == 1 and len(ocho["promociones_vigentes"]) == 8
    assert sum(len(p["alcances"]) for p in ocho["promociones_vigentes"]) == 16
    assert con_una == con_ocho, f"1 promoción: {con_una}, 8 promociones: {con_ocho}"
    assert con_ocho <= 25


# ---- 4. Paridad con el cálculo de venta ----------------------------------------------------------------


def _post(client, ruta: str, cuerpo: dict, headers: dict) -> dict:
    respuesta = client.post(f"/api/v1/{ruta}", json=cuerpo, headers=headers)
    assert respuesta.status_code in (200, 201), f"{ruta}: {respuesta.status_code} {respuesta.text}"
    return respuesta.json()


def _promocion(client, headers, nombre, tipo, valor, alcance, *, inicio=-1, fin=30) -> dict:
    hoy = hoy_utc()
    return _post(
        client,
        "promociones",
        {
            "nombre": nombre, "tipo": tipo, "valor": valor,
            "fecha_inicio": (hoy + dt.timedelta(days=inicio)).isoformat(),
            "fecha_fin": (hoy + dt.timedelta(days=fin)).isoformat(),
            "alcances": [alcance],
        },
        headers,
    )


def _producto_con_variantes(db, empresa_id, base, *, codigo, categoria_id, precio_base, precios) -> list[ProductoVariante]:
    """Un producto con una variante por cada precio propio de `precios` (None = hereda el del producto)."""
    with en_empresa(db, empresa_id):
        producto = Producto(
            codigo=codigo, nombre=f"Producto {codigo}", categoria_id=categoria_id, genero="hombre",
            precio_base=Decimal(precio_base),
        )
        db.add(producto)
        db.flush()
        variantes = [
            ProductoVariante(
                producto_id=producto.id, talla_id=base.tallas[i], color_id=base.color_id, sku=f"{codigo}-{'AB'[i]}",
                precio=None if precio is None else Decimal(precio),
            )
            for i, precio in enumerate(precios)
        ]
        db.add_all(variantes)
        db.commit()
        return producto.id


def test_el_descuento_del_paquete_es_el_mismo_que_calcula_la_venta_para_cada_variante(mundo):
    client, db, h = mundo.client, mundo.db, mundo.empresa.headers
    e, empresa_id = mundo.e, mundo.empresa.id
    from app.catalogo.models import Categoria

    with en_empresa(db, empresa_id):
        c2, c3, c4 = (Categoria(nombre=f"Categoria {n}") for n in (2, 3, 4))
        db.add_all([c2, c3, c4])
        db.commit()
        c1_id, c2_id, c3_id, c4_id = mundo.base.categoria_id, c2.id, c3.id, c4.id
    t1 = _post(client, "temporadas", {"nombre": "Verano", "anio": 2026}, h)["id"]
    t2 = _post(client, "temporadas", {"nombre": "Invierno", "anio": 2026}, h)["id"]

    # (codigo, categoria, precio del producto, precios propios de las variantes, temporada)
    p2 = _producto_con_variantes(db, empresa_id, mundo.base, codigo="P2", categoria_id=c2_id, precio_base="200.00", precios=(None, "80.00"))
    p3 = _producto_con_variantes(db, empresa_id, mundo.base, codigo="P3", categoria_id=c3_id, precio_base="50.00", precios=(None, "20.00"))
    p4 = _producto_con_variantes(db, empresa_id, mundo.base, codigo="P4", categoria_id=c3_id, precio_base="120.00", precios=(None,))
    p5 = _producto_con_variantes(db, empresa_id, mundo.base, codigo="P5", categoria_id=c2_id, precio_base="100.00", precios=(None, "40.00"))
    p6 = _producto_con_variantes(db, empresa_id, mundo.base, codigo="P6", categoria_id=c4_id, precio_base="99.99", precios=(None, "19.95"))
    for producto_id, temporada_id in ((p3, t1), (p5, t1), (p4, t2)):
        actualizado = client.put(f"/api/v1/productos/{producto_id}", json={"temporada_id": temporada_id}, headers=h)
        assert actualizado.status_code == 200, actualizado.text

    # Las que APLICAN
    _promocion(client, h, "P1 15%", "porcentaje", "15", {"producto_id": e.producto_id})
    _promocion(client, h, "Cat2 30 Bs", "monto", "30", {"categoria_id": c2_id})
    _promocion(client, h, "Temporada1 60 Bs (supera el precio)", "monto", "60", {"temporada_id": t1})
    _promocion(client, h, "P5 70%", "porcentaje", "70", {"producto_id": p5})
    _promocion(client, h, "Cat4 33.33% solo hoy", "porcentaje", "33.33", {"categoria_id": c4_id}, inicio=0, fin=0)
    # Las que NO aplican: vencida (categoría y temporada), futura, desactivada
    _promocion(client, h, "Cat3 vencida", "porcentaje", "50", {"categoria_id": c3_id}, inicio=-10, fin=-1)
    _promocion(client, h, "Temporada2 vencida", "monto", "40", {"temporada_id": t2}, inicio=-10, fin=-1)
    _promocion(client, h, "P4 futura", "porcentaje", "25", {"producto_id": p4}, inicio=1, fin=10)
    apagada = _promocion(client, h, "P4 apagada", "porcentaje", "90", {"producto_id": p4})
    desactivada = client.put(f"/api/v1/promociones/{apagada['id']}", json={"activo": False}, headers=h)
    assert desactivada.status_code == 200, desactivada.text

    # Todas las páginas del catálogo (aquí caben en una).
    paquete = client.get(f"{API}/paquete/catalogo", params={"limite": 500}, headers=e.cajero)
    assert paquete.status_code == 200, paquete.text
    variantes = [v for p in paquete.json()["items"] for v in p["variantes"]]
    assert len(variantes) == 2 + 2 + 2 + 1 + 2 + 2  # P1..P6

    esperado = {
        e.v1: ("100.00", "15.00"), e.v2: ("100.00", "15.00"),  # producto, 15 %
    }
    por_sku = {
        "P2-A": ("200.00", "30.00"), "P2-B": ("80.00", "30.00"),  # categoría, monto
        "P3-A": ("50.00", "50.00"), "P3-B": ("20.00", "20.00"),  # temporada, el monto supera el precio: tope = precio
        "P4-A": ("120.00", "0.00"),  # vencida, futura y desactivada: ninguna aplica
        "P5-A": ("100.00", "70.00"), "P5-B": ("40.00", "40.00"),  # la mayor de producto 70 %, categoría y temporada
        "P6-A": ("99.99", "33.33"), "P6-B": ("19.95", "6.65"),  # redondeo a 2 decimales, vigente solo hoy
    }
    esperado.update({v["id"]: por_sku[v["sku"]] for v in variantes if v["sku"] in por_sku})
    assert set(esperado) == {v["id"] for v in variantes}

    hoy = hoy_utc()
    with en_empresa(db, empresa_id):
        for variante in variantes:
            fila = db.get(ProductoVariante, variante["id"])
            precio, descuento, _ = calcular_linea(db, fila, 1, hoy)
            # Misma cifra que el servidor al vender...
            assert Decimal(variante["precio"]) == precio, variante
            assert Decimal(variante["descuento_unitario"]) == descuento, variante
            # ...y con las cifras que se calcularon a mano (por si ambos se equivocaran igual).
            assert (variante["precio"], variante["descuento_unitario"]) == esperado[variante["id"]], variante
    # El escenario ejercita de verdad las dos ramas: hay variantes con y sin descuento.
    descuentos = {Decimal(v["descuento_unitario"]) for v in variantes}
    assert Decimal("0.00") in descuentos and len(descuentos) >= 6
