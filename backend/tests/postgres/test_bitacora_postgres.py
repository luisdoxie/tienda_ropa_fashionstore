"""E06 en PostgreSQL real: la migración, la concurrencia al escribir y el uso del
índice de la consulta principal. Corre solo con TEST_DATABASE_URL (base `_test`)."""

import datetime as dt

from sqlalchemy import func, inspect, select, text

from app.plataforma import politicas
from app.plataforma.models import Bitacora
from tests.postgres.paralelo import ejecutar_en_paralelo


def test_la_migracion_crea_la_tabla_los_tres_indices_y_la_columna_jsonb(engine_pg):
    inspector = inspect(engine_pg)
    assert "bitacora" in inspector.get_table_names()
    columnas = {c["name"]: c for c in inspector.get_columns("bitacora")}
    assert set(columnas) == {"id", "empresa_id", "usuario_id", "entidad", "entidad_id", "accion", "datos", "ip", "creado_en"}
    assert columnas["datos"]["type"].__class__.__name__ == "JSONB"
    assert columnas["empresa_id"]["nullable"] and columnas["usuario_id"]["nullable"]
    assert not columnas["entidad"]["nullable"] and not columnas["accion"]["nullable"]
    assert columnas["accion"]["type"].length == 40
    indices = {i["name"]: i["column_names"] for i in inspector.get_indexes("bitacora")}
    assert indices == {
        "ix_bitacora_empresa_fecha": ["empresa_id", "creado_en"],
        "ix_bitacora_empresa_entidad": ["empresa_id", "entidad", "entidad_id"],
        "ix_bitacora_usuario_fecha": ["usuario_id", "creado_en"],
    }


def test_20_hilos_registrando_y_confirmando_a_la_vez_dejan_20_filas_con_ids_distintos(fabrica_pg):
    def registrar(i):
        def operacion(db):
            fila = politicas.registrar_bitacora(db, None, "usuario", i, "crear", {"n": i}, "10.0.0.1")
            db.commit()
            return fila.id

        return operacion

    resultados = ejecutar_en_paralelo(fabrica_pg, [registrar(i) for i in range(20)])
    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    ids = [r.valor for r in resultados]
    assert len(set(ids)) == 20
    with fabrica_pg() as db:
        assert db.scalar(select(func.count()).select_from(Bitacora)) == 20


def test_un_hilo_que_hace_rollback_no_deja_fila_y_los_demas_si(fabrica_pg):
    def confirma(i):
        def operacion(db):
            politicas.registrar_bitacora(db, None, "usuario", i, "crear")
            db.commit()

        return operacion

    def revierte(db):
        politicas.registrar_bitacora(db, None, "usuario", 999, "crear")
        db.rollback()

    resultados = ejecutar_en_paralelo(fabrica_pg, [confirma(i) for i in range(5)] + [revierte])
    assert all(r.ok for r in resultados)
    with fabrica_pg() as db:
        assert sorted(db.scalars(select(Bitacora.entidad_id))) == [0, 1, 2, 3, 4]


def test_los_datos_se_guardan_como_jsonb_y_se_consultan_por_clave(fabrica_pg):
    with fabrica_pg() as db:
        politicas.registrar_bitacora(db, None, "suscripcion", 3, "cambiar_plan", {"plan_antes": "basico", "plan_despues": "profesional"})
        politicas.registrar_bitacora(db, None, "usuario", 1, "crear", {"password": "no-debe-guardarse"})
        db.commit()
        encontrada = db.scalar(select(Bitacora.entidad_id).where(Bitacora.datos["plan_despues"].as_string() == "profesional"))
        assert encontrada == 3
        guardada = db.scalar(select(Bitacora.datos).where(Bitacora.entidad == "usuario"))
        assert guardada == {"password": "[omitido]"}


def test_la_consulta_principal_usa_el_indice_de_empresa_y_fecha(fabrica_pg, engine_pg):
    ahora = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    with fabrica_pg() as db:
        for i in range(300):
            db.add(
                Bitacora(
                    empresa_id=1 if i % 3 else None, entidad="usuario", entidad_id=i, accion="crear",
                    creado_en=ahora - dt.timedelta(minutes=i),
                )
            )
        db.commit()
    with engine_pg.connect() as conexion:
        conexion.execute(text("ANALYZE bitacora"))
        conexion.execute(text("SET enable_seqscan = off"))  # con una tabla chica el planificador preferiría recorrerla entera
        plan = "\n".join(
            fila[0]
            for fila in conexion.execute(
                text(
                    "EXPLAIN SELECT * FROM bitacora WHERE empresa_id = 1 AND creado_en >= :desde "
                    "ORDER BY creado_en DESC, id DESC LIMIT 20"
                ),
                {"desde": ahora - dt.timedelta(days=1)},
            )
        )
    assert "ix_bitacora_empresa_fecha" in plan, plan
