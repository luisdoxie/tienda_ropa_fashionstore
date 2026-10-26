"""E05, 4.6 (segunda mitad): reportes, vistas SQL y la guarda del SQL en texto. Solo lo que corre en SQLite.

- Los reportes de inventario y de reservas y las tres consultas de inventario devuelven totales y filas
  EXACTOS de la empresa del token: se comparan contra lo que hay en las tablas (`stock`, `reserva`)
  de esa empresa, no contra constantes, porque el universo es compartido y otras pruebas lo mueven.
- Con `sucursal_id` de la otra empresa: 404 (igual que una inexistente); `producto_id` ajeno: lista vacía.
- /ia/reporte-voz con el intérprete de Groq sustituido: dictar la sucursal de la otra empresa no la resuelve.
- Las vistas contienen las dos empresas con `empresa_id` correcto y las consultas del repositorio solo
  traen la de la sesión.
- Ninguna consulta en texto (`text(`) fuera de los sitios conocidos, y las que hay usan `condicion_empresa`.

/reportes/ventas, /reportes/dashboard y las consultas de ventas leen `vw_ventas_detalle`, que solo existe
en PostgreSQL (el universo de SQLite no la crea): quedan saltadas y las cubre tests/postgres/test_aislamiento_pg.py.
"""

import ast
import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.catalogo import repository as catalogo_repo
from app.catalogo.models import Stock
from app.comercial.models import EstadoReserva, Reserva
from app.core.tenant import fijar_empresa
from app.inteligencia.schemas import FiltrosReporteVoz

from .ayudas_tokens import API

MODULO_CU = "app.inteligencia.casos_uso.cu23_generar_reportes_con_ia"
RAIZ_APP = Path(__file__).resolve().parents[2] / "app"
CENTAVO = Decimal("0.01")


def _lado(mundo, lado):
    return (mundo.a, mundo.b) if lado == "A" else (mundo.b, mundo.a)


# --- lo esperado, calculado directo de las tablas de la empresa ----------------------------------------


def stock_de(mundo, empresa_id: int) -> list[dict]:
    t = Stock.__table__
    consulta = select(
        t.c.variante_id, t.c.sucursal_id, t.c.cantidad_fisica, t.c.cantidad_reservada, t.c.cantidad_disponible,
        t.c.stock_minimo, t.c.costo_promedio,
    ).where(t.c.empresa_id == empresa_id)
    with mundo.engine.connect() as conexion:
        return [dict(fila._mapping) for fila in conexion.execute(consulta)]


def valor_de(fila: dict) -> Decimal:
    return Decimal(str(fila["cantidad_fisica"])) * Decimal(str(fila["costo_promedio"]))


def reservas_de(mundo, empresa_id: int, desde: dt.date, hasta: dt.date) -> dict[str, int]:
    r, e = Reserva.__table__, EstadoReserva.__table__
    consulta = (
        select(e.c.codigo, r.c.id)
        .select_from(r.join(e, e.c.id == r.c.estado_id))
        .where(r.c.empresa_id == empresa_id, r.c.fecha_visita >= desde, r.c.fecha_visita <= hasta)
    )
    cuenta: dict[str, int] = {}
    with mundo.engine.connect() as conexion:
        for codigo, _ in conexion.execute(consulta):
            cuenta[codigo] = cuenta.get(codigo, 0) + 1
    return cuenta


def comprobar_consolidado(filas: list[dict], esperado: list[dict]):
    assert {(f["variante_id"], f["sucursal_id"]) for f in filas} == {(f["variante_id"], f["sucursal_id"]) for f in esperado}
    assert len(filas) == len(esperado)
    for campo in ("cantidad_fisica", "cantidad_reservada", "cantidad_disponible"):
        assert sum(f[campo] for f in filas) == sum(f[campo] for f in esperado), campo
    total = sum((Decimal(str(f["valor_inventario"])) for f in filas), Decimal(0))
    assert abs(total - sum((valor_de(f) for f in esperado), Decimal(0))) < CENTAVO


def comprobar_alertas(filas: list[dict], esperado: list[dict]):
    bajo_minimo = {(f["variante_id"], f["sucursal_id"]) for f in esperado if f["cantidad_disponible"] <= f["stock_minimo"]}
    assert {(f["variante_id"], f["sucursal_id"]) for f in filas} == bajo_minimo


def comprobar_valuacion(filas: list[dict], esperado: list[dict]):
    por_sucursal: dict[int, Decimal] = {}
    for f in esperado:
        por_sucursal[f["sucursal_id"]] = por_sucursal.get(f["sucursal_id"], Decimal(0)) + valor_de(f)
    assert {f["sucursal_id"] for f in filas} == set(por_sucursal)
    for fila in filas:
        assert abs(Decimal(str(fila["valor_total"])) - por_sucursal[fila["sucursal_id"]]) < CENTAVO, fila


# --- 1. inventario y reservas: totales y filas de la empresa del token -----------------------------------------

RUTAS_DE_INVENTARIO = ["/inventario/consolidado", "/inventario/alertas", "/inventario/valuacion", "/reportes/inventario"]


def _partes(ruta: str, cuerpo):
    """(consolidado, alertas, valuacion) de la respuesta; None si la ruta no lo trae."""
    if ruta == "/reportes/inventario":
        return cuerpo["consolidado"], cuerpo["alertas"], cuerpo["valuacion"]
    return (
        cuerpo if ruta.endswith("consolidado") else None,
        cuerpo if ruta.endswith("alertas") else None,
        cuerpo if ruta.endswith("valuacion") else None,
    )


def test_el_universo_tiene_existencias_distintas_en_cada_empresa(mundo):
    a, b = stock_de(mundo, mundo.a.id), stock_de(mundo, mundo.b.id)
    assert a and b
    assert sum(f["cantidad_fisica"] for f in a) != sum(f["cantidad_fisica"] for f in b) or sum(map(valor_de, a)) != sum(map(valor_de, b))
    assert {f["sucursal_id"] for f in a}.isdisjoint({f["sucursal_id"] for f in b})


@pytest.mark.parametrize("lado", ["A", "B"])
@pytest.mark.parametrize("ruta", RUTAS_DE_INVENTARIO)
def test_inventario_trae_totales_y_filas_solo_de_la_empresa_del_token(mundo, ruta, lado):
    propia, ajena = _lado(mundo, lado)
    esperado = stock_de(mundo, propia.id)
    assert esperado, "prueba mal armada: la empresa no tiene existencias"

    respuesta = mundo.client.get(f"{API}{ruta}", headers=propia.admin)
    assert respuesta.status_code == 200, respuesta.text[:300]
    assert ajena.m("") not in respuesta.text
    consolidado, alertas, valuacion = _partes(ruta, respuesta.json())
    if consolidado is not None:
        comprobar_consolidado(consolidado, esperado)
        assert all(f["sucursal_id"] in {e["sucursal_id"] for e in esperado} for f in consolidado)
        assert propia.m("") in respuesta.text
    if alertas is not None:
        comprobar_alertas(alertas, esperado)
    if valuacion is not None:
        comprobar_valuacion(valuacion, esperado)


@pytest.mark.parametrize("lado", ["A", "B"])
@pytest.mark.parametrize("ruta", RUTAS_DE_INVENTARIO + ["/reportes/reservas"])
def test_un_filtro_de_sucursal_de_la_otra_empresa_da_404_igual_que_uno_inexistente(mundo, ruta, lado):
    propia, ajena = _lado(mundo, lado)
    ajeno = mundo.client.get(f"{API}{ruta}", params={"sucursal_id": ajena.ids["sucursal"]}, headers=propia.admin)
    inexistente = mundo.client.get(f"{API}{ruta}", params={"sucursal_id": 999_999_999}, headers=propia.admin)
    assert ajeno.status_code == 404, f"{ruta}: {ajeno.status_code} {ajeno.text[:200]}"
    assert ajeno.status_code == inexistente.status_code and ajeno.json() == inexistente.json()
    assert ajena.m("") not in ajeno.text
    # Con la sucursal propia sí responde (evita un 404 de siempre).
    propio = mundo.client.get(f"{API}{ruta}", params={"sucursal_id": propia.ids["sucursal"]}, headers=propia.admin)
    assert propio.status_code == 200, f"{ruta}: {propio.status_code} {propio.text[:200]}"


@pytest.mark.parametrize("lado", ["A", "B"])
def test_un_producto_de_la_otra_empresa_no_trae_filas_en_el_consolidado(mundo, lado):
    propia, ajena = _lado(mundo, lado)
    respuesta = mundo.client.get(
        f"{API}/inventario/consolidado", params={"producto_id": ajena.ids["producto"]}, headers=propia.admin
    )
    assert respuesta.status_code == 200 and respuesta.json() == []


@pytest.mark.parametrize("lado", ["A", "B"])
def test_categoria_de_la_otra_empresa_no_cambia_ni_amplia_el_reporte_de_inventario(mundo, lado):
    """/reportes/inventario no filtra por categoría: el parámetro se ignora y el reporte sigue siendo el de la
    empresa del token, nunca el de la categoría ajena."""
    propia, ajena = _lado(mundo, lado)
    base = mundo.client.get(f"{API}/reportes/inventario", headers=propia.admin).json()
    con_filtro = mundo.client.get(
        f"{API}/reportes/inventario", params={"categoria_id": ajena.ids["categoria"]}, headers=propia.admin
    )
    assert con_filtro.status_code in (200, 404)
    if con_filtro.status_code == 200:
        assert con_filtro.json() == base
        assert ajena.m("") not in con_filtro.text


@pytest.mark.parametrize("lado", ["A", "B"])
def test_reporte_de_reservas_cuenta_solo_las_de_la_empresa(mundo, lado):
    propia, ajena = _lado(mundo, lado)
    desde, hasta = dt.date.today() - dt.timedelta(days=30), dt.date.today() + dt.timedelta(days=400)
    esperado = reservas_de(mundo, propia.id, desde, hasta)
    del_otro = reservas_de(mundo, ajena.id, desde, hasta)
    assert esperado and del_otro, "prueba mal armada: el universo trae reservas en las dos empresas"

    respuesta = mundo.client.get(
        f"{API}/reportes/reservas", params={"desde": desde.isoformat(), "hasta": hasta.isoformat()}, headers=propia.admin
    )
    assert respuesta.status_code == 200, respuesta.text[:300]
    cuerpo = respuesta.json()
    assert {f["codigo"]: f["cantidad"] for f in cuerpo["por_estado"]} == esperado
    assert 0 <= cuerpo["tasa_conversion"]


@pytest.mark.parametrize("ruta", ["/reportes/ventas", "/reportes/dashboard"])
def test_ventas_y_dashboard_traen_solo_cifras_de_la_empresa(mundo, ruta):
    pytest.skip(
        f"{ruta} lee la vista vw_ventas_detalle, que solo existe en PostgreSQL: "
        "cubierto en tests/postgres/test_aislamiento_pg.py"
    )


# --- 2. /ia/reporte-voz con el intérprete de Groq sustituido -----------------------------------------------------


class _InterpreteFalso:
    def __init__(self, filtros: FiltrosReporteVoz | None) -> None:
        self._filtros = filtros

    def parsear(self, texto: str) -> FiltrosReporteVoz | None:
        return self._filtros


@pytest.fixture()
def dictar(monkeypatch):
    """dictar(FiltrosReporteVoz(...)): Groq 'devuelve' esos filtros, sin red ni API key."""

    def _dictar(filtros: FiltrosReporteVoz | None) -> None:
        monkeypatch.setattr(f"{MODULO_CU}.obtener_parser_reporte_voz", lambda: _InterpreteFalso(filtros))

    return _dictar


def _preguntar(mundo, universo, texto="reporte de inventario"):
    return mundo.client.post(f"{API}/ia/reporte-voz", json={"texto": texto}, headers=universo.admin)


NOMBRES_AJENOS = [
    pytest.param(lambda b: b.m("sucursal"), id="nombre_exacto_de_b"),
    pytest.param(lambda b: b.m("sucursal").lower(), id="nombre_de_b_en_minusculas"),
    pytest.param(lambda b: b.m("sucursal-destino"), id="otra_sucursal_de_b"),
    pytest.param(lambda b: "sucursal inexistente", id="sucursal_inexistente"),
]


@pytest.mark.parametrize("nombre", NOMBRES_AJENOS)
def test_dictar_la_sucursal_de_b_desde_a_no_la_resuelve_y_el_reporte_es_de_a(mundo, dictar, nombre):
    a, b = mundo.a, mundo.b
    dictar(FiltrosReporteVoz(tipo_reporte="inventario", sucursal=nombre(b)))

    respuesta = _preguntar(mundo, a, f"reporte de inventario de la sucursal {nombre(b)}")

    assert respuesta.status_code == 200, respuesta.text[:300]
    cuerpo = respuesta.json()
    assert cuerpo["tipo_reporte"] == "inventario"
    # No resolvió ninguna sucursal: cae al comportamiento actual (sin filtro) pero sobre A.
    assert cuerpo["filtros_aplicados"]["sucursal_id"] is None
    assert b.m("") not in respuesta.text
    esperado = stock_de(mundo, a.id)
    comprobar_consolidado(cuerpo["resultado"]["consolidado"], esperado)
    comprobar_alertas(cuerpo["resultado"]["alertas"], esperado)
    comprobar_valuacion(cuerpo["resultado"]["valuacion"], esperado)


def test_dictar_la_sucursal_propia_si_la_resuelve(mundo, dictar):
    """Control del caso anterior: el mismo mecanismo con el nombre de una sucursal de A sí filtra."""
    a = mundo.a
    dictar(FiltrosReporteVoz(tipo_reporte="inventario", sucursal=a.m("sucursal")))

    cuerpo = _preguntar(mundo, a, "reporte de inventario").json()

    assert cuerpo["filtros_aplicados"]["sucursal_id"] == a.ids["sucursal"]
    propias = [f for f in stock_de(mundo, a.id) if f["sucursal_id"] == a.ids["sucursal"]]
    comprobar_consolidado(cuerpo["resultado"]["consolidado"], propias)
    assert f"en {a.m('sucursal')}" in cuerpo["respuesta"]


def test_dictar_una_sucursal_de_b_en_el_reporte_de_reservas_cuenta_solo_las_de_a(mundo, dictar):
    a, b = mundo.a, mundo.b
    desde, hasta = dt.date.today() - dt.timedelta(days=30), dt.date.today()
    dictar(FiltrosReporteVoz(tipo_reporte="reservas", sucursal=b.m("sucursal"), desde=desde, hasta=hasta))

    respuesta = _preguntar(mundo, a, "reservas de la sucursal de la otra tienda")

    assert respuesta.status_code == 200, respuesta.text[:300]
    cuerpo = respuesta.json()
    assert cuerpo["filtros_aplicados"]["sucursal_id"] is None
    assert {f["codigo"]: f["cantidad"] for f in cuerpo["resultado"]["por_estado"]} == reservas_de(mundo, a.id, desde, hasta)
    assert b.m("") not in respuesta.text


@pytest.mark.parametrize("tipo", ["ventas", "dashboard"])
def test_reporte_de_voz_de_ventas_y_dashboard_trae_solo_cifras_de_a(mundo, tipo):
    pytest.skip(
        f"el reporte '{tipo}' lee la vista vw_ventas_detalle, que solo existe en PostgreSQL: "
        "cubierto en tests/postgres/test_aislamiento_pg.py"
    )


def test_el_texto_dictado_con_nombres_de_b_no_aparece_ni_filtra_datos_de_b(mundo, dictar):
    """El texto que se pronuncia nunca se ejecuta ni se mezcla con datos: aunque nombre la sucursal y el
    producto de B, la respuesta y el reporte son de A."""
    a, b = mundo.a, mundo.b
    dictar(FiltrosReporteVoz(tipo_reporte="inventario"))
    respuesta = _preguntar(mundo, a, f"inventario de {b.m('sucursal')} y {b.m('producto')}")
    assert respuesta.status_code == 200
    assert b.m("") not in respuesta.text
    assert a.m("") in respuesta.text


# --- 3. las vistas y las consultas del repositorio ---------------------------------------------------------------


def test_la_vista_de_inventario_trae_las_dos_empresas_con_su_empresa_id(mundo):
    from sqlalchemy import text

    with mundo.engine.connect() as conexion:
        filas = conexion.execute(text("SELECT empresa_id, variante_id, sucursal_id FROM vw_inventario_consolidado")).all()
    por_empresa = {}
    for empresa_id, variante_id, sucursal_id in filas:
        por_empresa.setdefault(empresa_id, set()).add((variante_id, sucursal_id))
    assert {mundo.a.id, mundo.b.id} <= set(por_empresa)
    for empresa in (mundo.a, mundo.b):
        propio = {(f["variante_id"], f["sucursal_id"]) for f in stock_de(mundo, empresa.id)}
        assert por_empresa[empresa.id] == propio, "la vista asigna a la empresa filas que no son de su stock"
    assert por_empresa[mundo.a.id].isdisjoint(por_empresa[mundo.b.id])


FUNCIONES_DE_INVENTARIO = ["consolidado", "alertas", "valuacion"]
FUNCIONES_DE_VENTAS = ["detalle", "resumen", "top_productos", "por_canal", "por_sucursal"]


@pytest.mark.parametrize("lado", ["A", "B"])
@pytest.mark.parametrize("funcion", FUNCIONES_DE_INVENTARIO)
def test_las_consultas_del_repositorio_solo_traen_la_empresa_de_la_sesion(mundo, funcion, lado):
    propia, ajena = _lado(mundo, lado)
    esperado = stock_de(mundo, propia.id)
    with mundo.sesiones() as db:
        fijar_empresa(db, propia.id)
        filas = getattr(catalogo_repo, funcion)(db)
    assert ajena.m("") not in str(filas)
    {"consolidado": comprobar_consolidado, "alertas": comprobar_alertas, "valuacion": comprobar_valuacion}[funcion](
        filas, esperado
    )


@pytest.mark.parametrize("funcion", FUNCIONES_DE_VENTAS)
def test_las_consultas_de_ventas_del_repositorio_solo_traen_la_empresa_de_la_sesion(funcion):
    pytest.skip(
        f"comercial.repository.{funcion} lee la vista vw_ventas_detalle, que solo existe en PostgreSQL: "
        "cubierto en tests/postgres/test_aislamiento_pg.py"
    )


# --- 4. la guarda de E02: ningún SQL en texto sin condicion_empresa ----------------------------------------------------

# Archivos de app/ donde `text(` es legítimo: la sonda de salud (main.py), los índices parciales de los
# modelos (no son consultas) y las consultas sobre las vistas (que deben usar `condicion_empresa`).
ARCHIVOS_CON_TEXT = {"main.py", "catalogo/models.py", "plataforma/models.py", "catalogo/repository.py", "comercial/repository.py"}
REPOSITORIOS_CON_VISTAS = ("catalogo/repository.py", "comercial/repository.py")


def _arbol(relativa: str) -> ast.Module:
    return ast.parse((RAIZ_APP / relativa).read_text(encoding="utf-8"))


def _llama_a(nodo: ast.AST, *nombres: str) -> bool:
    for hijo in ast.walk(nodo):
        if isinstance(hijo, ast.Call):
            f = hijo.func
            if (isinstance(f, ast.Name) and f.id in nombres) or (isinstance(f, ast.Attribute) and f.attr in nombres):
                return True
    return False


def _funciones(arbol: ast.Module):
    return [n for n in ast.walk(arbol) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def lineas_con_sql_en_texto(codigo: str) -> list[int]:
    """Líneas donde el código arma SQL en texto: `text(...)`, `.exec_driver_sql(...)` o `.execute("...")`."""
    lineas = []
    for nodo in ast.walk(ast.parse(codigo)):
        if not isinstance(nodo, ast.Call):
            continue
        f = nodo.func
        es_text = (isinstance(f, ast.Name) and f.id == "text") or (
            isinstance(f, ast.Attribute) and f.attr in ("text", "exec_driver_sql")
        )
        primero = nodo.args[0] if nodo.args else None
        es_execute_literal = (
            isinstance(f, ast.Attribute)
            and f.attr == "execute"
            and (isinstance(primero, ast.JoinedStr) or (isinstance(primero, ast.Constant) and isinstance(primero.value, str)))
        )
        if es_text or es_execute_literal:
            lineas.append(nodo.lineno)
    return lineas


@pytest.mark.parametrize(
    "codigo",
    [
        "db.execute(text('SELECT * FROM producto'))",
        "sa.text('SELECT 1')",
        "db.execute('DELETE FROM venta')",
        "db.execute(f'SELECT * FROM {tabla}')",
        "conexion.exec_driver_sql('SELECT 1')",
    ],
)
def test_el_detector_de_sql_en_texto_detecta_cada_forma(codigo):
    """Control del detector: si dejara de ver una forma de SQL en texto, la guarda de abajo sería un falso verde."""
    assert lineas_con_sql_en_texto(codigo) == [1]
    assert lineas_con_sql_en_texto("db.execute(select(Producto).where(Producto.id == 1))") == []


def test_no_hay_text_ni_sql_crudo_fuera_de_los_sitios_permitidos():
    """Una consulta en texto no pasa por el filtro del ORM: si aparece en otro archivo, esta prueba falla."""
    fuera = []
    for ruta in sorted(RAIZ_APP.rglob("*.py")):
        relativa = ruta.relative_to(RAIZ_APP).as_posix()
        if relativa in ARCHIVOS_CON_TEXT or relativa == "core/tenant.py":
            continue
        fuera += [f"{relativa}:{linea}" for linea in lineas_con_sql_en_texto(ruta.read_text(encoding="utf-8"))]
    assert not fuera, f"SQL en texto fuera de los sitios permitidos (sin condicion_empresa): {fuera}"
    # Los sitios permitidos siguen existiendo: si alguno ya no usa texto, hay que quitarlo de la lista.
    for relativa in ARCHIVOS_CON_TEXT:
        assert lineas_con_sql_en_texto((RAIZ_APP / relativa).read_text(encoding="utf-8")), f"{relativa} ya no usa text()"


def test_las_consultas_en_texto_son_las_conocidas_y_todas_usan_condicion_empresa():
    """Las 8 consultas sobre las vistas (3 de inventario, 5 de ventas) están en dos repositorios; cada una
    arma su filtro con `condicion_empresa` (directo o por `_condiciones_ventas`). Una novena sin él falla aquí."""
    con_vista: dict[str, set[str]] = {}
    for relativa in REPOSITORIOS_CON_VISTAS:
        arbol = _arbol(relativa)
        for funcion in _funciones(arbol):
            menciona_vista = any(
                isinstance(n, ast.Constant) and isinstance(n.value, str) and "FROM vw_" in n.value for n in ast.walk(funcion)
            )
            if menciona_vista:
                con_vista.setdefault(relativa, set()).add(funcion.name)
                assert _llama_a(funcion, "condicion_empresa", "_condiciones_ventas"), (
                    f"{relativa}::{funcion.name} consulta una vista sin condicion_empresa"
                )
    # E09 (reportes generativos): una consulta más de existencias y dos de ventas (por día y por categoría).
    assert con_vista == {
        "catalogo/repository.py": set(FUNCIONES_DE_INVENTARIO) | {"existencias_por_producto"},
        "comercial/repository.py": set(FUNCIONES_DE_VENTAS) | {"serie_diaria", "por_categoria"},
    }
    # El único que arma el filtro de ventas, lo hace con condicion_empresa.
    condiciones = next(f for f in _funciones(_arbol("comercial/repository.py")) if f.name == "_condiciones_ventas")
    assert _llama_a(condiciones, "condicion_empresa")


def test_el_sql_en_texto_de_los_repositorios_esta_en_funciones_conocidas():
    """`text(` solo en el ayudante `_filas_a_dicts` (recibe el SQL ya armado) y en `resumen` (lo arma con el filtro)."""
    # E09: `existencias_por_producto` arma su consulta con un JOIN sobre la vista; `_consulta_en_texto` es el único
    # que envuelve el SQL de comercial en text() (declara las listas como parámetros, nunca pegadas al SQL).
    for relativa, permitidas in (
        ("catalogo/repository.py", {"_filas_a_dicts", "existencias_por_producto"}),
        ("comercial/repository.py", {"_consulta_en_texto"}),  # las demás llaman a este ayudante
    ):
        usan = {f.name for f in _funciones(_arbol(relativa)) if _llama_a(f, "text")}
        assert usan == permitidas, f"{relativa}: funciones con text() = {sorted(usan)}"
