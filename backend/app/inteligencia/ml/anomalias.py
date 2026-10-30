"""Detección de días inusuales de venta por sucursal (E12b, CU-24): modelo NO supervisado (IsolationForest) más una
regla de desviación robusta. Cálculo puro: recibe las filas planas que devuelve
`comercial.politicas.reporte_ventas_serie_diaria(desglose=("sucursal",))` y no sabe de la base de datos, de HTTP ni
de empresas. Una fila por (día, sucursal) CON ventas, con estas claves: `dia` (date), `sucursal_id` (int),
`sucursal` (nombre), `transacciones` (int), `unidades` (int) y `total_ventas` (Decimal o float). numpy y
scikit-learn se importan DENTRO de las funciones.

Qué es una anomalía aquí: un día cuyas ventas se apartan de lo esperado para ESA tienda en ESE día de la semana. No
es necesariamente un error: puede ser una liquidación, un cierre, un feriado o un día sin ventas.

Cómo se calcula lo esperado (por sucursal; todo se mide en "tickets" y "transacciones", dos conteos):
  1. Los días sin ventas de una sucursal se llenan con 0, desde su primera venta hasta `hasta`: un día sin ventas
     en una tienda que vende todos los días ES una anomalía (y en una tienda chica, donde pasa seguido, el modelo
     lo sabe porque lo esperado es bajo).
  2. Factor del día de la semana: mediana de (venta del día / media de su semana), normalizada a media 1.
  3. Nivel local: mediana móvil CENTRADA de 29 días de la venta ya corregida por el día de la semana. Absorbe la
     tendencia y la estacionalidad, y la mediana no se deja arrastrar por el propio día raro.
  4. Factor de días de pago (1 a 5 y 15 a 20 de cada mes), estimado por sucursal; si no hay efecto vale ~1.
  esperado = nivel x factor del día de la semana x factor de pago (con un piso de media transacción).

Características de cada (sucursal, día), todas ADIMENSIONALES para que un solo modelo sirva a todas las tiendas:
  z_ventas  = desviación de las ventas del día frente a lo esperado, en unidades de "error típico" casi-Poisson
              (x - esperado) / sqrt(esperado), centrada y escalada con la mediana y la MAD de la propia sucursal.
  z_transacciones = lo mismo con el número de transacciones.
  z_ticket  = desviación del ticket medio (total / transacciones) contra el esperado, en la misma escala.
El día de la semana NO entra como característica del modelo: ya está descontado en lo esperado, y agregarlo solo
dejaría que el bosque aislara "un domingo" en vez de "un domingo raro" (ver `USAR_DIA_SEMANA`).

Decisión de marcado (dos criterios, cualquiera basta):
  * IsolationForest: el puntaje de aislamiento queda en el `CONTAMINACION` (2 %) más extremo del entrenamiento.
  * Regla de desviación robusta: max(|z_ventas|, |z_transacciones|) >= `Z_REGLA`. Asegura que un día extremo se
    marque aunque el bosque se haya "acostumbrado" a otros extremos.
Con ambos el porcentaje marcado queda cerca del 2 % y casi nunca pasa del 3 %.

Límites que conviene conocer (se miden en las pruebas con el generador sintético, ver `SUPUESTOS`): con pocas ventas
por día (una sucursal de 5 a 10 transacciones diarias) el ruido natural es del orden de 2 a 3 errores típicos, así
que una caída del 70 % en una tienda así NO se distingue de un mal día sin marcar muchos días normales. Un pico de
200 % o un día sin ventas en una tienda grande sí se detectan de forma estable.
"""

from __future__ import annotations

import logging
import math
import time
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.inteligencia.ml import limites
from app.inteligencia.ml.limites import ML_SEMILLA_POR_DEFECTO

logger = logging.getLogger("app.inteligencia.ml")

# --- Datos mínimos y topes ---
MIN_DIAS_DATOS = 56  # 8 semanas entre la primera y la última fecha; menos -> "datos_insuficientes"
MIN_DIAS_SUCURSAL = 56  # días desde la primera venta de la sucursal hasta `hasta`
MIN_DIAS_CON_VENTAS = 14  # días con ventas de la sucursal para estimar su comportamiento
MAX_SUCURSALES = 30  # con más, se conservan las de mayor venta y se avisa
MAX_DIAS = limites.ML_MAX_SEMANAS * 7  # ventana máxima de entrenamiento (728 días); lo anterior se descarta
DIAS_INACTIVA = 28  # una sucursal sin ventas en tantos días hasta `hasta` se considera cerrada y no se evalúa

# --- Línea base ---
VENTANA_NIVEL = 29  # días de la mediana móvil centrada (impar)
MIN_PUNTOS_NIVEL = 7  # con menos puntos válidos en la ventana se usa el nivel reciente guardado
PISO_ESPERADO = 0.5  # lo esperado nunca baja de media transacción (evita dividir por cero)
FACTOR_DIA_MINIMO = 0.05  # un día de la semana "cerrado" (factor casi 0) no entra en el nivel
DIAS_DE_PAGO = ((1, 5), (15, 20))  # días del mes con cobro de sueldos (Bolivia): suelen vender más
MIN_DIAS_PAGO = 10  # días de pago y no de pago necesarios para estimar el factor de pago
FACTOR_PAGO_RANGO = (0.5, 2.0)
ESCALA_MINIMA = 0.5  # piso del error típico (una serie casi plana no debe volver todo "extremo")
Z_MAXIMO = 50.0  # recorte de las z para que ninguna sea infinita

# --- Modelo y marcado ---
USAR_DIA_SEMANA = False
CONTAMINACION = 0.025  # fracción más extrema que el bosque marca (a 0,03 ya se pasa del 3 % total marcado)
Z_REGLA = 4.5  # |z| a partir del cual la regla de desviación marca el día aunque el bosque no
N_ARBOLES = 100
MAX_MUESTRAS = 256
CARACTERISTICAS = ("z_ventas", "z_transacciones", "z_ticket")
VERSION_ARTEFACTO = 1

# --- Severidad y consulta ---
UMBRAL_FUERTE_PCT = 60.0  # |desviación| >= 60 % del esperado -> "fuerte"; por debajo, "leve"
SEVERIDAD_LEVE = "leve"
SEVERIDAD_FUERTE = "fuerte"
DIAS_DETECCION_MIN = 7
DIAS_DETECCION_MAX = 365
DIAS_DETECCION_DEFECTO = 90

SUPUESTOS = [
    "Una anomalía es un día inusual respecto al comportamiento habitual de esa tienda en ese día de la semana; no es "
    "necesariamente un error ni algo malo.",
    "Lo esperado se calcula por sucursal con el factor del día de la semana, un nivel local (mediana móvil de 29 días) "
    "y un factor de días de pago (1 a 5 y 15 a 20); no conoce feriados, campañas ni eventos futuros.",
    "Un día sin ventas de una sucursal que vende casi todos los días se marca; en una tienda chica, donde es normal, no.",
    "Una sucursal sin ventas en los últimos 28 días se considera cerrada y no se evalúa; una sucursal nueva (menos de "
    "56 días de ventas) tampoco hasta el próximo entrenamiento.",
    "El modelo mira solo ventas: una anomalía que no cambia las ventas (por ejemplo, un pico de devoluciones) no se ve.",
    "Con pocas transacciones por día, una caída moderada (alrededor de un 70 %) puede quedar dentro del ruido natural "
    "y no marcarse; los picos grandes y los días sin ventas en tiendas grandes sí.",
    "Si los datos son sintéticos, lo que se detecta refleja lo que puso el generador y no evidencia con datos reales.",
]


@dataclass
class ResultadoAnomalias:
    """Resultado de `entrenar_anomalias`. Nunca contiene NaN (las métricas van a JSON con `allow_nan=False`).
    `artefacto` es un diccionario con el modelo de scikit-learn y las líneas base: se guarda con
    `persistencia.serializar`."""

    estado: str  # "ok" | "datos_insuficientes"
    motivo: str | None = None
    avisos: list[str] = field(default_factory=list)
    metricas: dict[str, Any] = field(default_factory=dict)
    parametros: dict[str, Any] = field(default_factory=dict)
    filas_entrenamiento: int = 0
    datos_desde: date | None = None
    datos_hasta: date | None = None
    artefacto: dict[str, Any] | None = None


@dataclass
class Anomalia:
    fecha: date
    sucursal_id: int
    sucursal: str
    total_ventas: float
    esperado: float
    desviacion_pct: float  # + sobre lo esperado, - por debajo
    severidad: str  # "leve" | "fuerte"


# ---- Preparación de los datos ------------------------------------------------------------------


def _como_fecha(valor: Any) -> date:
    return valor.date() if isinstance(valor, datetime) else valor


def _dia_de_la_semana(ordinales: Any) -> Any:
    """Lunes = 0 ... domingo = 6, igual que `date.weekday()` (el ordinal 1 es un lunes)."""
    return (ordinales + 6) % 7


def _es_dia_de_pago(dias_del_mes: Any) -> Any:
    import numpy as np

    marca = np.zeros(len(dias_del_mes), dtype=bool)
    for desde, hasta in DIAS_DE_PAGO:
        marca |= (dias_del_mes >= desde) & (dias_del_mes <= hasta)
    return marca


@dataclass
class _Cuadricula:
    """Las ventas de todas las sucursales sobre una misma grilla diaria continua (los días sin ventas valen 0)."""

    inicio: date
    n: int
    ordinales: Any  # (n,) int
    dia_semana: Any  # (n,) int 0..6
    dia_mes: Any  # (n,) int
    sucursales: dict[int, dict[str, Any]]  # id -> {nombre, total, trans, i0}
    avisos: list[str]
    descartadas: int


def _cuadricula(filas: list[dict], hasta: date, inicio_minimo: date | None = None) -> _Cuadricula | None:
    """Agrupa las filas por (sucursal, día). Ignora las filas sin día o sucursal y las posteriores a `hasta`; las
    repetidas del mismo (día, sucursal) se SUMAN; un total negativo se toma como 0. Devuelve None si no hay filas
    utilizables. `inicio_minimo` recorta lo anterior a esa fecha."""
    import numpy as np

    avisos: list[str] = []
    acumulado: dict[tuple[int, int], list[float]] = {}
    nombres: dict[int, str] = {}
    descartadas = negativos = recortadas = 0
    primer = None
    for fila in filas:
        try:
            dia = _como_fecha(fila["dia"])
            sucursal_id = fila["sucursal_id"]
            total = float(fila["total_ventas"])
            transacciones = float(fila["transacciones"])
        except (KeyError, TypeError, ValueError):
            descartadas += 1
            continue
        if dia is None or sucursal_id is None or not math.isfinite(total) or dia > hasta:
            descartadas += 1
            continue
        if inicio_minimo is not None and dia < inicio_minimo:
            recortadas += 1
            continue
        if total < 0 or transacciones < 0:
            negativos += 1
            total, transacciones = max(total, 0.0), max(transacciones, 0.0)
        nombre = fila.get("sucursal")
        if nombre and int(sucursal_id) not in nombres:
            nombres[int(sucursal_id)] = str(nombre)
        celda = acumulado.setdefault((int(sucursal_id), dia.toordinal()), [0.0, 0.0])
        celda[0] += total
        celda[1] += transacciones
        primer = dia.toordinal() if primer is None else min(primer, dia.toordinal())
    if descartadas:
        avisos.append(f"{descartadas} fila(s) sin día o sucursal válidos, o posteriores a la fecha de corte, se ignoraron.")
    if negativos:
        avisos.append(f"{negativos} fila(s) traían ventas negativas; se tomaron como 0.")
    if recortadas:
        avisos.append(f"Se usaron solo los últimos {MAX_DIAS} días de ventas; {recortadas} fila(s) anteriores se ignoraron.")
    if primer is None:
        return None
    fin = hasta.toordinal()
    n = fin - primer + 1
    ordinales = np.arange(primer, fin + 1)
    dias_mes = np.array([date.fromordinal(int(o)).day for o in ordinales])
    sucursales: dict[int, dict[str, Any]] = {}
    for (sucursal_id, ordinal), (total, transacciones) in acumulado.items():
        s = sucursales.setdefault(
            sucursal_id,
            {"nombre": nombres.get(sucursal_id, f"Sucursal {sucursal_id}"), "total": np.zeros(n), "trans": np.zeros(n)},
        )
        s["total"][ordinal - primer] += total
        s["trans"][ordinal - primer] += transacciones
    for s in sucursales.values():
        con_ventas = np.nonzero((s["total"] > 0) | (s["trans"] > 0))[0]
        s["i0"] = int(con_ventas[0]) if len(con_ventas) else n  # primer día con ventas
        s["n_con_ventas"] = int(len(con_ventas))
        s["ultimo"] = int(con_ventas[-1]) if len(con_ventas) else -1
    return _Cuadricula(
        inicio=date.fromordinal(primer),
        n=n,
        ordinales=ordinales,
        dia_semana=_dia_de_la_semana(ordinales),
        dia_mes=dias_mes,
        sucursales=sucursales,
        avisos=avisos,
        descartadas=descartadas,
    )


# ---- Línea base de una sucursal ----------------------------------------------------------------


def _mediana_movil_centrada(valores: Any) -> tuple[Any, Any]:
    """Mediana de una ventana centrada de `VENTANA_NIVEL` días (los NaN no cuentan) y cuántos puntos válidos tuvo cada
    ventana. En los bordes la ventana queda incompleta, así que usa solo lo que existe (hacia atrás al final)."""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view

    medio = VENTANA_NIVEL // 2
    relleno = np.pad(np.asarray(valores, dtype=float), medio, constant_values=np.nan)
    ventanas = sliding_window_view(relleno, VENTANA_NIVEL)
    validos = (~np.isnan(ventanas)).sum(axis=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)  # ventanas enteras de NaN
        medianas = np.nanmedian(ventanas, axis=1)
    return medianas, validos


def _factor_dia_semana(x: Any, dia_semana: Any) -> Any:
    """Factor de cada día de la semana: mediana de (venta del día / media centrada de 7 días), con media 1."""
    import numpy as np

    n = len(x)
    if n < 7:
        return np.ones(7)
    suma = np.convolve(x, np.ones(7), mode="same")
    cuenta = np.convolve(np.ones(n), np.ones(7), mode="same")
    media_semana = suma / cuenta
    factores = np.ones(7)
    for d in range(7):
        sel = (dia_semana == d) & (media_semana > 0)
        factores[d] = float(np.median(x[sel] / media_semana[sel])) if sel.any() else 1.0
    promedio = factores.mean()
    return factores / promedio if promedio > 0 else np.ones(7)


def _nivel(x: Any, factor_dia: Any, dia_semana: Any, fallback: float | None) -> Any:
    """Nivel local (mediana móvil del dato corregido por el día de la semana). Donde la ventana tiene pocos puntos
    válidos se usa `fallback` (el nivel reciente guardado), o la mediana global si no hay."""
    import numpy as np

    f = factor_dia[dia_semana]
    abierto = f >= FACTOR_DIA_MINIMO
    base = np.where(abierto, x / np.maximum(f, FACTOR_DIA_MINIMO), np.nan)
    nivel, validos = _mediana_movil_centrada(base)
    if fallback is None:
        valores = base[~np.isnan(base)]
        fallback = float(np.median(valores)) if len(valores) else 0.0
    return np.where(validos >= MIN_PUNTOS_NIVEL, nivel, fallback)


def _esperado_conteo(x: Any, factor_dia: Any, factor_pago: float, es_pago: Any, dia_semana: Any, fallback: float | None) -> tuple[Any, Any]:
    """Esperado de un conteo y el nivel usado. Piso de `PISO_ESPERADO`."""
    import numpy as np

    nivel = _nivel(x, factor_dia, dia_semana, fallback)
    esperado = nivel * factor_dia[dia_semana] * np.where(es_pago, factor_pago, 1.0)
    return np.maximum(esperado, PISO_ESPERADO), nivel


def _centro_escala(r: Any) -> tuple[float, float]:
    """Mediana y error típico robusto (1,4826 x MAD) de r, con un piso en la escala."""
    import numpy as np

    centro = float(np.median(r))
    escala = float(1.4826 * np.median(np.abs(r - centro)))
    return centro, max(escala, ESCALA_MINIMA)


def _z(r: Any, centro: float, escala: float) -> Any:
    import numpy as np

    return np.clip((r - centro) / escala, -Z_MAXIMO, Z_MAXIMO)


def _ajustar_metrica(x: Any, dia_semana: Any, es_pago: Any) -> dict[str, Any]:
    """Línea base de un conteo (ventas en tickets o transacciones): factor del día de la semana, factor de pago, nivel
    reciente y el centro y la escala de su error."""
    import numpy as np

    factor_dia = _factor_dia_semana(x, dia_semana)
    esperado0, _ = _esperado_conteo(x, factor_dia, 1.0, es_pago, dia_semana, None)
    factor_pago = 1.0
    if es_pago.sum() >= MIN_DIAS_PAGO and (~es_pago).sum() >= MIN_DIAS_PAGO:
        razon = x / esperado0
        mediana_no_pago = float(np.median(razon[~es_pago]))
        if mediana_no_pago > 0:
            factor_pago = float(np.clip(np.median(razon[es_pago]) / mediana_no_pago, *FACTOR_PAGO_RANGO))
    esperado, nivel = _esperado_conteo(x, factor_dia, factor_pago, es_pago, dia_semana, None)
    centro, escala = _centro_escala((x - esperado) / np.sqrt(esperado))
    return {
        "factor_dia": factor_dia.tolist(),
        "factor_pago": factor_pago,
        "nivel_reciente": float(nivel[-1]),
        "centro": centro,
        "escala": escala,
    }


def _esperado_con_linea(x: Any, linea: dict[str, Any], dia_semana: Any, es_pago: Any) -> Any:
    """Esperado de un conteo con una línea base ya ajustada (el nivel sale de los datos disponibles)."""
    import numpy as np

    esperado, _ = _esperado_conteo(
        x, np.asarray(linea["factor_dia"]), linea["factor_pago"], es_pago, dia_semana, linea["nivel_reciente"]
    )
    return esperado


def _aplicar_metrica(x: Any, linea: dict[str, Any], dia_semana: Any, es_pago: Any) -> tuple[Any, Any]:
    """z y esperado de un conteo con una línea base ya ajustada."""
    import numpy as np

    esperado = _esperado_con_linea(x, linea, dia_semana, es_pago)
    return _z((x - esperado) / np.sqrt(esperado), linea["centro"], linea["escala"]), esperado


def _z_ticket_crudo(x_ventas: Any, x_trans: Any, esp_ventas: Any, esp_trans: Any) -> Any:
    """log(ticket observado / ticket esperado) por la raíz de las transacciones (su error baja con más ventas).
    Sin transacciones, 0 (no hay ticket que comparar)."""
    import numpy as np

    con = x_trans > 0
    observado = np.maximum(x_ventas, 1e-3) / np.where(con, x_trans, 1.0)
    crudo = np.log(observado / (esp_ventas / esp_trans)) * np.sqrt(np.where(con, x_trans, 0.0))
    return np.where(con, crudo, 0.0)


def _caracteristicas_sucursal(
    total: Any, trans: Any, ticket_ref: float, linea: dict[str, Any], dia_semana: Any, es_pago: Any
) -> dict[str, Any]:
    """z de ventas, transacciones y ticket de una sucursal, y lo esperado en moneda. `linea` es su línea base."""
    x_ventas = total / ticket_ref
    z_ventas, esp_ventas = _aplicar_metrica(x_ventas, linea["ventas"], dia_semana, es_pago)
    z_trans, esp_trans = _aplicar_metrica(trans, linea["transacciones"], dia_semana, es_pago)
    crudo = _z_ticket_crudo(x_ventas, trans, esp_ventas, esp_trans)
    z_ticket = _z(crudo, linea["ticket"]["centro"], linea["ticket"]["escala"])
    return {"z_ventas": z_ventas, "z_transacciones": z_trans, "z_ticket": z_ticket, "esperado": esp_ventas * ticket_ref}


def _linea_base_sucursal(total: Any, trans: Any, dia_semana: Any, es_pago: Any) -> dict[str, Any]:
    """Todo lo que hace falta para evaluar una sucursal sin volver a la base: factores, niveles, escalas y ticket."""
    import numpy as np

    suma_trans = float(trans.sum())
    ticket_ref = float(total.sum() / suma_trans) if suma_trans > 0 else 1.0
    if not ticket_ref > 0:
        ticket_ref = 1.0
    x_ventas = total / ticket_ref
    linea = {
        "ticket_ref": ticket_ref,
        "ventas": _ajustar_metrica(x_ventas, dia_semana, es_pago),
        "transacciones": _ajustar_metrica(trans, dia_semana, es_pago),
    }
    esperado_v = _esperado_con_linea(x_ventas, linea["ventas"], dia_semana, es_pago)
    esperado_t = _esperado_con_linea(trans, linea["transacciones"], dia_semana, es_pago)
    crudo = _z_ticket_crudo(x_ventas, trans, esperado_v, esperado_t)
    activos = trans > 0
    centro, escala = _centro_escala(crudo[activos]) if activos.any() else (0.0, 1.0)
    linea["ticket"] = {"centro": centro, "escala": escala}
    return linea


# ---- Entrenamiento -----------------------------------------------------------------------------


def _finito(valor: Any, decimales: int = 6) -> float | None:
    """Float de Python redondeado, o None si no es finito (los NaN no viajan a JSON)."""
    if valor is None:
        return None
    valor = float(valor)
    return round(valor, decimales) if math.isfinite(valor) else None


def _matriz(z_ventas: Any, z_trans: Any, z_ticket: Any, dia_semana: Any, con_dia_semana: bool) -> Any:
    import numpy as np

    columnas = [z_ventas, z_trans, z_ticket]
    if con_dia_semana:
        angulo = 2.0 * np.pi * dia_semana / 7.0
        columnas += [np.sin(angulo), np.cos(angulo)]
    return np.column_stack(columnas)


def _insuficiente(motivo: str, avisos: list[str], hasta: date, semilla: int, metricas: dict[str, Any] | None = None) -> ResultadoAnomalias:
    return ResultadoAnomalias(
        estado="datos_insuficientes",
        motivo=motivo,
        avisos=avisos,
        metricas=metricas or {},
        parametros={
            "semilla": semilla,
            "hasta": hasta.isoformat(),
            "minimo_dias": MIN_DIAS_DATOS,
            "minimo_dias_sucursal": MIN_DIAS_SUCURSAL,
        },
    )


def entrenar_anomalias(filas: list[dict], hasta: date, *, semilla: int = ML_SEMILLA_POR_DEFECTO) -> ResultadoAnomalias:
    """Ajusta la línea base de cada sucursal y un IsolationForest sobre sus z. Con menos de 8 semanas de ventas, o sin
    ninguna sucursal con datos suficientes, devuelve `estado="datos_insuficientes"` (sin excepción y sin artefacto).
    Determinista: la misma entrada y semilla dan el mismo artefacto (`segundos_entrenamiento` es lo único que cambia)."""
    import numpy as np
    import sklearn
    from sklearn.ensemble import IsolationForest

    inicio_reloj = time.perf_counter()
    hasta = _como_fecha(hasta)
    inicio_minimo = hasta - timedelta(days=MAX_DIAS - 1)
    grilla = _cuadricula(filas, hasta, inicio_minimo)
    if grilla is None:
        return _insuficiente("No hay ventas diarias por sucursal para entrenar.", [], hasta, semilla, {"n_dias": 0})
    avisos = list(grilla.avisos)
    if grilla.n < MIN_DIAS_DATOS:
        return _insuficiente(
            f"Se necesitan al menos {MIN_DIAS_DATOS // 7} semanas ({MIN_DIAS_DATOS} días) de ventas y hay {grilla.n} días.",
            avisos,
            hasta,
            semilla,
            {"n_dias": grilla.n},
        )

    # Sucursales con datos suficientes.
    aptas: list[int] = []
    motivos: list[str] = []
    for sucursal_id in sorted(grilla.sucursales):
        s = grilla.sucursales[sucursal_id]
        if s["n_con_ventas"] < MIN_DIAS_CON_VENTAS or grilla.n - s["i0"] < MIN_DIAS_SUCURSAL:
            motivos.append(f"{s['nombre']}: menos de {MIN_DIAS_SUCURSAL} días de historia o de {MIN_DIAS_CON_VENTAS} días con ventas")
        elif grilla.n - 1 - s["ultimo"] >= DIAS_INACTIVA:
            motivos.append(f"{s['nombre']}: sin ventas en los últimos {DIAS_INACTIVA} días (se considera cerrada)")
        else:
            aptas.append(sucursal_id)
    if not aptas:
        return _insuficiente(
            "Ninguna sucursal tiene datos suficientes (se necesitan "
            f"{MIN_DIAS_SUCURSAL} días de historia, {MIN_DIAS_CON_VENTAS} con ventas y ventas recientes).",
            avisos + [m for m in motivos],
            hasta,
            semilla,
            {"n_dias": grilla.n},
        )
    if motivos:
        avisos.append("No se evaluaron estas sucursales: " + "; ".join(motivos) + ".")
    if len(aptas) > MAX_SUCURSALES:
        aptas.sort(key=lambda i: (-float(grilla.sucursales[i]["total"].sum()), i))
        avisos.append(f"Había {len(aptas)} sucursales y el máximo es {MAX_SUCURSALES}: se usaron las de mayor venta.")
        aptas = sorted(aptas[:MAX_SUCURSALES])

    es_pago = _es_dia_de_pago(grilla.dia_mes)
    lineas: dict[int, dict[str, Any]] = {}
    bloques: list[Any] = []
    z_ventas_todas: list[Any] = []
    z_trans_todas: list[Any] = []
    dias_semana_todos: list[Any] = []
    for sucursal_id in aptas:
        s = grilla.sucursales[sucursal_id]
        i0 = s["i0"]
        total, trans = s["total"][i0:], s["trans"][i0:]
        dia_semana, pago = grilla.dia_semana[i0:], es_pago[i0:]
        linea = _linea_base_sucursal(total, trans, dia_semana, pago)
        car = _caracteristicas_sucursal(total, trans, linea["ticket_ref"], linea, dia_semana, pago)
        lineas[sucursal_id] = {
            "nombre": s["nombre"],
            "desde": date.fromordinal(int(grilla.ordinales[i0])).isoformat(),
            "hasta": hasta.isoformat(),
            **linea,
        }
        bloques.append(_matriz(car["z_ventas"], car["z_transacciones"], car["z_ticket"], dia_semana, USAR_DIA_SEMANA))
        z_ventas_todas.append(car["z_ventas"])
        z_trans_todas.append(car["z_transacciones"])
        dias_semana_todos.append(dia_semana)

    X = np.vstack(bloques)
    z_ventas, z_trans = np.concatenate(z_ventas_todas), np.concatenate(z_trans_todas)
    modelo = IsolationForest(
        n_estimators=N_ARBOLES,
        max_samples=min(MAX_MUESTRAS, len(X)),
        contamination=CONTAMINACION,
        random_state=semilla,
        n_jobs=limites.ML_N_JOBS,
    ).fit(X)
    puntajes = modelo.score_samples(X)
    umbral = float(np.quantile(puntajes, CONTAMINACION))
    por_modelo = puntajes < umbral
    por_regla = np.maximum(np.abs(z_ventas), np.abs(z_trans)) >= Z_REGLA
    marcado = por_modelo | por_regla
    n_marcados = int(marcado.sum())
    pct = 100.0 * n_marcados / len(X)
    if pct > 5.0:
        avisos.append(f"Se marcó el {pct:.1f} % de los días: los datos son muy irregulares y conviene revisar con cautela.")

    segundos = time.perf_counter() - inicio_reloj
    if segundos > limites.ML_TIEMPO_ENTRENAMIENTO_AVISO_SEG:
        avisos.append(f"El entrenamiento tardó {segundos:.1f} s (aviso a partir de {limites.ML_TIEMPO_ENTRENAMIENTO_AVISO_SEG} s).")
        logger.warning("ml_anomalias_lento segundos=%.1f filas=%d", segundos, len(X))

    metricas = {
        "n_dias": int(len(X)),
        "n_sucursales": len(aptas),
        "n_marcados": n_marcados,
        "n_marcados_modelo": int(por_modelo.sum()),
        "n_marcados_regla": int(por_regla.sum()),
        "pct_marcados": _finito(pct, 3),
        "umbral": _finito(umbral, 6),
        "contamination": CONTAMINACION,
        "z_regla": Z_REGLA,
    }
    artefacto = {
        "version_artefacto": VERSION_ARTEFACTO,
        "modelo": modelo,
        "umbral": umbral,
        "z_regla": Z_REGLA,
        "usa_dia_semana": USAR_DIA_SEMANA,
        "caracteristicas": list(CARACTERISTICAS),
        "sucursales": lineas,
        "hasta": hasta.isoformat(),
        "semilla": semilla,
        "supuestos": list(SUPUESTOS),
    }
    parametros = {
        "algoritmo": "IsolationForest",
        "semilla": semilla,
        "hiperparametros": {"n_estimators": N_ARBOLES, "max_samples": min(MAX_MUESTRAS, len(X)), "contamination": CONTAMINACION},
        "z_regla": Z_REGLA,
        "ventana_nivel_dias": VENTANA_NIVEL,
        "dias_de_pago": [list(r) for r in DIAS_DE_PAGO],
        "umbral_fuerte_pct": UMBRAL_FUERTE_PCT,
        "caracteristicas": list(CARACTERISTICAS),
        "hasta": hasta.isoformat(),
        "n_jobs": limites.ML_N_JOBS,
        "version_sklearn": sklearn.__version__,
        "version_numpy": np.__version__,
        "supuestos": list(SUPUESTOS),
        "segundos_entrenamiento": round(segundos, 3),
    }
    return ResultadoAnomalias(
        estado="ok",
        avisos=avisos,
        metricas=metricas,
        parametros=parametros,
        filas_entrenamiento=int(len(X)),
        datos_desde=grilla.inicio,
        datos_hasta=hasta,
        artefacto=artefacto,
    )


# ---- Detección ---------------------------------------------------------------------------------


def _severidad(desviacion_pct: float) -> str:
    return SEVERIDAD_FUERTE if abs(desviacion_pct) >= UMBRAL_FUERTE_PCT else SEVERIDAD_LEVE


def detectar_anomalias(artefacto: dict, filas: list[dict], hasta: date, dias: int = DIAS_DETECCION_DEFECTO) -> list[Anomalia]:
    """Los días inusuales de los últimos `dias` (7 a 365) hasta `hasta`, de la fecha más reciente a la más antigua y,
    dentro de una fecha, las fuertes primero. `filas` tiene el mismo formato que en el entrenamiento y debe incluir
    algunas semanas ANTERIORES a la ventana (el nivel local sale de ellas; si faltan se usa el nivel reciente guardado).
    Las sucursales que no estaban en el entrenamiento no se evalúan. Sin datos devuelve una lista vacía, nunca un error."""
    import numpy as np

    if isinstance(dias, bool) or not isinstance(dias, int) or not DIAS_DETECCION_MIN <= dias <= DIAS_DETECCION_MAX:
        raise ValueError(f"Los días a revisar van de {DIAS_DETECCION_MIN} a {DIAS_DETECCION_MAX}")
    try:
        modelo, umbral, z_regla = artefacto["modelo"], float(artefacto["umbral"]), float(artefacto["z_regla"])
        sucursales_modelo = artefacto["sucursales"]
        usa_dia_semana = bool(artefacto.get("usa_dia_semana", False))
    except (KeyError, TypeError) as exc:
        raise ValueError("El artefacto del modelo de anomalías no tiene el formato esperado") from exc
    if not filas:
        return []
    hasta = _como_fecha(hasta)
    desde_ventana = hasta - timedelta(days=dias - 1)
    # Un año y medio hacia atrás basta para el nivel local; nunca más que la ventana de entrenamiento.
    grilla = _cuadricula(filas, hasta, hasta - timedelta(days=MAX_DIAS - 1))
    if grilla is None:
        return []
    es_pago = _es_dia_de_pago(grilla.dia_mes)
    inicio_ordinal = int(grilla.ordinales[0])
    indice_ventana = max(0, desde_ventana.toordinal() - inicio_ordinal)

    resultado: list[Anomalia] = []
    for sucursal_id, s in grilla.sucursales.items():
        linea = sucursales_modelo.get(sucursal_id)
        if linea is None:
            continue
        # La serie de la sucursal arranca el día de su primera venta del ENTRENAMIENTO (o al inicio de las filas, si
        # estas empiezan después): antes de abrir no se inventan ceros, y después, un día sin ventas vale 0.
        i0 = max(0, date.fromisoformat(linea["desde"]).toordinal() - inicio_ordinal)
        if i0 >= grilla.n:
            continue
        total, trans = s["total"][i0:], s["trans"][i0:]
        dia_semana, pago = grilla.dia_semana[i0:], es_pago[i0:]
        car = _caracteristicas_sucursal(total, trans, linea["ticket_ref"], linea, dia_semana, pago)
        X = _matriz(car["z_ventas"], car["z_transacciones"], car["z_ticket"], dia_semana, usa_dia_semana)
        desde_local = max(indice_ventana - i0, 0)
        if desde_local >= len(total):
            continue
        sel = slice(desde_local, None)
        puntajes = modelo.score_samples(X[sel])
        extremo = np.maximum(np.abs(car["z_ventas"][sel]), np.abs(car["z_transacciones"][sel]))
        marcado = (puntajes < umbral) | (extremo >= z_regla)
        for k in np.nonzero(marcado)[0]:
            posicion = desde_local + int(k)
            ordinal = inicio_ordinal + i0 + posicion
            observado = float(total[posicion])
            esperado = float(car["esperado"][posicion])
            desviacion = (observado - esperado) / esperado * 100.0 if esperado > 0 else 0.0
            resultado.append(
                Anomalia(
                    fecha=date.fromordinal(ordinal),
                    sucursal_id=int(sucursal_id),
                    sucursal=str(linea.get("nombre") or s["nombre"]),
                    total_ventas=round(observado, 2),
                    esperado=round(esperado, 2),
                    desviacion_pct=round(desviacion, 1),
                    severidad=_severidad(desviacion),
                )
            )
    resultado.sort(
        key=lambda a: (-a.fecha.toordinal(), 0 if a.severidad == SEVERIDAD_FUERTE else 1, -abs(a.desviacion_pct), a.sucursal_id)
    )
    return resultado
