"""E11, paso 7: modelo supervisado de demanda semanal (`ml/demanda.py`). Cálculo puro, sin base ni red."""

import json
import math
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from app.inteligencia.ml import limites
from app.inteligencia.ml.demanda import (
    SEMANAS_TEST,
    PrediccionCategoria,
    ResultadoDemanda,
    entrenar_demanda,
    predecir_demanda,
)
from app.inteligencia.ml.persistencia import deserializar, serializar
from tests.inteligencia.ml._datos_demanda import HASTA_BASE, generar_filas


@pytest.fixture(scope="module")
def filas():
    return generar_filas(n_semanas=78, n_categorias=5)


@pytest.fixture(scope="module")
def resultado(filas) -> ResultadoDemanda:
    return entrenar_demanda(filas, HASTA_BASE)


def _constantes(n_semanas, n_categorias=3, unidades=10):
    """Todas las categorías venden lo mismo todas las semanas (el lunes)."""
    primero = HASTA_BASE - timedelta(days=6) - timedelta(weeks=n_semanas - 1)
    return [
        {
            "dia": primero + timedelta(weeks=j),
            "categoria_id": c,
            "categoria": f"Cat {c}",
            "transacciones": 2,
            "unidades": unidades,
            "total_ventas": Decimal(unidades * 10),
            "ventas_brutas": Decimal(unidades * 10),
        }
        for c in range(1, n_categorias + 1)
        for j in range(n_semanas)
    ]


def _numeros(valor):
    """Todos los números que aparecen en una estructura anidada."""
    if isinstance(valor, dict):
        return [n for v in valor.values() for n in _numeros(v)]
    if isinstance(valor, (list, tuple)):
        return [n for v in valor for n in _numeros(v)]
    return [valor] if isinstance(valor, (int, float)) and not isinstance(valor, bool) else []


def test_con_datos_suficientes_el_estado_es_ok_y_trae_el_artefacto(resultado):
    assert resultado.estado == "ok" and resultado.motivo is None
    assert resultado.artefacto is not None
    assert resultado.datos_desde is not None and resultado.datos_hasta == HASTA_BASE
    assert resultado.parametros["n_semanas"] == 78 and resultado.parametros["n_categorias"] == 5
    assert resultado.filas_entrenamiento == (78 - 4) * 5


def test_las_metricas_estan_presentes_y_son_finitas_o_none(resultado):
    m = resultado.metricas
    for clave in ("mae", "rmse", "r2", "mae_base", "rmse_base", "r2_base", "mejora_mae_pct", "modelo_elegido",
                  "validacion_cruzada", "filas_train", "filas_test"):
        assert clave in m, clave
    assert all(math.isfinite(n) for n in _numeros(m))
    assert m["modelo_elegido"] in ("ridge", "mezcla", "random_forest")
    assert set(m["validacion_cruzada"]) == {"ridge", "mezcla", "random_forest"}
    assert m["validacion_cruzada"][m["modelo_elegido"]]["mae_medio"] == min(
        v["mae_medio"] for v in m["validacion_cruzada"].values()
    )  # gana el de menor MAE medio en la validación cruzada
    for candidato in ("ridge", "mezcla", "random_forest"):
        cv = m["validacion_cruzada"][candidato]
        assert len(cv["mae_por_pliegue"]) == 3
        assert cv["mae_medio"] == pytest.approx(sum(cv["mae_por_pliegue"]) / 3)


def test_el_test_son_las_ultimas_12_semanas_y_va_despues_del_train(resultado):
    m = resultado.metricas
    # 78 semanas, sin las 4 primeras (sin rezagos): 74 semanas con filas x 5 categorías; 12 semanas son test.
    assert m["filas_test"] == SEMANAS_TEST * 5 == 60
    assert m["filas_train"] == (74 - SEMANAS_TEST) * 5
    assert m["filas_train"] + m["filas_test"] == resultado.filas_entrenamiento


def test_el_modelo_no_es_peor_que_la_linea_base_sobre_los_datos_de_juguete(resultado):
    m = resultado.metricas
    assert m["mae"] <= m["mae_base"]
    assert m["rmse"] <= m["rmse_base"]
    assert m["mejora_mae_pct"] == pytest.approx((m["mae_base"] - m["mae"]) / m["mae_base"] * 100)
    assert m["mejora_mae_pct"] >= 5  # umbral del paso 7 (ver el informe de la etapa)


def test_el_r2_en_test_es_razonable(resultado):
    assert resultado.metricas["r2"] >= 0.50


def test_entrenar_dos_veces_da_metricas_artefacto_y_predicciones_identicos(filas, resultado):
    otra = entrenar_demanda(filas, HASTA_BASE)
    assert otra.metricas == resultado.metricas
    assert serializar(otra.artefacto)[0] == serializar(resultado.artefacto)[0]
    assert predecir_demanda(otra.artefacto, 6) == predecir_demanda(resultado.artefacto, 6)
    quitar = lambda p: {k: v for k, v in p.items() if k != "segundos_entrenamiento"}  # noqa: E731
    assert quitar(otra.parametros) == quitar(resultado.parametros)


def test_la_semilla_se_registra_y_otra_semilla_no_rompe(filas, resultado):
    assert resultado.parametros["semilla"] == limites.ML_SEMILLA_POR_DEFECTO
    otra = entrenar_demanda(filas, HASTA_BASE, semilla=7)
    assert otra.estado == "ok" and otra.parametros["semilla"] == 7


def test_prediccion_a_4_semanas_da_4_por_n_categorias_filas_enteras_y_no_negativas(resultado):
    predicciones = predecir_demanda(resultado.artefacto, 4)
    assert len(predicciones) == 4 * 5
    assert all(isinstance(p, PrediccionCategoria) for p in predicciones)
    assert all(isinstance(p.unidades, int) and p.unidades >= 0 for p in predicciones)
    assert all(isinstance(p.minimo, int) and isinstance(p.maximo, int) for p in predicciones)
    assert all(0 <= p.minimo <= p.unidades <= p.maximo for p in predicciones)
    assert [p.semana_numero for p in predicciones] == [1] * 5 + [2] * 5 + [3] * 5 + [4] * 5
    assert {p.categoria for p in predicciones} == {"Poleras", "Camisas", "Chamarras", "Pantalones", "Accesorios"}


def test_el_rango_estimado_es_la_prediccion_mas_menos_el_rmse_del_test(resultado):
    rmse = resultado.metricas["rmse"]
    for p in predecir_demanda(resultado.artefacto, 2):
        assert abs((p.maximo - p.unidades) - rmse) <= 1  # la diferencia es el RMSE salvo el redondeo a entero
        if p.unidades - rmse > 1:
            assert abs((p.unidades - p.minimo) - rmse) <= 1
        else:
            assert p.minimo <= 1  # recortado a 0 (o casi): nunca negativo


def test_se_puede_predecir_hasta_12_semanas_y_ninguna_otra_cantidad(resultado):
    assert len(predecir_demanda(resultado.artefacto, 12)) == 12 * 5
    for invalido in (0, 13, -1):
        with pytest.raises(ValueError):
            predecir_demanda(resultado.artefacto, invalido)


def test_ninguna_semana_predicha_cae_en_el_pasado_y_son_lunes_consecutivos(resultado):
    predicciones = predecir_demanda(resultado.artefacto, 8)
    assert all(p.semana_inicio > HASTA_BASE for p in predicciones)  # el cierre de los datos es el domingo
    assert all(p.semana_inicio.weekday() == 0 for p in predicciones)
    lunes = sorted({p.semana_inicio for p in predicciones})
    assert lunes[0] == HASTA_BASE + timedelta(days=1)
    assert all((b - a).days == 7 for a, b in zip(lunes, lunes[1:]))


def test_la_semana_en_curso_no_entra_en_el_entrenamiento(filas):
    jueves = HASTA_BASE + timedelta(days=4)  # jueves 29: la semana del 26 está en curso
    con_curso = filas + [
        {"dia": HASTA_BASE + timedelta(days=2), "categoria_id": 1, "categoria": "Poleras", "transacciones": 1,
         "unidades": 9999, "total_ventas": Decimal("1.00"), "ventas_brutas": Decimal("1.00")}
    ]
    resultado = entrenar_demanda(con_curso, jueves)
    assert resultado.estado == "ok" and resultado.datos_hasta == HASTA_BASE
    assert resultado.metricas == entrenar_demanda(filas, HASTA_BASE).metricas  # lo de la semana en curso no cuenta


def test_menos_de_26_semanas_devuelve_datos_insuficientes_sin_excepcion():
    resultado = entrenar_demanda(generar_filas(n_semanas=25), HASTA_BASE)
    assert resultado.estado == "datos_insuficientes"
    assert "26" in resultado.motivo
    assert resultado.artefacto is None and resultado.metricas == {} and resultado.filas_entrenamiento == 0
    assert entrenar_demanda([], HASTA_BASE).estado == "datos_insuficientes"
    assert entrenar_demanda(generar_filas(n_semanas=26), HASTA_BASE).estado == "ok"  # el mínimo exacto sí entrena


def test_una_sola_categoria_con_ventas_no_alcanza_el_minimo_de_categorias(monkeypatch):
    una = generar_filas(n_semanas=60, n_categorias=1)
    resultado = entrenar_demanda(una, HASTA_BASE)
    assert resultado.estado == "datos_insuficientes" and "categoría" in resultado.motivo
    # Si el umbral se baja a 1 (decisión de negocio), el flujo completo funciona con una sola categoría.
    monkeypatch.setattr(limites, "ML_MIN_CATEGORIAS", 1)
    resultado = entrenar_demanda(una, HASTA_BASE)
    assert resultado.estado == "ok"
    predicciones = predecir_demanda(resultado.artefacto, 3)
    assert len(predicciones) == 3 and all(p.unidades >= 0 for p in predicciones)


def test_una_serie_constante_da_r2_none_y_no_rompe():
    resultado = entrenar_demanda(_constantes(40), HASTA_BASE)
    assert resultado.estado == "ok"
    assert resultado.metricas["r2"] is None and resultado.metricas["r2_base"] is None
    assert resultado.metricas["mae"] == pytest.approx(0, abs=1e-6)
    assert json.dumps(resultado.metricas)  # sin NaN
    assert all(p.unidades == 10 for p in predecir_demanda(resultado.artefacto, 4))


def test_el_artefacto_serializado_y_cargado_predice_igual(resultado):
    datos, huella, tamano = serializar(resultado.artefacto)
    assert tamano == len(datos) <= limites.ML_MAX_ARTEFACTO_BYTES
    cargado = deserializar(datos, huella)
    assert predecir_demanda(cargado, 12) == predecir_demanda(resultado.artefacto, 12)


def test_la_mezcla_de_ridge_y_bosque_es_el_promedio_y_se_puede_serializar():
    from app.inteligencia.ml.demanda import MezclaRidgeBosque

    rng = np.random.default_rng(3)
    X = rng.normal(size=(120, 4))
    y = X[:, 0] * 3 + rng.normal(scale=0.1, size=120)
    mezcla = MezclaRidgeBosque(42).fit(X, y)
    esperado = (mezcla.ridge_.predict(X[:10]) + mezcla.bosque_.predict(X[:10])) / 2.0
    assert np.allclose(mezcla.predict(X[:10]), esperado)
    datos, huella, _ = serializar(mezcla)  # una clase de nivel de módulo: joblib la puede guardar
    assert np.allclose(deserializar(datos, huella).predict(X[:10]), mezcla.predict(X[:10]))


def test_el_modelo_predice_la_correccion_sobre_la_media_movil_y_no_la_demanda_cruda():
    """Con una serie plana el modelo no debe inventar nada: sus predicciones quedan en el nivel de la serie. Un bosque que
    predijera la demanda cruda tendería a quedarse en el rango de lo visto; aquí parte de la media móvil."""
    from app.inteligencia.ml.demanda import _residuo
    from app.inteligencia.ml.preprocesamiento import INDICE_MEDIA_MOVIL

    X = np.zeros((3, INDICE_MEDIA_MOVIL + 1))
    X[:, INDICE_MEDIA_MOVIL] = [10.0, 20.0, 30.0]
    assert _residuo(X, np.array([12.0, 18.0, 30.0])).tolist() == [2.0, -2.0, 0.0]


def test_guarda_la_version_de_scikit_learn_las_columnas_y_los_supuestos(resultado):
    import numpy
    import sklearn

    p = resultado.parametros
    assert p["version_sklearn"] == sklearn.__version__ and p["version_numpy"] == numpy.__version__
    assert p["supuestos"] and any("descuento" in s and "4 semanas" in s for s in p["supuestos"])
    assert any("intervalo de confianza" in s for s in p["supuestos"])
    assert p["hiperparametros"]["random_forest"]["n_jobs"] == 1 and p["segundos_entrenamiento"] >= 0
    assert p["columnas"] == resultado.artefacto["columnas"]
    columnas = resultado.artefacto["columnas"]
    assert columnas[-15:-10] == [f"categoria_{i}" for i in range(1, 6)]  # el one-hot, luego el ciclo por categoría
    assert columnas[-10:-5] == [f"ciclo_sin_{i}" for i in range(1, 6)]
    assert columnas[-5:] == [f"ciclo_cos_{i}" for i in range(1, 6)]
    assert resultado.artefacto["version_artefacto"] == 2  # el modelo predice la diferencia contra la media móvil
    # Lo necesario para predecir sin la base: las últimas semanas de cada categoría.
    for categoria in resultado.artefacto["categorias"]:
        assert len(categoria["unidades_recientes"]) >= 4
        assert len(categoria["precio_reciente"]) >= 1 and len(categoria["pct_descuento_reciente"]) >= 1


def test_el_artefacto_no_guarda_datos_personales_ni_filas_originales(resultado):
    texto = repr({k: v for k, v in resultado.artefacto.items() if k not in ("modelo", "escalador")})
    assert "total_ventas" not in texto and "transacciones" not in texto
    assert set(resultado.artefacto["categorias"][0]) == {
        "id", "nombre", "unidades_recientes", "precio_reciente", "pct_descuento_reciente"
    }


def test_metricas_y_parametros_se_pueden_guardar_como_json(resultado):
    json.dumps(resultado.metricas, allow_nan=False)
    json.dumps(resultado.parametros, allow_nan=False)


def test_mas_de_104_semanas_y_30_categorias_entrena_y_avisa_del_recorte():
    resultado = entrenar_demanda(generar_filas(n_semanas=110, n_categorias=33), HASTA_BASE)
    assert resultado.estado == "ok"
    assert resultado.parametros["n_semanas"] == 104 and resultado.parametros["n_categorias"] == 30
    assert len(resultado.avisos) == 2
    assert len(predecir_demanda(resultado.artefacto, 4)) == 4 * 30


def test_un_entrenamiento_lento_deja_aviso_y_warning(filas, monkeypatch, caplog):
    monkeypatch.setattr(limites, "ML_TIEMPO_ENTRENAMIENTO_AVISO_SEG", -1)  # cualquier tiempo lo supera
    with caplog.at_level("WARNING", logger="app.inteligencia.ml"):
        resultado = entrenar_demanda(filas, HASTA_BASE)
    assert any("tardó" in aviso for aviso in resultado.avisos)
    assert any(r.levelname == "WARNING" and "ml_demanda_lento" in r.getMessage() for r in caplog.records)


def test_las_filas_de_entrada_no_se_modifican(filas):
    copia = [dict(f) for f in filas]
    entrenar_demanda(filas, HASTA_BASE)
    assert filas == copia


def test_las_fechas_de_los_datos_corresponden_a_semanas_completas(resultado):
    assert resultado.datos_desde.weekday() == 0
    assert resultado.datos_hasta.weekday() == 6
    assert (resultado.datos_hasta - resultado.datos_desde).days + 1 == 78 * 7
    assert resultado.datos_desde == date.fromisoformat(resultado.parametros["semana_desde"])
