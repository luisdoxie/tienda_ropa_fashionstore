"""E11 en PostgreSQL real: la tabla `modelo_ml` creada por la migración (tipos jsonb y bytea, índice
parcial único), el artefacto de ~1 MB y el aislamiento entre empresas. Corre solo con TEST_DATABASE_URL
(base `_test`)."""

import hashlib

import pytest
from sqlalchemy import func, inspect, insert, select
from sqlalchemy.exc import IntegrityError

from app.core.tenant import en_empresa
from app.inteligencia.models import ModeloML
from app.inteligencia.repository import ModeloMLRepository
from app.plataforma.models import Empresa

REPO = ModeloMLRepository()
DEMANDA = "demanda_semanal"


def test_la_migracion_crea_la_tabla_con_bytea_jsonb_y_el_indice_parcial_unico(engine_pg):
    inspector = inspect(engine_pg)
    columnas = {c["name"]: c for c in inspector.get_columns("modelo_ml")}
    assert columnas["artefacto"]["type"].__class__.__name__ == "BYTEA" and columnas["artefacto"]["nullable"]
    assert columnas["metricas"]["type"].__class__.__name__ == "JSONB" and not columnas["metricas"]["nullable"]
    assert columnas["parametros"]["type"].__class__.__name__ == "JSONB"
    assert not columnas["empresa_id"]["nullable"]
    indices = {i["name"]: i for i in inspector.get_indexes("modelo_ml")}
    assert indices["uq_modelo_ml_activo"]["unique"] and indices["uq_modelo_ml_activo"]["column_names"] == ["empresa_id", "tipo"]
    assert "activo" in indices["uq_modelo_ml_activo"]["dialect_options"]["postgresql_where"]


def test_un_artefacto_de_1_mb_se_guarda_y_se_lee_igual(fabrica_pg):
    contenido = bytes(range(256)) * 4096  # 1 MiB con todos los valores de byte
    with fabrica_pg() as db:
        REPO.guardar_nueva_version(
            db, DEMANDA, metricas={"mae": 1.2, "r2": 0.8}, parametros={"semilla": 42, "k": [2, 3]},
            artefacto=contenido, filas_entrenamiento=3120,
        )  # fmt: skip
    with fabrica_pg() as db:
        modelo = REPO.obtener_activo(db, DEMANDA, con_artefacto=True)
        assert len(modelo.artefacto) == 1024 * 1024 and modelo.artefacto == contenido
        assert modelo.artefacto_sha256 == hashlib.sha256(contenido).hexdigest()
        assert modelo.metricas == {"mae": 1.2, "r2": 0.8} and modelo.parametros["k"] == [2, 3]  # JSONB ida y vuelta
    with fabrica_pg() as db:  # el listado no trae el BYTEA
        assert "artefacto" in inspect(REPO.listar_versiones(db, DEMANDA)[0]).unloaded


def test_la_base_rechaza_dos_versiones_vigentes_del_mismo_tipo(fabrica_pg):
    with fabrica_pg() as db:
        modelo = REPO.guardar_nueva_version(
            db, DEMANDA, metricas={}, parametros={}, artefacto=b"a", filas_entrenamiento=1
        )  # fmt: skip
        empresa_id = modelo.empresa_id
    with fabrica_pg() as db:
        with pytest.raises(IntegrityError):
            db.execute(
                insert(ModeloML).values(
                    empresa_id=empresa_id, tipo=DEMANDA, version=7, activo=True, metricas={}, parametros={},
                    filas_entrenamiento=1,
                )
            )  # fmt: skip
            db.flush()
        db.rollback()


def test_el_modelo_de_una_empresa_no_lo_ve_otra_y_cada_una_numera_sola(fabrica_pg):
    with fabrica_pg() as db:
        REPO.guardar_nueva_version(db, DEMANDA, metricas={"de": "A"}, parametros={}, artefacto=b"A", filas_entrenamiento=1)
        otra = Empresa(nombre="Otra", codigo="otra-ml", activo=True)
        db.add(otra)
        db.commit()
        otra_id = otra.id
    with fabrica_pg() as db:
        with en_empresa(db, otra_id):
            assert REPO.obtener_activo(db, DEMANDA) is None
            assert db.scalar(select(func.count()).select_from(ModeloML)) == 0
            propio = REPO.guardar_nueva_version(
                db, DEMANDA, metricas={"de": "B"}, parametros={}, artefacto=b"B", filas_entrenamiento=1
            )  # fmt: skip
            assert (propio.version, propio.empresa_id) == (1, otra_id)  # ambas son la versión 1 vigente
    with fabrica_pg() as db:
        assert REPO.obtener_activo(db, DEMANDA, con_artefacto=True).artefacto == b"A"  # la de A sigue intacta
