"""E09: lo común de las pruebas de los reportes generativos (CU-23).

- `hoy_fijo`: "hoy" es el 20/09/2026, así que "este mes" o "los últimos 7 días" caen sobre los datos de
  `sembrar_mundo_reportes` (septiembre de 2026).
- `dos_profesionales`: dos empresas con plan Profesional (tienda-a y tienda-b) y su administrador.
  (`dos_empresas` trae una Básica, que no puede pedir reportes con IA.)
- `mundo_ia`: esas dos empresas con ventas y stock (A con m=1, B con m=3: mismos nombres, cifras distintas).
- `interprete_falso`: reemplaza al intérprete de Groq; ninguna prueba sale a la red.
"""

import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.comercial.repository import VW_VENTAS_DETALLE_V2_SQL
from app.core.rate_limit import limiter
from app.core.tenant import empresa_de, fijar_empresa
from app.inteligencia.groq_cliente import ResultadoInterpretacion
from app.inteligencia.schemas import SolicitudReporte
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.comercial.ayudas_reportes_ia import sembrar_mundo_reportes
from tests.conftest import EmpresaDePrueba, crear_empresa, token_de

API = "/api/v1/reportes-ia"
MODULO_CU = "app.inteligencia.casos_uso.cu23_generar_reportes_con_ia"
HOY = dt.date(2026, 9, 20)
CLAVE = "claveSegura123"


@pytest.fixture(autouse=True)
def _limpiar_limite():
    # 15/min por IP y todas las pruebas comparten la IP del cliente de pruebas.
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def _sin_clave_groq(monkeypatch):
    """Aunque la máquina tenga GROQ_API_KEY, las pruebas no la usan: Groq responde `sin_clave` salvo que
    la prueba reemplace al intérprete."""
    from app.inteligencia import groq_cliente

    ajustes = groq_cliente.get_settings().model_copy(update={"groq_api_key": ""})
    monkeypatch.setattr(groq_cliente, "get_settings", lambda: ajustes)


@pytest.fixture()
def hoy_fijo(monkeypatch):
    monkeypatch.setattr("app.core.tiempo.hoy_utc", lambda: HOY)
    return HOY


@pytest.fixture()
def dos_profesionales(db_session):
    original = empresa_de(db_session)
    repo = UsuarioRepository()
    creadas = {}
    for clave, codigo in (("a", "tienda-a"), ("b", "tienda-b")):
        empresa = crear_empresa(db_session, codigo, plan="profesional")
        fijar_empresa(db_session, empresa.id)
        admin = repo.crear(
            db_session,
            UsuarioCrear(nombre="Admin", apellido=clave.upper(), email=f"admin@{codigo}.example.com", password=CLAVE),
        )
        repo.asignar_roles(db_session, admin, ["administrador"])
        creadas[clave] = EmpresaDePrueba(
            id=empresa.id, codigo=codigo, admin_id=admin.id, headers=token_de(db_session, admin)
        )
    fijar_empresa(db_session, original)
    return SimpleNamespace(**creadas)


@pytest.fixture()
def mundo_ia(db_session, dos_profesionales, hoy_fijo):
    """A (m=1) y B (m=3) con las ventas y el stock de `sembrar_mundo_reportes`, y la vista de ventas."""
    db_session.execute(text(VW_VENTAS_DETALLE_V2_SQL))
    db_session.commit()
    datos_a = sembrar_mundo_reportes(db_session, dos_profesionales.a.id, m=1)
    datos_b = sembrar_mundo_reportes(db_session, dos_profesionales.b.id, m=3)
    return SimpleNamespace(a=dos_profesionales.a, b=dos_profesionales.b, datos_a=datos_a, datos_b=datos_b)


class InterpreteFalso:
    """Devuelve lo que se le diga y guarda lo que recibió."""

    def __init__(self, solicitud: SolicitudReporte | None, error: str | None = None, origen: str = "groq") -> None:
        self._resultado = ResultadoInterpretacion(solicitud, origen, error)
        self.textos: list[str] = []

    def interpretar(self, texto, funcionalidades, **kwargs):
        self.textos.append(texto)
        return self._resultado


@pytest.fixture()
def interprete_falso(monkeypatch):
    """`interprete_falso(solicitud_o_dict, error=None)`: el intérprete de Groq devuelve eso. Si se pasa
    un dict se arma SIN validar nada más que la forma de SolicitudReporte (lo hostil se prueba con
    `solicitud_cruda`, que salta la validación)."""

    def _poner(solicitud=None, error: str | None = None) -> InterpreteFalso:
        if isinstance(solicitud, dict):
            solicitud = SolicitudReporte.model_validate(solicitud)
        falso = InterpreteFalso(solicitud, error)
        monkeypatch.setattr(f"{MODULO_CU}.obtener_interprete_reportes", lambda: falso)
        return falso

    return _poner


def ejecutar(client, headers, **cuerpo):
    return client.post(f"{API}/ejecutar", json=cuerpo, headers=headers)


def interpretar(client, headers, **cuerpo):
    return client.post(f"{API}/interpretar", json=cuerpo, headers=headers)


def filas_de(respuesta) -> list[dict]:
    cuerpo = respuesta.json()
    assert respuesta.status_code == 200, respuesta.text
    assert cuerpo["estado"] == "ok", cuerpo
    return cuerpo["reporte"]["filas"]
