"""Generación del probador en segundo plano: abre su propia sesión (sin
empresa), así que recibe la de la petición como parámetro explícito."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.catalogo.casos_uso import cu11_probar_prenda_con_ia as cu11
from app.catalogo.models import ProbadorGeneracion
from app.catalogo.repository import GeneracionRepository
from app.core import storage
from app.core.tenant import empresa_de, fijar_empresa
from app.plataforma.models import Cliente
from tests.comercial._datos_empresa import sembrar_empresa


class _ProveedorFalso:
    nombre = "fake"

    def generar(self, foto_cliente: bytes, imagen_prenda: bytes) -> bytes:
        return b"png-generado-falso"


@pytest.fixture(autouse=True)
def _entorno_del_segundo_plano(monkeypatch, db_session):
    """SessionLocal -> sesiones nuevas sobre el engine de la prueba (sin
    empresa, como las de producción); sin red ni Cloudinary."""
    fabrica = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(cu11, "SessionLocal", fabrica)
    monkeypatch.setattr(cu11, "_descargar_bytes", lambda url: b"prenda")
    monkeypatch.setattr(storage, "subir_imagen", lambda contenido, carpeta, *, formato_forzado=None: f"{carpeta}/res")
    monkeypatch.setattr(storage, "url_probador", lambda public_id: f"https://cdn.example/{public_id}.png")


def _generacion_en(db_session, empresa, datos) -> int:
    """Una generación 'en_proceso' creada dentro de `empresa`."""
    original = empresa_de(db_session)
    fijar_empresa(db_session, empresa.id)
    try:
        cliente_id = db_session.scalar(select(Cliente.id))
        generacion = GeneracionRepository().crear(db_session, cliente_id, datos["variante_id"], "h" * 64)
        generacion_id = generacion.id
        db_session.commit()  # la tarea usa otra sesión sobre la MISMA conexión: sin transacción abierta
        return generacion_id
    finally:
        fijar_empresa(db_session, original)


def _leer(db_session, empresa, generacion_id) -> tuple[str, str | None]:
    """(estado, url_resultado) de la generación, vista desde `empresa`."""
    original = empresa_de(db_session)
    fijar_empresa(db_session, empresa.id)
    try:
        db_session.expire_all()
        fila = db_session.get(ProbadorGeneracion, generacion_id)
        return fila.estado, fila.url_resultado
    finally:
        db_session.commit()
        fijar_empresa(db_session, original)


@pytest.fixture()
def generaciones(client_por_peticion, dos_empresas, db_session):
    datos_a = sembrar_empresa(client_por_peticion, db_session, dos_empresas.a)
    datos_b = sembrar_empresa(client_por_peticion, db_session, dos_empresas.b)
    return {
        "a": _generacion_en(db_session, dos_empresas.a, datos_a),
        "b": _generacion_en(db_session, dos_empresas.b, datos_b),
    }


def test_la_tarea_actualiza_la_generacion_de_su_empresa(dos_empresas, generaciones, db_session):
    cu11._ejecutar_generacion(generaciones["a"], "https://x/prenda.png", b"foto", _ProveedorFalso(), dos_empresas.a.id)

    estado, url = _leer(db_session, dos_empresas.a, generaciones["a"])
    assert estado == "completado"
    assert url.startswith("https://cdn.example/")
    # La generación de la otra empresa no se tocó.
    assert _leer(db_session, dos_empresas.b, generaciones["b"]) == ("en_proceso", None)


def test_con_la_empresa_equivocada_no_encuentra_la_generacion(dos_empresas, generaciones, db_session):
    # La tarea de la empresa B apunta al id de una generación de A: no la ve.
    cu11._ejecutar_generacion(generaciones["a"], "https://x/prenda.png", b"foto", _ProveedorFalso(), dos_empresas.b.id)

    # Ni completada ni modificada desde la otra empresa; la de B tampoco cambia.
    assert _leer(db_session, dos_empresas.a, generaciones["a"]) == ("en_proceso", None)
    assert _leer(db_session, dos_empresas.b, generaciones["b"]) == ("en_proceso", None)
