"""Consultas agrupadas del catálogo (N+1 y subconsulta, puntos 5 y 6 de 04_analisis):
disponibilidad por variante en una sola consulta (CU-06), `solo_disponibles`
como subconsulta (sin traer los variante_id a Python), `listar_items_por_variantes`
con las imágenes precargadas y las tallas de la recomendación en un solo SELECT."""

import pytest
from sqlalchemy import event

from app.catalogo.models import ProductoImagen
from app.catalogo.politicas import listar_items_por_variantes, obtener_tallas
from app.catalogo.repository import StockRepository
from app.core import storage
from app.core.exceptions import NoEncontradoError


def _crear_producto(client, admin_headers, categoria_id, tallas_ids, colores_ids, codigo):
    return client.post(
        "/api/v1/productos",
        json={
            "codigo": codigo,
            "nombre": f"Camisa {codigo}",
            "categoria_id": categoria_id,
            "precio_base": "150.00",
            "tallas_ids": tallas_ids,
            "colores_ids": colores_ids,
        },
        headers=admin_headers,
    ).json()


def _variantes(client, admin_headers, producto_id):
    return client.get(f"/api/v1/productos/{producto_id}/variantes", headers=admin_headers).json()


def _sucursal(client, admin_headers, codigo):
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": f"Ciudad {codigo}", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    return client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": codigo, "nombre": codigo, "direccion": "Km 5"},
        headers=admin_headers,
    ).json()


def _stock(client, admin_headers, variante_id, sucursal_id, cantidad):
    respuesta = client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": cantidad,
            "costo_unitario": "10.00",
        },
        headers=admin_headers,
    )
    assert respuesta.status_code == 201


class _Sentencias:
    """Registra las sentencias SQL que ejecuta el engine mientras está activo."""

    def __init__(self, db_session):
        self._engine = db_session.get_bind()
        self.sql: list[str] = []

    def _registrar(self, conn, cursor, statement, parameters, context, executemany):
        self.sql.append(statement)

    def __enter__(self):
        event.listen(self._engine, "before_cursor_execute", self._registrar)
        return self

    def __exit__(self, *exc):
        event.remove(self._engine, "before_cursor_execute", self._registrar)

    def selects(self) -> list[str]:
        return [s for s in self.sql if s.lstrip().upper().startswith("SELECT")]


@pytest.fixture()
def escenario(client, admin_headers, db_session):
    categoria = client.post("/api/v1/categorias", json={"nombre": "Camisas"}, headers=admin_headers).json()
    tallas = [
        client.post("/api/v1/tallas", json={"codigo": c, "orden": i}, headers=admin_headers).json()
        for i, c in enumerate(["S", "M", "L"], start=1)
    ]
    colores = [
        client.post("/api/v1/colores", json={"nombre": n}, headers=admin_headers).json()
        for n in ["Rojo", "Azul"]
    ]
    return {"categoria": categoria, "tallas": tallas, "colores": colores}


# ---- Disponibilidad agrupada (StockRepository.disponible_por_variante) -----------------


def test_disponible_por_variante_suma_sucursales_y_respeta_sucursal_id(client, admin_headers, db_session, escenario):
    producto = _crear_producto(
        client,
        admin_headers,
        escenario["categoria"]["id"],
        [t["id"] for t in escenario["tallas"][:2]],
        [escenario["colores"][0]["id"]],
        "AGR-1",
    )
    con_stock, sin_stock = _variantes(client, admin_headers, producto["id"])
    suc_a = _sucursal(client, admin_headers, "SUC-AGR-A")
    suc_b = _sucursal(client, admin_headers, "SUC-AGR-B")
    _stock(client, admin_headers, con_stock["id"], suc_a["id"], 7)
    _stock(client, admin_headers, con_stock["id"], suc_b["id"], 5)

    repo = StockRepository()
    ids = [con_stock["id"], sin_stock["id"]]

    assert repo.disponible_por_variante(db_session, ids) == {con_stock["id"]: 12}
    assert repo.disponible_por_variante(db_session, ids, suc_a["id"]) == {con_stock["id"]: 7}
    assert repo.disponible_por_variante(db_session, ids, suc_b["id"]) == {con_stock["id"]: 5}
    assert repo.disponible_por_variante(db_session, []) == {}


def test_disponible_por_variante_resta_lo_reservado(client, admin_headers, db_session, escenario):
    from app.catalogo.politicas import reservar_stock

    producto = _crear_producto(
        client, admin_headers, escenario["categoria"]["id"], [escenario["tallas"][0]["id"]],
        [escenario["colores"][0]["id"]], "AGR-RES",
    )
    variante = _variantes(client, admin_headers, producto["id"])[0]
    sucursal = _sucursal(client, admin_headers, "SUC-AGR-R")
    _stock(client, admin_headers, variante["id"], sucursal["id"], 10)
    reservar_stock(db_session, variante["id"], sucursal["id"], 4)
    db_session.commit()

    assert StockRepository().disponible_por_variante(db_session, [variante["id"]]) == {variante["id"]: 6}


def test_detalle_publico_cantidad_disponible_igual_que_antes(client, admin_headers, db_session, escenario):
    producto = _crear_producto(
        client,
        admin_headers,
        escenario["categoria"]["id"],
        [t["id"] for t in escenario["tallas"][:2]],
        [escenario["colores"][0]["id"]],
        "AGR-DET",
    )
    con_stock, sin_stock = _variantes(client, admin_headers, producto["id"])
    suc_a = _sucursal(client, admin_headers, "SUC-DET-A")
    suc_b = _sucursal(client, admin_headers, "SUC-DET-B")
    _stock(client, admin_headers, con_stock["id"], suc_a["id"], 3)
    _stock(client, admin_headers, con_stock["id"], suc_b["id"], 4)

    total = client.get(f"/api/v1/catalogo/{producto['id']}").json()["variantes"]
    solo_a = client.get(f"/api/v1/catalogo/{producto['id']}?sucursal_id={suc_a['id']}").json()["variantes"]

    assert {v["id"]: v["cantidad_disponible"] for v in total} == {con_stock["id"]: 7, sin_stock["id"]: 0}
    assert {v["id"]: v["cantidad_disponible"] for v in solo_a} == {con_stock["id"]: 3, sin_stock["id"]: 0}
    assert all(v["precio_efectivo"] == "150.00" for v in total)


def test_detalle_publico_no_hace_una_consulta_de_stock_por_variante(client, admin_headers, db_session, escenario):
    una = _crear_producto(
        client, admin_headers, escenario["categoria"]["id"], [escenario["tallas"][0]["id"]],
        [escenario["colores"][0]["id"]], "AGR-N1",
    )
    muchas = _crear_producto(
        client,
        admin_headers,
        escenario["categoria"]["id"],
        [t["id"] for t in escenario["tallas"]],
        [c["id"] for c in escenario["colores"]],
        "AGR-N6",
    )
    assert len(_variantes(client, admin_headers, muchas["id"])) == 6

    with _Sentencias(db_session) as con_una:
        assert client.get(f"/api/v1/catalogo/{una['id']}").status_code == 200
    with _Sentencias(db_session) as con_muchas:
        assert client.get(f"/api/v1/catalogo/{muchas['id']}").status_code == 200

    assert len(con_muchas.selects()) == len(con_una.selects())
    assert sum("FROM stock" in s for s in con_muchas.selects()) == 1


# ---- solo_disponibles como subconsulta ---------------------------------------------------


def test_solo_disponibles_usa_subconsulta_sin_traer_ids_a_python(client, admin_headers, db_session, escenario):
    con_stock = _crear_producto(
        client, admin_headers, escenario["categoria"]["id"], [escenario["tallas"][0]["id"]],
        [escenario["colores"][0]["id"]], "SUB-CON",
    )
    _crear_producto(
        client, admin_headers, escenario["categoria"]["id"], [escenario["tallas"][0]["id"]],
        [escenario["colores"][0]["id"]], "SUB-SIN",
    )
    variante = _variantes(client, admin_headers, con_stock["id"])[0]
    sucursal = _sucursal(client, admin_headers, "SUC-SUB")
    _stock(client, admin_headers, variante["id"], sucursal["id"], 5)

    with _Sentencias(db_session) as sentencias:
        resultados = client.get("/api/v1/catalogo/buscar?solo_disponibles=true").json()

    assert {p["codigo"] for p in resultados} == {"SUB-CON"}
    # Ninguna consulta aparte por los variante_id con stock: el stock entra
    # como subconsulta de la consulta de productos.
    consultas_de_stock_sueltas = [s for s in sentencias.selects() if s.lstrip().upper().startswith("SELECT DISTINCT STOCK.VARIANTE_ID")]
    assert consultas_de_stock_sueltas == []
    consulta_productos = [s for s in sentencias.selects() if "FROM producto" in s]
    assert len(consulta_productos) >= 1
    assert any("stock" in s and "producto_variante" in s for s in consulta_productos)


def test_solo_disponibles_sin_ningun_stock_devuelve_lista_vacia(client, admin_headers, escenario):
    _crear_producto(
        client, admin_headers, escenario["categoria"]["id"], [escenario["tallas"][0]["id"]],
        [escenario["colores"][0]["id"]], "SUB-NADA",
    )

    assert client.get("/api/v1/catalogo/buscar?solo_disponibles=true").json() == []


def test_solo_disponibles_combina_con_talla_y_sucursal(client, admin_headers, escenario):
    producto = _crear_producto(
        client,
        admin_headers,
        escenario["categoria"]["id"],
        [t["id"] for t in escenario["tallas"][:2]],
        [escenario["colores"][0]["id"]],
        "SUB-TALLA",
    )
    variante_s, variante_m = _variantes(client, admin_headers, producto["id"])
    sucursal = _sucursal(client, admin_headers, "SUC-SUB-T")
    _stock(client, admin_headers, variante_s["id"], sucursal["id"], 5)

    talla_con_stock = variante_s["talla_id"]
    talla_sin_stock = variante_m["talla_id"]
    base = f"/api/v1/catalogo/buscar?solo_disponibles=true&sucursal_id={sucursal['id']}"

    con = client.get(f"{base}&talla_id={talla_con_stock}").json()
    sin = client.get(f"{base}&talla_id={talla_sin_stock}").json()

    assert [p["codigo"] for p in con] == ["SUB-TALLA"]
    assert sin == []


# ---- listar_items_por_variantes: imágenes precargadas -------------------------------------


def test_listar_items_por_variantes_precarga_las_imagenes(client, admin_headers, db_session, escenario, monkeypatch):
    monkeypatch.setattr(storage, "url_catalogo", lambda public_id, ancho=None, alto=None: f"https://cdn.test/{public_id}")
    variante_ids = []
    for i in range(4):
        producto = _crear_producto(
            client, admin_headers, escenario["categoria"]["id"], [escenario["tallas"][0]["id"]],
            [escenario["colores"][0]["id"]], f"IMG-{i}",
        )
        variante_ids.append(_variantes(client, admin_headers, producto["id"])[0]["id"])
        db_session.add(ProductoImagen(producto_id=producto["id"], url=f"catalogo/img-{i}", es_principal=True, orden=0))
        db_session.commit()  # antes del siguiente request: el get_db de pruebas hace rollback al terminar
    db_session.expire_all()

    with _Sentencias(db_session) as sentencias:
        items = listar_items_por_variantes(db_session, variante_ids)

    assert set(items) == set(variante_ids)
    assert all(item.imagen_principal is not None for item in items.values())
    # Una consulta de variantes+productos y una sola de imágenes (selectinload),
    # no una por producto.
    assert len(sentencias.selects()) == 2


# ---- obtener_tallas: varias tallas en una sola consulta -------------------------------------


def test_obtener_tallas_resuelve_todas_en_un_select(db_session, client, admin_headers, escenario):
    ids = [t["id"] for t in escenario["tallas"]]
    db_session.expire_all()

    with _Sentencias(db_session) as sentencias:
        tallas = obtener_tallas(db_session, ids + ids)  # repetidos no importan

    assert {i: t.codigo for i, t in tallas.items()} == {ids[0]: "S", ids[1]: "M", ids[2]: "L"}
    assert len(sentencias.selects()) == 1


def test_obtener_tallas_con_un_id_inexistente_lanza_404():
    # Sin tocar la base: el repositorio devuelve menos tallas de las pedidas.
    from app.catalogo import politicas

    class _RepoFalso:
        def listar_por_ids(self, db, ids):
            return {}

    original = politicas.talla_repo
    politicas.talla_repo = _RepoFalso()
    try:
        with pytest.raises(NoEncontradoError):
            politicas.obtener_tallas(None, [999])
    finally:
        politicas.talla_repo = original
