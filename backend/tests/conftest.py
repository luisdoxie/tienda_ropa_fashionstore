import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "clave-de-pruebas")
os.environ.setdefault("TAREAS_TOKEN", "token-de-pruebas")
os.environ.setdefault("TAREAS_AUTOMATICAS", "false")
# Sin valor por defecto en el código (regla 9): los tests firman los
# webhooks con estos.
os.environ.setdefault("LIBELULA_WEBHOOK_SECRET", "secreto-libelula-de-pruebas")
os.environ.setdefault("PAYPAL_WEBHOOK_SECRET", "secreto-paypal-de-pruebas")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.rate_limit import limiter
from app.main import app
from app.catalogo import models as _catalogo_models  # noqa: F401  (registra las tablas)
from app.catalogo.repository import VW_INVENTARIO_CONSOLIDADO_SQL
from app.comercial import models as _comercial_models  # noqa: F401  (registra las tablas)
from app.plataforma import models as _plataforma_models  # noqa: F401  (registra las tablas)
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from scripts.seed_entregas import seed as seed_entregas
from scripts.seed_inventario import seed as seed_inventario
from scripts.seed_pagos import seed as seed_pagos
from scripts.seed_reservas import seed as seed_reservas
from scripts.seed_seguridad import seed as seed_seguridad
from scripts.seed_ventas import seed as seed_ventas


@pytest.fixture(autouse=True)
def _limpiar_limite_de_trafico():
    """Todas las pruebas comparten la IP del cliente de pruebas, así que
    comparten el balde del limiter: sin esto, las fixtures que hacen login
    agotan el límite de /auth/login y el resto de la suite recibe 429 en vez
    del token. Se resetea por prueba para que cada una arranque con el balde
    vacío, sin desactivar el limiter (queda activo y se comporta como en
    producción dentro de cada prueba)."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Receta oficial de SQLAlchemy para SQLite (docs "Serializable isolation /
    # Savepoints / Transactional DDL"): el driver pysqlite no emite BEGIN por su
    # cuenta, así que un SAVEPOINT (begin_nested, que usan los repositorios con
    # `commit=False`) abría y CONFIRMABA la transacción al liberarse, y un
    # rollback posterior no deshacía nada. Con BEGIN explícito, SQLite se
    # comporta como Postgres: savepoints y rollback de la unidad de trabajo.
    @event.listens_for(engine, "connect")
    def _sin_begin_implicito(dbapi_conexion, _registro):
        dbapi_conexion.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_explicito(conexion):
        conexion.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(VW_INVENTARIO_CONSOLIDADO_SQL))
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    seed_seguridad(session)
    seed_inventario(session)
    seed_reservas(session)
    seed_ventas(session)
    seed_pagos(session)
    seed_entregas(session)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        # rollback (no close) al final de cada request: simula el
        # `finally: db.close()` de get_db real -- si un endpoint lanza a
        # mitad de una transacción con varios flush() antes del commit
        # final (p. ej. RegistrarRecepcionMercaderia.registrar), lo que quedó sin
        # commitear no debe filtrarse al siguiente request de este mismo
        # test. rollback() y no close() para no dejar detached los objetos
        # que ya tienen otros fixtures (p. ej. admin_headers).
        try:
            yield db_session
        finally:
            db_session.rollback()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(client, email, password):
    respuesta = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return respuesta.json()["access_token"]


@pytest.fixture()
def admin_headers(client, db_session):
    usuario_repo = UsuarioRepository()
    usuario = usuario_repo.crear(
        db_session,
        UsuarioCrear(nombre="Admin", apellido="Root", email="admin@example.com", password="claveSegura123"),
    )
    usuario_repo.asignar_roles(db_session, usuario, ["administrador"])

    token = _login(client, "admin@example.com", "claveSegura123")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def cliente_headers(client):
    # Vía /auth/registro (no usuario_repo.crear a mano): así el usuario
    # también tiene su fila en `cliente`, igual que en producción. Varios
    # endpoints (favoritos, perfil) la necesitan.
    client.post(
        "/api/v1/auth/registro",
        json={
            "nombre": "Cli",
            "apellido": "Ente",
            "email": "cliente@example.com",
            "password": "claveSegura123",
        },
    )
    token = _login(client, "cliente@example.com", "claveSegura123")
    return {"Authorization": f"Bearer {token}"}


def crear_staff(
    client, admin_headers, db_session, *, rol: str, cargo: str, sucursal_id: int, email: str
):
    """No es un fixture (necesita `sucursal_id`, que cada test arma
    distinto): un helper que los tests llaman directo. Devuelve los headers
    del empleado ya logueado, con su rol y su fila en `empleado`."""
    usuario_repo = UsuarioRepository()
    usuario = usuario_repo.crear(
        db_session,
        UsuarioCrear(nombre="Staff", apellido="Prueba", email=email, password="claveSegura123"),
    )
    usuario_repo.asignar_roles(db_session, usuario, [rol])

    client.post(
        "/api/v1/empleados",
        json={"usuario_id": usuario.id, "sucursal_id": sucursal_id, "cargo": cargo},
        headers=admin_headers,
    )

    token = _login(client, email, "claveSegura123")
    return {"Authorization": f"Bearer {token}"}


def crear_cajero(client, admin_headers, db_session, *, sucursal_id: int, email: str = "cajero@example.com"):
    return crear_staff(
        client, admin_headers, db_session, rol="cajero", cargo="Cajero", sucursal_id=sucursal_id, email=email
    )


class EspiaBloqueos:
    """Registra cómo se piden los bloqueos de stock (T3). SQLite no aplica
    FOR UPDATE, así que lo único verificable es el ORDEN en que se piden:
    cada evento es ("lote", [claves]) (pasada previa ordenada) o
    ("linea", clave) (bloqueo línea por línea)."""

    def __init__(self) -> None:
        self.eventos: list[tuple[str, object]] = []

    def lotes(self) -> list[list[tuple[int, int]]]:
        return [dato for tipo, dato in self.eventos if tipo == "lote"]

    def orden_de_adquisicion(self) -> list[tuple[int, int]]:
        """Claves (variante_id, sucursal_id) en el orden en que se tocaron por
        primera vez: lo que decide si hay deadlock entre dos lotes."""
        vistas: list[tuple[int, int]] = []
        for tipo, dato in self.eventos:
            for clave in dato if tipo == "lote" else [dato]:
                if clave not in vistas:
                    vistas.append(clave)
        return vistas


@pytest.fixture()
def espia_bloqueos(monkeypatch):
    from app.catalogo.repository import StockRepository

    espia = EspiaBloqueos()
    original_lote = StockRepository.bloquear_existentes
    original_linea = StockRepository.obtener_o_crear_bloqueado

    def lote(self, db, claves):
        espia.eventos.append(("lote", list(claves)))
        return original_lote(self, db, claves)

    def linea(self, db, variante_id, sucursal_id):
        espia.eventos.append(("linea", (variante_id, sucursal_id)))
        return original_linea(self, db, variante_id, sucursal_id)

    monkeypatch.setattr(StockRepository, "bloquear_existentes", lote)
    monkeypatch.setattr(StockRepository, "obtener_o_crear_bloqueado", linea)
    return espia
