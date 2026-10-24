"""E05, 4.8: la matriz de aislamiento sobre PostgreSQL real (base `fashionstore_test`).

SQLite no aplica `SELECT ... FOR UPDATE`, no tiene las vistas V2 de producción ni la concurrencia
real. Aquí se vuelve a armar el universo de dos empresas (A Profesional y B Básico, los mismos de
`tests/aislamiento`) sobre PostgreSQL y se comprueba:

  1. una ruta representativa por RECURSO con el oráculo O1..O4, los listados y las rutas que
     bloquean filas (FOR UPDATE): con ids propios funcionan; con ids de B dan 404 y B no cambia;
  2. que dos transacciones de empresas distintas no se esperan, y que 25 reservas simultáneas en A
     no tocan el stock de B;
  3. las vistas V2 y los reportes: solo cifras de la empresa de la sesión o del token;
  4. las llaves únicas por empresa (los datos solapados de A y B conviven);
  5. que el cambio de plan simultáneo y el índice parcial de la suscripción (tests de E04) siguen
     valiendo junto con la matriz;
  6. al final, `test_consistencia_entre_empresas`: ninguna fila apunta a otra empresa.

Orden: el módulo comparte UN universo (se crea una vez, como en SQLite), así que el orden de las
pruebas importa: primero las que solo leen (vistas, reportes, listados), después las que escriben
con datos propios de A, y la consulta de consistencia siempre al final.
"""

import datetime as dt
import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.catalogo import repository as catalogo_repo
from app.catalogo.politicas import reservar_stock
from app.comercial import repository as comercial_repo
from app.comercial.politicas import crear_reserva
from app.comercial.schemas import ReservaCrear, ReservaDetalleCrear
from app.core.database import get_db
from app.core.tenant import EmpresaNoDefinidaError, fijar_empresa
from app.main import app
from scripts.seed_entregas import seed as seed_entregas
from scripts.seed_inventario import seed as seed_inventario
from scripts.seed_pagos import seed as seed_pagos
from scripts.seed_reservas import seed as seed_reservas
from scripts.seed_seguridad import seed as seed_seguridad
from scripts.seed_ventas import seed as seed_ventas
from tests.aislamiento.casos_fk import CASOS_FK, _ruta
from tests.aislamiento.conftest import Mundo, _dos_empresas
from tests.aislamiento.oraculo import ID_INEXISTENTE, combinaciones, espejo, intento_cruzado, parametros_de_recurso
from tests.aislamiento.plantillas import ESPEJO_ACEPTADO, PARAMETROS
from tests.aislamiento.rutas_esperadas import LISTADO, MATRIZ, POR_ID, RUTAS
from tests.aislamiento.test_matriz_fk_en_cuerpo import _con_valor
from tests.aislamiento.test_matriz_fk_en_cuerpo import _pedir as _pedir_fk
from tests.aislamiento.test_matriz_listados import LISTADOS, SIN_MARCA, _consulta, fuga_por_ids
from tests.aislamiento.test_matriz_listados import _pedir as _pedir_listado
from tests.aislamiento.test_zz_consistencia_final import contar_inconsistentes, relaciones_entre_tablas_de_empresa
from tests.aislamiento.universo import TOTAL_VENDIDO, UNIDADES_POR_VENTA, crear, crear_universo
from tests.postgres import test_suscripcion_pg as suscripcion_pg
from tests.postgres.conftest import sembrar_empresa_de_pruebas

from .paralelo import ejecutar_en_paralelo

API = "/api/v1"
HOY = dt.date.today()
DESCUENTO_DE_LA_PROMOCION = Decimal("0.90")  # el universo crea en cada empresa una promoción del 10 %
DESDE, HASTA = HOY - dt.timedelta(days=1), HOY + dt.timedelta(days=1)


# =================================================================================================
# Fixtures del módulo: base limpia UNA vez, universo UNA vez, cliente HTTP sobre PostgreSQL
# =================================================================================================


@pytest.fixture(scope="module", autouse=True)
def base_limpia(engine_pg):
    """Sustituye, solo en este módulo, a la fixture `base_limpia` de conftest (que vacía la base
    ANTES DE CADA PRUEBA): aquí se vacía y se resiembra una sola vez, porque el universo de dos
    empresas es caro de armar y todas las pruebas del módulo lo comparten. Las demás pruebas de
    tests/postgres siguen vaciando la base antes de cada una, así que no quedan restos."""
    fabrica = sessionmaker(bind=engine_pg, autoflush=False, autocommit=False)
    with engine_pg.begin() as conexion:
        tablas = conexion.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
        ).scalars().all()
        conexion.execute(text("TRUNCATE TABLE " + ", ".join(f'"{t}"' for t in tablas) + " RESTART IDENTITY CASCADE"))
    with fabrica() as db:
        empresa = sembrar_empresa_de_pruebas(db)
        fijar_empresa(db, empresa.id)
        db.commit()
        seed_seguridad(db)
        seed_inventario(db)
        seed_reservas(db)
        seed_ventas(db)
        seed_pagos(db)
        seed_entregas(db)


@pytest.fixture(scope="module")
def sesiones(engine_pg):
    """Sesiones SIN empresa: la fija cada petición (o cada prueba, a mano)."""
    return sessionmaker(bind=engine_pg, autoflush=False, autocommit=False)


@pytest.fixture(scope="module")
def _mundo_pg(engine_pg, sesiones, base_limpia):
    empresa_a, empresa_b = _dos_empresas(sesiones)

    def _db_por_peticion():
        sesion = sesiones()
        try:
            yield sesion
        except Exception:
            sesion.rollback()
            raise
        finally:
            sesion.close()

    app.dependency_overrides[get_db] = _db_por_peticion
    try:
        with TestClient(app) as client:
            a = crear_universo(client, sesiones, empresa_a, "A")
            b = crear_universo(client, sesiones, empresa_b, "B")
            mundo = Mundo(engine_pg, sesiones, client, a, b)
            mundo.db_por_peticion = _db_por_peticion
            yield mundo
    finally:
        app.dependency_overrides.clear()  # el módulo no deja ningún override instalado


@pytest.fixture()
def mundo(_mundo_pg):
    app.dependency_overrides[get_db] = _mundo_pg.db_por_peticion
    return _mundo_pg


@pytest.fixture(autouse=True)
def _almacenamiento_falso(monkeypatch):
    """Cloudinary no está configurado en las pruebas: sus funciones se reemplazan por dobles."""
    from app.core import storage

    monkeypatch.setattr(storage, "subir_imagen", lambda contenido, carpeta, **_: f"{carpeta}/falso")
    monkeypatch.setattr(storage, "eliminar_imagen", lambda public_id: None)
    monkeypatch.setattr(storage, "url_catalogo", lambda public_id, ancho=None, alto=None: f"https://cdn.test/{public_id}")
    monkeypatch.setattr(storage, "url_probador", lambda public_id: f"https://cdn.test/{public_id}")


def _ok(respuesta, esperados=(200, 201)):
    assert respuesta.status_code in esperados, f"{respuesta.request.method} {respuesta.request.url.path}: {respuesta.status_code} {respuesta.text[:300]}"
    return respuesta.json() if respuesta.content else None


def _fila(mundo, consulta: str, **parametros):
    with mundo.engine.connect() as conexion:
        return conexion.execute(text(consulta), parametros).all()


# =================================================================================================
# 4. Vistas V2 y reportes (solo lectura: van PRIMERO para que A y B conserven sus cifras de origen)
# =================================================================================================

VENTAS_EFECTIVAS = (
    "SELECT ve.empresa_id, count(*) AS ventas, COALESCE(sum(ve.total), 0) AS total "
    "FROM venta ve JOIN estado_venta ev ON ev.id = ve.estado_id "
    "WHERE ev.codigo IN ('pagada', 'entregada') GROUP BY ve.empresa_id"
)
DETALLE_EFECTIVO = (
    "SELECT ve.empresa_id, count(DISTINCT ve.id) AS ventas, COALESCE(sum(vd.subtotal), 0) AS total, "
    "COALESCE(sum(vd.cantidad), 0) AS unidades "
    "FROM venta_detalle vd JOIN venta ve ON ve.id = vd.venta_id JOIN estado_venta ev ON ev.id = ve.estado_id "
    "WHERE ev.codigo IN ('pagada', 'entregada') GROUP BY ve.empresa_id"
)


def _ventas_reales(mundo) -> dict:
    """{empresa_id: (ventas efectivas, total vendido, unidades)} leído de las tablas, no supuesto."""
    return {f.empresa_id: (f.ventas, Decimal(f.total), f.unidades) for f in _fila(mundo, DETALLE_EFECTIVO)}


def test_las_ventas_del_universo_son_las_documentadas(mundo):
    """Control del universo, leído de las tablas (no supuesto): A vendió 3 ventas pagadas (4 unidades
    a 25.00 = 100.00 de lista) y B 5 (5 unidades a 1400.00 = 7000.00 de lista) según PRECIO y
    UNIDADES_POR_VENTA de universo.py. Lo COBRADO es lo de lista menos la promoción de 10 % que el
    universo crea en cada empresa (`Universo._promocion`): 90.00 y 6300.00. Si esto cambia, las
    demás cifras de abajo no tienen sentido."""
    reales = _ventas_reales(mundo)
    a, b = mundo.a, mundo.b
    for universo, tag in ((a, "A"), (b, "B")):
        ventas, total, unidades = reales[universo.id]
        assert (ventas, unidades) == (len(UNIDADES_POR_VENTA[tag]), sum(UNIDADES_POR_VENTA[tag])), reales[universo.id]
        assert total == TOTAL_VENDIDO[tag] * DESCUENTO_DE_LA_PROMOCION, f"{tag}: {total}"
    assert (reales[a.id][1], reales[b.id][1]) == (Decimal("90.00"), Decimal("6300.00"))
    totales_venta = {f.empresa_id: (f.ventas, Decimal(f.total)) for f in _fila(mundo, VENTAS_EFECTIVAS)}
    assert totales_venta[a.id] == reales[a.id][:2] and totales_venta[b.id] == reales[b.id][:2]


def test_las_vistas_v2_tienen_filas_de_las_dos_empresas_con_su_empresa_id(mundo):
    a, b = mundo.a, mundo.b
    inventario = {f.empresa_id: f.n for f in _fila(mundo, "SELECT empresa_id, count(*) AS n FROM vw_inventario_consolidado GROUP BY 1")}
    ventas = {f.empresa_id: (f.n, Decimal(f.total)) for f in _fila(mundo, "SELECT empresa_id, count(*) AS n, sum(subtotal) AS total FROM vw_ventas_detalle GROUP BY 1")}
    assert {a.id, b.id} <= set(inventario), f"vw_inventario_consolidado sin filas de ambas empresas: {inventario}"
    assert {a.id, b.id} <= set(ventas), f"vw_ventas_detalle sin filas de ambas empresas: {ventas}"
    # La vista incluye ventas pendientes y pagadas: lo EFECTIVO es lo que filtra el repositorio, ver abajo.
    for empresa in (a, b):
        assert ventas[empresa.id][1] >= _ventas_reales(mundo)[empresa.id][1]

    # El empresa_id de la vista es el de la fila de origen: ninguna fila "mezcla" empresas.
    desalineadas_ventas = _fila(mundo, "SELECT count(*) FROM vw_ventas_detalle v JOIN venta ve ON ve.id = v.venta_id WHERE v.empresa_id <> ve.empresa_id")[0][0]
    desalineadas_stock = _fila(
        mundo,
        "SELECT count(*) FROM vw_inventario_consolidado v JOIN stock s ON s.variante_id = v.variante_id AND s.sucursal_id = v.sucursal_id "
        "WHERE v.empresa_id <> s.empresa_id",
    )[0][0]
    assert desalineadas_ventas == 0 and desalineadas_stock == 0


def test_las_consultas_del_repositorio_solo_traen_la_empresa_de_la_sesion(mundo, sesiones):
    """Las 8 consultas con SQL en texto (3 de inventario y 5 de ventas): con la sesión de A solo
    filas de A, con la de B solo de B, y las sumas coinciden con las calculadas del universo."""
    reales = _ventas_reales(mundo)
    for universo in (mundo.a, mundo.b):
        esperado_ventas, esperado_total, esperadas_unidades = reales[universo.id]
        sucursales = {universo.ids["sucursal"], universo.ids["sucursal_destino"]}
        with sesiones() as db:
            fijar_empresa(db, universo.id)
            filas = {
                "consolidado": catalogo_repo.consolidado(db),
                "alertas": catalogo_repo.alertas(db),
                "valuacion": catalogo_repo.valuacion(db),
                "detalle": comercial_repo.detalle(db, DESDE, HASTA),
                "resumen": [comercial_repo.resumen(db, DESDE, HASTA)],
                "top_productos": comercial_repo.top_productos(db, DESDE, HASTA),
                "por_canal": comercial_repo.por_canal(db, DESDE, HASTA),
                "por_sucursal": comercial_repo.por_sucursal(db, DESDE, HASTA),
            }
        assert len(filas) == 8
        # Inventario: solo las sucursales de la empresa y el valor de SU stock.
        assert filas["consolidado"] and {f["empresa_id"] for f in filas["consolidado"]} == {universo.id}
        assert {f["sucursal_id"] for f in filas["consolidado"]} <= sucursales
        assert all(f["empresa_id"] == universo.id for f in filas["alertas"])
        assert {f["sucursal_id"] for f in filas["valuacion"]} <= sucursales
        valor_real = Decimal(_fila(mundo, "SELECT COALESCE(sum(valor_inventario), 0) FROM vw_inventario_consolidado WHERE empresa_id = :e", e=universo.id)[0][0])
        assert sum(Decimal(f["valor_total"]) for f in filas["valuacion"]) == valor_real
        # Ventas: solo las de la empresa y las cifras del universo.
        assert {f["empresa_id"] for f in filas["detalle"]} == {universo.id}
        assert sum(Decimal(f["subtotal"]) for f in filas["detalle"]) == esperado_total
        assert sum(f["cantidad"] for f in filas["detalle"]) == esperadas_unidades
        assert filas["resumen"][0]["transacciones"] == esperado_ventas
        assert Decimal(filas["resumen"][0]["total_ventas"]) == esperado_total
        assert sum(Decimal(f["total_vendido"]) for f in filas["top_productos"]) == esperado_total
        assert sum(Decimal(f["total_ventas"]) for f in filas["por_canal"]) == esperado_total
        assert sum(f["transacciones"] for f in filas["por_canal"]) == esperado_ventas
        assert {f["sucursal_id"] for f in filas["por_sucursal"]} <= sucursales
        assert sum(Decimal(f["total_ventas"]) for f in filas["por_sucursal"]) == esperado_total
    # Sin empresa en la sesión, ninguna de las consultas se ejecuta (falla cerrado).
    with sesiones() as db:
        with pytest.raises(EmpresaNoDefinidaError):
            catalogo_repo.consolidado(db)
        with pytest.raises(EmpresaNoDefinidaError):
            comercial_repo.detalle(db, DESDE, HASTA)


def test_los_reportes_por_la_api_traen_solo_cifras_de_la_empresa_del_token(mundo):
    """/reportes/ventas y /reportes/dashboard no corren en SQLite (leen la vista de ventas)."""
    reales = _ventas_reales(mundo)
    for universo in (mundo.a, mundo.b):
        ventas, total, _ = reales[universo.id]
        ajena = mundo.b if universo is mundo.a else mundo.a
        reporte = _ok(mundo.client.get(f"{API}/reportes/ventas", headers=universo.admin))
        assert reporte["resumen"]["transacciones"] == ventas
        assert Decimal(str(reporte["resumen"]["total_ventas"])) == total
        assert sum(Decimal(str(f["total_ventas"])) for f in reporte["por_sucursal"]) == total
        assert {f["sucursal_id"] for f in reporte["por_sucursal"]} <= {universo.ids["sucursal"], universo.ids["sucursal_destino"]}
        assert ajena.m("") not in str(reporte)

        dashboard = _ok(mundo.client.get(f"{API}/reportes/dashboard", headers=universo.admin))
        assert dashboard["transacciones"] == ventas
        assert Decimal(str(dashboard["ventas_del_periodo"])) == total
        assert {f["sucursal_id"] for f in dashboard["ventas_por_sucursal"]} <= {universo.ids["sucursal"], universo.ids["sucursal_destino"]}
        assert ajena.m("") not in str(dashboard)

    # Filtrar por una sucursal de la otra empresa no devuelve sus cifras.
    for universo, ajena in ((mundo.a, mundo.b), (mundo.b, mundo.a)):
        for ruta in ("/reportes/ventas", "/reportes/dashboard"):
            respuesta = mundo.client.get(f"{API}{ruta}", params={"sucursal_id": ajena.ids["sucursal"]}, headers=universo.admin)
            assert respuesta.status_code == 404, f"{ruta} con sucursal ajena: {respuesta.status_code} {respuesta.text[:200]}"
            assert ajena.m("") not in respuesta.text


# =================================================================================================
# 1a. Listados (todos, en PostgreSQL: incluye los reportes que SQLite no corre)
# =================================================================================================

SIN_MARCA_PG = {**SIN_MARCA, ("GET", f"{API}/reportes/ventas"): "solo cifras y nombres de producto sin marca",
                ("GET", f"{API}/reportes/dashboard"): "solo cifras"}


@pytest.mark.parametrize("clave", LISTADOS, ids=[f"{m} {r.removeprefix(API)}" for m, r in LISTADOS])
def test_el_listado_trae_solo_datos_de_la_empresa(mundo, clave):
    metodo, ruta = clave
    for propia, ajena in ((mundo.a, mundo.b), (mundo.b, mundo.a)):
        respuesta = _pedir_listado(mundo, metodo, ruta, propia, _consulta(metodo, ruta, propia))
        assert respuesta.status_code == 200, f"{metodo} {ruta}: {respuesta.status_code} {respuesta.text[:300]}"
        assert ajena.m("") not in respuesta.text, f"{metodo} {ruta}: marca de la otra empresa en la respuesta"
        assert fuga_por_ids(respuesta.json(), ajena) == [], f"{metodo} {ruta}: ids de la otra empresa"
        if clave not in SIN_MARCA_PG:
            assert propia.m("") in respuesta.text, f"{metodo} {ruta}: no trae datos de la propia empresa"


# =================================================================================================
# 1b. Matriz reducida: UNA ruta representativa por recurso (oráculo O1..O4 y espejo O5)
# =================================================================================================


def _recurso_de(ruta: str) -> str:
    return PARAMETROS[parametros_de_recurso(ruta)[-1]]


def _representante(rutas: list[tuple[str, str]]) -> tuple[str, str]:
    """Prefiere un GET con un solo id (no modifica nada); si el recurso no tiene, la primera ruta."""
    simples = [c for c in rutas if c[0] == "GET" and len(parametros_de_recurso(c[1])) == 1]
    return (simples or [c for c in rutas if c[0] == "GET"] or rutas)[0]


def _representantes_por_recurso() -> list[tuple[str, str]]:
    por_recurso: dict[str, list[tuple[str, str]]] = {}
    for clave in sorted(c for c, r in RUTAS.items() if r.clase == POR_ID and r.cobertura == MATRIZ and parametros_de_recurso(c[1])):
        por_recurso.setdefault(_recurso_de(clave[1]), []).append(clave)
    return [_representante(rutas) for _, rutas in sorted(por_recurso.items())]


REPRESENTANTES = _representantes_por_recurso()


@pytest.mark.parametrize("clave", REPRESENTANTES, ids=[f"{_recurso_de(r)}: {m} {r.removeprefix(API)}" for m, r in REPRESENTANTES])
def test_a_no_alcanza_el_recurso_de_b_en_postgres(mundo, clave):
    metodo, ruta = clave
    intento_cruzado(mundo, metodo, ruta, combinaciones(ruta)[0])
    espejo(mundo, metodo, ruta)  # O5: con el id propio la misma ruta SÍ responde


def test_hay_un_representante_por_cada_recurso_de_la_matriz():
    recursos = {_recurso_de(r) for _, r in REPRESENTANTES}
    assert len(REPRESENTANTES) == len(recursos) >= 25, f"{len(REPRESENTANTES)} representantes para {len(recursos)} recursos"


# =================================================================================================
# 1c. Rutas que bloquean filas (SELECT ... FOR UPDATE): con ids propios funcionan; con ids de B, 404
# =================================================================================================

PREFIJOS_CON_BLOQUEO = (
    "movimiento.", "ajuste.", "transferencia.", "reserva.", "venta_presencial.", "venta_digital.",
    "devolucion.", "pago_caja.", "pago_iniciar.", "recepcion.",
)
CASOS_CON_BLOQUEO = [c for c in CASOS_FK if c.nombre.startswith(PREFIJOS_CON_BLOQUEO)]


@pytest.mark.parametrize("caso", CASOS_CON_BLOQUEO, ids=[c.nombre for c in CASOS_CON_BLOQUEO])
def test_un_id_de_b_en_una_operacion_con_bloqueo_da_404_y_no_deja_filas(mundo, caso):
    a, b = mundo.a, mundo.b
    ruta = _ruta(caso, a)
    base = caso.cuerpo(a)
    ajeno = _con_valor(base, caso.campo, b.ids[caso.ajeno])
    inexistente = _con_valor(base, caso.campo, ID_INEXISTENTE)

    antes_a, antes_b = mundo.instantanea(a.id), mundo.instantanea(b.id)
    respuesta = _pedir_fk(mundo, caso, a, ruta, ajeno)
    despues_a, despues_b = mundo.instantanea(a.id), mundo.instantanea(b.id)
    control = _pedir_fk(mundo, caso, a, ruta, inexistente)

    detalle = f"{caso.metodo} {ruta} -> {respuesta.status_code} {respuesta.text[:300]}"
    assert respuesta.status_code == 404, f"se esperaba 404: {detalle}"
    assert control.status_code == 404
    assert control.text.replace(str(ID_INEXISTENTE), "<id>") == respuesta.text.replace(str(b.ids[caso.ajeno]), "<id>")
    assert b.m("") not in respuesta.text
    assert mundo.cambios(antes_a, despues_a) == [], f"A cambió con un 404: {mundo.cambios(antes_a, despues_a)}"
    assert mundo.cambios(antes_b, despues_b) == [], f"B cambió: {mundo.cambios(antes_b, despues_b)}"
    if caso.espejo:  # con ids propios la misma petición funciona (el bloqueo con filtro de empresa no la rompe)
        propio = _pedir_fk(mundo, caso, a, ruta, caso.cuerpo(a))
        assert propio.status_code in ESPEJO_ACEPTADO, f"con ids propios: {propio.status_code} {propio.text[:300]}"


RUTAS_DE_ACCION_CON_BLOQUEO = [
    ("POST", f"{API}/transferencias/{{transferencia_id}}/enviar"),
    ("POST", f"{API}/transferencias/{{transferencia_id}}/recibir"),
    ("DELETE", f"{API}/transferencias/{{transferencia_id}}"),
    ("POST", f"{API}/pagos/{{pago_id}}/anular"),
    ("POST", f"{API}/pagos/venta/{{venta_id}}/cancelar"),
    ("PUT", f"{API}/reservas/{{reserva_id}}/preparar"),
    ("PUT", f"{API}/reservas/{{reserva_id}}/confirmar-llegada"),
    ("PUT", f"{API}/reservas/{{reserva_id}}/seleccion"),
    ("DELETE", f"{API}/reservas/{{reserva_id}}"),
    ("POST", f"{API}/ordenes-compra/{{orden_id}}/enviar"),
    ("PUT", f"{API}/inventario/stock/{{stock_id}}/limites"),
]


def test_las_rutas_de_accion_con_bloqueo_existen_en_el_registro():
    faltan = [c for c in RUTAS_DE_ACCION_CON_BLOQUEO if c not in RUTAS]
    assert not faltan, f"rutas que ya no están en rutas_esperadas.py: {faltan}"


@pytest.mark.parametrize("clave", RUTAS_DE_ACCION_CON_BLOQUEO, ids=[f"{m} {r.removeprefix(API)}" for m, r in RUTAS_DE_ACCION_CON_BLOQUEO])
def test_una_accion_con_bloqueo_sobre_un_recurso_de_b_da_404_y_b_no_cambia(mundo, clave):
    metodo, ruta = clave
    for con_b in combinaciones(ruta):
        intento_cruzado(mundo, metodo, ruta, con_b)


def test_el_flujo_completo_con_bloqueos_funciona_con_ids_propios(mundo):
    """Cada paso toma `SELECT ... FOR UPDATE` con el filtro de empresa y debe terminar bien: ajuste,
    movimiento, transferencia enviada y recibida, reserva atendida, venta presencial cobrada, pago
    anulado y devolución."""
    a, h, c = mundo.a, mundo.a.admin, mundo.client
    v, s = a.ids["variante"], a.ids["sucursal"]
    ajuste = crear(c, "/inventario/ajustes", {"variante_id": v, "sucursal_id": s, "cantidad": 3, "observacion": "pg"}, h)
    assert ajuste
    movimiento = crear(
        c, "/inventario/movimientos",
        {"variante_id": v, "sucursal_id": s, "tipo_movimiento_codigo": "ajuste_positivo", "cantidad": 2}, h,
    )
    assert movimiento["id"]

    transferencia = a.nuevo("transferencia")
    assert crear(c, f"/transferencias/{transferencia}/enviar", None, h)["id"] == transferencia
    assert crear(c, f"/transferencias/{transferencia}/recibir", None, h)["id"] == transferencia

    reserva = a.nuevo("reserva")
    assert _ok(c.put(f"{API}/reservas/{reserva}/preparar", headers=h))["id"] == reserva
    assert _ok(c.put(f"{API}/reservas/{reserva}/confirmar-llegada", headers=h))["id"] == reserva
    otra = a.nuevo("reserva")
    assert _ok(c.delete(f"{API}/reservas/{otra}", headers=a.headers["cliente"]))["id"] == otra  # libera su stock

    venta = crear(c, "/ventas/presencial", {"sucursal_id": s, "cliente_id": a.cliente.id, "detalle": [{"variante_id": v, "cantidad": 1}]}, h)
    pago = crear(c, "/pagos/caja", {"venta_id": venta["id"], "metodo_pago": "efectivo", "monto_recibido": "99999"}, h)["pago"]
    assert _ok(c.post(f"{API}/pagos/{pago['id']}/anular", headers=h))["id"] == pago["id"]

    pagada = crear(c, "/ventas/presencial", {"sucursal_id": s, "cliente_id": a.cliente.id, "detalle": [{"variante_id": v, "cantidad": 1}]}, h)
    crear(c, "/pagos/caja", {"venta_id": pagada["id"], "metodo_pago": "efectivo", "monto_recibido": "99999"}, h)
    devolucion = crear(
        c, "/devoluciones",
        {"venta_id": pagada["id"], "motivo": "pg", "detalle": [{"venta_detalle_id": pagada["detalle"][0]["id"], "cantidad": 1}]}, h,
    )
    assert devolucion["id"]


# =================================================================================================
# 2. Concurrencia entre empresas
# =================================================================================================


def _stock(mundo, universo) -> tuple[int, int]:
    fila = _fila(
        mundo, "SELECT cantidad_fisica, cantidad_reservada FROM stock WHERE variante_id = :v AND sucursal_id = :s",
        v=universo.ids["variante"], s=universo.ids["sucursal"],
    )[0]
    return fila.cantidad_fisica, fila.cantidad_reservada


def test_dos_transacciones_de_empresas_distintas_no_se_bloquean_entre_si(mundo, sesiones):
    """A y B toman, a la vez, el lock de SU fila de stock y esperan en una barrera a que la otra
    también lo tenga: si una bloqueara a la otra, la barrera vencería y la prueba fallaría.
    Las claves de negocio de las dos filas son las mismas (mismo SKU, misma sucursal 'SUC-1'); los
    ids de PostgreSQL no se repiten entre empresas (son secuencias globales), así que lo que se
    solapa es lo que el filtro de empresa debe distinguir."""
    a, b = mundo.a, mundo.b
    assert a.ids["sku"] == b.ids["sku"]
    barrera = threading.Barrier(2, timeout=15)

    def transaccion(universo):
        def operacion(db):
            fijar_empresa(db, universo.id)
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            reservar_stock(db, universo.ids["variante"], universo.ids["sucursal"], 1, commit=False)  # FOR UPDATE
            barrera.wait()  # las DOS transacciones tienen su bloqueo al mismo tiempo
            db.commit()
            return universo.id

        return operacion

    antes = {u.id: _stock(mundo, u) for u in (a, b)}
    resultados = ejecutar_en_paralelo(sesiones, [transaccion(a), transaccion(b)])
    assert all(r.ok for r in resultados), [repr(r.error) for r in resultados]
    despues = {u.id: _stock(mundo, u) for u in (a, b)}
    for u in (a, b):  # cada una reservó UNA unidad, solo en su stock
        assert despues[u.id] == (antes[u.id][0], antes[u.id][1] + 1)


def test_control_en_la_misma_empresa_si_se_esperan(mundo, sesiones):
    """Contrapunto: dos transacciones de la MISMA empresa sobre la misma fila sí se esperan (si no, la
    prueba anterior no probaría nada). La que llega segunda vence su lock_timeout."""
    a = mundo.a
    segunda_fallo = threading.Event()

    def transaccion(db):
        fijar_empresa(db, a.id)
        db.execute(text("SET LOCAL lock_timeout = '700ms'"))
        try:
            reservar_stock(db, a.ids["variante"], a.ids["sucursal"], 1, commit=False)
        except OperationalError:
            segunda_fallo.set()
            raise
        segunda_fallo.wait(timeout=10)  # quien tiene el lock lo conserva hasta que la otra falla
        db.rollback()
        return True

    resultados = ejecutar_en_paralelo(sesiones, [transaccion, transaccion])
    errores = [r.error for r in resultados if not r.ok]
    assert len(errores) == 1 and isinstance(errores[0], OperationalError), [repr(r.error) for r in resultados]


def test_25_reservas_simultaneas_en_a_no_afectan_el_stock_de_b(mundo, sesiones):
    a, b = mundo.a, mundo.b
    stock_a_antes, stock_b_antes, b_antes = _stock(mundo, a), _stock(mundo, b), mundo.instantanea(b.id)

    def reserva(indice):
        def operacion(db):
            fijar_empresa(db, a.id)
            datos = ReservaCrear(
                sucursal_id=a.ids["sucursal"],
                fecha_visita=HOY + dt.timedelta(days=2 + indice),
                hora_visita_desde=dt.time(10, 0),
                hora_visita_hasta=dt.time(11, 0),
                detalle=[ReservaDetalleCrear(variante_id=a.ids["variante"], cantidad=1)],
            )
            return crear_reserva(db, a.cliente.usuario_id, datos).id

        return operacion

    resultados = ejecutar_en_paralelo(sesiones, [reserva(i) for i in range(25)])
    errores = [repr(r.error) for r in resultados if not r.ok]
    assert not errores, errores
    assert len({r.valor for r in resultados}) == 25  # 25 reservas distintas
    stock_a_despues = _stock(mundo, a)
    assert stock_a_despues == (stock_a_antes[0], stock_a_antes[1] + 25), (stock_a_antes, stock_a_despues)
    # B ni se enteró: su stock y todas sus tablas son idénticas.
    assert _stock(mundo, b) == stock_b_antes
    assert mundo.cambios(b_antes, mundo.instantanea(b.id)) == []


def test_reservas_simultaneas_de_a_y_b_se_resuelven_cada_una_en_su_stock(mundo, sesiones):
    """15 reservas de A y 5 de B a la vez: cada empresa suma solo las suyas y ninguna espera a la otra."""
    a, b = mundo.a, mundo.b
    antes = {u.id: _stock(mundo, u) for u in (a, b)}

    def reserva(universo, indice):
        def operacion(db):
            fijar_empresa(db, universo.id)
            datos = ReservaCrear(
                sucursal_id=universo.ids["sucursal"],
                fecha_visita=HOY + dt.timedelta(days=40 + indice),
                hora_visita_desde=dt.time(10, 0),
                hora_visita_hasta=dt.time(11, 0),
                detalle=[ReservaDetalleCrear(variante_id=universo.ids["variante"], cantidad=1)],
            )
            return crear_reserva(db, universo.cliente.usuario_id, datos).id

        return operacion

    operaciones = [reserva(a, i) for i in range(15)] + [reserva(b, i) for i in range(5)]
    resultados = ejecutar_en_paralelo(sesiones, operaciones)
    assert all(r.ok for r in resultados), [repr(r.error) for r in resultados if not r.ok]
    assert _stock(mundo, a)[1] == antes[a.id][1] + 15
    assert _stock(mundo, b)[1] == antes[b.id][1] + 5


# =================================================================================================
# 5. Únicas por empresa (E01): los datos solapados de A y B conviven
# =================================================================================================

SOLAPADOS = [
    ("producto", "codigo", "CAM-001"),
    ("sucursal", "codigo", "SUC-1"),
    ("sucursal", "codigo", "SUC-2"),
    ("usuario", "email", "caja@tienda.bo"),
    ("usuario", "email", "admin@tienda.bo"),
    ("categoria", "nombre", "Camisas"),
    ("talla", "codigo", "M"),
    ("color", "nombre", "Negro"),
]


@pytest.mark.parametrize("tabla, columna, valor", SOLAPADOS, ids=[f"{t}.{c}={v}" for t, c, v in SOLAPADOS])
def test_los_datos_solapados_de_a_y_b_conviven(mundo, tabla, columna, valor):
    filas = _fila(mundo, f"SELECT empresa_id FROM {tabla} WHERE {columna} = :valor", valor=valor)  # noqa: S608 (nombres fijos)
    assert sorted(f.empresa_id for f in filas if f.empresa_id in (mundo.a.id, mundo.b.id)) == sorted([mundo.a.id, mundo.b.id]), (
        f"{tabla}.{columna}='{valor}' debe existir UNA vez en A y UNA en B: {[f.empresa_id for f in filas]}"
    )


def test_el_mismo_sku_existe_en_a_y_en_b(mundo):
    filas = _fila(mundo, "SELECT empresa_id FROM producto_variante WHERE sku = :sku", sku=mundo.a.ids["sku"])
    assert sorted(f.empresa_id for f in filas) == sorted([mundo.a.id, mundo.b.id])


@pytest.mark.parametrize("tabla, columna", [("producto", "codigo"), ("producto_variante", "sku"), ("sucursal", "codigo"), ("usuario", "email")])
def test_las_llaves_unicas_de_negocio_incluyen_la_empresa(engine_pg, tabla, columna):
    """Toda llave única que contiene la columna de negocio incluye `empresa_id` (única POR EMPRESA);
    la única excepción es el índice parcial de correos de superadministradores (sin empresa)."""
    inspector = inspect(engine_pg)
    unicas = [i for i in inspector.get_indexes(tabla) if i.get("unique")] + inspector.get_unique_constraints(tabla)
    con_la_columna = [u for u in unicas if columna in u["column_names"]]
    assert con_la_columna, f"{tabla}.{columna} no tiene ninguna llave única"
    for unica in con_la_columna:
        parcial_de_plataforma = "empresa_id IS NULL" in str(unica.get("dialect_options", {}).get("postgresql_where", ""))
        assert "empresa_id" in unica["column_names"] or parcial_de_plataforma, f"única sin empresa_id en {tabla}: {unica}"


def test_dentro_de_una_misma_empresa_la_duplicada_sigue_rechazada(mundo):
    a, b = mundo.a, mundo.b
    antes_b = mundo.instantanea(b.id)
    duplicado = mundo.client.post(
        f"{API}/productos",
        json={"codigo": "CAM-001", "nombre": "Duplicado", "categoria_id": a.ids["categoria"], "precio_base": "10.00",
              "tallas_ids": [a.ids["talla"]], "colores_ids": [a.ids["color"]]},
        headers=a.admin,
    )
    assert duplicado.status_code in (400, 409, 422), f"{duplicado.status_code} {duplicado.text[:200]}"
    assert mundo.cambios(antes_b, mundo.instantanea(b.id)) == []
    sucursal = mundo.client.post(
        f"{API}/sucursales",
        json={"ciudad_id": a.ids["ciudad"], "codigo": "SUC-1", "nombre": "Otra", "direccion": "Calle"},
        headers=a.admin,
    )
    assert sucursal.status_code in (400, 409, 422), f"{sucursal.status_code} {sucursal.text[:200]}"


# =================================================================================================
# 6. Suscripción: las pruebas de E04 (índice parcial, altas y cambios de plan simultáneos, tarea de
#    vencimiento) se vuelven a disparar aquí, con el universo de dos empresas presente en la base.
# =================================================================================================

PRUEBAS_DE_SUSCRIPCION = [
    "test_dos_altas_simultaneas_de_sucursal_con_un_solo_cupo_dejan_exactamente_una",
    "test_el_indice_parcial_rechaza_una_segunda_suscripcion_vigente",
    "test_dos_cambios_de_plan_simultaneos_dejan_una_sola_suscripcion_vigente",
    "test_la_tarea_de_vencimiento_actua_sobre_todas_las_empresas",
]


def _estado_de_suscripciones(mundo) -> dict:
    return {
        f.empresa_id: (f.plan, f.estado)
        for f in _fila(
            mundo,
            "SELECT s.empresa_id, p.codigo AS plan, s.estado FROM suscripcion s JOIN plan p ON p.id = s.plan_id "
            "WHERE s.empresa_id IN (:a, :b) AND s.estado <> 'cancelada'",
            a=mundo.a.id, b=mundo.b.id,
        )
    }


@pytest.mark.parametrize("nombre", PRUEBAS_DE_SUSCRIPCION)
def test_las_pruebas_de_suscripcion_de_e04_siguen_valiendo_con_el_universo(mundo, engine_pg, fabrica_pg, nombre):
    esperado = {mundo.a.id: ("profesional", "activa"), mundo.b.id: ("basico", "activa")}
    assert _estado_de_suscripciones(mundo) == esperado
    prueba = getattr(suscripcion_pg, nombre)
    argumentos = [engine_pg if p == "engine_pg" else fabrica_pg for p in prueba.__code__.co_varnames[: prueba.__code__.co_argcount]]
    try:
        prueba(*argumentos)
    finally:
        # La prueba de altas fija el cupo del plan 'profesional' en "activas + 1": se restaura (el plan es global).
        with engine_pg.begin() as conexion:
            conexion.execute(text("UPDATE plan SET max_sucursales = 10 WHERE codigo = 'profesional'"))
    # El universo no se movió y sigue operando.
    assert _estado_de_suscripciones(mundo) == esperado
    for universo in (mundo.a, mundo.b):
        _ok(mundo.client.get(f"{API}/productos", headers=universo.admin))
        _ok(mundo.client.get(f"{API}/mi-empresa/suscripcion", headers=universo.admin))


# =================================================================================================
# 3. Consistencia entre empresas (SIEMPRE LA ÚLTIMA: mira el estado final tras todas las escrituras)
# =================================================================================================


def test_consistencia_entre_empresas(mundo):
    relaciones = relaciones_entre_tablas_de_empresa()
    with mundo.engine.connect() as conexion:
        inconsistentes = contar_inconsistentes(conexion)
    print(f"\nRelaciones revisadas entre tablas de empresa (PostgreSQL): {len(relaciones)}")
    assert len(relaciones) >= 50, f"se esperaban decenas de relaciones, hay {len(relaciones)}"
    assert inconsistentes == [], "filas que apuntan a otra empresa:\n  " + "\n  ".join(inconsistentes)
