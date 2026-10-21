"""Aislamiento por empresa en PostgreSQL real: lo que SQLite no puede probar.

- El filtro automático convive con `SELECT ... FOR UPDATE` y no genera esperas
  entre empresas distintas.
- Las dos vistas V2 (`vw_inventario_consolidado`, `vw_ventas_detalle`) se
  filtran por empresa con `condicion_empresa`.
- El listener `do_orm_execute` funciona con el pool de conexiones real (cada
  hilo, su sesión, su empresa) y falla cerrado sin empresa.
- Los bloqueos de las pruebas de concurrencia siguen pidiendo el lock Y el
  predicado de empresa en la misma sentencia.

Las pruebas `test_concurrencia_*.py` de esta carpeta siguen corriendo igual:
las sesiones de `fabrica_pg` nacen en la empresa 1 y el filtro las deja pasar.
"""

import datetime as dt
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.catalogo import repository as catalogo_repo
from app.catalogo.models import Stock
from app.catalogo.politicas import reservar_stock
from app.catalogo.repository import StockRepository
from app.comercial import repository as comercial_repo
from app.comercial.repository import ReservaRepository
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import NoEncontradoError
from app.core.tenant import EmpresaNoDefinidaError, fijar_empresa
from app.main import app
from app.plataforma.models import Sucursal
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.comercial._datos_empresa import iniciar_pago, reservar, sembrar_empresa
from tests.conftest import crear_empresa, token_de

from .conftest import CLAVE

SECRETO_LIBELULA = get_settings().libelula_webhook_secret
HOY = dt.date.today()


@pytest.fixture()
def client_pg(engine_pg):
    """Cliente HTTP contra PostgreSQL con una sesión NUEVA y SIN empresa por
    petición, como en producción (el `client_pg` de conftest nace en la empresa
    1 y rechazaría el token de otra empresa)."""
    fabrica = sessionmaker(bind=engine_pg, autoflush=False, autocommit=False)

    def _get_db():
        db = fabrica()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as cliente:
        yield cliente
    app.dependency_overrides.clear()


@pytest.fixture()
def dos_empresas_pg(fabrica_pg, client_pg):
    """A ('tienda-a', profesional) y B ('tienda-b', básico) en la base de
    pruebas, cada una con catálogo, stock y cliente. A tiene 10 unidades; B,
    4. Como `dos_empresas`, con el administrador de cada una."""
    cuerpo = {}
    with fabrica_pg() as db:
        repo = UsuarioRepository()
        for clave, codigo, plan in (("a", "tienda-a", "profesional"), ("b", "tienda-b", "basico")):
            empresa = crear_empresa(db, codigo, plan=plan)
            fijar_empresa(db, empresa.id)
            admin = repo.crear(
                db, UsuarioCrear(nombre="Admin", apellido=clave.upper(), email=f"admin@{codigo}.example.com", password=CLAVE)
            )
            repo.asignar_roles(db, admin, ["administrador"])
            cuerpo[clave] = SimpleNamespace(
                id=empresa.id, codigo=codigo, admin_id=admin.id, headers=token_de(db, admin)
            )
        fijar_empresa(db, None)
        a = sembrar_empresa(client_pg, db, cuerpo["a"], stock=10)
        b = sembrar_empresa(client_pg, db, cuerpo["b"], stock=4)
    return SimpleNamespace(a=cuerpo["a"], b=cuerpo["b"], datos_a=a, datos_b=b)


def _sesion_de(fabrica, empresa_id: int | None):
    """Sesión NUEVA del pool real, con la empresa dada (o sin ninguna)."""
    db = fabrica()
    fijar_empresa(db, empresa_id)
    return db


# ---- 1. FOR UPDATE con el filtro de empresa -------------------------------------------


def test_for_update_con_filtro_no_bloquea_entre_empresas(fabrica_pg, dos_empresas_pg):
    e = dos_empresas_pg
    claves = {
        "a": (e.datos_a["variante_id"], e.datos_a["sucursal_id"]),
        "b": (e.datos_b["variante_id"], e.datos_b["sucursal_id"]),
    }
    repo = StockRepository()
    sesion_a = _sesion_de(fabrica_pg, e.a.id)
    sesion_b = _sesion_de(fabrica_pg, e.b.id)
    try:
        # La transacción de A toma el lock de SU fila de stock y no la suelta.
        bloqueada_a = repo.obtener_o_crear_bloqueado(sesion_a, *claves["a"])
        assert bloqueada_a.empresa_id == e.a.id

        # La de B bloquea la suya sin esperar a A (si esperara, saltaría el timeout).
        sesion_b.execute(text("SET LOCAL lock_timeout = '2s'"))
        bloqueada_b = repo.obtener_o_crear_bloqueado(sesion_b, *claves["b"])
        assert bloqueada_b.empresa_id == e.b.id

        # Y desde B la fila de A ni se ve: el predicado de empresa la descarta
        # ANTES de intentar el lock, así que tampoco hay espera (una fila ajena
        # se "crearía" vacía de no ser por el filtro; lo que importa acá es que
        # la consulta con FOR UPDATE vuelve enseguida).
        filas_de_a_vistas_desde_b = sesion_b.scalars(
            select(Stock).where(Stock.variante_id == claves["a"][0], Stock.sucursal_id == claves["a"][1]).with_for_update()
        ).all()
        assert filas_de_a_vistas_desde_b == []
    finally:
        sesion_a.rollback()
        sesion_b.rollback()
        sesion_a.close()
        sesion_b.close()


def test_el_lock_sigue_vigente_para_la_misma_empresa(fabrica_pg, dos_empresas_pg):
    """Contrapunto de la anterior: dentro de la MISMA empresa el lock sí espera
    (si el filtro lo anulara, el aislamiento no costaría nada y no probaría
    nada)."""
    e = dos_empresas_pg
    clave = (e.datos_a["variante_id"], e.datos_a["sucursal_id"])
    repo = StockRepository()
    primera = _sesion_de(fabrica_pg, e.a.id)
    segunda = _sesion_de(fabrica_pg, e.a.id)
    try:
        repo.obtener_o_crear_bloqueado(primera, *clave)
        segunda.execute(text("SET LOCAL lock_timeout = '500ms'"))
        with pytest.raises(OperationalError):
            repo.obtener_o_crear_bloqueado(segunda, *clave)
    finally:
        primera.rollback()
        segunda.rollback()
        primera.close()
        segunda.close()


# ---- 2. Las dos vistas V2 --------------------------------------------------------------


def _aprobar_por_webhook(client_pg, id_transaccion: str) -> None:
    cuerpo = json.dumps({"id_transaccion": id_transaccion, "estado": "aprobado"}).encode("utf-8")
    firma = hmac.new(SECRETO_LIBELULA.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()
    respuesta = client_pg.post(
        "/api/v1/pagos/webhook/libelula",
        content=cuerpo,
        headers={"Content-Type": "application/json", "x-signature": firma},
    )
    assert respuesta.status_code == 200, respuesta.text


def test_las_dos_vistas_filtran_por_empresa(client_pg, fabrica_pg, dos_empresas_pg):
    e = dos_empresas_pg
    # Una venta pagada en cada empresa (la vista de ventas solo cuenta las efectivas).
    for datos, cantidad in ((e.datos_a, 2), (e.datos_b, 3)):
        _, pago = iniciar_pago(client_pg, datos, cantidad=cantidad)
        _aprobar_por_webhook(client_pg, pago["referencia_externa"])

    with fabrica_pg() as db:
        # Las vistas SÍ tienen filas de las dos empresas (si no, la prueba no probaría nada).
        por_empresa = {
            fila.empresa_id: fila.n
            for fila in db.execute(text("SELECT empresa_id, count(*) AS n FROM vw_inventario_consolidado GROUP BY 1"))
        }
        assert {e.a.id, e.b.id} <= set(por_empresa)
        ventas_por_empresa = {
            fila.empresa_id: fila.n
            for fila in db.execute(text("SELECT empresa_id, count(*) AS n FROM vw_ventas_detalle GROUP BY 1"))
        }
        assert {e.a.id, e.b.id} <= set(ventas_por_empresa)

        for empresa, datos, fisica, vendidas in ((e.a, e.datos_a, 10, 2), (e.b, e.datos_b, 4, 3)):
            fijar_empresa(db, empresa.id)
            # vw_inventario_consolidado: solo el stock de la empresa (consolidado, alertas, valuación).
            filas = catalogo_repo.consolidado(db)
            assert {f["sucursal_id"] for f in filas} == {datos["sucursal_id"]}
            assert {f["empresa_id"] for f in filas} == {empresa.id}
            assert sum(f["cantidad_fisica"] for f in filas) == fisica - vendidas
            assert {f["sucursal_id"] for f in catalogo_repo.valuacion(db)} == {datos["sucursal_id"]}
            assert all(f["empresa_id"] == empresa.id for f in catalogo_repo.alertas(db))
            # vw_ventas_detalle: solo las ventas de la empresa.
            detalle = comercial_repo.detalle(db, HOY - dt.timedelta(days=1), HOY + dt.timedelta(days=1))
            assert {f["empresa_id"] for f in detalle} == {empresa.id}
            assert sum(f["cantidad"] for f in detalle) == vendidas
            db.rollback()

        # Sin empresa en la sesión las consultas ni se ejecutan.
        fijar_empresa(db, None)
        with pytest.raises(EmpresaNoDefinidaError):
            catalogo_repo.consolidado(db)


# ---- 3. El listener con el pool real ---------------------------------------------------


def test_el_filtro_funciona_con_el_pool_real(fabrica_pg, dos_empresas_pg):
    e = dos_empresas_pg
    esperado = {e.a.id: {e.datos_a["sucursal_id"]}, e.b.id: {e.datos_b["sucursal_id"]}}

    def sucursales_vistas(empresa_id: int) -> set[int]:
        # Cada hilo toma una conexión del pool, la usa con SU empresa y la devuelve.
        with fabrica_pg() as db:
            fijar_empresa(db, empresa_id)
            return set(db.scalars(select(Sucursal.id)))

    # Muchas vueltas y varios hilos: una conexión reutilizada no arrastra la empresa anterior.
    pedidos = [e.a.id, e.b.id] * 20
    with ThreadPoolExecutor(max_workers=8) as pool:
        resultados = list(pool.map(sucursales_vistas, pedidos))
    assert all(vistas == esperado[empresa_id] for empresa_id, vistas in zip(pedidos, resultados))

    # Sin empresa, falla cerrado también en el pool real (y la sesión se puede reutilizar).
    sin_empresa = sessionmaker(bind=fabrica_pg.kw["bind"], autoflush=False, autocommit=False)
    with sin_empresa() as db:
        with pytest.raises(EmpresaNoDefinidaError):
            db.scalars(select(Sucursal.id)).all()
        fijar_empresa(db, e.a.id)
        assert set(db.scalars(select(Sucursal.id))) == esperado[e.a.id]
        # Una consulta de otra empresa por id devuelve None, como un id inexistente.
        assert db.get(Sucursal, next(iter(esperado[e.b.id]))) is None


# ---- 4. Los bloqueos existentes siguen pidiendo el lock y el predicado de empresa -----


def test_los_bloqueos_existentes_llevan_for_update_y_el_filtro_de_empresa(
    engine_pg, fabrica_pg, client_pg, dos_empresas_pg
):
    e = dos_empresas_pg
    reserva = reservar(client_pg, e.datos_a)
    _, pago = iniciar_pago(client_pg, e.datos_a)
    capturadas: list[str] = []

    def _capturar(conexion, cursor, sentencia, parametros, contexto, many):
        if "FOR UPDATE" in sentencia:
            capturadas.append(sentencia)

    event.listen(engine_pg, "before_cursor_execute", _capturar)
    try:
        with fabrica_pg() as db:
            fijar_empresa(db, e.a.id)
            reservar_stock(db, e.datos_a["variante_id"], e.datos_a["sucursal_id"], 1)  # bloquea stock
            ReservaRepository().obtener_bloqueado(db, reserva["id"])  # bloquea reserva
            comercial_repo.PagoRepository().obtener_bloqueado(db, pago["id"])  # bloquea pago
            db.rollback()

            # Las mismas filas, pedidas desde la otra empresa: ni se ven, ni se bloquean.
            fijar_empresa(db, e.b.id)
            with pytest.raises(NoEncontradoError):
                ReservaRepository().obtener_bloqueado(db, reserva["id"])
            with pytest.raises(NoEncontradoError):
                comercial_repo.PagoRepository().obtener_bloqueado(db, pago["id"])
            db.rollback()
    finally:
        event.remove(engine_pg, "before_cursor_execute", _capturar)

    tablas = {"stock": "FROM stock", "reserva": "FROM reserva ", "pago": "FROM pago "}
    for tabla, fragmento in tablas.items():
        propias = [q for q in capturadas if fragmento in q]
        assert propias, f"{tabla}: ninguna sentencia FOR UPDATE capturada"
        assert all("empresa_id" in q for q in propias), (tabla, propias)
