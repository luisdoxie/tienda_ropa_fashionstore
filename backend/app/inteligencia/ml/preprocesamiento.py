"""Preprocesamiento de la demanda semanal por categoría (E11, paso 7). Cálculo puro: recibe las filas planas que
devuelve `comercial.politicas.reporte_ventas_serie_diaria(desglose=("categoria",))` (más `ventas_brutas`) y arma
la serie semanal y la matriz de características. No toca la base de datos ni importa paquetes de negocio; numpy
solo se importa dentro de las funciones para no frenar el arranque de la aplicación.

SERIE. Semanas ISO lunes-domingo, SOLO completas: la última es la más reciente cuyo domingo es menor o igual a
`hasta` (la semana en curso se descarta: aún le faltan días y subestimaría la demanda). Las semanas sin ventas
valen 0 (no se omiten: omitirlas haría creer que nunca hay semanas flojas). Máximo `ML_MAX_SEMANAS` semanas
recientes y `ML_MAX_CATEGORIAS` categorías; lo que sobra se recorta con un aviso.

SIN FUGA. La fila de la semana `t` se arma SOLO con datos de semanas anteriores (`lag_*`, `media_movil_4`,
`tendencia`, `precio_medio_lag_1`), con el calendario de `t` (`semana_sin`, `semana_cos`, que se conocen de
antemano) y con una covariable declarada: `pct_descuento_semana`, la promoción de la propia semana `t` (la
tienda decide sus promociones antes de vender; al predecir el futuro se asume el promedio de las últimas 4
semanas y eso queda escrito en los `supuestos`). Nada más de la semana `t`, y nunca `y_t`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.inteligencia.ml import limites

#: Semanas de historia mínimas para armar una fila (los 4 rezagos).
REZAGOS = 4
#: Semanas que se conservan por categoría para poder calcular la tendencia (4 de nivel + 4 anteriores).
SEMANAS_DE_HISTORIA = 8

COLUMNAS_NUMERICAS: tuple[str, ...] = (
    "lag_1",
    "lag_2",
    "lag_3",
    "lag_4",
    "media_movil_4",
    "tendencia",
    "semana_sin",
    "semana_cos",
    "pct_descuento_semana",
    "precio_medio_lag_1",
)
INDICE_MEDIA_MOVIL = COLUMNAS_NUMERICAS.index("media_movil_4")


class DatosInsuficientesError(Exception):
    """No hay datos para entrenar (pocas semanas o pocas categorías con ventas). Lleva el motivo para mostrar y
    los avisos que se alcanzaron a generar. `entrenar_demanda` la convierte en un resultado estructurado."""

    def __init__(self, motivo: str, avisos: list[str] | None = None) -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.avisos = list(avisos or [])


@dataclass
class SerieSemanal:
    """Matriz categorías x semanas. `categorias` va ordenada por id y `semanas` por fecha (lunes)."""

    categorias: list[tuple[int, str]]
    semanas: list[date]
    unidades: Any  # np.ndarray (n_categorias, n_semanas), float
    neto: Any  # ventas con descuento
    bruto: Any  # ventas sin descuento
    pct_descuento: Any  # 1 - neto/bruto, en [0, 1]; 0 si la semana no vendió
    precio_medio: Any  # ticket por unidad (neto/unidades); en semanas sin ventas arrastra el último conocido
    avisos: list[str] = field(default_factory=list)

    @property
    def n_semanas(self) -> int:
        return len(self.semanas)

    @property
    def n_categorias(self) -> int:
        return len(self.categorias)


@dataclass
class MatrizCaracteristicas:
    X: Any  # np.ndarray (n_filas, n_columnas)
    y: Any  # unidades de la semana objetivo
    indice_semana: Any  # posición de la semana de cada fila dentro de `serie.semanas`
    indice_categoria: Any
    columnas: list[str]


def ultimo_lunes_completo(hasta: date) -> date:
    """Lunes de la última semana completa que termina en `hasta` o antes (el domingo cuenta como completo)."""
    lunes_de_hasta = hasta - timedelta(days=hasta.weekday())
    return lunes_de_hasta if hasta.weekday() == 6 else lunes_de_hasta - timedelta(days=7)


def _como_fecha(valor: Any) -> date:
    return valor.date() if isinstance(valor, datetime) else valor


def construir_serie_semanal(filas: list[dict], hasta: date) -> SerieSemanal:
    """La serie semanal por categoría. `DatosInsuficientesError` si hay menos de `ML_MIN_SEMANAS` semanas de
    historia o menos de `ML_MIN_CATEGORIAS` categorías con ventas.

    Las "semanas con ventas" se cuentan desde la primera venta hasta la última semana completa (las semanas
    intermedias sin ventas valen 0 y cuentan: son historia real de la tienda)."""
    import numpy as np

    avisos: list[str] = []
    ultimo = ultimo_lunes_completo(hasta)
    fin_historia = ultimo + timedelta(days=6)
    en_rango = [f for f in filas if _como_fecha(f["dia"]) <= fin_historia]
    if not en_rango:
        raise DatosInsuficientesError("No hay ventas registradas hasta la última semana completa", avisos)

    primer_dia = min(_como_fecha(f["dia"]) for f in en_rango)
    primer_lunes = primer_dia - timedelta(days=primer_dia.weekday())
    n_semanas = (ultimo - primer_lunes).days // 7 + 1
    if n_semanas > limites.ML_MAX_SEMANAS:
        primer_lunes = ultimo - timedelta(weeks=limites.ML_MAX_SEMANAS - 1)
        avisos.append(
            f"Hay {n_semanas} semanas de historia: se usan solo las {limites.ML_MAX_SEMANAS} más recientes."
        )
        n_semanas = limites.ML_MAX_SEMANAS
        en_rango = [f for f in en_rango if _como_fecha(f["dia"]) >= primer_lunes]
    if n_semanas < limites.ML_MIN_SEMANAS:
        raise DatosInsuficientesError(
            f"Hay {n_semanas} semanas de historia y se necesitan al menos {limites.ML_MIN_SEMANAS}", avisos
        )

    # Unidades totales por categoría: sirven para contar las que tienen ventas y para recortar por volumen.
    nombres: dict[int, str] = {}
    totales: dict[int, int] = {}
    for f in sorted(en_rango, key=lambda fila: _como_fecha(fila["dia"])):
        nombres[f["categoria_id"]] = f["categoria"]  # el nombre más reciente
        totales[f["categoria_id"]] = totales.get(f["categoria_id"], 0) + int(f["unidades"])
    if len(totales) < limites.ML_MIN_CATEGORIAS:
        raise DatosInsuficientesError(
            f"Hay {len(totales)} categoría(s) con ventas y se necesitan al menos {limites.ML_MIN_CATEGORIAS}", avisos
        )
    if len(totales) > limites.ML_MAX_CATEGORIAS:
        # Volumen descendente y, a igualdad, el id menor: así el recorte es determinista.
        conservadas = sorted(totales, key=lambda cid: (-totales[cid], cid))[: limites.ML_MAX_CATEGORIAS]
        avisos.append(
            f"Hay {len(totales)} categorías con ventas: se usan las {limites.ML_MAX_CATEGORIAS} de mayor volumen."
        )
        totales = {cid: totales[cid] for cid in conservadas}
    ids = sorted(totales)
    posicion = {cid: i for i, cid in enumerate(ids)}

    unidades = np.zeros((len(ids), n_semanas))
    neto = np.zeros((len(ids), n_semanas))
    bruto = np.zeros((len(ids), n_semanas))
    for f in en_rango:
        if f["categoria_id"] not in posicion:
            continue
        i = posicion[f["categoria_id"]]
        j = (_como_fecha(f["dia"]) - primer_lunes).days // 7
        unidades[i, j] += int(f["unidades"])
        neto[i, j] += float(f["total_ventas"])
        bruto[i, j] += float(f["ventas_brutas"])

    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where(bruto > 0, 1.0 - neto / bruto, 0.0)
    pct = np.clip(pct, 0.0, 1.0)

    # Ticket por unidad; si la semana no vendió se arrastra el último conocido (usar el siguiente sería mirar
    # al futuro). Antes de la primera venta de la categoría vale 0.
    precio = np.zeros_like(unidades)
    for i in range(len(ids)):
        ultimo_precio = 0.0
        for j in range(n_semanas):
            if unidades[i, j] > 0:
                ultimo_precio = neto[i, j] / unidades[i, j]
            precio[i, j] = ultimo_precio

    return SerieSemanal(
        categorias=[(cid, nombres[cid]) for cid in ids],
        semanas=[primer_lunes + timedelta(weeks=j) for j in range(n_semanas)],
        unidades=unidades,
        neto=neto,
        bruto=bruto,
        pct_descuento=pct,
        precio_medio=precio,
        avisos=avisos,
    )


def nombres_de_columnas(ids_categoria: list[int]) -> list[str]:
    """Orden de columnas guardado en el artefacto: las numéricas, luego el one-hot por id de categoría y, al final,
    el ciclo anual PROPIO de cada categoría (seno y coseno de la semana multiplicados por su one-hot). Sin esto, un
    modelo lineal tendría un único ciclo anual para todas, y las chamarras (suben en invierno) y las poleras
    (suben en verano) tienen fases opuestas: lo que una gana, la otra lo pierde."""
    ids = sorted(ids_categoria)
    return (
        list(COLUMNAS_NUMERICAS)
        + [f"categoria_{cid}" for cid in ids]
        + [f"ciclo_sin_{cid}" for cid in ids]
        + [f"ciclo_cos_{cid}" for cid in ids]
    )


def fila_de_caracteristicas(
    unidades_previas: list[float],
    precio_lag_1: float,
    pct_descuento: float,
    lunes: date,
    indice_categoria: int,
    n_categorias: int,
) -> list[float]:
    """Una fila de características. `unidades_previas` son las semanas ANTERIORES a la objetivo (la más
    reciente al final; se usan hasta 8). La misma función arma las filas de entrenamiento y las de predicción,
    para que no puedan divergir. `tendencia` = media de las 4 últimas menos la media de las 4 anteriores; si
    aún no hay 4 anteriores se usan las que haya, y si no hay ninguna vale 0."""
    if len(unidades_previas) < REZAGOS:
        raise ValueError(f"Se necesitan al menos {REZAGOS} semanas previas")
    previas = list(unidades_previas[-SEMANAS_DE_HISTORIA:])
    reciente = previas[-REZAGOS:]
    anteriores = previas[:-REZAGOS]
    media_movil = sum(reciente) / REZAGOS
    tendencia = media_movil - sum(anteriores) / len(anteriores) if anteriores else 0.0
    angulo = 2.0 * math.pi * lunes.isocalendar()[1] / 52.0
    numericas = [
        reciente[-1],
        reciente[-2],
        reciente[-3],
        reciente[-4],
        media_movil,
        tendencia,
        math.sin(angulo),
        math.cos(angulo),
        pct_descuento,
        precio_lag_1,
    ]
    one_hot = [0.0] * n_categorias
    one_hot[indice_categoria] = 1.0
    ciclo_sin = [0.0] * n_categorias
    ciclo_cos = [0.0] * n_categorias
    ciclo_sin[indice_categoria] = math.sin(angulo)
    ciclo_cos[indice_categoria] = math.cos(angulo)
    return [float(v) for v in numericas] + one_hot + ciclo_sin + ciclo_cos


def construir_matriz(serie: SerieSemanal) -> MatrizCaracteristicas:
    """Las filas de entrenamiento: una por (semana, categoría) desde la 5.ª semana, ordenadas por semana y,
    dentro de ella, por id de categoría (el orden temporal permite partir train/test sin mezclar)."""
    import numpy as np

    filas, objetivo, idx_semana, idx_categoria = [], [], [], []
    for j in range(REZAGOS, serie.n_semanas):
        for i in range(serie.n_categorias):
            previas = [float(v) for v in serie.unidades[i, max(0, j - SEMANAS_DE_HISTORIA) : j]]
            filas.append(
                fila_de_caracteristicas(
                    previas,
                    float(serie.precio_medio[i, j - 1]),
                    float(serie.pct_descuento[i, j]),
                    serie.semanas[j],
                    i,
                    serie.n_categorias,
                )
            )
            objetivo.append(float(serie.unidades[i, j]))
            idx_semana.append(j)
            idx_categoria.append(i)
    return MatrizCaracteristicas(
        X=np.array(filas, dtype=float),
        y=np.array(objetivo, dtype=float),
        indice_semana=np.array(idx_semana, dtype=int),
        indice_categoria=np.array(idx_categoria, dtype=int),
        columnas=nombres_de_columnas([cid for cid, _ in serie.categorias]),
    )
