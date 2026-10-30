"""Analítica ML por HTTP (CU-24, E12) en PostgreSQL real. Corre solo con TEST_DATABASE_URL (base `_test`).

Lo que SQLite no puede demostrar: el BYTEA del artefacto vuelve íntegro de la base (misma huella, calculada también por
PostgreSQL), el flujo completo entrenar -> estado -> demanda -> segmentos -> anomalías -> reposición -> panel con DOS
empresas y sesiones nuevas por petición, el aislamiento con la base real y la invalidación de la caché de modelos al
reentrenar. Son TRES modelos por empresa (demanda, segmentos y anomalías) y cinco rutas de consulta.

Escenario: FashionStore (A, empresa 1) y Chaski Sport (B), pobladas con `scripts.poblar_demo` y con su historial
sintético reducido. La fecha de la aplicación se fija en `HOY` para que el entrenamiento por HTTP use los mismos datos
que el resto de las pruebas del ML y no dependa del reloj.
"""

import datetime as dt
import hashlib
import json
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.catalogo import politicas as catalogo_politicas
from app.comercial import politicas as comercial_politicas
from app.core.database import get_db
from app.core.deps import ParametrosPeriodo
from app.core.tenant import en_empresa
from app.inteligencia.casos_uso import cu24_analizar_con_machine_learning as cu24
from app.inteligencia.casos_uso.cu24_analizar_con_machine_learning import (
    CACHE_MODELOS,
    LIMITE_PRODUCTOS_DE_EXISTENCIAS,
    TIPO_ANOMALIAS,
    TIPO_DEMANDA,
    TIPO_SEGMENTOS,
)
from app.inteligencia.ml import anomalias as ml_anomalias
from app.inteligencia.ml import demanda as ml_demanda
from app.inteligencia.ml import persistencia, reposicion as ml_reposicion, segmentos as ml_segmentos
from app.inteligencia.ml.limites import ML_MAX_CLIENTES, ML_MAX_SEMANAS
from app.inteligencia.models import ModeloML
from app.inteligencia.repository import ModeloMLRepository
from app.main import app
from app.plataforma.models import Sucursal
from scripts.poblar_demo import seed
from tests.inteligencia._analitica_comun import FIN, HOY, cabeceras_de, cargar_historia, entrenar, id_de
from tests.inteligencia.ml._escenario import PASSWORD, organizaciones
from tests.scripts._prendas_falsas import crear_carpeta

REPO = ModeloMLRepository()
A, B = "fashionstore", "chaski-sport"
RUTA = "/api/v1/analitica"
TIPOS = (TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS)  # el orden en que `/estado` los lista


@pytest.fixture()
def http(engine_pg):
    """Cliente HTTP contra PostgreSQL con una sesión NUEVA y SIN empresa por petición, como en producción (el
    `client_pg` de conftest nace en la empresa 1 y rechazaría el token de otra empresa)."""
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
def mundo(fabrica_pg, http, tmp_path, monkeypatch):
    """A y B pobladas, con historial y SIN entrenar; con las cabeceras de cada administrador."""
    monkeypatch.setattr(cu24, "hoy_utc", lambda: HOY)  # el entrenamiento por HTTP usa hasta = HOY - 1 = FIN
    with fabrica_pg() as db:
        seed(
            db, ejecutar=True, password=PASSWORD, origen=crear_carpeta(tmp_path),
            organizaciones=organizaciones()[:2], con_fotos=False,
        )  # fmt: skip
        cargar_historia(db, A)
        cargar_historia(db, B, perfil="B")
        ids = {A: id_de(db, A), B: id_de(db, B)}
        cabeceras = {A: cabeceras_de(db, A), B: cabeceras_de(db, B)}
    for empresa_id in ids.values():
        CACHE_MODELOS.invalidar(empresa_id)  # la caché es del proceso: nada de pruebas anteriores
    yield SimpleNamespace(fabrica=fabrica_pg, http=http, id=ids, h=cabeceras)
    for empresa_id in ids.values():
        CACHE_MODELOS.invalidar(empresa_id)


def _get(mundo, empresa: str, ruta: str, **params):
    return mundo.http.get(f"{RUTA}{ruta}", headers=mundo.h[empresa], params=params or None)


def _ok(respuesta) -> dict:
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _entrenar_http(mundo, empresa: str, tipos: list[str] | None = None) -> dict:
    return _ok(mundo.http.post(f"{RUTA}/entrenar", headers=mundo.h[empresa], json={"tipos": tipos} if tipos else {}))


def _lunes(dia: dt.date) -> dt.date:
    return dia - dt.timedelta(days=dia.weekday())


def _serie(mundo, empresa: str) -> list[dict]:
    with mundo.fabrica() as db, en_empresa(db, mundo.id[empresa]):
        periodo = ParametrosPeriodo(desde=FIN - dt.timedelta(weeks=ML_MAX_SEMANAS), hasta=FIN)
        return comercial_politicas.reporte_ventas_serie_diaria(db, periodo, desglose=("categoria",))


def _rfm(mundo, empresa: str) -> list[dict]:
    with mundo.fabrica() as db, en_empresa(db, mundo.id[empresa]):
        return comercial_politicas.reporte_rfm_clientes(db, FIN, dias=365, tope=ML_MAX_CLIENTES)


def _modelo_guardado(mundo, empresa: str, tipo: str) -> dict:
    """El artefacto VIGENTE leído de PostgreSQL y deserializado verificando su huella (lo que usa la API, pero sin ella)."""
    fila = _fila_completa(mundo, empresa, tipo)
    return persistencia.deserializar(fila.artefacto, fila.artefacto_sha256)


def _anomalias_directas(mundo, empresa: str, dias: int) -> list[tuple]:
    """Lo que `/anomalias` debe responder, calculado SIN la API: el artefacto guardado y las mismas filas por sucursal de
    `comercial` (la ventana pedida más las 8 semanas anteriores, hasta ayer = FIN) pasados a `detectar_anomalias`."""
    modelo = _modelo_guardado(mundo, empresa, TIPO_ANOMALIAS)
    with mundo.fabrica() as db, en_empresa(db, mundo.id[empresa]):
        periodo = ParametrosPeriodo(desde=FIN - dt.timedelta(days=dias + 56), hasta=FIN)
        filas = comercial_politicas.reporte_ventas_serie_diaria(db, periodo, desglose=("sucursal",))
    detectadas = ml_anomalias.detectar_anomalias(modelo, filas, FIN, dias)
    return [(a.fecha.isoformat(), a.sucursal_id, a.sucursal, a.total_ventas, a.esperado, a.desviacion_pct, a.severidad) for a in detectadas]


def _anomalias_de_la_api(cuerpo: dict) -> list[tuple]:
    return [
        (a["fecha"], a["sucursal_id"], a["sucursal"], a["total_ventas"], a["esperado"], a["desviacion_pct"], a["severidad"])
        for a in cuerpo["anomalias"]
    ]


CAMPOS_REPOSICION = (
    "categoria_id", "categoria", "disponible", "demanda_semanal_promedio", "semanas_cobertura", "agotado_en_semana", "estado",
    "sugerencia_unidades",
)  # fmt: skip


def _reposicion_directa(mundo, empresa: str, semanas: int) -> list[tuple]:
    """Lo que `/reposicion` debe responder, sin la API: el modelo de demanda guardado, lo disponible por categoría que
    entrega `catalogo.politicas.reporte_existencias_por_producto` y `calcular_reposicion`."""
    modelo = _modelo_guardado(mundo, empresa, TIPO_DEMANDA)
    por_categoria: dict[int, list[int]] = {}
    for p in ml_demanda.predecir_demanda(modelo, semanas):
        por_categoria.setdefault(p.categoria_id, []).append(p.unidades)
    categorias = [{"categoria_id": c["id"], "categoria": c["nombre"], "unidades_semanales": por_categoria[c["id"]]} for c in modelo["categorias"]]
    with mundo.fabrica() as db, en_empresa(db, mundo.id[empresa]):
        disponible = {
            c["id"]: max(
                sum(int(f["disponible"]) for f in catalogo_politicas.reporte_existencias_por_producto(db, None, [c["id"]], None, LIMITE_PRODUCTOS_DE_EXISTENCIAS)),
                0,
            )
            for c in modelo["categorias"]
        }  # fmt: skip
    calculados = ml_reposicion.calcular_reposicion(categorias, disponible, semanas)
    return [tuple(getattr(i, campo) for campo in CAMPOS_REPOSICION) for i in calculados]


def _reposicion_de_la_api(cuerpo: dict) -> list[tuple]:
    return [tuple(i[campo] for campo in CAMPOS_REPOSICION) for i in cuerpo["items"]]


def _fila_completa(mundo, empresa: str, tipo: str, version: int | None = None) -> ModeloML:
    """La fila (vigente o la `version` dada) CON su artefacto, leída por una sesión nueva de la empresa."""
    with mundo.fabrica() as db, en_empresa(db, mundo.id[empresa]):
        fila = REPO.obtener_activo(db, tipo, con_artefacto=True) if version is None else REPO.obtener_version(db, tipo, version, con_artefacto=True)
        assert fila is not None
        _ = fila.artefacto  # cargar el campo diferido antes de cerrar la sesión
        db.expunge(fila)
        return fila


# ---- 1. El flujo completo con dos empresas -----------------------------------------------------------------------------------


def test_flujo_completo_entrenar_demanda_segmentos_y_panel_con_dos_empresas(mundo):
    # Antes de entrenar: nada vigente, pero hay datos de sobra para entrenar los dos modelos.
    for empresa in (A, B):
        estado = _ok(_get(mundo, empresa, "/estado"))
        assert [(m["tipo"], m["estado"], m["version"]) for m in estado["modelos"]] == [(t, "sin_entrenar", None) for t in TIPOS]
        assert estado["puede_entrenar"] == {TIPO_DEMANDA: True, TIPO_SEGMENTOS: True, TIPO_ANOMALIAS: True}
        for ruta in ("/demanda", "/segmentos", "/anomalias", "/reposicion"):
            sin_modelo = _get(mundo, empresa, ruta)
            assert (sin_modelo.status_code, sin_modelo.json()["codigo"]) == (409, "modelo_no_entrenado"), ruta
        panel_vacio = _ok(_get(mundo, empresa, "/panel"))  # el panel no se cae: sus cuatro bloques van en None con su aviso
        assert [panel_vacio[b] for b in ("demanda", "segmentos", "anomalias", "reposicion")] == [None] * 4 and len(panel_vacio["avisos"]) == 4

    # Se entrena A por HTTP (sin indicar tipos: los TRES): B sigue sin modelo hasta que entrena la suya.
    entrenados_a = _entrenar_http(mundo, A)["resultados"]
    assert [(r["tipo"], r["estado"], r["version"]) for r in entrenados_a] == [(t, "entrenado", 1) for t in TIPOS]
    assert len(TIPOS) == 3
    for ruta in ("/demanda", "/anomalias", "/reposicion"):
        assert _get(mundo, B, ruta).status_code == 409, ruta
    entrenados_b = _entrenar_http(mundo, B)["resultados"]
    assert [(r["tipo"], r["estado"], r["version"]) for r in entrenados_b] == [(t, "entrenado", 1) for t in TIPOS]

    resultados = {}
    for empresa in (A, B):
        serie, rfm = _serie(mundo, empresa), _rfm(mundo, empresa)
        estado = _ok(_get(mundo, empresa, "/estado"))
        assert [(m["tipo"], m["estado"], m["version"]) for m in estado["modelos"]] == [(t, "vigente", 1) for t in TIPOS]
        assert estado["datos"] == {
            "semanas_con_ventas": len({_lunes(f["dia"]) for f in serie}),
            "categorias_con_ventas": len({f["categoria_id"] for f in serie}),
            "clientes_con_compras": len(rfm),
        }

        dem, seg, panel = _ok(_get(mundo, empresa, "/demanda")), _ok(_get(mundo, empresa, "/segmentos")), _ok(_get(mundo, empresa, "/panel"))
        # Demanda: las categorías y el histórico de la empresa, calculados aparte con `comercial`.
        assert {c["categoria_id"]: c["categoria"] for c in dem["categorias"]} == {f["categoria_id"]: f["categoria"] for f in serie}
        for categoria in dem["categorias"]:
            real = {}
            for fila in serie:
                if fila["categoria_id"] == categoria["categoria_id"]:
                    real[_lunes(fila["dia"])] = real.get(_lunes(fila["dia"]), 0.0) + float(fila["unidades"])
            assert [p["valor"] for p in categoria["historico"]] == [real.get(dt.date.fromisoformat(p["etiqueta"]), 0.0) for p in categoria["historico"]]
            assert len(categoria["prediccion"]) == 4 and all(p["es_prediccion"] and p["minimo"] <= p["valor"] <= p["maximo"] for p in categoria["prediccion"])
        assert dem["total_empresa"]["total_predicho"] == int(sum(p["valor"] for p in dem["total_empresa"]["prediccion"])) > 0
        # Segmentos: todos los clientes de la empresa, en segmentos que suman el 100 %.
        assert seg["clientes_segmentados"] == sum(s["clientes"] for s in seg["segmentos"]) == len(rfm)
        assert sum(s["porcentaje_monto"] for s in seg["segmentos"]) == pytest.approx(100.0, abs=0.1)
        # El panel trae los mismos bloques que las rutas sueltas (misma versión, mismas cifras) y sus KPIs.
        ano30, rep = _ok(_get(mundo, empresa, "/anomalias", dias=30)), _ok(_get(mundo, empresa, "/reposicion"))
        assert panel["demanda"] == dem and panel["segmentos"] == seg and panel["estado"] == estado and panel["avisos"] == []
        assert panel["anomalias"] == ano30 and panel["reposicion"] == rep  # el panel pide 30 días y 4 semanas (los valores por defecto de reposición)
        kpis = {k["clave"]: k for k in panel["kpis"]}
        assert set(kpis) >= {
            "demanda_proxima_semana", "mejora_modelo", "clientes_segmentados", "clientes_en_riesgo", "anomalias_30_dias", "categorias_criticas",
        }  # fmt: skip
        assert kpis["anomalias_30_dias"]["valor"] == ano30["total"] == len(ano30["anomalias"])
        assert kpis["categorias_criticas"]["valor"] == rep["criticos"] == sum(1 for i in rep["items"] if i["estado"] == "critico")
        # Anomalías y reposición: lo mismo que se calcula SIN la API, con el artefacto leído de PostgreSQL y las filas de `comercial`.
        assert _anomalias_de_la_api(_ok(_get(mundo, empresa, "/anomalias"))) == _anomalias_directas(mundo, empresa, 90)
        assert _reposicion_de_la_api(rep) == _reposicion_directa(mundo, empresa, 4)
        resultados[empresa] = (dem, seg)

    # Las dos empresas, misma versión y respuestas distintas.
    (dem_a, seg_a), (dem_b, seg_b) = resultados[A], resultados[B]
    assert {c["categoria_id"] for c in dem_a["categorias"]}.isdisjoint({c["categoria_id"] for c in dem_b["categorias"]})
    assert [p["valor"] for p in dem_a["total_empresa"]["historico"]] != [p["valor"] for p in dem_b["total_empresa"]["historico"]]
    assert [(s["nombre"], s["clientes"], s["monto_total"]) for s in seg_a["segmentos"]] != [
        (s["nombre"], s["clientes"], s["monto_total"]) for s in seg_b["segmentos"]
    ]


def test_anomalias_y_reposicion_en_postgresql_coinciden_con_el_calculo_directo_en_todo_el_rango_de_parametros(mundo):
    """`/anomalias?dias=` (7..365) y `/reposicion?semanas=` (1..12) contra `detectar_anomalias` y `calcular_reposicion`
    con las mismas filas de `comercial` y `catalogo`; los extremos fuera de rango son 422 y no tocan la base."""
    _entrenar_http(mundo, A, [TIPO_DEMANDA, TIPO_ANOMALIAS])
    for dias in (7, 30, 90, 180, 365):
        cuerpo = _ok(_get(mundo, A, "/anomalias", dias=dias))
        assert (cuerpo["dias"], cuerpo["hasta"]) == (dias, FIN.isoformat())
        assert cuerpo["desde"] == (FIN - dt.timedelta(days=dias - 1)).isoformat()
        assert _anomalias_de_la_api(cuerpo) == _anomalias_directas(mundo, A, dias), dias
        assert all(dt.date.fromisoformat(x["fecha"]) >= FIN - dt.timedelta(days=dias - 1) for x in cuerpo["anomalias"])
    grandes = [_ok(_get(mundo, A, "/anomalias", dias=d))["total"] for d in (7, 90, 365)]
    assert grandes == sorted(grandes)  # una ventana más larga contiene a la más corta
    for semanas in (1, 2, 4, 8, 12):
        cuerpo = _ok(_get(mundo, A, "/reposicion", semanas=semanas))
        assert cuerpo["semanas"] == semanas
        assert _reposicion_de_la_api(cuerpo) == _reposicion_directa(mundo, A, semanas), semanas
        assert cuerpo["criticos"] == sum(1 for i in cuerpo["items"] if i["estado"] == "critico")
    for ruta, parametros in (("/anomalias", {"dias": 6}), ("/anomalias", {"dias": 366}), ("/reposicion", {"semanas": 0}), ("/reposicion", {"semanas": 13})):
        assert _get(mundo, A, ruta, **parametros).status_code == 422, (ruta, parametros)


# ---- 2. El BYTEA del artefacto vuelve íntegro ----------------------------------------------------------------------------------


def test_el_artefacto_bytea_vuelve_integro_de_postgresql_y_predice_lo_que_dice_la_api(mundo):
    _entrenar_http(mundo, A)
    dem, seg = _ok(_get(mundo, A, "/demanda", semanas=4)), _ok(_get(mundo, A, "/segmentos"))
    ano, rep = _ok(_get(mundo, A, "/anomalias", dias=365)), _ok(_get(mundo, A, "/reposicion", semanas=4))
    textos = json.dumps([dem, seg, ano, rep])

    for tipo in TIPOS:
        fila = _fila_completa(mundo, A, tipo)
        assert isinstance(fila.artefacto, bytes) and len(fila.artefacto) == fila.artefacto_bytes > 0
        assert hashlib.sha256(fila.artefacto).hexdigest() == fila.artefacto_sha256 == persistencia.huella(fila.artefacto)
        # La huella también la calcula PostgreSQL sobre los bytes que tiene guardados: nada se alteró en el viaje.
        with mundo.fabrica() as db:
            en_la_base = db.execute(
                text("SELECT length(artefacto), encode(sha256(artefacto), 'hex') FROM modelo_ml WHERE id = :i"), {"i": fila.id}
            ).one()
        assert (en_la_base[0], en_la_base[1]) == (fila.artefacto_bytes, fila.artefacto_sha256)
        assert fila.artefacto_sha256 not in textos and fila.artefacto.hex()[:40] not in textos  # y la API no lo expone
        assert re.search(r"[0-9a-f]{64}", textos) is None

    # Se deserializa verificando la huella, y el modelo predice exactamente lo que respondió la API.
    demanda_ml = _fila_completa(mundo, A, TIPO_DEMANDA)
    artefacto = persistencia.deserializar(demanda_ml.artefacto, demanda_ml.artefacto_sha256)
    predicciones = ml_demanda.predecir_demanda(artefacto, 4)
    assert len(predicciones) == 4 * len(dem["categorias"]) > 0
    por_categoria = {c["categoria_id"]: c["prediccion"] for c in dem["categorias"]}
    for p in predicciones:
        punto = por_categoria[p.categoria_id][(p.semana_inicio - dt.date.fromisoformat(por_categoria[p.categoria_id][0]["etiqueta"])).days // 7]
        assert (punto["etiqueta"], punto["valor"]) == (p.semana_inicio.isoformat(), p.unidades)
    assert {c["id"] for c in artefacto["categorias"]} == set(por_categoria)

    segmentos_ml = _fila_completa(mundo, A, TIPO_SEGMENTOS)
    modelo_rfm = persistencia.deserializar(segmentos_ml.artefacto, segmentos_ml.artefacto_sha256)
    ids_segmento = {s["id"] for s in seg["segmentos"]}
    filas = _rfm(mundo, A)
    asignados = [ml_segmentos.asignar_segmento(modelo_rfm, f["ultima_compra"], f["frecuencia"], f["monto_total"], FIN) for f in filas]
    assert set(asignados) <= ids_segmento
    # Y la cuenta de clientes por segmento que dice la API sale de volver a asignar a los clientes con el modelo cargado.
    for segmento in seg["segmentos"]:
        assert asignados.count(segmento["id"]) == segmento["clientes"], segmento["nombre"]

    # Anomalías: el BYTEA vuelve íntegro, el artefacto es de la empresa y detecta exactamente lo que respondió la API
    # (365 días: toda la historia cargada). El generador inyecta días inusuales, así que no es una comparación de listas vacías.
    anomalias_ml = _fila_completa(mundo, A, TIPO_ANOMALIAS)
    modelo_ano = persistencia.deserializar(anomalias_ml.artefacto, anomalias_ml.artefacto_sha256)
    assert modelo_ano["empresa_id"] == mundo.id[A] and modelo_ano["hasta"] == FIN.isoformat()
    assert _anomalias_de_la_api(ano) == _anomalias_directas(mundo, A, 365)
    assert ano["total"] == len(ano["anomalias"]) > 0 and ano["fuertes"] == sum(1 for x in ano["anomalias"] if x["severidad"] == "fuerte")
    with mundo.fabrica() as db, en_empresa(db, mundo.id[A]):
        assert set(modelo_ano["sucursales"]) <= set(db.scalars(select(Sucursal.id)))  # solo conoce sucursales de A
    # Reposición: sale del artefacto de la demanda (ya verificado arriba) y de las existencias de A.
    assert _reposicion_de_la_api(rep) == _reposicion_directa(mundo, A, 4)
    assert {i["categoria_id"] for i in rep["items"]} == set(por_categoria) and any(i["disponible"] > 0 for i in rep["items"])

    # Una alteración de un solo byte se detecta ANTES de cargar (la huella ya no coincide), en los tres modelos.
    for modelo_guardado in (demanda_ml, segmentos_ml, anomalias_ml):
        alterado = bytearray(modelo_guardado.artefacto)
        alterado[len(alterado) // 2] ^= 0x01
        with pytest.raises(persistencia.ArtefactoCorrupto):
            persistencia.deserializar(bytes(alterado), modelo_guardado.artefacto_sha256)


def test_un_artefacto_de_anomalias_danado_en_postgresql_da_409_y_no_tumba_ni_la_reposicion_ni_el_panel(mundo):
    """Se altera un byte del BYTEA YA guardado (como una corrupción de disco). La API no debe dar 500: `/anomalias`
    responde 409 `modelo_obsoleto`, `/reposicion` (otro modelo) sigue bien y el panel deja su bloque en None con un aviso.
    Reentrenar lo repara."""
    a = mundo.id[A]
    _entrenar_http(mundo, A, [TIPO_DEMANDA, TIPO_ANOMALIAS])
    bueno = _ok(_get(mundo, A, "/anomalias"))
    fila = _fila_completa(mundo, A, TIPO_ANOMALIAS)
    with mundo.fabrica() as db:
        db.execute(  # el byte del medio, invertido: la huella guardada ya no coincide
            text("UPDATE modelo_ml SET artefacto = set_byte(artefacto, length(artefacto) / 2, get_byte(artefacto, length(artefacto) / 2) # 1) WHERE id = :i"),
            {"i": fila.id},
        )
        db.commit()
    CACHE_MODELOS.invalidar(a)  # la caché es del proceso: se fuerza a leer de la base

    danado = _get(mundo, A, "/anomalias")
    assert (danado.status_code, danado.json()["codigo"]) == (409, "modelo_obsoleto"), danado.text
    assert _ok(_get(mundo, A, "/reposicion"))["semanas"] == 4
    panel = _ok(_get(mundo, A, "/panel"))
    assert panel["anomalias"] is None and panel["demanda"] is not None and panel["reposicion"] is not None
    assert any(aviso.startswith("Anomalías") for aviso in panel["avisos"])

    _entrenar_http(mundo, A, [TIPO_ANOMALIAS])  # reentrenar deja una versión nueva y sana
    reparado = _ok(_get(mundo, A, "/anomalias"))
    assert reparado["modelo"]["version"] == 2 and _anomalias_de_la_api(reparado) == _anomalias_de_la_api(bueno)


# ---- 3. Aislamiento y caché con la base real ----------------------------------------------------------------------------------


def test_el_aislamiento_se_mantiene_y_la_cache_se_invalida_al_reentrenar_en_postgresql(mundo):
    a, b = mundo.id[A], mundo.id[B]
    _entrenar_http(mundo, A)
    with mundo.fabrica() as db:
        entrenar(db, B)  # B entrena con el caso de uso directo (el límite de tráfico de /entrenar es de 3 por minuto)

    # -- Aislamiento: ids ajenos, parámetros del cliente y B sin modelo cuando solo A lo tiene --
    dem_a, dem_b = _ok(_get(mundo, A, "/demanda")), _ok(_get(mundo, B, "/demanda"))
    id_ajeno, id_propio = dem_b["categorias"][0]["categoria_id"], dem_a["categorias"][0]["categoria_id"]
    assert {c["categoria_id"] for c in dem_a["categorias"]}.isdisjoint({c["categoria_id"] for c in dem_b["categorias"]})
    ajena, inexistente = _get(mundo, A, "/demanda", categoria_id=id_ajeno), _get(mundo, A, "/demanda", categoria_id=9_999_999)
    assert ajena.status_code == inexistente.status_code == 404 and ajena.json() == inexistente.json()
    assert [c["categoria_id"] for c in _ok(_get(mundo, A, "/demanda", categoria_id=id_propio))["categorias"]] == [id_propio]
    for ruta in ("/estado", "/demanda", "/segmentos", "/anomalias", "/reposicion", "/panel"):
        assert _ok(_get(mundo, A, ruta, empresa_id=b)) == _ok(_get(mundo, A, ruta)), ruta
    with mundo.fabrica() as db, en_empresa(db, a):
        assert {m.empresa_id for m in db.scalars(select(ModeloML))} == {a}
        sucursales_a = set(db.scalars(select(Sucursal.id)))
    with mundo.fabrica() as db, en_empresa(db, b):
        assert {m.empresa_id for m in db.scalars(select(ModeloML))} == {b}
        assert db.get(ModeloML, _fila_completa(mundo, A, TIPO_DEMANDA).id) is None  # la fila de A no existe para B
        assert db.get(ModeloML, _fila_completa(mundo, A, TIPO_ANOMALIAS).id) is None
        sucursales_b = set(db.scalars(select(Sucursal.id)))
    assert sucursales_a and sucursales_b and sucursales_a.isdisjoint(sucursales_b)

    # -- Anomalías y reposición: cada empresa ve SOLO lo suyo, con cualquier ventana --
    for dias in (30, 365):
        ano_a, ano_b = _ok(_get(mundo, A, "/anomalias", dias=dias)), _ok(_get(mundo, B, "/anomalias", dias=dias))
        assert {x["sucursal_id"] for x in ano_a["anomalias"]} <= sucursales_a, dias
        assert {x["sucursal_id"] for x in ano_b["anomalias"]} <= sucursales_b, dias
        assert _anomalias_de_la_api(ano_a) == _anomalias_directas(mundo, A, dias)
        assert _anomalias_de_la_api(ano_b) == _anomalias_directas(mundo, B, dias)
    ano_365_a, ano_365_b = _ok(_get(mundo, A, "/anomalias", dias=365)), _ok(_get(mundo, B, "/anomalias", dias=365))
    assert ano_365_a["anomalias"] and ano_365_b["anomalias"]  # el generador inyecta días inusuales en las dos: no es vacío contra vacío
    assert {x["sucursal"] for x in ano_365_a["anomalias"]}.isdisjoint({x["sucursal"] for x in ano_365_b["anomalias"]})
    rep_a, rep_b = _ok(_get(mundo, A, "/reposicion")), _ok(_get(mundo, B, "/reposicion"))
    assert {i["categoria_id"] for i in rep_a["items"]} == {c["categoria_id"] for c in dem_a["categorias"]}
    assert {i["categoria_id"] for i in rep_b["items"]} == {c["categoria_id"] for c in dem_b["categorias"]}
    assert {i["categoria_id"] for i in rep_a["items"]}.isdisjoint({i["categoria_id"] for i in rep_b["items"]})
    assert _reposicion_de_la_api(rep_a) == _reposicion_directa(mundo, A, 4) != _reposicion_de_la_api(rep_b)
    assert _reposicion_de_la_api(rep_b) == _reposicion_directa(mundo, B, 4)

    # -- Caché: A v1 y B v1 conviven, con su empresa en la clave --
    assert CACHE_MODELOS.obtener(a, TIPO_DEMANDA, 1) is not None and CACHE_MODELOS.obtener(b, TIPO_DEMANDA, 1) is not None
    modelo_a1, modelo_b1 = CACHE_MODELOS.obtener(a, TIPO_DEMANDA, 1), CACHE_MODELOS.obtener(b, TIPO_DEMANDA, 1)
    assert modelo_a1 is not modelo_b1 and modelo_a1["ultima_semana"] is not None
    ano_cache_a1, ano_cache_b1 = CACHE_MODELOS.obtener(a, TIPO_ANOMALIAS, 1), CACHE_MODELOS.obtener(b, TIPO_ANOMALIAS, 1)
    assert ano_cache_a1 is not None and ano_cache_b1 is not None and ano_cache_a1 is not ano_cache_b1
    assert (ano_cache_a1["empresa_id"], ano_cache_b1["empresa_id"]) == (a, b)
    antes_b = _ok(_get(mundo, B, "/demanda"))
    antes_b_ano, antes_b_rep = _ok(_get(mundo, B, "/anomalias")), _ok(_get(mundo, B, "/reposicion"))

    # -- Reentrenar A con otro corte de datos (14 días antes): la versión 2 es la que responde, la 1 sale de la caché --
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cu24, "hoy_utc", lambda: HOY - dt.timedelta(days=14))
        segundo = _entrenar_http(mundo, A, [TIPO_DEMANDA])["resultados"]
    assert [(r["tipo"], r["version"]) for r in segundo] == [(TIPO_DEMANDA, 2)]
    assert CACHE_MODELOS.obtener(a, TIPO_DEMANDA, 1) is None  # invalidada al guardar la versión nueva
    assert CACHE_MODELOS.obtener(b, TIPO_DEMANDA, 1) is modelo_b1  # y la de B, intacta

    nueva = _ok(_get(mundo, A, "/demanda"))
    assert nueva["modelo"]["version"] == 2
    assert nueva["modelo"]["datos_hasta"] != dem_a["modelo"]["datos_hasta"]  # de verdad es otro modelo, entrenado con otro corte
    assert nueva["modelo"]["filas_entrenamiento"] != dem_a["modelo"]["filas_entrenamiento"]
    assert [p["etiqueta"] for p in nueva["total_empresa"]["prediccion"]] != [p["etiqueta"] for p in dem_a["total_empresa"]["prediccion"]]
    modelo_a2 = CACHE_MODELOS.obtener(a, TIPO_DEMANDA, 2)
    fila_2 = _fila_completa(mundo, A, TIPO_DEMANDA, 2)
    assert fila_2.activo and modelo_a2["ultima_semana"] == persistencia.deserializar(fila_2.artefacto, fila_2.artefacto_sha256)["ultima_semana"]
    assert modelo_a2["ultima_semana"] != modelo_a1["ultima_semana"]
    # La versión 1 sigue guardada (con su artefacto) pero ya no es la vigente; los segmentos y las anomalías no se reentrenaron.
    assert _fila_completa(mundo, A, TIPO_DEMANDA, 1).activo is False
    assert [(m["tipo"], m["version"]) for m in _ok(_get(mundo, A, "/estado"))["modelos"]] == [
        (TIPO_DEMANDA, 2), (TIPO_SEGMENTOS, 1), (TIPO_ANOMALIAS, 1),
    ]  # fmt: skip
    assert CACHE_MODELOS.obtener(a, TIPO_ANOMALIAS, 1) is ano_cache_a1  # reentrenar la demanda no toca la caché de anomalías
    assert _ok(_get(mundo, B, "/demanda")) == antes_b  # B, igual que antes de reentrenar A
    assert _ok(_get(mundo, B, "/anomalias")) == antes_b_ano and _ok(_get(mundo, B, "/reposicion")) == antes_b_rep
    # La reposición de A usa el modelo de demanda NUEVO (versión 2) y sigue coincidiendo con el cálculo directo.
    rep_nueva = _ok(_get(mundo, A, "/reposicion"))
    assert rep_nueva["modelo"]["version"] == 2 and _reposicion_de_la_api(rep_nueva) == _reposicion_directa(mundo, A, 4)

    # -- Reentrenar SOLO las anomalías de A: su caché se invalida (la de B no) y responde la versión 2, sin cambiar las otras --
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cu24, "hoy_utc", lambda: HOY - dt.timedelta(days=14))
        tercero = _entrenar_http(mundo, A, [TIPO_ANOMALIAS])["resultados"]
    assert [(r["tipo"], r["version"]) for r in tercero] == [(TIPO_ANOMALIAS, 2)]
    assert CACHE_MODELOS.obtener(a, TIPO_ANOMALIAS, 1) is None
    assert CACHE_MODELOS.obtener(b, TIPO_ANOMALIAS, 1) is ano_cache_b1
    assert CACHE_MODELOS.obtener(a, TIPO_DEMANDA, 2) is modelo_a2  # y la de la demanda de A, intacta
    nueva_ano = _ok(_get(mundo, A, "/anomalias", dias=30))
    assert nueva_ano["modelo"]["version"] == 2
    assert nueva_ano["modelo"]["datos_hasta"] == (FIN - dt.timedelta(days=14)).isoformat()  # de verdad es otro corte de datos
    assert _fila_completa(mundo, A, TIPO_ANOMALIAS, 1).activo is False and _fila_completa(mundo, A, TIPO_ANOMALIAS, 2).activo is True
    assert _ok(_get(mundo, B, "/anomalias")) == antes_b_ano
