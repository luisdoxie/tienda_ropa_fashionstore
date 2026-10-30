"""Modelo supervisado de demanda semanal por categoría (E11, paso 7). Cálculo puro: recibe las filas planas de
ventas, devuelve métricas y un artefacto serializable; no toca la base de datos ni importa paquetes de negocio.
numpy y scikit-learn solo se importan dentro de las funciones.

Flujo de `entrenar_demanda`:
  1. Serie semanal y características (`preprocesamiento`).
  2. División TEMPORAL: las últimas 12 semanas son TEST; el resto, TRAIN. Nunca al azar: mezclar semanas
     dejaría que el modelo viera el futuro de la serie y las métricas saldrían infladas.
  3. `StandardScaler` ajustado SOLO con TRAIN (en cada pliegue, solo con el tramo de entrenamiento del pliegue).
  4. Validación cruzada temporal (`TimeSeriesSplit(n_splits=3)` sobre las SEMANAS de TRAIN, de modo que una
     semana nunca queda partida entre entrenamiento y validación) para escoger entre Ridge y Random Forest:
     gana el de menor MAE medio; si empatan, Ridge (más simple).
  5. Métricas del ganador en TEST frente a una LÍNEA BASE (`media_movil_4` como predicción de la misma fila).
  6. El ganador se REENTRENA con todas las semanas; ese es el que va en el artefacto. Las métricas guardadas son
     las del hold-out (las del paso 5), para no inflarlas con datos que el modelo ya vio.

Honestidad: con datos sintéticos el modelo aprende los patrones que puso el generador; no es evidencia de
desempeño con datos reales.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.inteligencia.ml import limites
from app.inteligencia.ml.limites import ML_SEMILLA_POR_DEFECTO
from app.inteligencia.ml.preprocesamiento import (
    INDICE_MEDIA_MOVIL,
    REZAGOS,
    SEMANAS_DE_HISTORIA,
    DatosInsuficientesError,
    construir_matriz,
    construir_serie_semanal,
    fila_de_caracteristicas,
)

logger = logging.getLogger("app.inteligencia.ml")

SEMANAS_TEST = 12
MAX_SEMANAS_PREDICCION = 12
VERSION_ARTEFACTO = 2  # 2: el modelo predice la diferencia contra la media móvil de 4 semanas (antes, la demanda cruda)
HIPERPARAMETROS = {
    "ridge": {"alpha": 1.0},
    "random_forest": {"n_estimators": 200, "max_depth": 8, "min_samples_leaf": 3, "n_jobs": limites.ML_N_JOBS},
}
SUPUESTOS = [
    "El descuento de las semanas futuras se asume igual al promedio de las últimas 4 semanas.",
    "El ticket por unidad de las semanas futuras se asume igual al promedio de las últimas 4 semanas "
    "(la primera semana predicha usa el de la última semana real).",
    "La predicción es recursiva: para la semana t+2 se usa la predicción de t+1 como rezago, y así hasta 12 semanas; "
    "el error crece con el horizonte.",
    "El rango estimado es la predicción más/menos el RMSE del hold-out; NO es un intervalo de confianza estadístico.",
    "No se conocen eventos futuros (feriados, campañas, quiebres de stock): la demanda es la que se vendió, no la deseada.",
]


@dataclass
class ResultadoDemanda:
    estado: str  # "ok" | "datos_insuficientes"
    motivo: str | None = None
    avisos: list[str] = field(default_factory=list)
    metricas: dict = field(default_factory=dict)
    parametros: dict = field(default_factory=dict)
    filas_entrenamiento: int = 0
    datos_desde: date | None = None
    datos_hasta: date | None = None
    artefacto: dict | None = None


@dataclass
class PrediccionCategoria:
    categoria_id: int
    categoria: str
    semana_inicio: date  # lunes de la semana predicha
    semana_numero: int  # 1..h
    unidades: int
    minimo: int  # "rango estimado": unidades -/+ RMSE del test, no un intervalo de confianza
    maximo: int


def _finito(valor: Any) -> float | None:
    """Un float de Python, o None si no es finito (los NaN no viajan a JSON)."""
    if valor is None:
        return None
    valor = float(valor)
    return valor if math.isfinite(valor) else None


def _metricas_de(y: Any, prediccion: Any) -> tuple[float, float, float | None]:
    """MAE, RMSE y R2. El R2 es None cuando los valores reales no varían (no hay varianza que explicar)."""
    import numpy as np

    error = y - prediccion
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(error**2)))
    ss_total = float(np.sum((y - np.mean(y)) ** 2))
    r2 = None if ss_total <= 1e-12 else _finito(1.0 - float(np.sum(error**2)) / ss_total)
    return mae, rmse, r2


def _residuo(X: Any, y: Any) -> Any:
    """Lo que el modelo aprende a predecir: cuánto se aparta la demanda de la semana de la media móvil de 4
    semanas. Predecir la demanda cruda hace que un bosque (que no extrapola niveles) pierda contra el promedio
    móvil cuando la serie cambia de nivel por la estacionalidad; así el modelo parte de la línea base y solo
    aprende la corrección (estacionalidad, promoción, tendencia)."""
    return y - X[:, INDICE_MEDIA_MOVIL]


def _prediccion(modelo: Any, escalador: Any, X: Any) -> Any:
    """La demanda predicha: media móvil + corrección del modelo, sin pasar de 0."""
    import numpy as np

    return np.clip(X[:, INDICE_MEDIA_MOVIL] + modelo.predict(escalador.transform(X)), 0.0, None)


class MezclaRidgeBosque:
    """Promedio de Ridge y Random Forest. Cada uno se equivoca distinto (el lineal capta bien la estacionalidad y
    el bosque las interacciones), así que su promedio es más estable que cualquiera de los dos cuando hay pocas
    semanas de historia. Va a nivel de módulo para que `joblib` pueda serializarla."""

    def __init__(self, semilla: int) -> None:
        self.semilla = semilla

    def fit(self, X: Any, y: Any) -> "MezclaRidgeBosque":
        self.ridge_ = _crear_modelo("ridge", self.semilla).fit(X, y)
        self.bosque_ = _crear_modelo("random_forest", self.semilla).fit(X, y)
        return self

    def predict(self, X: Any) -> Any:
        return (self.ridge_.predict(X) + self.bosque_.predict(X)) / 2.0


def _crear_modelo(nombre: str, semilla: int) -> Any:
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import Ridge

    if nombre == "ridge":
        return Ridge(**HIPERPARAMETROS["ridge"])
    if nombre == "mezcla":
        return MezclaRidgeBosque(semilla)
    return RandomForestRegressor(**HIPERPARAMETROS["random_forest"], random_state=semilla)


def _validacion_cruzada(X: Any, y: Any, semana: Any, semilla: int) -> dict[str, list[float]]:
    """MAE por pliegue de cada candidato, con cortes que respetan el orden de las semanas."""
    import numpy as np
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.preprocessing import StandardScaler

    semanas_unicas = np.unique(semana)
    resultado: dict[str, list[float]] = {"ridge": [], "random_forest": [], "mezcla": []}
    for corte_entrenamiento, corte_validacion in TimeSeriesSplit(n_splits=3).split(semanas_unicas):
        en_train = np.isin(semana, semanas_unicas[corte_entrenamiento])
        en_valid = np.isin(semana, semanas_unicas[corte_validacion])
        escalador = StandardScaler().fit(X[en_train])
        for nombre in resultado:
            modelo = _crear_modelo(nombre, semilla).fit(escalador.transform(X[en_train]), _residuo(X[en_train], y[en_train]))
            prediccion = _prediccion(modelo, escalador, X[en_valid])
            resultado[nombre].append(float(np.mean(np.abs(y[en_valid] - prediccion))))
    return resultado


def entrenar_demanda(filas: list[dict], hasta: date, *, semilla: int = ML_SEMILLA_POR_DEFECTO) -> ResultadoDemanda:
    """Entrena, evalúa y empaqueta el modelo de demanda. Con pocos datos devuelve `datos_insuficientes` (con su
    motivo) en vez de lanzar. Dos corridas con los mismos datos y semilla dan métricas, artefacto y
    predicciones idénticos (`segundos_entrenamiento` en `parametros` es lo único que cambia)."""
    import numpy as np
    import sklearn
    from sklearn.preprocessing import StandardScaler

    inicio = time.perf_counter()
    try:
        serie = construir_serie_semanal(filas, hasta)
    except DatosInsuficientesError as exc:
        return ResultadoDemanda(estado="datos_insuficientes", motivo=exc.motivo, avisos=exc.avisos)
    matriz = construir_matriz(serie)
    X, y, semana = matriz.X, matriz.y, matriz.indice_semana

    primera_semana_test = serie.n_semanas - SEMANAS_TEST
    es_test = semana >= primera_semana_test
    es_train = ~es_test

    # --- Elección de modelo: validación cruzada temporal solo dentro de TRAIN.
    cruzada = _validacion_cruzada(X[es_train], y[es_train], semana[es_train], semilla)
    medias = {nombre: float(np.mean(maes)) for nombre, maes in cruzada.items()}
    # El de menor MAE medio; si empatan, el más simple (Ridge, luego la mezcla, luego el bosque).
    elegido = min(("ridge", "mezcla", "random_forest"), key=lambda nombre: medias[nombre])

    # --- Hold-out: el escalador y el modelo solo ven TRAIN.
    escalador = StandardScaler().fit(X[es_train])
    modelo = _crear_modelo(elegido, semilla).fit(escalador.transform(X[es_train]), _residuo(X[es_train], y[es_train]))
    prediccion_test = _prediccion(modelo, escalador, X[es_test])
    y_test = y[es_test]
    mae, rmse, r2 = _metricas_de(y_test, prediccion_test)
    # Línea base: la media móvil de 4 semanas de la propia fila (lo que haría alguien sin modelo).
    mae_base, rmse_base, r2_base = _metricas_de(y_test, X[es_test][:, INDICE_MEDIA_MOVIL])
    mejora = None if mae_base <= 1e-12 else _finito((mae_base - mae) / mae_base * 100.0)

    metricas = {
        "mae": _finito(mae),
        "rmse": _finito(rmse),
        "r2": r2,
        "mae_base": _finito(mae_base),
        "rmse_base": _finito(rmse_base),
        "r2_base": r2_base,
        "mejora_mae_pct": mejora,
        "modelo_elegido": elegido,
        "validacion_cruzada": {
            nombre: {"mae_por_pliegue": [float(v) for v in maes], "mae_medio": medias[nombre]}
            for nombre, maes in cruzada.items()
        },
        "filas_train": int(es_train.sum()),
        "filas_test": int(es_test.sum()),
    }

    # --- Modelo de producción: el ganador reentrenado con TODAS las semanas.
    escalador_final = StandardScaler().fit(X)
    modelo_final = _crear_modelo(elegido, semilla).fit(escalador_final.transform(X), _residuo(X, y))

    artefacto = {
        "version_artefacto": VERSION_ARTEFACTO,
        "modelo": modelo_final,
        "escalador": escalador_final,
        "modelo_elegido": elegido,
        "columnas": matriz.columnas,
        "categorias": [
            {
                "id": cid,
                "nombre": nombre,
                # Lo mínimo para predecir sin volver a la base: 8 semanas de unidades (rezagos y tendencia) y
                # las 4 últimas de ticket y descuento (para los supuestos del futuro).
                "unidades_recientes": [int(v) for v in serie.unidades[i, -SEMANAS_DE_HISTORIA:]],
                "precio_reciente": [float(v) for v in serie.precio_medio[i, -REZAGOS:]],
                "pct_descuento_reciente": [float(v) for v in serie.pct_descuento[i, -REZAGOS:]],
            }
            for i, (cid, nombre) in enumerate(serie.categorias)
        ],
        "ultima_semana": serie.semanas[-1],  # lunes de la última semana con datos
        "rmse_test": float(rmse),
        "semilla": semilla,
        "supuestos": list(SUPUESTOS),
    }

    segundos = time.perf_counter() - inicio
    avisos = list(serie.avisos)
    if segundos > limites.ML_TIEMPO_ENTRENAMIENTO_AVISO_SEG:
        aviso = f"El entrenamiento tardó {segundos:.1f} s (aviso a partir de {limites.ML_TIEMPO_ENTRENAMIENTO_AVISO_SEG} s)."
        avisos.append(aviso)
        logger.warning("ml_demanda_lento segundos=%.1f filas=%d", segundos, len(y))

    parametros = {
        "semilla": semilla,
        "hiperparametros": HIPERPARAMETROS,
        "n_semanas": serie.n_semanas,
        "n_categorias": serie.n_categorias,
        "semanas_test": SEMANAS_TEST,
        "semana_desde": serie.semanas[0].isoformat(),
        "semana_hasta": serie.semanas[-1].isoformat(),
        "version_sklearn": sklearn.__version__,
        "version_numpy": np.__version__,
        "columnas": matriz.columnas,
        "supuestos": list(SUPUESTOS),
        "segundos_entrenamiento": round(segundos, 3),
    }
    return ResultadoDemanda(
        estado="ok",
        avisos=avisos,
        metricas=metricas,
        parametros=parametros,
        filas_entrenamiento=int(len(y)),
        datos_desde=serie.semanas[0],
        datos_hasta=serie.semanas[-1] + timedelta(days=6),
        artefacto=artefacto,
    )


def predecir_demanda(artefacto: dict, semanas: int = 4) -> list[PrediccionCategoria]:
    """Unidades por categoría para las próximas `semanas` (1..12), de forma recursiva. Solo usa el artefacto.
    Devuelve `semanas x n_categorias` filas, ordenadas por semana y luego por id de categoría."""
    import numpy as np

    if isinstance(semanas, bool) or not isinstance(semanas, int) or not 1 <= semanas <= MAX_SEMANAS_PREDICCION:
        raise ValueError(f"Las semanas a predecir van de 1 a {MAX_SEMANAS_PREDICCION}")
    try:
        modelo, escalador = artefacto["modelo"], artefacto["escalador"]
        categorias, ultima_semana = artefacto["categorias"], artefacto["ultima_semana"]
        rmse = float(artefacto["rmse_test"])
    except (KeyError, TypeError) as exc:
        raise ValueError("El artefacto del modelo de demanda no tiene el formato esperado") from exc

    historia = [[float(v) for v in c["unidades_recientes"]] for c in categorias]
    # Supuesto: el descuento y el ticket futuros son el promedio de las últimas 4 semanas.
    descuento_futuro = [sum(c["pct_descuento_reciente"]) / len(c["pct_descuento_reciente"]) for c in categorias]
    precio_futuro = [sum(c["precio_reciente"]) / len(c["precio_reciente"]) for c in categorias]
    precio_anterior = [float(c["precio_reciente"][-1]) for c in categorias]

    resultado: list[PrediccionCategoria] = []
    for h in range(1, semanas + 1):
        lunes = ultima_semana + timedelta(weeks=h)
        filas = [
            fila_de_caracteristicas(historia[i], precio_anterior[i], descuento_futuro[i], lunes, i, len(categorias))
            for i in range(len(categorias))
        ]
        prediccion = _prediccion(modelo, escalador, np.array(filas, dtype=float))
        for i, categoria in enumerate(categorias):
            valor = float(prediccion[i])
            resultado.append(
                PrediccionCategoria(
                    categoria_id=categoria["id"],
                    categoria=categoria["nombre"],
                    semana_inicio=lunes,
                    semana_numero=h,
                    unidades=int(math.floor(valor + 0.5)),
                    minimo=max(0, int(math.floor(valor - rmse + 0.5))),
                    maximo=int(math.floor(valor + rmse + 0.5)),
                )
            )
            historia[i].append(valor)  # la predicción sin redondear alimenta el rezago siguiente
            precio_anterior[i] = precio_futuro[i]
    return resultado
