"""Segmentación de clientes por RFM (E11, paso 8, CU-24): modelo NO supervisado (KMeans).

Cálculo puro: recibe las filas que devuelve `comercial.politicas.reporte_rfm_clientes` y no sabe de la
base de datos, de HTTP ni de empresas. Una fila por cliente con compras efectivas en la ventana, con
EXACTAMENTE estas claves: `cliente_id` (int), `ultima_compra` (date), `frecuencia` (int, número de
ventas) y `monto_total` (Decimal). No hay nombres ni correos: este módulo nunca los pide ni los guarda.

Variables (las tres pasan por un StandardScaler):
  R = días desde la última compra hasta `hasta` (menor = más reciente).
  F = log1p(frecuencia) y M = log1p(monto_total): ambos tienen cola larga y el logaritmo evita que dos
      clientes enormes dominen la distancia.

Cuántos segmentos (k) se decide con la silhouette: se prueba k de 2 a 6 y se elige el de mayor
silhouette; si otro k queda a menos de 0,02 de distancia se prefiere el MENOR (menos segmentos, más
fáciles de explicar). Las curvas del codo y de silhouette se devuelven en `metricas`.

Los nombres de los segmentos salen de reglas fijas (no de la IA): se compara el centroide de cada
segmento, en unidades originales, con la mediana global de R, F y M.

Decisiones propias de este módulo (el paso 8 no las fija):
  * Si TODOS los clientes son iguales (o solo hay un punto distinto) no se puede separar nada: el
    resultado es `ok` con k = 1, un único segmento "Todos los clientes", `silhouette` None y un aviso.
  * Si hay entre 2 y 5 puntos distintos, k máximo = número de puntos distintos (KMeans no puede formar
    más grupos que puntos diferentes).
  * Con más de `ML_MAX_CLIENTES` clientes se conservan los de compra más reciente (empate por
    cliente_id) y los demás quedan fuera de `asignaciones`, con un aviso.
  * El monto de un segmento se suma en unidades originales (no en logaritmo).

Los imports de numpy y scikit-learn van DENTRO de las funciones: este módulo se importa al arrancar la
aplicación y el arranque no debe pagar el costo de cargarlos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.inteligencia.ml import limites
from app.inteligencia.ml.limites import ML_SEMILLA_POR_DEFECTO

K_MINIMO = 2
K_MAXIMO = 6
UMBRAL_EMPATE_SILHOUETTE = 0.02  # diferencia por debajo de la cual se prefiere el k menor
SILHOUETTE_MAX_MUESTRA = 2000  # la silhouette es O(n^2): con más clientes se calcula sobre una muestra fija
SILHOUETTE_DEBIL = 0.25  # por debajo, los segmentos están poco separados y se avisa
N_INIT = 10
DECIMALES_MODELO = 10  # redondeo de escalador y centroides: ruido de 1e-16 fuera del artefacto
VARIABLES = ("recencia_dias", "log1p_frecuencia", "log1p_monto")
FORMATO_MODELO = 1

# nombre base -> (descripción, acción sugerida). Plantillas fijas: no cambian entre corridas.
PLANTILLAS: dict[str, tuple[str, str]] = {
    "Campeones": (
        "Compran seguido, gastan mucho y compraron hace poco.",
        "Cuídalos: acceso anticipado a novedades, programa de recompensas y pídeles reseñas.",
    ),
    "Leales": (
        "Compran con frecuencia y de forma reciente, con un gasto moderado.",
        "Súbeles el ticket con combos o prendas complementarias y reconoce su fidelidad.",
    ),
    "Compradores de ticket alto": (
        "Compran pocas veces, pero gastan mucho cada vez, y lo hicieron hace poco.",
        "Anímalos a repetir con recomendaciones de prendas premium y recordatorios personalizados.",
    ),
    "Nuevos o en desarrollo": (
        "Clientes recientes con pocas compras y gasto bajo.",
        "Dales la bienvenida con un incentivo para la segunda compra y guíalos por el catálogo.",
    ),
    "En riesgo": (
        "Fueron buenos clientes (frecuentes y de gasto alto), pero hace tiempo que no compran.",
        "Contáctalos pronto con una oferta personalizada antes de perderlos.",
    ),
    "Por reactivar": (
        "Compraban con frecuencia, con gasto bajo, y dejaron de comprar hace tiempo.",
        "Lanza una campaña de reactivación con promociones sobre lo que solían comprar.",
    ),
    "Grandes dormidos": (
        "Gastaron mucho en pocas compras y llevan tiempo sin volver.",
        "Escríbeles con novedades de alto valor y un motivo concreto para volver, como una preventa.",
    ),
    "Hibernando": (
        "Pocas compras, gasto bajo y mucho tiempo sin comprar.",
        "Inclúyelos solo en campañas masivas de liquidación; no inviertas más esfuerzo en ellos.",
    ),
    "Todos los clientes": (
        "Todos los clientes tienen el mismo comportamiento de compra, así que no hay grupos que separar.",
        "No hay diferencias que aprovechar todavía: revisa de nuevo cuando haya más historial.",
    ),
}

# (reciente, frecuencia_alta, monto_alto) -> nombre base
NOMBRES_POR_REGLA: dict[tuple[bool, bool, bool], str] = {
    (True, True, True): "Campeones",
    (True, True, False): "Leales",
    (True, False, True): "Compradores de ticket alto",
    (True, False, False): "Nuevos o en desarrollo",
    (False, True, True): "En riesgo",
    (False, True, False): "Por reactivar",
    (False, False, True): "Grandes dormidos",
    (False, False, False): "Hibernando",
}

SUPUESTOS = [
    "La segmentación describe el comportamiento de compra de la ventana indicada; no predice conductas futuras.",
    "Recencia, frecuencia y monto se calculan solo con ventas efectivas (no anuladas) de la empresa.",
    "Frecuencia y monto se transforman con log1p y las tres variables se estandarizan antes de agrupar.",
    "Los nombres de los segmentos salen de reglas fijas que comparan cada centroide con la mediana global.",
    "Si los datos son sintéticos, los grupos reflejan los patrones del generador y no evidencia con datos reales.",
]


@dataclass
class ResultadoSegmentacion:
    """Resultado de `segmentar_clientes`. Nunca contiene NaN ni objetos que no sean JSON simples
    (salvo `modelo`, que es un diccionario de listas y números y se guarda con `persistencia.serializar`)."""

    estado: str  # "ok" | "datos_insuficientes"
    motivo: str | None = None
    avisos: list[str] = field(default_factory=list)
    metricas: dict[str, Any] = field(default_factory=dict)
    segmentos: list[dict[str, Any]] = field(default_factory=list)
    asignaciones: dict[int, int] = field(default_factory=dict)  # cliente_id -> id de segmento
    parametros: dict[str, Any] = field(default_factory=dict)
    filas_entrenamiento: int = 0
    modelo: dict[str, Any] | None = None


# ---- Preparación de los datos ------------------------------------------------------------------


def _como_fecha(valor: Any) -> date:
    return valor.date() if isinstance(valor, datetime) else valor


def _normalizar(filas: list[dict], hasta: date) -> tuple[list[int], list[int], list[int], list[float], list[str]]:
    """Ids, recencia (días), frecuencia, monto y avisos. Un cliente repetido se toma una sola vez; una
    última compra posterior a `hasta` cuenta como recencia 0 y los valores negativos como 0."""
    avisos: list[str] = []
    vistos: set[int] = set()
    ids: list[int] = []
    recencias: list[int] = []
    frecuencias: list[int] = []
    montos: list[float] = []
    repetidos = futuros = negativos = 0
    for fila in filas:
        cliente_id = fila["cliente_id"]
        if cliente_id in vistos:
            repetidos += 1
            continue
        vistos.add(cliente_id)
        dias = (hasta - _como_fecha(fila["ultima_compra"])).days
        frecuencia = int(fila["frecuencia"])
        monto = float(fila["monto_total"])
        if dias < 0:
            futuros += 1
            dias = 0
        if frecuencia < 0 or monto < 0:
            negativos += 1
            frecuencia, monto = max(frecuencia, 0), max(monto, 0.0)
        ids.append(cliente_id)
        recencias.append(dias)
        frecuencias.append(frecuencia)
        montos.append(monto)
    if repetidos:
        avisos.append(f"{repetidos} fila(s) repetida(s) del mismo cliente se ignoraron (se usó la primera).")
    if futuros:
        avisos.append(f"{futuros} cliente(s) tienen su última compra después de la fecha de corte; se tomó recencia 0.")
    if negativos:
        avisos.append(f"{negativos} cliente(s) traían frecuencia o monto negativos; se tomaron como 0.")
    return ids, recencias, frecuencias, montos, avisos


def _versiones() -> dict[str, str]:
    import numpy
    import sklearn

    return {"sklearn": sklearn.__version__, "numpy": numpy.__version__}


def _parametros_base(semilla: int, hasta: date, k_maximo: int) -> dict[str, Any]:
    return {
        "algoritmo": "KMeans",
        "semilla": semilla,
        "n_init": N_INIT,
        "k_minimo": K_MINIMO,
        "k_maximo": k_maximo,
        "umbral_empate_silhouette": UMBRAL_EMPATE_SILHOUETTE,
        "silhouette_max_muestra": SILHOUETTE_MAX_MUESTRA,
        "variables": list(VARIABLES),
        "hasta": hasta.isoformat(),
        "n_jobs": limites.ML_N_JOBS,
        "versiones": _versiones(),
        "supuestos": list(SUPUESTOS),
    }


def _vectorizar(recencias: Any, frecuencias: Any, montos: Any) -> Any:
    """Matriz (n, 3) con R, log1p(F) y log1p(M). La usan el entrenamiento y la asignación de un cliente
    nuevo, para que ambos pasen por exactamente las mismas operaciones."""
    import numpy as np

    return np.column_stack(
        [
            np.asarray(recencias, dtype=float),
            np.log1p(np.asarray(frecuencias, dtype=float)),
            np.log1p(np.asarray(montos, dtype=float)),
        ]
    )


def _etiquetas_mas_cercanas(escalados: Any, centroides: Any) -> Any:
    """Índice del centroide más cercano de cada fila (en caso de empate, el de menor índice)."""
    import numpy as np

    diferencias = escalados[:, None, :] - centroides[None, :, :]
    return np.argmin((diferencias**2).sum(axis=2), axis=1)


# ---- Entrenamiento -----------------------------------------------------------------------------


def _redondear(valor: float | None, decimales: int = 6) -> float | None:
    """Float JSON seguro: None si no es finito (nunca NaN ni infinito en las salidas)."""
    import math

    if valor is None or not math.isfinite(valor):
        return None
    return round(float(valor), decimales)


def _elegir_k(candidatos: dict[int, float | None]) -> int:
    """Mayor silhouette; entre los que quedan a menos de 0,02 de ella, el menor k."""
    con_valor = {k: s for k, s in candidatos.items() if s is not None}
    if not con_valor:
        return min(candidatos)
    mejor = max(con_valor.values())
    return min(k for k, s in con_valor.items() if mejor - s < UMBRAL_EMPATE_SILHOUETTE)


def _nombrar(centro_r: float, centro_f: float, centro_m: float, mediana_r: float, mediana_f: float, mediana_m: float) -> str:
    # Estrictos, como dice el paso 8: R "reciente" si es MENOR que la mediana; F y M "altos" si la SUPERAN.
    return NOMBRES_POR_REGLA[(centro_r < mediana_r, centro_f > mediana_f, centro_m > mediana_m)]


def _desambiguar(nombres: list[str]) -> list[str]:
    """Nombres únicos: el primero conserva el nombre, los repetidos reciben un número ("Leales 2")."""
    contador: dict[str, int] = {}
    unicos: list[str] = []
    for nombre in nombres:
        contador[nombre] = contador.get(nombre, 0) + 1
        unicos.append(nombre if contador[nombre] == 1 else f"{nombre} {contador[nombre]}")
    return unicos


def segmentar_clientes(
    filas: list[dict], hasta: date, *, semilla: int = ML_SEMILLA_POR_DEFECTO
) -> ResultadoSegmentacion:
    """Agrupa a los clientes en segmentos RFM. Determinista: la misma entrada y semilla dan el mismo
    resultado. Con menos de `ML_MIN_CLIENTES` clientes devuelve `estado="datos_insuficientes"` (sin
    excepción y sin modelo)."""
    ids, recencias, frecuencias, montos, avisos = _normalizar(filas, hasta)
    n_total = len(ids)
    if n_total < limites.ML_MIN_CLIENTES:
        return ResultadoSegmentacion(
            estado="datos_insuficientes",
            motivo=(
                f"Se necesitan al menos {limites.ML_MIN_CLIENTES} clientes con compras para segmentar "
                f"y hay {n_total}."
            ),
            avisos=avisos,
            metricas={"n_clientes": n_total},
            parametros={"semilla": semilla, "hasta": hasta.isoformat(), "minimo_clientes": limites.ML_MIN_CLIENTES},
        )

    if n_total > limites.ML_MAX_CLIENTES:
        # Se quedan los de compra más reciente; el desempate por cliente_id mantiene el resultado determinista.
        orden = sorted(range(n_total), key=lambda i: (recencias[i], ids[i]))[: limites.ML_MAX_CLIENTES]
        orden.sort()
        ids = [ids[i] for i in orden]
        recencias = [recencias[i] for i in orden]
        frecuencias = [frecuencias[i] for i in orden]
        montos = [montos[i] for i in orden]
        avisos.append(
            f"Había {n_total} clientes y el máximo es {limites.ML_MAX_CLIENTES}: se usaron los de compra más "
            "reciente y los demás quedaron sin segmento."
        )

    from threadpoolctl import threadpool_limits

    # Un solo hilo en BLAS/OpenMP: el contenedor de producción es chico (ML_N_JOBS).
    with threadpool_limits(limits=limites.ML_N_JOBS):
        return _ajustar(ids, recencias, frecuencias, montos, hasta, semilla, avisos)


def _ajustar(
    ids: list[int],
    recencias: list[int],
    frecuencias: list[int],
    montos: list[float],
    hasta: date,
    semilla: int,
    avisos: list[str],
) -> ResultadoSegmentacion:
    import warnings

    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    n = len(ids)
    recencia = np.asarray(recencias, dtype=float)
    frecuencia = np.asarray(frecuencias, dtype=float)
    monto = np.asarray(montos, dtype=float)

    brutas = _vectorizar(recencia, frecuencia, monto)
    escalador = StandardScaler().fit(brutas)
    # Escala 1 donde la variable es constante. Se redondea a 10 decimales (como los centros, más abajo) para que
    # el modelo guardado sea reproducible bit a bit: el mismo cálculo puede diferir en el último dígito (1e-16)
    # entre la primera corrida del proceso y las siguientes, y ese ruido no debe llegar al artefacto.
    media, escala = np.round(escalador.mean_, DECIMALES_MODELO), np.round(escalador.scale_, DECIMALES_MODELO)
    escalados = (brutas - media) / escala

    n_distintos = int(np.unique(escalados, axis=0).shape[0])
    k_maximo = min(K_MAXIMO, n_distintos)
    parametros = _parametros_base(semilla, hasta, max(k_maximo, 1))
    parametros["ventana"] = {
        "ultima_compra_desde": (hasta.fromordinal(hasta.toordinal() - int(recencia.max()))).isoformat(),
        "ultima_compra_hasta": (hasta.fromordinal(hasta.toordinal() - int(recencia.min()))).isoformat(),
    }
    mediana_r, mediana_f, mediana_m = (float(np.median(v)) for v in (recencia, frecuencia, monto))

    curva_codo: list[dict[str, Any]] = []
    curva_silhouette: list[dict[str, Any]] = []

    if k_maximo < 2:
        # Todos los clientes son iguales: nada que separar. Un único segmento, sin silhouette.
        avisos.append("Todos los clientes tienen el mismo comportamiento de compra: no se pudo separar en grupos (k = 1).")
        k = 1
        centros = escalados[:1].copy()
        inercia = 0.0
        silhouette_elegida = None
    else:
        centros_por_k: dict[int, Any] = {}
        inercia_por_k: dict[int, float] = {}
        silhouette_por_k: dict[int, float | None] = {}
        muestra = SILHOUETTE_MAX_MUESTRA if n > SILHOUETTE_MAX_MUESTRA else None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # ConvergenceWarning con pocos puntos distintos
            for candidato in range(K_MINIMO, k_maximo + 1):
                ajuste = KMeans(n_clusters=candidato, n_init=N_INIT, random_state=semilla).fit(escalados)
                centros_por_k[candidato] = ajuste.cluster_centers_
                inercia_por_k[candidato] = float(ajuste.inertia_)
                silhouette: float | None = None
                if len(np.unique(ajuste.labels_)) >= 2:
                    try:
                        silhouette = float(
                            silhouette_score(escalados, ajuste.labels_, sample_size=muestra, random_state=semilla)
                        )
                    except ValueError:  # una muestra con una sola etiqueta
                        silhouette = None
                silhouette_por_k[candidato] = silhouette
        k = _elegir_k(silhouette_por_k)
        centros = centros_por_k[k]
        inercia = inercia_por_k[k]
        silhouette_elegida = silhouette_por_k[k]
        curva_codo = [{"k": c, "inercia": _redondear(inercia_por_k[c])} for c in sorted(inercia_por_k)]
        curva_silhouette = [{"k": c, "silhouette": _redondear(silhouette_por_k[c])} for c in sorted(silhouette_por_k)]
        if silhouette_elegida is None:
            avisos.append("No se pudo calcular la silhouette: no hay evidencia de que los segmentos estén separados.")
        elif silhouette_elegida < SILHOUETTE_DEBIL:
            avisos.append(
                f"La silhouette ({silhouette_elegida:.2f}) es baja: los segmentos están poco separados y "
                "conviene interpretarlos con cautela."
            )

    # Las etiquetas salen del vecino más cercano sobre los centros finales: son las mismas que usará
    # `asignar_segmento`, así que lo guardado y lo asignado a un cliente nuevo nunca se contradicen.
    centros = np.round(centros, DECIMALES_MODELO)
    etiquetas = _etiquetas_mas_cercanas(escalados, centros)
    presentes = sorted(int(c) for c in np.unique(etiquetas))  # un cluster vacío no genera segmento
    resumen_clusters = []
    for cluster in presentes:
        mascara = etiquetas == cluster
        resumen_clusters.append(
            {
                "cluster": cluster,
                "n": int(mascara.sum()),
                "recencia": float(recencia[mascara].mean()),
                "frecuencia": float(frecuencia[mascara].mean()),
                "monto_medio": float(monto[mascara].mean()),
                "monto_total": float(monto[mascara].sum()),
            }
        )
    # id 0 = el de mayor valor (monto total); el empate se rompe por el índice del cluster.
    resumen_clusters.sort(key=lambda r: (-round(r["monto_total"], 2), r["cluster"]))

    # Centroide en unidades originales: R se deshace del escalado; F y M, además, de log1p.
    en_originales = centros * escala + media
    nombres_base = []
    for resumen in resumen_clusters:
        r, f, m = en_originales[resumen["cluster"]]
        if k == 1:
            nombres_base.append("Todos los clientes")
        else:
            nombres_base.append(_nombrar(float(r), float(np.expm1(f)), float(np.expm1(m)), mediana_r, mediana_f, mediana_m))
    nombres = _desambiguar(nombres_base)

    segmentos: list[dict[str, Any]] = []
    conversion = np.full(len(centros), -1, dtype=int)  # cluster -> id de segmento
    for id_segmento, (resumen, nombre, base) in enumerate(zip(resumen_clusters, nombres, nombres_base, strict=True)):
        conversion[resumen["cluster"]] = id_segmento
        descripcion, accion = PLANTILLAS[base]
        segmentos.append(
            {
                "id": id_segmento,
                "nombre": nombre,
                "descripcion": descripcion,
                "accion_sugerida": accion,
                "n_clientes": resumen["n"],
                "pct_clientes": _redondear(100.0 * resumen["n"] / n, 2),
                "recencia_media": _redondear(resumen["recencia"], 1),
                "frecuencia_media": _redondear(resumen["frecuencia"], 2),
                "monto_medio": _redondear(resumen["monto_medio"], 2),
                "monto_total": _redondear(resumen["monto_total"], 2),
            }
        )

    ids_segmento = conversion[etiquetas]
    asignaciones = {cliente: int(segmento) for cliente, segmento in zip(ids, ids_segmento.tolist(), strict=True)}

    orden_centros = [r["cluster"] for r in resumen_clusters]  # centroide i = el del segmento con id i
    modelo = {
        "formato": FORMATO_MODELO,
        "variables": list(VARIABLES),
        "escalador": {"media": media.tolist(), "escala": escala.tolist()},
        "centroides": centros[orden_centros].tolist(),
        "segmentos": [{"id": s["id"], "nombre": s["nombre"]} for s in segmentos],
        "k": len(segmentos),
    }
    metricas = {
        "k": len(segmentos),
        "silhouette": _redondear(silhouette_elegida),
        "inercia": _redondear(inercia),
        "curva_codo": curva_codo,
        "curva_silhouette": curva_silhouette,
        "n_clientes": n,
    }
    return ResultadoSegmentacion(
        estado="ok",
        motivo=None,
        avisos=avisos,
        metricas=metricas,
        segmentos=segmentos,
        asignaciones=asignaciones,
        parametros=parametros,
        filas_entrenamiento=n,
        modelo=modelo,
    )


# ---- Asignación de un cliente nuevo ------------------------------------------------------------


def asignar_segmento(modelo: dict, ultima_compra: date, frecuencia: int, monto_total: Any, hasta: date) -> int:
    """Id del segmento al que pertenece un cliente, con el escalador y los centroides guardados.
    `monto_total` puede ser Decimal, float o int. Devuelve el mismo id que `asignaciones` para un
    cliente que ya estaba en el entrenamiento."""
    import numpy as np

    dias = max((hasta - _como_fecha(ultima_compra)).days, 0)
    punto = _vectorizar([dias], [max(int(frecuencia), 0)], [max(float(monto_total), 0.0)])
    media = np.asarray(modelo["escalador"]["media"], dtype=float)
    escala = np.asarray(modelo["escalador"]["escala"], dtype=float)
    centroides = np.asarray(modelo["centroides"], dtype=float)
    indice = int(_etiquetas_mas_cercanas((punto - media) / escala, centroides)[0])
    return int(modelo["segmentos"][indice]["id"])
