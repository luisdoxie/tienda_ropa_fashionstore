"""Tabla `modelo_ml` y `ModeloMLRepository` (E11, pasos 3 y 12): versiones, una sola vigente, poda,
tope de tamaño, artefacto diferido y, sobre todo, aislamiento entre empresas. Todo sobre SQLite en
memoria (la fixture `db_session`); el perfil PostgreSQL está en tests/postgres/test_ml_postgres.py."""

import ast
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, insert, select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictoError, DomainError
from app.core.tenant import EmpresaNoDefinidaError, ModoPlataformaError, en_empresa, fijar_plataforma
from app.inteligencia.ml.limites import ML_MAX_ARTEFACTO_BYTES, ML_VERSIONES_CON_ARTEFACTO
from app.inteligencia.models import TIPOS_MODELO_ML, ModeloML
from app.inteligencia.repository import ModeloMLRepository
from tests.conftest import crear_empresa

REPO = ModeloMLRepository()
DEMANDA = "demanda_semanal"
SEGMENTOS = "segmentos_rfm"


def _guardar(db, tipo=DEMANDA, artefacto=b"modelo", **kwargs):
    datos = {
        "metricas": {"mae": 1.5},
        "parametros": {"semilla": 42},
        "artefacto": artefacto,
        "filas_entrenamiento": 100,
    }
    datos.update(kwargs)
    return REPO.guardar_nueva_version(db, tipo, **datos)


def test_la_tabla_tiene_sus_columnas_restricciones_e_indices(db_session):
    inspector = inspect(db_session.get_bind())
    columnas = {c["name"] for c in inspector.get_columns("modelo_ml")}
    assert {
        "id", "empresa_id", "tipo", "version", "activo", "metricas", "parametros", "artefacto",
        "artefacto_sha256", "artefacto_bytes", "filas_entrenamiento", "datos_desde", "datos_hasta",
        "entrenado_por", "entrenado_en",
    } <= columnas  # fmt: skip
    indices = {i["name"]: i for i in inspector.get_indexes("modelo_ml")}
    assert indices["uq_modelo_ml_activo"]["unique"] and indices["uq_modelo_ml_activo"]["column_names"] == ["empresa_id", "tipo"]
    assert "ix_modelo_ml_empresa_id" in indices
    assert {u["name"] for u in inspector.get_unique_constraints("modelo_ml")} == {"uq_modelo_ml_empresa_tipo_version"}
    assert set(TIPOS_MODELO_ML) == {"demanda_semanal", "segmentos_rfm", "anomalias_ventas"}


def test_la_primera_version_es_la_1_y_queda_vigente(db_session):
    modelo = _guardar(db_session, artefacto=b"abc", datos_desde=None)
    assert (modelo.version, modelo.activo, modelo.tipo) == (1, True, DEMANDA)
    assert modelo.artefacto_sha256 == hashlib.sha256(b"abc").hexdigest()
    assert modelo.artefacto_bytes == 3 and modelo.filas_entrenamiento == 100
    assert REPO.obtener_activo(db_session, DEMANDA).id == modelo.id


def test_una_version_nueva_desactiva_la_anterior(db_session):
    primera = _guardar(db_session)
    segunda = _guardar(db_session, metricas={"mae": 0.9})
    db_session.refresh(primera)
    assert (primera.version, primera.activo) == (1, False)
    assert (segunda.version, segunda.activo) == (2, True)
    assert REPO.obtener_activo(db_session, DEMANDA).version == 2
    assert [m.version for m in REPO.listar_versiones(db_session, DEMANDA)] == [2, 1]
    assert REPO.ultima_version(db_session, DEMANDA) == 2
    assert REPO.obtener_version(db_session, DEMANDA, 1).metricas == {"mae": 1.5}  # las métricas de la vieja se conservan


def test_el_indice_parcial_impide_dos_vigentes_del_mismo_tipo(db_session):
    _guardar(db_session)
    empresa_id = REPO.obtener_activo(db_session, DEMANDA).empresa_id
    with pytest.raises(IntegrityError):
        db_session.execute(
            insert(ModeloML).values(
                empresa_id=empresa_id, tipo=DEMANDA, version=9, activo=True, metricas={}, parametros={},
                filas_entrenamiento=0,
            )
        )  # fmt: skip
        db_session.flush()
    db_session.rollback()


def test_tipos_distintos_conviven_vigentes(db_session):
    demanda = _guardar(db_session, DEMANDA)
    segmentos = _guardar(db_session, SEGMENTOS)
    assert (demanda.version, segmentos.version) == (1, 1)  # la numeración es por tipo
    assert REPO.obtener_activo(db_session, DEMANDA).id == demanda.id
    assert REPO.obtener_activo(db_session, SEGMENTOS).id == segmentos.id
    assert REPO.obtener_activo(db_session, "anomalias_ventas") is None


def test_solo_las_ultimas_tres_versiones_conservan_el_artefacto(db_session):
    for n in range(1, 6):
        _guardar(db_session, artefacto=f"modelo-{n}".encode(), metricas={"mae": float(n)})
    versiones = {m.version: m for m in REPO.listar_versiones(db_session, DEMANDA)}
    assert ML_VERSIONES_CON_ARTEFACTO == 3
    con = {
        v: REPO.obtener_version(db_session, DEMANDA, v, con_artefacto=True).artefacto for v in versiones
    }
    assert con == {1: None, 2: None, 3: b"modelo-3", 4: b"modelo-4", 5: b"modelo-5"}
    # Las podadas conservan métricas y hash: no hay DELETE físico.
    assert versiones[1].metricas == {"mae": 1.0} and versiones[1].artefacto_sha256 == hashlib.sha256(b"modelo-1").hexdigest()
    assert db_session.scalar(select(func.count()).select_from(ModeloML)) == 5


def test_un_modelo_de_mas_de_8_mb_se_rechaza_y_uno_de_exactamente_8_mb_entra(db_session):
    assert ML_MAX_ARTEFACTO_BYTES == 8 * 1024 * 1024
    with pytest.raises(DomainError, match="máximo"):
        _guardar(db_session, artefacto=b"x" * (ML_MAX_ARTEFACTO_BYTES + 1))
    assert db_session.scalar(select(func.count()).select_from(ModeloML)) == 0
    justo = _guardar(db_session, artefacto=b"x" * ML_MAX_ARTEFACTO_BYTES)
    assert justo.artefacto_bytes == ML_MAX_ARTEFACTO_BYTES


def test_los_listados_y_las_consultas_normales_no_cargan_el_artefacto(db_session):
    _guardar(db_session, artefacto=b"x" * 5000)
    db_session.expire_all()
    for modelo in (REPO.obtener_activo(db_session, DEMANDA), *REPO.listar_versiones(db_session, DEMANDA)):
        assert "artefacto" in inspect(modelo).unloaded
    cargado = REPO.obtener_activo(db_session, DEMANDA, con_artefacto=True)
    assert "artefacto" not in inspect(cargado).unloaded and len(cargado.artefacto) == 5000


def test_un_tipo_desconocido_se_rechaza(db_session):
    with pytest.raises(DomainError, match="no soportado"):
        _guardar(db_session, tipo="bola_de_cristal")
    # y la base lo rechaza aunque alguien se salte el repositorio
    with pytest.raises(IntegrityError):
        db_session.execute(
            insert(ModeloML).values(
                empresa_id=db_session.scalar(select(func.min(ModeloML.empresa_id))) or 1, tipo="bola_de_cristal",
                version=1, activo=False, metricas={}, parametros={}, filas_entrenamiento=0,
            )
        )  # fmt: skip
        db_session.flush()
    db_session.rollback()


def test_un_modelo_sin_artefacto_es_valido(db_session):
    modelo = _guardar(db_session, artefacto=None)
    assert modelo.artefacto_sha256 is None and modelo.artefacto_bytes is None


def test_commit_false_deja_la_transaccion_al_llamador(db_session):
    modelo = _guardar(db_session, commit=False)
    assert modelo.id is not None  # ya tiene id (flush)
    db_session.rollback()
    assert REPO.obtener_activo(db_session, DEMANDA) is None  # lo revirtió quien tenía la transacción


def test_dos_entrenamientos_que_eligen_la_misma_version_chocan_con_conflicto(db_session, monkeypatch):
    _guardar(db_session)
    monkeypatch.setattr(REPO, "ultima_version", lambda db, tipo: 0)  # simula la carrera: ambos creen que van por la 1
    with pytest.raises(ConflictoError):
        _guardar(db_session)
    db_session.rollback()
    monkeypatch.undo()
    assert [m.version for m in REPO.listar_versiones(db_session, DEMANDA)] == [1]
    assert REPO.obtener_activo(db_session, DEMANDA).version == 1  # la vigente no se perdió


# ---- Aislamiento entre empresas (D22) ---------------------------------------------------------


@pytest.fixture()
def dos_empresas(db_session):
    a = crear_empresa(db_session, "empresa-ml-a", "profesional").id
    b = crear_empresa(db_session, "empresa-ml-b", "profesional").id
    return a, b


def test_el_modelo_de_una_empresa_no_aparece_en_otra(db_session, dos_empresas):
    a, b = dos_empresas
    with en_empresa(db_session, a):
        modelo_a = _guardar(db_session, artefacto=b"secreto-de-A", metricas={"mae": 1.0})
        id_a = modelo_a.id
    with en_empresa(db_session, b):
        assert REPO.obtener_activo(db_session, DEMANDA) is None
        assert REPO.obtener_version(db_session, DEMANDA, 1, con_artefacto=True) is None
        assert REPO.listar_versiones(db_session, DEMANDA) == []
        assert db_session.get(ModeloML, id_a) is None  # ni por id
        assert db_session.scalar(select(ModeloML.id).where(ModeloML.id == id_a)) is None
        assert REPO.ultima_version(db_session, DEMANDA) == 0  # su numeración arranca sola
    with en_empresa(db_session, a):
        assert REPO.obtener_activo(db_session, DEMANDA, con_artefacto=True).artefacto == b"secreto-de-A"


def test_cada_empresa_tiene_su_propia_version_1_vigente_del_mismo_tipo(db_session, dos_empresas):
    a, b = dos_empresas
    for empresa in (a, b):
        with en_empresa(db_session, empresa):
            nuevo = _guardar(db_session, metricas={"empresa": empresa})
            assert (nuevo.version, nuevo.activo, nuevo.empresa_id) == (1, True, empresa)
    with en_empresa(db_session, b):
        _guardar(db_session)  # la versión 2 de B no toca a A
    with en_empresa(db_session, a):
        assert [m.version for m in REPO.listar_versiones(db_session, DEMANDA)] == [1]
        assert REPO.obtener_activo(db_session, DEMANDA).metricas == {"empresa": a}
    with en_empresa(db_session, b):
        assert [m.version for m in REPO.listar_versiones(db_session, DEMANDA)] == [2, 1]


def test_entrenar_sin_empresa_falla_cerrado(db_session):
    fijar_plataforma(db_session)
    with pytest.raises(ModoPlataformaError):
        REPO.obtener_activo(db_session, DEMANDA)
    db_session.info.pop("empresa_id", None)


def test_la_poda_de_una_empresa_no_toca_los_artefactos_de_otra(db_session, dos_empresas):
    a, b = dos_empresas
    with en_empresa(db_session, a):
        _guardar(db_session, artefacto=b"A-1")
    with en_empresa(db_session, b):
        for n in range(1, 6):
            _guardar(db_session, artefacto=f"B-{n}".encode())
    with en_empresa(db_session, a):
        assert REPO.obtener_version(db_session, DEMANDA, 1, con_artefacto=True).artefacto == b"A-1"


# ---- El subpaquete ml/ es cálculo puro --------------------------------------------------------

ML = Path(__file__).resolve().parents[3] / "app" / "inteligencia" / "ml"
PROHIBIDOS = ("app.comercial", "app.catalogo", "app.plataforma", "sqlalchemy", "app.core.database")
PESADOS = ("numpy", "scipy", "sklearn", "joblib", "threadpoolctl")


def _importados(arbol, solo_nivel_modulo):
    nodos = arbol.body if solo_nivel_modulo else ast.walk(arbol)
    encontrados = []
    for nodo in nodos:
        if isinstance(nodo, ast.Import):
            encontrados += [alias.name for alias in nodo.names]
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            encontrados.append(nodo.module)
    return encontrados


def test_ningun_archivo_de_ml_importa_paquetes_de_negocio_ni_recibe_session():
    archivos = sorted(ML.glob("*.py"))
    assert archivos, "no se encontró el subpaquete ml/"
    for archivo in archivos:
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for modulo in _importados(arbol, solo_nivel_modulo=False):
            assert not modulo.startswith(PROHIBIDOS), f"{archivo.name} importa {modulo}"
        nombres = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
        parametros = {a.arg for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef) for a in n.args.args}
        assert "Session" not in nombres, f"{archivo.name} usa Session"
        assert not parametros & {"db", "session", "sesion"}, f"{archivo.name} recibe una sesión de base de datos"


def test_ml_solo_importa_numpy_y_scikit_learn_dentro_de_las_funciones():
    for archivo in sorted(ML.glob("*.py")):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for modulo in _importados(arbol, solo_nivel_modulo=True):
            assert not modulo.split(".")[0] in PESADOS, f"{archivo.name} importa {modulo} a nivel de módulo"
