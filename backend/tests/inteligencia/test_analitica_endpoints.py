"""CU-24 (E12a): la analítica de Machine Learning por HTTP (`/api/v1/analitica/...`). Estado, entrenamiento, demanda,
segmentos y panel; los 409 (sin modelo, obsoleto), el aviso de "desactualizado", el aislamiento por empresa y que el
artefacto del modelo jamás salga en una respuesta. SQLite en memoria con el escenario de `_analitica_comun` (40 semanas,
80 clientes, fin el 25/10/2026). Cada prueba compara contra datos calculados por otro camino (el historial sintético, la
lectura directa de `comercial` o el artefacto guardado), no contra la propia respuesta.

La fecha de la aplicación se fija en `HOY` (= `FIN` + 1) sobre el módulo del caso de uso: así el entrenamiento por HTTP
(que usa "ayer" como último día) y la vigencia no dependen del día en que se corra la suite."""

import datetime as dt
import math
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.catalogo.models import Categoria
from app.comercial import politicas as comercial_politicas
from app.core.deps import ParametrosPeriodo
from app.core.rate_limit import limiter
from app.core.tenant import en_empresa
from app.inteligencia.casos_uso import cu24_analizar_con_machine_learning as cu24
from app.inteligencia.casos_uso.cu24_analizar_con_machine_learning import (
    CACHE_MODELOS,
    TIPO_ANOMALIAS,
    TIPO_DEMANDA,
    TIPO_SEGMENTOS,
    ConsultarAnaliticaML,
)
from app.inteligencia.ml import demanda, persistencia, sintetico
from app.inteligencia.models import ModeloML
from app.inteligencia.repository import ModeloMLRepository
from scripts.demo_organizaciones import por_codigo
from tests.inteligencia._analitica_comun import (
    FIN,
    HOY,
    cabeceras_de,
    cargar_historia,
    entrenar,
    id_de,
    poblar_mundo,
    usuario_de,
)

BASE = "/api/v1/analitica"
REPO = ModeloMLRepository()
NOMBRES_EN_RIESGO = ("En riesgo", "Por reactivar", "Grandes dormidos")
CLAVES_DE_CLIENTE = {"cliente_id", "id_cliente", "cliente_n", "clientes_ids", "email", "correo", "ci_nit", "telefono"}


# ---- Escenario ---------------------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fecha_fija_y_cache_limpia(monkeypatch):
    """La fecha de la aplicación para el caso de uso es HOY (FIN + 1) y el caché de modelos arranca y termina vacío
    (guarda por (empresa, tipo, versión) y los ids se repiten entre las bases de prueba)."""
    monkeypatch.setattr(cu24, "hoy_utc", lambda: HOY)
    for empresa_id in range(1, 12):
        CACHE_MODELOS.invalidar(empresa_id)
    yield
    for empresa_id in range(1, 12):
        CACHE_MODELOS.invalidar(empresa_id)


@pytest.fixture()
def mundo(db_session, tmp_path):
    """Las tres organizaciones pobladas (sin historial de ventas)."""
    poblar_mundo(db_session, tmp_path)
    return db_session


@pytest.fixture()
def admin_fs(mundo):
    """El administrador de FashionStore, sin ventas ni modelos."""
    return SimpleNamespace(db=mundo, id=id_de(mundo, "fashionstore"), h=cabeceras_de(mundo, "fashionstore"))


@pytest.fixture()
def fs(mundo):
    """FashionStore con su historial sintético cargado (sin entrenar nada). `catalogo` e `historial` son la verdad
    contra la que se compara."""
    empresa_id, catalogo, historial, _ = cargar_historia(mundo, "fashionstore")
    return SimpleNamespace(
        db=mundo, id=empresa_id, h=cabeceras_de(mundo, "fashionstore"), catalogo=catalogo, historial=historial
    )


@pytest.fixture()
def entrenado(fs):
    """FashionStore con los tres modelos entrenados (versión 1) hasta `FIN`."""
    resumen = entrenar(fs.db, "fashionstore")
    assert resumen.entrenados == [TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS]
    return fs


# ---- Ayudas ----------------------------------------------------------------------------------------------------------------


def _get(client, ruta, headers, **params):
    return client.get(f"{BASE}/{ruta}", headers=headers, params=params or None)


def _ok(respuesta) -> dict:
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _lunes(dia: dt.date) -> dt.date:
    return dia - dt.timedelta(days=dia.weekday())


def _fila_modelo(db, empresa_id, tipo, *, version=None, con_artefacto=False):
    with en_empresa(db, empresa_id):
        fila = (
            REPO.obtener_activo(db, tipo, con_artefacto=con_artefacto)
            if version is None
            else REPO.obtener_version(db, tipo, version, con_artefacto=con_artefacto)
        )
        assert fila is not None
        if con_artefacto:
            _ = fila.artefacto  # cargar el campo diferido antes de salir del alcance de la empresa
        return fila


def _alterar(db, empresa_id, tipo, cambio):
    """Aplica `cambio(fila)` a la fila VIGENTE del modelo (como lo haría alguien con acceso a la base) y confirma."""
    with en_empresa(db, empresa_id):
        fila = REPO.obtener_activo(db, tipo, con_artefacto=True)
        cambio(fila)
        db.commit()
    CACHE_MODELOS.invalidar(empresa_id)


def _con_sklearn(version):
    """Cambio que deja el modelo como entrenado con otra versión de scikit-learn (demanda y segmentos la guardan en
    sitios distintos)."""

    def cambio(fila):
        parametros = dict(fila.parametros)
        if "version_sklearn" in parametros:
            parametros["version_sklearn"] = version
        else:
            parametros["versiones"] = {**parametros["versiones"], "sklearn": version}
        fila.parametros = parametros

    return cambio


def _cantidad_de_modelos(db, empresa_id) -> int:
    with en_empresa(db, empresa_id):
        return db.scalar(select(func.count()).select_from(ModeloML))


def _recorrer(valor, ruta="$"):
    """(ruta, clave o None, valor) de cada elemento de un JSON, a cualquier profundidad."""
    if isinstance(valor, dict):
        for clave, hijo in valor.items():
            yield f"{ruta}.{clave}", clave, hijo
            yield from _recorrer(hijo, f"{ruta}.{clave}")
    elif isinstance(valor, list):
        for i, hijo in enumerate(valor):
            yield f"{ruta}[{i}]", None, hijo
            yield from _recorrer(hijo, f"{ruta}[{i}]")


_BASE64_LARGO = re.compile(r"[A-Za-z0-9+/=_-]{200,}")


def _sin_artefacto(cuerpo) -> None:
    """Falla si en el JSON aparece una clave 'artefacto*', bytes, o un texto largo con pinta de base64."""
    for ruta, clave, valor in _recorrer(cuerpo):
        assert clave is None or "artefacto" not in clave.lower(), f"clave de artefacto en {ruta}"
        assert not isinstance(valor, (bytes, bytearray)), f"bytes en {ruta}"
        if isinstance(valor, str):
            assert not _BASE64_LARGO.fullmatch(valor), f"texto con forma de base64 en {ruta}"


def _sin_datos_de_cliente(cuerpo) -> None:
    for ruta, clave, _ in _recorrer(cuerpo):
        assert clave not in CLAVES_DE_CLIENTE, f"dato de cliente en {ruta}"


def _lunes_consecutivos(etiquetas: list[str]) -> list[dt.date]:
    fechas = [dt.date.fromisoformat(e) for e in etiquetas]
    assert all(f.weekday() == 0 for f in fechas), etiquetas
    assert all((b - a).days == 7 for a, b in zip(fechas, fechas[1:])), etiquetas
    return fechas


def _unidades_semanales_sinteticas(fs, categoria_id=None) -> dict[str, int]:
    """Unidades vendidas por semana (clave: lunes ISO) según el historial sintético, que no pasa por la base."""
    por_semana: dict[str, int] = {}
    for fila in sintetico.filas_serie_diaria(fs.historial, fs.catalogo):
        if categoria_id is None or fila["categoria_id"] == categoria_id:
            clave = _lunes(fila["dia"]).isoformat()
            por_semana[clave] = por_semana.get(clave, 0) + fila["unidades"]
    return por_semana


# ---- Acceso ----------------------------------------------------------------------------------------------------------------


RUTAS_ANALITICA = (
    ("get", "estado"), ("post", "entrenar"), ("get", "demanda"), ("get", "segmentos"), ("get", "anomalias"), ("get", "reposicion"),
    ("get", "panel"),
)  # fmt: skip


def test_sin_token_las_siete_rutas_responden_401(client_por_peticion, mundo):
    for metodo, ruta in RUTAS_ANALITICA:
        respuesta = getattr(client_por_peticion, metodo)(f"{BASE}/{ruta}")
        assert respuesta.status_code == 401, (ruta, respuesta.text)


def test_el_plan_basico_recibe_403_en_todas_las_rutas_y_no_se_guarda_nada(client_por_peticion, mundo):
    pampa = id_de(mundo, "pampa-casual")
    cabeceras = cabeceras_de(mundo, "pampa-casual")
    for metodo, ruta in RUTAS_ANALITICA:
        respuesta = getattr(client_por_peticion, metodo)(f"{BASE}/{ruta}", headers=cabeceras)
        assert respuesta.status_code == 403, (ruta, respuesta.text)
        cuerpo = respuesta.json()
        assert cuerpo["codigo"] == "plan_no_incluye_funcionalidad" and cuerpo["funcionalidad"] == "analitica_ml", ruta
    assert _cantidad_de_modelos(mundo, pampa) == 0


def test_un_encargado_de_sucursal_no_ve_la_analitica_de_toda_la_empresa(client_por_peticion, mundo):
    email = next(p.email for p in por_codigo("fashionstore").personal() if p.rol == "encargado_sucursal")
    cabeceras = cabeceras_de(mundo, "fashionstore", email)
    for metodo, ruta in RUTAS_ANALITICA:
        respuesta = getattr(client_por_peticion, metodo)(f"{BASE}/{ruta}", headers=cabeceras)
        assert respuesta.status_code == 403, (ruta, respuesta.text)
        assert "toda la empresa" in respuesta.json()["detail"], ruta
    assert _cantidad_de_modelos(mundo, id_de(mundo, "fashionstore")) == 0  # y el POST no entrenó nada


# ---- Estado y entrenamiento --------------------------------------------------------------------------------------------


def test_estado_sin_entrenar_dice_que_falta_y_cuenta_los_datos_del_historial(client_por_peticion, fs):
    cuerpo = _ok(_get(client_por_peticion, "estado", fs.h))

    assert [m["tipo"] for m in cuerpo["modelos"]] == [TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS]
    for modelo in cuerpo["modelos"]:
        assert modelo["entrenado"] is False and modelo["estado"] == "sin_entrenar"
        assert modelo["mensaje"] == cu24.MENSAJE_SIN_MODELO
        assert modelo["version"] is None and modelo["entrenado_en"] is None and modelo["metricas"] == {}
    # Lo que hay para entrenar, contado sobre el historial sintético (no sobre la base).
    filas = sintetico.filas_serie_diaria(fs.historial, fs.catalogo)
    assert cuerpo["datos"] == {
        "semanas_con_ventas": len({_lunes(f["dia"]) for f in filas}),
        "categorias_con_ventas": len({f["categoria_id"] for f in filas}),
        "clientes_con_compras": len(sintetico.filas_rfm(fs.historial, FIN)),
    }
    assert cuerpo["datos"]["semanas_con_ventas"] >= 26 and cuerpo["datos"]["clientes_con_compras"] >= 30
    assert cuerpo["puede_entrenar"] == {TIPO_DEMANDA: True, TIPO_SEGMENTOS: True, TIPO_ANOMALIAS: True}
    assert cuerpo["interpretacion"] and all(isinstance(f, str) and f.strip() for f in cuerpo["interpretacion"])


def test_estado_dice_que_no_se_puede_entrenar_cuando_faltan_datos(client_por_peticion, mundo):
    # Chaski Sport recién poblada: sin ventas no hay con qué entrenar y el estado lo dice sin fallar.
    cuerpo = _ok(_get(client_por_peticion, "estado", cabeceras_de(mundo, "chaski-sport")))
    assert cuerpo["datos"] == {"semanas_con_ventas": 0, "categorias_con_ventas": 0, "clientes_con_compras": 0}
    assert cuerpo["puede_entrenar"] == {TIPO_DEMANDA: False, TIPO_SEGMENTOS: False, TIPO_ANOMALIAS: False}


def test_entrenar_todo_por_http_devuelve_las_metricas_de_ambos_y_guarda_la_version_1(client_por_peticion, fs):
    respuesta = client_por_peticion.post(f"{BASE}/entrenar", headers=fs.h, json={"tipos": [TIPO_DEMANDA, TIPO_SEGMENTOS]})
    cuerpo = _ok(respuesta)

    por_tipo = {r["tipo"]: r for r in cuerpo["resultados"]}
    assert [r["tipo"] for r in cuerpo["resultados"]] == [TIPO_DEMANDA, TIPO_SEGMENTOS]
    assert all(r["estado"] == "entrenado" and r["version"] == 1 and r["duracion_ms"] >= 0 for r in por_tipo.values())
    dem, seg = por_tipo[TIPO_DEMANDA]["metricas"], por_tipo[TIPO_SEGMENTOS]["metricas"]
    assert {"mae", "rmse", "r2", "mae_base", "mejora_mae_pct", "modelo_elegido"} <= set(dem)
    assert dem["modelo_elegido"] in ("ridge", "mezcla", "random_forest") and dem["mae"] > 0
    assert "validacion_cruzada" not in dem  # solo las métricas visibles
    assert set(seg) == {"k", "silhouette", "n_clientes"}
    assert 2 <= seg["k"] <= 6 and -1 <= seg["silhouette"] <= 1
    assert seg["n_clientes"] == len(sintetico.filas_rfm(fs.historial, FIN))
    # Lo devuelto es lo guardado.
    guardado = _fila_modelo(fs.db, fs.id, TIPO_DEMANDA)
    assert guardado.version == 1 and guardado.activo and dem["mae"] == guardado.metricas["mae"]
    assert _fila_modelo(fs.db, fs.id, TIPO_SEGMENTOS).metricas["k"] == seg["k"]


def test_el_estado_despues_de_entrenar_es_vigente_con_version_fechas_y_solo_las_metricas_visibles(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "estado", entrenado.h))

    for modelo in cuerpo["modelos"]:
        fila = _fila_modelo(entrenado.db, entrenado.id, modelo["tipo"])
        assert modelo["entrenado"] is True and modelo["estado"] == "vigente" and modelo["version"] == 1
        assert modelo["mensaje"].startswith("Vigente: versión 1")
        assert modelo["filas_entrenamiento"] == fila.filas_entrenamiento > 0
        assert modelo["datos_hasta"] == FIN.isoformat() and modelo["datos_desde"] == fila.datos_desde.isoformat()
        assert modelo["entrenado_en"] is not None
    metricas_dem = cuerpo["modelos"][0]["metricas"]
    assert "validacion_cruzada" not in metricas_dem and metricas_dem["mae"] > 0
    # Los segmentos (con sus montos) están guardados en las métricas de la fila, pero el estado no los saca.
    assert set(cuerpo["modelos"][1]["metricas"]) == {"k", "silhouette", "n_clientes"}


def test_entrenar_un_solo_tipo_deja_el_otro_sin_entrenar(client_por_peticion, fs):
    cuerpo = _ok(client_por_peticion.post(f"{BASE}/entrenar", headers=fs.h, json={"tipos": [TIPO_SEGMENTOS]}))

    assert [r["tipo"] for r in cuerpo["resultados"]] == [TIPO_SEGMENTOS]
    with en_empresa(fs.db, fs.id):
        assert {(m.tipo, m.version) for m in fs.db.scalars(select(ModeloML))} == {(TIPO_SEGMENTOS, 1)}
    estados = {m["tipo"]: m["estado"] for m in _ok(_get(client_por_peticion, "estado", fs.h))["modelos"]}
    assert estados == {TIPO_DEMANDA: "sin_entrenar", TIPO_SEGMENTOS: "vigente", TIPO_ANOMALIAS: "sin_entrenar"}


def test_entrenar_sin_cuerpo_o_con_tipos_vacios_entrena_los_tres(client_por_peticion, fs):
    sin_cuerpo = _ok(client_por_peticion.post(f"{BASE}/entrenar", headers=fs.h))  # sin cuerpo
    assert [(r["tipo"], r["version"]) for r in sin_cuerpo["resultados"]] == [
        (TIPO_DEMANDA, 1), (TIPO_SEGMENTOS, 1), (TIPO_ANOMALIAS, 1),
    ]  # fmt: skip
    vacio = _ok(client_por_peticion.post(f"{BASE}/entrenar", headers=fs.h, json={"tipos": []}))
    assert [(r["tipo"], r["version"]) for r in vacio["resultados"]] == [
        (TIPO_DEMANDA, 2), (TIPO_SEGMENTOS, 2), (TIPO_ANOMALIAS, 2),
    ]  # fmt: skip


def test_un_cuerpo_invalido_en_entrenar_da_422_y_no_entrena_nada(client_por_peticion, admin_fs):
    cuerpos = [
        {"tipos": ["bola_de_cristal"]},
        {"tipos": ["anomalias"]},  # el tipo se llama `anomalias_ventas`
        {"tipos": TIPO_DEMANDA},  # un texto, no una lista
        {"tipos": [TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS, TIPO_DEMANDA]},  # más de tres
        {"tipos": [TIPO_SEGMENTOS], "empresa_id": 2},  # el cliente no elige la empresa
        {"cualquier_cosa": 1},
    ]
    for cuerpo in cuerpos:
        limiter.reset()
        respuesta = client_por_peticion.post(f"{BASE}/entrenar", headers=admin_fs.h, json=cuerpo)
        assert respuesta.status_code == 422, (cuerpo, respuesta.text)
    assert _cantidad_de_modelos(admin_fs.db, admin_fs.id) == 0


def test_reentrenar_crea_la_version_2_y_la_1_queda_inactiva(client_por_peticion, entrenado):
    cuerpo = _ok(client_por_peticion.post(f"{BASE}/entrenar", headers=entrenado.h))

    assert [(r["tipo"], r["version"]) for r in cuerpo["resultados"]] == [(TIPO_DEMANDA, 2), (TIPO_SEGMENTOS, 2), (TIPO_ANOMALIAS, 2)]
    for tipo in (TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS):
        assert _fila_modelo(entrenado.db, entrenado.id, tipo, version=1).activo is False
        assert _fila_modelo(entrenado.db, entrenado.id, tipo, version=2).activo is True
        assert _fila_modelo(entrenado.db, entrenado.id, tipo).version == 2
    estado = _ok(_get(client_por_peticion, "estado", entrenado.h))
    assert [m["version"] for m in estado["modelos"]] == [2, 2, 2]
    assert _ok(_get(client_por_peticion, "anomalias", entrenado.h))["modelo"]["version"] == 2
    assert _ok(_get(client_por_peticion, "demanda", entrenado.h))["modelo"]["version"] == 2
    assert _ok(_get(client_por_peticion, "segmentos", entrenado.h))["modelo"]["version"] == 2


# ---- Demanda -----------------------------------------------------------------------------------------------------------------


def test_demanda_trae_12_semanas_reales_y_4_de_prediccion_por_categoria(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "demanda", entrenado.h, semanas=4))

    assert cuerpo["horizonte_semanas"] == 4
    nombres_esperados = {c.nombre for c in entrenado.catalogo.categorias if c.categoria_id in {
        f["categoria_id"] for f in sintetico.filas_serie_diaria(entrenado.historial, entrenado.catalogo)
    }}
    assert {c["categoria"] for c in cuerpo["categorias"]} == nombres_esperados and len(nombres_esperados) >= 2
    assert [c["categoria"].lower() for c in cuerpo["categorias"]] == sorted(c["categoria"].lower() for c in cuerpo["categorias"])
    for bloque in cuerpo["categorias"] + [cuerpo["total_empresa"]]:
        historico, prediccion = bloque["historico"], bloque["prediccion"]
        assert len(historico) == 12 and len(prediccion) == 4, bloque["categoria"]
        assert all(p["es_prediccion"] is False for p in historico)
        assert all(p["es_prediccion"] is True for p in prediccion)
        # Doce lunes seguidos de reales y, sin hueco, cuatro lunes de predicción desde la semana siguiente a FIN.
        fechas = _lunes_consecutivos([p["etiqueta"] for p in historico + prediccion])
        assert fechas[11] == FIN - dt.timedelta(days=6) and fechas[12] == FIN + dt.timedelta(days=1)
        for p in prediccion:
            assert p["valor"] >= 0 and p["minimo"] is not None and p["maximo"] is not None
            assert 0 <= p["minimo"] <= p["valor"] <= p["maximo"], p
        assert bloque["total_predicho"] == round(sum(p["valor"] for p in prediccion))
    # La variación contra el promedio de las últimas 4 semanas reales se recalcula a mano.
    for bloque in cuerpo["categorias"]:
        reciente = sum(p["valor"] for p in bloque["historico"][-4:]) / 4
        if reciente <= 0:
            assert bloque["variacion_pct_vs_ultimas_semanas"] is None
        else:
            esperada = (bloque["total_predicho"] / 4 - reciente) / reciente * 100
            assert bloque["variacion_pct_vs_ultimas_semanas"] == pytest.approx(esperada, abs=0.06), bloque["categoria"]


def test_el_historico_son_las_ventas_reales_leidas_por_otro_camino(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "demanda", entrenado.h))

    # 1) Cada categoría contra el historial sintético (el generador, sin base de datos).
    for bloque in cuerpo["categorias"]:
        esperado = _unidades_semanales_sinteticas(entrenado, bloque["categoria_id"])
        reales = [esperado.get(p["etiqueta"], 0) for p in bloque["historico"]]
        assert [p["valor"] for p in bloque["historico"]] == reales, bloque["categoria"]
    # 2) El total contra la lectura directa de `comercial` (lo que hay en la base), sin desglose.
    etiquetas = [p["etiqueta"] for p in cuerpo["total_empresa"]["historico"]]
    with en_empresa(entrenado.db, entrenado.id):
        filas = comercial_politicas.reporte_ventas_serie_diaria(
            entrenado.db,
            ParametrosPeriodo(desde=dt.date.fromisoformat(etiquetas[0]), hasta=dt.date.fromisoformat(etiquetas[-1]) + dt.timedelta(days=6)),
        )
    por_semana: dict[str, int] = {}
    for fila in filas:
        clave = _lunes(fila["dia"]).isoformat()
        por_semana[clave] = por_semana.get(clave, 0) + fila["unidades"]
    leidos = [por_semana.get(e, 0) for e in etiquetas]
    assert [p["valor"] for p in cuerpo["total_empresa"]["historico"]] == leidos
    assert sum(leidos) > 0 and len(set(leidos)) > 1  # no es una serie vacía ni plana


def test_el_total_de_la_empresa_es_la_suma_de_las_categorias_punto_por_punto(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "demanda", entrenado.h, semanas=6))
    categorias, total = cuerpo["categorias"], cuerpo["total_empresa"]

    assert total["categoria_id"] is None and total["categoria"] == "Total de la empresa"
    assert len(categorias) >= 2
    for serie in ("historico", "prediccion"):
        for i, punto in enumerate(total[serie]):
            assert punto["etiqueta"] == categorias[0][serie][i]["etiqueta"]
            for campo in ("valor", "minimo", "maximo"):
                if punto[campo] is None:
                    continue
                assert punto[campo] == pytest.approx(sum(c[serie][i][campo] for c in categorias)), (serie, i, campo)
    assert total["total_predicho"] == sum(c["total_predicho"] for c in categorias) == round(sum(p["valor"] for p in total["prediccion"]))


def test_la_demanda_trae_interpretacion_supuestos_metricas_y_grafico(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "demanda", entrenado.h))
    fila = _fila_modelo(entrenado.db, entrenado.id, TIPO_DEMANDA)

    assert cuerpo["interpretacion"] and all(isinstance(f, str) and len(f.strip()) > 10 for f in cuerpo["interpretacion"])
    assert len(cuerpo["supuestos"]) >= 3 and all(isinstance(s, str) and s.strip() for s in cuerpo["supuestos"])
    assert f"El modelo se entrenó con datos del {fila.datos_desde} al {fila.datos_hasta}." in cuerpo["supuestos"]
    assert {k: cuerpo["metricas"][k] for k in ("mae", "rmse", "r2", "mejora_mae_pct", "modelo_elegido")} == {
        k: fila.metricas[k] for k in ("mae", "rmse", "r2", "mejora_mae_pct", "modelo_elegido")
    }
    assert cuerpo["modelo"]["estado"] == "vigente" and cuerpo["modelo"]["version"] == 1 and cuerpo["avisos"] == []
    assert cuerpo["grafico_sugerido"]["tipo"] == "linea"


def test_el_filtro_por_categoria_deja_solo_esa_y_el_total_sigue_siendo_de_toda_la_empresa(client_por_peticion, entrenado):
    completo = _ok(_get(client_por_peticion, "demanda", entrenado.h, semanas=5))
    elegida = completo["categorias"][-1]

    filtrado = _ok(_get(client_por_peticion, "demanda", entrenado.h, semanas=5, categoria_id=elegida["categoria_id"]))

    assert [c["categoria_id"] for c in filtrado["categorias"]] == [elegida["categoria_id"]]
    assert filtrado["categorias"][0] == elegida
    assert filtrado["total_empresa"] == completo["total_empresa"]
    assert len(completo["categorias"]) > 1
    assert filtrado["total_empresa"]["total_predicho"] > elegida["total_predicho"]  # no se redujo al filtro


@pytest.mark.parametrize("semanas", ["0", "13", "-1", "abc", ""])
def test_semanas_fuera_de_1_a_12_da_422(client_por_peticion, entrenado, semanas):
    respuesta = client_por_peticion.get(f"{BASE}/demanda", headers=entrenado.h, params={"semanas": semanas})
    assert respuesta.status_code == 422, respuesta.text


def test_una_categoria_inexistente_o_de_otra_empresa_da_el_mismo_404(client_por_peticion, entrenado):
    with en_empresa(entrenado.db, id_de(entrenado.db, "chaski-sport")):
        ajena = entrenado.db.scalars(select(Categoria.id).order_by(Categoria.id)).first()
    propias = {c["categoria_id"] for c in _ok(_get(client_por_peticion, "demanda", entrenado.h))["categorias"]}
    assert ajena is not None and ajena not in propias
    assert _get(client_por_peticion, "demanda", entrenado.h, categoria_id=next(iter(propias))).status_code == 200  # la ruta está bien armada

    de_otra = _get(client_por_peticion, "demanda", entrenado.h, categoria_id=ajena)
    inexistente = _get(client_por_peticion, "demanda", entrenado.h, categoria_id=987654)
    sin_sentido = client_por_peticion.get(f"{BASE}/demanda", headers=entrenado.h, params={"categoria_id": 0})

    assert de_otra.status_code == inexistente.status_code == 404, (de_otra.text, inexistente.text)
    assert de_otra.json() == inexistente.json()  # indistinguibles
    assert sin_sentido.status_code == 422


def test_la_prediccion_por_http_es_la_del_artefacto_guardado(client_por_peticion, entrenado):
    modelo = _fila_modelo(entrenado.db, entrenado.id, TIPO_DEMANDA, con_artefacto=True)
    artefacto = persistencia.deserializar(modelo.artefacto, modelo.artefacto_sha256)
    esperadas = demanda.predecir_demanda(artefacto, 6)
    assert any(p.unidades > 0 for p in esperadas)

    cuerpo = _ok(_get(client_por_peticion, "demanda", entrenado.h, semanas=6))

    por_id = {c["categoria_id"]: c for c in cuerpo["categorias"]}
    assert set(por_id) == {c["id"] for c in artefacto["categorias"]}
    for categoria_id, bloque in por_id.items():
        propias = [p for p in esperadas if p.categoria_id == categoria_id]
        assert [p["etiqueta"] for p in bloque["prediccion"]] == [p.semana_inicio.isoformat() for p in propias]
        assert [p["valor"] for p in bloque["prediccion"]] == [p.unidades for p in propias]
        assert [p["minimo"] for p in bloque["prediccion"]] == [p.minimo for p in propias]
        assert [p["maximo"] for p in bloque["prediccion"]] == [p.maximo for p in propias]


def test_la_demanda_funciona_con_el_horizonte_minimo_y_el_maximo(client_por_peticion, entrenado):
    una = _ok(_get(client_por_peticion, "demanda", entrenado.h, semanas=1))
    doce = _ok(_get(client_por_peticion, "demanda", entrenado.h, semanas=12))

    assert una["horizonte_semanas"] == 1 and all(len(c["prediccion"]) == 1 for c in una["categorias"])
    assert doce["horizonte_semanas"] == 12 and all(len(c["prediccion"]) == 12 for c in doce["categorias"])
    assert len(doce["total_empresa"]["prediccion"]) == 12
    fechas = _lunes_consecutivos([p["etiqueta"] for p in doce["total_empresa"]["prediccion"]])
    assert fechas[0] == FIN + dt.timedelta(days=1)
    # La primera semana de la predicción recursiva no depende del horizonte pedido.
    assert doce["total_empresa"]["prediccion"][0] == una["total_empresa"]["prediccion"][0]


# ---- Segmentos ---------------------------------------------------------------------------------------------------------------


def test_los_segmentos_suman_los_clientes_y_los_porcentajes(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "segmentos", entrenado.h))
    segmentos = cuerpo["segmentos"]
    rfm = sintetico.filas_rfm(entrenado.historial, FIN)

    assert cuerpo["clientes_segmentados"] == len(rfm) == sum(s["clientes"] for s in segmentos)
    assert cuerpo["k"] == len(segmentos) and 2 <= cuerpo["k"] <= 6
    assert len({s["nombre"] for s in segmentos}) == len(segmentos) and len({s["id"] for s in segmentos}) == len(segmentos)
    assert sum(s["porcentaje_clientes"] for s in segmentos) == pytest.approx(100, abs=0.5)
    assert sum(s["porcentaje_monto"] for s in segmentos) == pytest.approx(100, abs=0.5)
    for s in segmentos:
        assert s["clientes"] > 0 and s["porcentaje_clientes"] == pytest.approx(s["clientes"] / len(rfm) * 100, abs=0.1)
        assert s["descripcion"].strip() and s["accion_sugerida"].strip()
        assert s["monto_total"] == pytest.approx(s["monto_medio"] * s["clientes"], rel=0.02)
    # El dinero de todos los segmentos es el de las compras del historial.
    assert sum(s["monto_total"] for s in segmentos) == pytest.approx(float(sum(f["monto_total"] for f in rfm)), rel=0.001)
    assert -1 <= cuerpo["silhouette"] <= 1 and cuerpo["supuestos"] and cuerpo["interpretacion"]
    assert cuerpo["grafico_sugerido"]["tipo"] == "torta"


def test_la_dispersion_es_anonima_y_reparte_a_los_clientes_en_sus_segmentos(client_por_peticion, entrenado):
    respuesta = _get(client_por_peticion, "segmentos", entrenado.h)
    cuerpo = _ok(respuesta)
    rfm = sintetico.filas_rfm(entrenado.historial, FIN)
    puntos = cuerpo["dispersion"]

    _sin_datos_de_cliente(cuerpo)
    assert all(set(p) == {"segmento_id", "frecuencia", "monto"} for p in puntos)
    # Con 80 clientes la muestra los incluye a todos: mismos pares (frecuencia, monto) que las compras reales...
    assert sorted((p["frecuencia"], round(p["monto"], 2)) for p in puntos) == sorted(
        (f["frecuencia"], float(f["monto_total"])) for f in rfm
    )
    # ...y cada segmento recibe tantos puntos como clientes dice tener (la asignación coincide con la del entrenamiento).
    for s in cuerpo["segmentos"]:
        assert sum(1 for p in puntos if p["segmento_id"] == s["id"]) == s["clientes"], s["nombre"]
    assert {p["segmento_id"] for p in puntos} <= {s["id"] for s in cuerpo["segmentos"]}


def test_la_dispersion_se_limita_a_300_puntos_y_es_determinista(client_por_peticion, mundo):
    empresa_id, _, historial, _ = cargar_historia(mundo, "fashionstore", clientes=450)
    entrenar(mundo, "fashionstore", [TIPO_SEGMENTOS])
    cabeceras = cabeceras_de(mundo, "fashionstore")
    con_compras = len(sintetico.filas_rfm(historial, FIN))
    assert con_compras > 300  # si no, la prueba no ejercitaría el tope

    primera = _ok(_get(client_por_peticion, "segmentos", cabeceras))
    segunda = _ok(_get(client_por_peticion, "segmentos", cabeceras))

    paso = max(1, math.ceil(con_compras / 300))
    assert primera["clientes_segmentados"] == con_compras
    assert 0 < len(primera["dispersion"]) <= 300
    assert len(primera["dispersion"]) == len(range(0, con_compras, paso))
    assert primera["dispersion"] == segunda["dispersion"]  # la misma muestra en cada consulta
    _sin_datos_de_cliente(primera)
    assert empresa_id == id_de(mundo, "fashionstore")


def test_las_curvas_del_silhouette_y_del_codo_cubren_los_mismos_k(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "segmentos", entrenado.h))
    silhouette, codo = cuerpo["curva_silhouette"], cuerpo["curva_codo"]

    ks = [int(p["etiqueta"]) for p in silhouette]
    assert ks == list(range(2, max(ks) + 1)) and min(ks) == 2 and max(ks) <= 6
    assert [int(p["etiqueta"]) for p in codo] == ks
    assert all(-1 <= p["valor"] <= 1 for p in silhouette)
    assert all(p["valor"] > 0 for p in codo) and codo[0]["valor"] > codo[-1]["valor"]  # más grupos, menos dispersión interna
    # El k elegido está en la curva y su silhouette es el que se informa.
    elegido = next(p for p in silhouette if int(p["etiqueta"]) == cuerpo["k"])
    assert elegido["valor"] == pytest.approx(cuerpo["silhouette"], abs=1e-6)


# ---- Panel ---------------------------------------------------------------------------------------------------------------------


def test_el_panel_es_coherente_con_las_rutas_individuales(client_por_peticion, entrenado):
    panel = _ok(_get(client_por_peticion, "panel", entrenado.h))
    estado = _ok(_get(client_por_peticion, "estado", entrenado.h))
    dem = _ok(_get(client_por_peticion, "demanda", entrenado.h))
    seg = _ok(_get(client_por_peticion, "segmentos", entrenado.h))
    ano = _ok(_get(client_por_peticion, "anomalias", entrenado.h, dias=30))
    rep = _ok(_get(client_por_peticion, "reposicion", entrenado.h))

    assert panel["estado"] == estado and panel["demanda"] == dem and panel["segmentos"] == seg and panel["avisos"] == []
    assert panel["anomalias"] == ano and panel["reposicion"] == rep
    kpis = {k["clave"]: k for k in panel["kpis"]}
    assert len(kpis) == len(panel["kpis"])  # sin claves repetidas
    assert set(kpis) == {
        "demanda_proxima_semana", "mejora_modelo", "clientes_segmentados", "pct_campeones", "clientes_en_riesgo",
        "anomalias_30_dias", "categorias_criticas",
    }  # fmt: skip
    assert kpis["anomalias_30_dias"]["valor"] == ano["total"] and kpis["categorias_criticas"]["valor"] == rep["criticos"]
    assert kpis["demanda_proxima_semana"]["valor"] == dem["total_empresa"]["prediccion"][0]["valor"] > 0
    assert kpis["mejora_modelo"]["valor"] == pytest.approx(dem["metricas"]["mejora_mae_pct"], abs=0.05)
    assert kpis["clientes_segmentados"]["valor"] == seg["clientes_segmentados"]
    en_riesgo = sum(s["clientes"] for s in seg["segmentos"] if s["nombre"] in NOMBRES_EN_RIESGO)
    assert kpis["clientes_en_riesgo"]["valor"] == en_riesgo <= seg["clientes_segmentados"]
    campeones = [s for s in seg["segmentos"] if s["nombre"].startswith("Campeones")]
    assert len(campeones) == 1 and kpis["pct_campeones"]["valor"] == campeones[0]["porcentaje_clientes"]


@pytest.mark.parametrize(
    "entrenado_solo, bloques_null, avisos, kpi_presente, kpi_ausente",
    [
        # Con solo los segmentos faltan la demanda, las anomalías y la reposición (que se apoya en la demanda).
        (TIPO_SEGMENTOS, {"demanda", "anomalias", "reposicion"}, ["Demanda", "Anomalías", "Reposición"], "clientes_segmentados", "demanda_proxima_semana"),
        # Con solo la demanda faltan los segmentos y las anomalías; la reposición sí sale.
        (TIPO_DEMANDA, {"segmentos", "anomalias"}, ["Segmentos", "Anomalías"], "demanda_proxima_semana", "clientes_segmentados"),
    ],
)  # fmt: skip
def test_el_panel_con_un_solo_modelo_deja_los_demas_bloques_en_null_con_su_aviso(
    client_por_peticion, fs, entrenado_solo, bloques_null, avisos, kpi_presente, kpi_ausente
):
    entrenar(fs.db, "fashionstore", [entrenado_solo])

    panel = _ok(_get(client_por_peticion, "panel", fs.h))

    for bloque in ("demanda", "segmentos", "anomalias", "reposicion"):
        assert (panel[bloque] is None) == (bloque in bloques_null), bloque
    assert panel["avisos"] == [f"{titulo}: {cu24.MENSAJE_SIN_MODELO}" for titulo in avisos]
    claves = {k["clave"] for k in panel["kpis"]}
    assert kpi_presente in claves and kpi_ausente not in claves
    assert "anomalias_30_dias" not in claves  # sin el modelo de anomalías no hay ese KPI
    assert ("categorias_criticas" in claves) == ("reposicion" not in bloques_null)
    estados = {m["tipo"]: m["estado"] for m in panel["estado"]["modelos"]}
    assert estados == {t: ("vigente" if t == entrenado_solo else "sin_entrenar") for t in (TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS)}


def test_el_panel_sin_ningun_modelo_responde_200_con_avisos_y_sin_kpis(client_por_peticion, fs):
    respuesta = _get(client_por_peticion, "panel", fs.h)

    panel = _ok(respuesta)  # no es un 409: el panel se muestra y dice qué falta
    assert all(panel[b] is None for b in ("demanda", "segmentos", "anomalias", "reposicion")) and panel["kpis"] == []
    assert panel["avisos"] == [f"{t}: {cu24.MENSAJE_SIN_MODELO}" for t in ("Demanda", "Segmentos", "Anomalías", "Reposición")]
    assert [m["estado"] for m in panel["estado"]["modelos"]] == ["sin_entrenar"] * 3
    assert panel["estado"]["puede_entrenar"] == {TIPO_DEMANDA: True, TIPO_SEGMENTOS: True, TIPO_ANOMALIAS: True}


# ---- Sin modelo / obsoleto / desactualizado -------------------------------------------------------------------------------------


def test_sin_modelo_las_cuatro_rutas_de_consulta_dan_409_modelo_no_entrenado(client_por_peticion, fs):
    # La reposición depende del modelo de DEMANDA: ese es el tipo que dice faltar.
    for ruta, tipo in (("demanda", TIPO_DEMANDA), ("segmentos", TIPO_SEGMENTOS), ("anomalias", TIPO_ANOMALIAS), ("reposicion", TIPO_DEMANDA)):
        respuesta = _get(client_por_peticion, ruta, fs.h)
        assert respuesta.status_code == 409, (ruta, respuesta.text)
        cuerpo = respuesta.json()
        assert cuerpo["codigo"] == "modelo_no_entrenado" and cuerpo["tipo"] == tipo
        assert cuerpo["mensaje"] == cu24.MENSAJE_SIN_MODELO
    # También con un filtro: primero se resuelve que no hay modelo.
    assert _get(client_por_peticion, "demanda", fs.h, categoria_id=1).status_code == 409


@pytest.mark.parametrize(
    "dano",
    [
        pytest.param(lambda fila: setattr(fila, "artefacto_sha256", "0" * 64), id="huella_alterada"),
        pytest.param(lambda fila: setattr(fila, "artefacto", fila.artefacto[:-8] + b"alterado"), id="bytes_alterados"),
        pytest.param(lambda fila: setattr(fila, "artefacto", b"esto no es un modelo"), id="bytes_basura_con_su_huella"),
    ],
)
def test_un_artefacto_alterado_da_409_modelo_obsoleto_y_nunca_500(client_por_peticion, entrenado, dano):
    def cambio(fila):
        dano(fila)
        if fila.artefacto_sha256 != "0" * 64 and fila.artefacto == b"esto no es un modelo":
            fila.artefacto_sha256 = persistencia.huella(fila.artefacto)  # huella válida pero contenido ilegible

    _alterar(entrenado.db, entrenado.id, TIPO_DEMANDA, cambio)

    respuesta = _get(client_por_peticion, "demanda", entrenado.h)
    assert respuesta.status_code == 409, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "modelo_obsoleto" and cuerpo["tipo"] == TIPO_DEMANDA
    assert "reentrenar" in cuerpo["mensaje"].lower()
    # El otro modelo, intacto, sigue funcionando, y el panel no se cae: muestra el bloque dañado como null con su aviso.
    assert _get(client_por_peticion, "segmentos", entrenado.h).status_code == 200
    assert _get(client_por_peticion, "anomalias", entrenado.h).status_code == 200
    # La reposición se apoya en el modelo de demanda: con él dañado también da 409 (y con el mismo tipo).
    reposicion = _get(client_por_peticion, "reposicion", entrenado.h)
    assert reposicion.status_code == 409 and reposicion.json()["codigo"] == "modelo_obsoleto" and reposicion.json()["tipo"] == TIPO_DEMANDA
    panel = _ok(_get(client_por_peticion, "panel", entrenado.h))
    assert panel["demanda"] is None and panel["reposicion"] is None
    assert panel["segmentos"] is not None and panel["anomalias"] is not None
    assert len(panel["avisos"]) == 2
    assert panel["avisos"][0].startswith("Demanda: ") and panel["avisos"][1].startswith("Reposición: ")


def test_otra_version_de_scikit_learn_marca_el_modelo_obsoleto_y_da_409(client_por_peticion, entrenado):
    _alterar(entrenado.db, entrenado.id, TIPO_DEMANDA, _con_sklearn("0.0.1"))

    estado = {m["tipo"]: m for m in _ok(_get(client_por_peticion, "estado", entrenado.h))["modelos"]}
    assert estado[TIPO_DEMANDA]["estado"] == "obsoleto" and estado[TIPO_DEMANDA]["entrenado"] is True
    assert "0.0.1" in estado[TIPO_DEMANDA]["mensaje"] and "reentrenarlo" in estado[TIPO_DEMANDA]["mensaje"]
    assert estado[TIPO_SEGMENTOS]["estado"] == "vigente" and estado[TIPO_ANOMALIAS]["estado"] == "vigente"
    respuesta = _get(client_por_peticion, "demanda", entrenado.h)
    assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "modelo_obsoleto"
    assert _get(client_por_peticion, "segmentos", entrenado.h).status_code == 200
    assert _get(client_por_peticion, "anomalias", entrenado.h).status_code == 200  # no usa el modelo de demanda
    assert _get(client_por_peticion, "reposicion", entrenado.h).status_code == 409  # sí lo usa

    # Los segmentos guardan la versión en otro sitio (`versiones.sklearn`): también cuentan.
    _alterar(entrenado.db, entrenado.id, TIPO_SEGMENTOS, _con_sklearn("0.0.1"))
    respuesta = _get(client_por_peticion, "segmentos", entrenado.h)
    assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "modelo_obsoleto"
    panel = _ok(_get(client_por_peticion, "panel", entrenado.h))  # con dos obsoletos el panel sigue respondiendo
    assert panel["demanda"] is None and panel["segmentos"] is None and panel["reposicion"] is None
    assert panel["anomalias"] is not None and [k["clave"] for k in panel["kpis"]] == ["anomalias_30_dias"]
    assert [a.split(":")[0] for a in panel["avisos"]] == ["Demanda", "Segmentos", "Reposición"]
    assert [m["estado"] for m in panel["estado"]["modelos"]] == ["obsoleto", "obsoleto", "vigente"]

    # Reentrenar lo arregla: la versión 2 se entrenó con la versión instalada.
    cuerpo = _ok(client_por_peticion.post(f"{BASE}/entrenar", headers=entrenado.h))
    assert [r["version"] for r in cuerpo["resultados"]] == [2, 2, 2]
    assert _get(client_por_peticion, "reposicion", entrenado.h).status_code == 200
    assert _get(client_por_peticion, "demanda", entrenado.h).status_code == 200
    assert _get(client_por_peticion, "segmentos", entrenado.h).status_code == 200


def test_con_la_fecha_adelantada_el_modelo_sigue_sirviendo_pero_dice_que_esta_desactualizado(client_por_peticion, entrenado, monkeypatch):
    monkeypatch.setattr(cu24, "hoy_utc", lambda: FIN + dt.timedelta(days=40))

    estado = _ok(_get(client_por_peticion, "estado", entrenado.h))
    assert [m["estado"] for m in estado["modelos"]] == ["desactualizado"] * 3
    assert all("Conviene reentrenarlo" in m["mensaje"] and m["entrenado"] is True for m in estado["modelos"])
    dem = _ok(_get(client_por_peticion, "demanda", entrenado.h))
    seg = _ok(_get(client_por_peticion, "segmentos", entrenado.h))
    assert dem["modelo"]["estado"] == "desactualizado" and dem["avisos"] == [dem["modelo"]["mensaje"]]
    assert seg["modelo"]["estado"] == "desactualizado" and seg["avisos"] == [seg["modelo"]["mensaje"]]
    assert len(dem["total_empresa"]["prediccion"]) == 4 and seg["clientes_segmentados"] > 0  # sigue dando resultados
    panel = _ok(_get(client_por_peticion, "panel", entrenado.h))
    assert panel["demanda"] is not None and panel["segmentos"] is not None and panel["kpis"]
    assert panel["demanda"]["avisos"] == dem["avisos"]
    # Las otras dos consultas también avisan, cada una con el mensaje de SU modelo.
    ano = _ok(_get(client_por_peticion, "anomalias", entrenado.h))
    rep = _ok(_get(client_por_peticion, "reposicion", entrenado.h))
    assert ano["avisos"] == [ano["modelo"]["mensaje"]] and ano["modelo"]["tipo"] == TIPO_ANOMALIAS and ano["modelo"]["estado"] == "desactualizado"
    assert rep["avisos"] == [rep["modelo"]["mensaje"]] and rep["modelo"]["tipo"] == TIPO_DEMANDA
    assert panel["anomalias"]["avisos"] == [panel["anomalias"]["modelo"]["mensaje"]] and panel["reposicion"]["avisos"] == rep["avisos"]


def test_los_umbrales_de_vigencia_se_prueban_en_el_caso_de_uso_con_la_fecha_inyectada(entrenado):
    db, uid = entrenado.db, usuario_de(entrenado.db, "fashionstore").id
    caso = ConsultarAnaliticaML()

    def entrenado_el(dia: dt.date):
        for tipo in (TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS):
            _alterar(db, entrenado.id, tipo, lambda fila: setattr(fila, "entrenado_en", dt.datetime.combine(dia, dt.time(12), tzinfo=dt.timezone.utc)))

    def estados(hoy):
        with en_empresa(db, entrenado.id):
            return [(m.estado, m.mensaje) for m in caso.estado(db, uid, hoy=hoy).modelos]

    # Recién entrenado, un día después de los datos: vigente.
    entrenado_el(HOY)
    assert [e for e, _ in estados(HOY)] == ["vigente"] * 3
    # Por los DÍAS desde el entrenamiento: 30 todavía vigente, 31 ya no (datos al día en los tres casos).
    entrenado_el(HOY - dt.timedelta(days=30))
    assert [e for e, _ in estados(HOY)] == ["vigente"] * 3
    entrenado_el(HOY - dt.timedelta(days=31))
    desactualizados = estados(HOY)
    assert [e for e, _ in desactualizados] == ["desactualizado"] * 3
    assert all("hace 31 días" in m for _, m in desactualizados)
    # Por las SEMANAS de ventas posteriores a los datos del modelo (entrenado "hoy" en cada caso): 4 vigente, 5 no.
    cuatro = FIN + dt.timedelta(days=28)
    entrenado_el(cuatro)
    assert [e for e, _ in estados(cuatro)] == ["vigente"] * 3
    cinco = FIN + dt.timedelta(days=35)
    entrenado_el(cinco)
    nuevos = estados(cinco)
    assert [e for e, _ in nuevos] == ["desactualizado"] * 3
    assert all("hace 5 semanas" in m for _, m in nuevos)

    # Las respuestas llevan el aviso solo cuando corresponde.
    with en_empresa(db, entrenado.id):
        tarde = caso.demanda(db, uid, 4, hoy=cinco)
        al_dia = caso.demanda(db, uid, 4, hoy=cuatro)
        segmentos_tarde = caso.segmentos(db, uid, hoy=cinco)
    assert tarde.modelo.estado == "desactualizado" and tarde.avisos == [tarde.modelo.mensaje]
    assert segmentos_tarde.avisos == [segmentos_tarde.modelo.mensaje]
    assert al_dia.modelo.estado == "vigente" and al_dia.avisos == []


# ---- Aislamiento y secreto del artefacto ------------------------------------------------------------------------------------------


def test_cada_empresa_ve_solo_su_modelo_y_el_cliente_no_elige_la_empresa(client_por_peticion, entrenado):
    ch_id, catalogo_ch, historial_ch, _ = cargar_historia(entrenado.db, "chaski-sport", perfil="B")
    entrenar(entrenado.db, "chaski-sport")
    cabeceras_ch = cabeceras_de(entrenado.db, "chaski-sport")
    esperado_fs = len(sintetico.filas_rfm(entrenado.historial, FIN))
    esperado_ch = len(sintetico.filas_rfm(historial_ch, FIN))
    assert esperado_fs != esperado_ch  # historiales distintos: la prueba distingue de quién son los datos

    propio = _ok(_get(client_por_peticion, "segmentos", entrenado.h))
    con_empresa_ajena = _ok(_get(client_por_peticion, "segmentos", entrenado.h, empresa_id=ch_id))
    de_chaski = _ok(_get(client_por_peticion, "segmentos", cabeceras_ch))

    assert propio["clientes_segmentados"] == esperado_fs and de_chaski["clientes_segmentados"] == esperado_ch
    assert con_empresa_ajena == propio  # el parámetro `empresa_id` se ignora
    ids_ch = {c.categoria_id for c in catalogo_ch.categorias}
    ids_fs = {c.categoria_id for c in entrenado.catalogo.categorias}
    categorias_fs = {c["categoria_id"] for c in _ok(_get(client_por_peticion, "demanda", entrenado.h))["categorias"]}
    categorias_ch = {c["categoria_id"] for c in _ok(_get(client_por_peticion, "demanda", cabeceras_ch))["categorias"]}
    assert categorias_fs <= ids_fs and categorias_ch <= ids_ch and not (categorias_fs & categorias_ch)
    # El entrenamiento de una no toca la versión de la otra.
    _ok(client_por_peticion.post(f"{BASE}/entrenar", headers=cabeceras_ch, json={"tipos": [TIPO_SEGMENTOS]}))
    assert _fila_modelo(entrenado.db, entrenado.id, TIPO_SEGMENTOS).version == 1
    assert _fila_modelo(entrenado.db, ch_id, TIPO_SEGMENTOS).version == 2


def test_ninguna_respuesta_deja_salir_el_artefacto_ni_datos_de_clientes(client_por_peticion, entrenado):
    respuestas = [
        _get(client_por_peticion, "estado", entrenado.h),
        client_por_peticion.post(f"{BASE}/entrenar", headers=entrenado.h),  # versión 2: la vigente al consultar
        _get(client_por_peticion, "demanda", entrenado.h, semanas=12),
        _get(client_por_peticion, "segmentos", entrenado.h),
        _get(client_por_peticion, "anomalias", entrenado.h, dias=365),
        _get(client_por_peticion, "reposicion", entrenado.h, semanas=12),
        _get(client_por_peticion, "panel", entrenado.h),
    ]
    huellas = {
        _fila_modelo(entrenado.db, entrenado.id, t, version=v).artefacto_sha256
        for t in (TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS)
        for v in (1, 2)
    }
    assert len(huellas) >= 3
    for respuesta in respuestas:
        cuerpo = _ok(respuesta)
        _sin_artefacto(cuerpo)
        _sin_datos_de_cliente(cuerpo)
        assert not any(h in respuesta.text for h in huellas), respuesta.request.url  # ni siquiera la huella
        assert "joblib" not in respuesta.text


def test_el_detector_de_artefactos_detecta_lo_que_debe():
    _sin_artefacto({"modelo": {"mae": 1.5, "mensaje": "Vigente: versión 1, entrenado hace 0 días."}, "lista": [1, "a b c"]})
    with pytest.raises(AssertionError):
        _sin_artefacto({"modelo": {"artefacto": "x"}})
    with pytest.raises(AssertionError):
        _sin_artefacto({"a": [{"Artefacto_Sha256": "x"}]})
    with pytest.raises(AssertionError):
        _sin_artefacto({"a": ["QUJD" * 100]})  # 400 caracteres base64
    with pytest.raises(AssertionError):
        _sin_artefacto({"a": b"bytes"})
    _sin_datos_de_cliente({"clientes": 3, "dispersion": [{"segmento_id": 1}]})
    with pytest.raises(AssertionError):
        _sin_datos_de_cliente({"dispersion": [{"cliente_id": 7}]})
