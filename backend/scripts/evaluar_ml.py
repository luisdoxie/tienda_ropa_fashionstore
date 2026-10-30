"""Evalúa los modelos de ML del CU-24 (E11, pasos 10 y 11) y los imprime como UNA tabla de texto plano, lista para
pegar en la documentación (E25). NUNCA escribe en la base: entrena en memoria y descarta todo (no hay `commit` en
ningún camino; no crea filas en `modelo_ml`, ni ventas, ni clientes).

Qué imprime, en este orden:
  1. Encabezado: nombre de la base (jamás la URL ni el host), empresa y plan, fuente de datos, rango y última fecha.
  2. Demanda semanal (supervisado): el modelo elegido contra la LÍNEA BASE (promedio móvil de 4 semanas), la validación
     cruzada de cada candidato y los tres criterios de calidad de la etapa con su veredicto.
  3. Segmentos de clientes (no supervisado): k, silhouette (con veredicto), curvas del codo y de silhouette, la tabla de
     segmentos y, solo con `--fuente memoria` (la única que conoce la verdad de arquetipos), la PUREZA.
  4. "HONESTIDAD Y LIMITACIONES": texto fijo.

Fuentes:
  --fuente base     (por defecto) lee lo que YA hay en la base de la empresa con las mismas consultas del CU-24
                    (`EntrenarModelosAnaliticos._calcular`). No hay verdad de arquetipos: no imprime pureza.
  --fuente memoria  toma el catálogo real de la empresa y genera el historial SINTÉTICO en memoria (sin insertar
                    nada): sirve para evaluar una empresa que aún no tiene historial cargado, e imprime la pureza.

Uso (desde backend/):
    python -m scripts.evaluar_ml --empresa chaski-sport
    python -m scripts.evaluar_ml --empresa chaski-sport --fuente memoria --perfil B --semilla 7

Los umbrales de los criterios son los de la etapa y NO se ajustan para que "cumpla": si no cumple, el veredicto lo dice.
Las funciones `formatear_*` son puras (reciben resultados y devuelven texto) para probarlas sin base; `main` solo conecta.
Se imprime en ASCII (sin tildes ni colores) para que salga igual en cualquier terminal y en el documento.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import textwrap
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# ---- Umbrales de la etapa (E11). No se bajan ni se reinterpretan. ------------------------------------------------------
UMBRAL_R2 = 0.50
UMBRAL_MEJORA_MAE_PCT = 5.0
UMBRAL_SILHOUETTE = 0.25
UMBRAL_PUREZA_PCT = 75.0

ANCHO_MAXIMO = 100  # columnas de cada línea del informe
ANCHO_TITULO = 96
CANDIDATOS = ("ridge", "mezcla", "random_forest")
PREFIJO_CAMPEONES = "Campeones"
# Segmentos de recencia antigua: lo que esperamos para los clientes "dormidos" del generador.
PREFIJOS_RECENCIA_ANTIGUA = ("En riesgo", "Por reactivar", "Grandes dormidos", "Hibernando")
VENTANA_RFM_DIAS = 365

LIMITACIONES = (
    "Datos sinteticos: el modelo aprende los patrones del generador; no prueba desempeno real.",
    "La promocion futura se asume igual al promedio de las ultimas 4 semanas (no se conoce).",
    "El rango de prediccion (+/- RMSE del hold-out) NO es un intervalo de confianza estadistico.",
    "Los nombres de los segmentos se deciden contra la mediana de la propia empresa (relativos).",
    "Metricas del hold-out (ultimas 12 semanas); varian con la semilla y con el historial.",
)


# ---- Estructuras: lo que reciben los formateadores (datos simples, sin base ni modelos) ---------------------------------


@dataclass
class Contexto:
    """Lo que dice el encabezado. `base` es solo el NOMBRE de la base de datos, nunca la URL."""

    base: str
    ubicacion: str  # "local" | "remota" | "en memoria"
    empresa: str
    plan: str
    fuente: str  # "base" | "memoria"
    detalle_fuente: str = ""
    corte: dt.date | None = None  # el `hasta` con que se entrenó
    desde: dt.date | None = None  # semanas completas que usó el modelo de demanda
    hasta: dt.date | None = None
    ultima_fecha: dt.date | None = None  # último día con ventas en los datos


@dataclass
class EvaluacionDemanda:
    estado: str  # "ok" | "datos_insuficientes"
    motivo: str | None = None
    metricas: dict = field(default_factory=dict)
    parametros: dict = field(default_factory=dict)
    tamano_artefacto: int | None = None
    avisos: list[str] = field(default_factory=list)


@dataclass
class EvaluacionSegmentos:
    estado: str
    motivo: str | None = None
    metricas: dict = field(default_factory=dict)  # k, silhouette, curva_codo, curva_silhouette, n_clientes
    segmentos: list[dict] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    segundos: float | None = None


@dataclass
class Pureza:
    """Cuántos clientes de cada arquetipo "puro" quedaron donde se esperaba. Solo existe con datos sintéticos."""

    campeones_total: int = 0
    campeones_bien: int = 0
    dormidos_total: int = 0
    dormidos_bien: int = 0

    @staticmethod
    def porcentaje(bien: int, total: int) -> float | None:
        return None if total <= 0 else 100.0 * bien / total


@dataclass
class Criterio:
    nombre: str
    valor: str
    umbral: str
    cumple: bool

    @property
    def veredicto(self) -> str:
        return "CUMPLE" if self.cumple else "NO CUMPLE"


# ---- Utilidades de texto -------------------------------------------------------------------------------------------------


def _ascii(texto: Any) -> str:
    """Quita tildes y cualquier carácter no ASCII (un nombre de empresa con ñ no debe romper la terminal)."""
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")


def _finito(valor: Any) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None


def _num(valor: Any, decimales: int = 2) -> str:
    """Número a la española (1.234,56). 'n/d' si falta o no es finito."""
    numero = _finito(valor)
    if numero is None:
        return "n/d"
    if round(numero, decimales) == 0:
        numero = 0.0  # evita "-0,00" cuando el valor es un negativo diminuto
    texto = f"{numero:,.{decimales}f}"
    return texto.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _fecha(valor: dt.date | None) -> str:
    return valor.isoformat() if valor is not None else "n/d"


def _envolver(texto: str, sangria: str = "") -> list[str]:
    return textwrap.wrap(_ascii(texto), width=ANCHO_MAXIMO, subsequent_indent=sangria) or [""]


def _titulo(texto: str) -> list[str]:
    return ["", "=" * ANCHO_TITULO, _ascii(texto), "=" * ANCHO_TITULO]


def _subtitulo(texto: str) -> list[str]:
    texto = _ascii(texto)
    return ["", texto, "-" * min(len(texto), ANCHO_MAXIMO)]


def _tabla(encabezados: list[str], filas: list[list[Any]], alinear: str | None = None) -> list[str]:
    """Tabla ASCII con bordes. `alinear`: una letra por columna ('l' izquierda, 'r' derecha). Si la tabla pasa de
    `ANCHO_MAXIMO`, recorta la columna más ancha con '..' (nunca se desborda la línea)."""
    columnas = len(encabezados)
    alinear = alinear or "l" * columnas
    cabeza = [_ascii(e) for e in encabezados]
    cuerpo = [[_ascii(c) for c in fila] for fila in filas]
    anchos = [max([len(cabeza[i])] + [len(f[i]) for f in cuerpo]) for i in range(columnas)]
    while sum(anchos) + 3 * columnas + 1 > ANCHO_MAXIMO:
        ancha = anchos.index(max(anchos))
        if anchos[ancha] <= 6:
            break
        anchos[ancha] -= 1

    def celda(texto: str, i: int) -> str:
        if len(texto) > anchos[i]:
            texto = texto[: anchos[i] - 2] + ".."
        return texto.rjust(anchos[i]) if alinear[i] == "r" else texto.ljust(anchos[i])

    def linea(fila: list[str]) -> str:
        return "| " + " | ".join(celda(t, i) for i, t in enumerate(fila)) + " |"

    borde = "+" + "+".join("-" * (a + 2) for a in anchos) + "+"
    return [borde, linea(cabeza), borde, *[linea(f) for f in cuerpo], borde]


# ---- Criterios de calidad ------------------------------------------------------------------------------------------------


def criterios_demanda(metricas: dict) -> list[Criterio]:
    """Los tres criterios de la etapa. Si falta un número (R2 sin varianza, línea base perfecta...) NO se puede afirmar
    que cumple: el veredicto es NO CUMPLE y el valor dice 'n/d'."""
    mae, mae_base = _finito(metricas.get("mae")), _finito(metricas.get("mae_base"))
    r2, mejora = _finito(metricas.get("r2")), _finito(metricas.get("mejora_mae_pct"))
    return [
        Criterio(
            "MAE del modelo <= MAE de la linea base",
            f"{_num(mae)} vs {_num(mae_base)}",
            "modelo <= base",
            mae is not None and mae_base is not None and mae <= mae_base,
        ),
        Criterio("R2 >= 0,50", _num(r2), ">= 0,50", r2 is not None and r2 >= UMBRAL_R2),
        Criterio(
            "Mejora de MAE >= 5 %",
            f"{_num(mejora, 1)} %" if mejora is not None else "n/d",
            ">= 5 %",
            mejora is not None and mejora >= UMBRAL_MEJORA_MAE_PCT,
        ),
    ]


def criterio_silhouette(metricas: dict) -> Criterio:
    silhouette = _finito(metricas.get("silhouette"))
    return Criterio("Silhouette >= 0,25", _num(silhouette), ">= 0,25", silhouette is not None and silhouette >= UMBRAL_SILHOUETTE)


def criterios_pureza(pureza: Pureza) -> list[tuple[str, int, int, Criterio]]:
    """(arquetipo, clientes del arquetipo, bien ubicados, criterio). Sin clientes del arquetipo no hay porcentaje:
    NO CUMPLE (no se puede afirmar)."""
    resultado = []
    for nombre, total, bien in (
        ("campeon", pureza.campeones_total, pureza.campeones_bien),
        ("dormido", pureza.dormidos_total, pureza.dormidos_bien),
    ):
        porcentaje = Pureza.porcentaje(bien, total)
        criterio = Criterio(
            f"Pureza de {nombre}s >= 75 %",
            f"{_num(porcentaje, 1)} %" if porcentaje is not None else "n/d",
            ">= 75 %",
            porcentaje is not None and porcentaje >= UMBRAL_PUREZA_PCT,
        )
        resultado.append((nombre, total, bien, criterio))
    return resultado


def calcular_pureza(clientes: Any, asignaciones: dict[int, int], segmentos: list[dict]) -> Pureza:
    """Compara el arquetipo REAL de cada cliente sintético (`cliente.n`, `cliente.arquetipo`) con el segmento que le tocó
    (`asignaciones`: cliente_id -> id de segmento; el generador usa `n` como id). Un cliente sin segmento (no compró en
    la ventana) no cuenta: la pureza mide la separación entre quienes SÍ se segmentaron."""
    nombre_de = {s["id"]: str(s["nombre"]) for s in segmentos}
    pureza = Pureza()
    for cliente in clientes:
        if cliente.n not in asignaciones:
            continue
        nombre = nombre_de.get(asignaciones[cliente.n], "")
        if cliente.arquetipo == "campeon":
            pureza.campeones_total += 1
            pureza.campeones_bien += nombre.startswith(PREFIJO_CAMPEONES)
        elif cliente.arquetipo == "dormido":
            pureza.dormidos_total += 1
            pureza.dormidos_bien += nombre.startswith(PREFIJOS_RECENCIA_ANTIGUA)
    return pureza


# ---- Formateadores (puros) -----------------------------------------------------------------------------------------------


def formatear_encabezado(ctx: Contexto) -> str:
    lineas = _titulo("EVALUACION DE MODELOS DE ML - CU-24 (FashionStore)")
    base = _ascii(ctx.base) if ctx.ubicacion == "en memoria" else f"{_ascii(ctx.base)} ({_ascii(ctx.ubicacion)})"
    lineas.append(f"Base de datos : {base}")
    lineas.append(f"Empresa       : {_ascii(ctx.empresa)}    Plan: {_ascii(ctx.plan)}")
    fuente = f"{ctx.fuente}" + (f" - {ctx.detalle_fuente}" if ctx.detalle_fuente else "")
    lineas += _envolver(f"Fuente        : {fuente}", sangria=" " * 16)
    lineas.append(f"Fecha de corte: {_fecha(ctx.corte)}")
    lineas.append(f"Rango (semanas completas): {_fecha(ctx.desde)} a {_fecha(ctx.hasta)}")
    lineas.append(f"Ultima fecha con datos   : {_fecha(ctx.ultima_fecha)}")
    return "\n".join(lineas)


def _avisos(avisos: list[str]) -> list[str]:
    lineas: list[str] = []
    for aviso in avisos:
        lineas += _envolver(f"Aviso: {aviso}", sangria="       ")
    return lineas


def formatear_demanda(ev: EvaluacionDemanda) -> str:
    lineas = _titulo("1. DEMANDA SEMANAL POR CATEGORIA (modelo supervisado)")
    if ev.estado != "ok":
        lineas += _envolver(f"Estado: {ev.estado}. Motivo: {ev.motivo or 'sin motivo'}")
        lineas += _avisos(ev.avisos)
        return "\n".join(lineas)

    m, p = ev.metricas, ev.parametros
    elegido = str(m.get("modelo_elegido", "n/d"))
    lineas += _subtitulo("Hold-out: ultimas 12 semanas (el modelo nunca las vio al elegir ni al entrenar)")
    lineas += _tabla(
        ["Metrica", f"Modelo ({elegido})", "Linea base (media movil 4 sem.)"],
        [
            ["MAE (unidades por semana y categoria)", _num(m.get("mae")), _num(m.get("mae_base"))],
            ["RMSE", _num(m.get("rmse")), _num(m.get("rmse_base"))],
            ["R2", _num(m.get("r2")), _num(m.get("r2_base"))],
            ["Mejora de MAE contra la linea base", f"{_num(m.get('mejora_mae_pct'), 1)} %", "-"],
        ],
        "lrr",
    )

    cruzada = m.get("validacion_cruzada") or {}
    filas_cv = []
    for nombre in CANDIDATOS:
        if nombre in cruzada:
            medio = (cruzada[nombre] or {}).get("mae_medio")
            filas_cv.append([nombre, _num(medio), "SI" if nombre == elegido else ""])
    if filas_cv:
        lineas += _subtitulo("Validacion cruzada temporal (3 cortes, solo con las semanas de entrenamiento)")
        lineas += _tabla(["Candidato", "MAE medio de validacion", "Elegido"], filas_cv, "lrl")

    lineas += _subtitulo("Datos y costo")
    segundos = _finito(p.get("segundos_entrenamiento"))
    lineas += _tabla(
        ["Dato", "Valor"],
        [
            ["Filas de entrenamiento (train)", _num(m.get("filas_train"), 0)],
            ["Filas de prueba (test)", _num(m.get("filas_test"), 0)],
            ["Semanas usadas", _num(p.get("n_semanas"), 0)],
            ["Categorias usadas", _num(p.get("n_categorias"), 0)],
            ["Tamano del artefacto serializado (bytes)", _num(ev.tamano_artefacto, 0)],
            ["Segundos de entrenamiento", _num(segundos, 2)],
        ],
        "lr",
    )

    lineas += _subtitulo("Criterios de calidad de la etapa")
    lineas += _tabla(
        ["Criterio", "Valor", "Umbral", "Veredicto"],
        [[c.nombre, c.valor, c.umbral, c.veredicto] for c in criterios_demanda(m)],
        "lrrl",
    )
    lineas += _avisos(ev.avisos)
    return "\n".join(lineas)


def formatear_segmentos(ev: EvaluacionSegmentos, pureza: Pureza | None = None) -> str:
    lineas = _titulo("2. SEGMENTOS DE CLIENTES POR RFM (modelo no supervisado, KMeans)")
    if ev.estado != "ok":
        lineas += _envolver(f"Estado: {ev.estado}. Motivo: {ev.motivo or 'sin motivo'}")
        lineas += _avisos(ev.avisos)
        return "\n".join(lineas)

    m = ev.metricas
    k = m.get("k")
    criterio = criterio_silhouette(m)
    lineas += _subtitulo("Resultado")
    lineas += _tabla(
        ["Dato", "Valor", "Veredicto"],
        [
            ["k elegido", _num(k, 0), ""],
            ["Clientes segmentados", _num(m.get("n_clientes"), 0), ""],
            ["Silhouette (umbral >= 0,25)", criterio.valor, criterio.veredicto],
            ["Segundos de entrenamiento", _num(ev.segundos, 2), ""],
        ],
        "lrl",
    )

    codo = {int(c["k"]): c.get("inercia") for c in (m.get("curva_codo") or [])}
    silhouette = {int(c["k"]): c.get("silhouette") for c in (m.get("curva_silhouette") or [])}
    ks = sorted(set(codo) | set(silhouette))
    if ks:
        lineas += _subtitulo("Curvas por k (silhouette: mayor es mejor; codo: inercia, busca donde deja de bajar rapido)")
        lineas += _tabla(
            ["k", "Silhouette", "Inercia (codo)", "Elegido"],
            [[str(c), _num(silhouette.get(c), 4), _num(codo.get(c), 1), "SI" if c == k else ""] for c in ks],
            "rrrl",
        )

    lineas += _subtitulo("Segmentos (id 0 = el de mayor monto total)")
    lineas += _tabla(
        ["Id", "Segmento", "Clientes", "% cli.", "Rec.(d)", "Frec.", "Monto med.", "Monto total"],
        [
            [
                str(s.get("id")),
                str(s.get("nombre")),
                _num(s.get("n_clientes"), 0),
                _num(s.get("pct_clientes"), 1),
                _num(s.get("recencia_media"), 1),
                _num(s.get("frecuencia_media"), 2),
                _num(s.get("monto_medio"), 2),
                _num(s.get("monto_total"), 2),
            ]
            for s in ev.segmentos
        ],
        "rlrrrrrr",
    )
    lineas += _envolver("Rec.(d) = recencia media en dias; Frec. = frecuencia media (compras); montos en bolivianos (Bs).")

    if pureza is not None:
        lineas += _subtitulo("PUREZA contra la verdad del generador (solo datos sinteticos en memoria)")
        lineas += _tabla(
            ["Arquetipo", "Clientes", "Bien ubicados", "Pureza", "Umbral", "Veredicto"],
            [
                [nombre, _num(total, 0), _num(bien, 0), c.valor, c.umbral, c.veredicto]
                for nombre, total, bien, c in criterios_pureza(pureza)
            ],
            "lrrrrl",
        )
        lineas += _envolver('campeon bien ubicado = segmento cuyo nombre empieza por "Campeones".')
        lineas += _envolver('dormido bien ubicado = segmento "En riesgo", "Por reactivar", "Grandes dormidos" o "Hibernando".')
    lineas += _avisos(ev.avisos)
    return "\n".join(lineas)


def formatear_limitaciones() -> str:
    lineas = _titulo("HONESTIDAD Y LIMITACIONES")
    lineas += [f"- {_ascii(texto)}" for texto in LIMITACIONES]
    lineas.append("=" * ANCHO_TITULO)
    return "\n".join(lineas)


def formatear_informe(
    ctx: Contexto, demanda: EvaluacionDemanda, segmentos: EvaluacionSegmentos, pureza: Pureza | None = None
) -> str:
    """El informe completo. Cada línea mide como máximo `ANCHO_MAXIMO` columnas."""
    return "\n".join(
        [formatear_encabezado(ctx), formatear_demanda(demanda), formatear_segmentos(segmentos, pureza), formatear_limitaciones()]
    )


# ---- Descripción de la base (nunca la URL) -------------------------------------------------------------------------------


def describir_base(url: Any) -> tuple[str, str]:
    """(nombre de la base, 'local' | 'remota' | 'en memoria') a partir de una URL de SQLAlchemy. Solo el nombre: ni el
    host, ni el usuario, ni la contraseña salen de aquí."""
    nombre = getattr(url, "database", None)
    if not nombre or nombre == ":memory:":
        return "(en memoria)", "en memoria"
    host = getattr(url, "host", None)
    local = host in (None, "", "localhost", "127.0.0.1")
    return str(nombre).replace("\\", "/").rsplit("/", 1)[-1], "local" if local else "remota"


# ---- Evaluación (conecta con el cálculo; no escribe nada) ---------------------------------------------------------------


def _como_dia(valor: Any) -> dt.date:
    return valor.date() if isinstance(valor, dt.datetime) else valor


def rango_de_filas(filas: list[dict]) -> tuple[dt.date | None, dt.date | None]:
    """Primer y último día con ventas de una serie diaria."""
    dias = [_como_dia(f["dia"]) for f in filas]
    return (min(dias), max(dias)) if dias else (None, None)


def _tamano_artefacto(artefacto: Any, avisos: list[str]) -> int | None:
    from app.inteligencia.ml import persistencia

    try:
        return persistencia.serializar(artefacto)[2]
    except ValueError as exc:  # ArtefactoDemasiadoGrande: el CU-24 tampoco lo guardaría
        avisos.append(f"El artefacto no se pudo serializar: {exc}")
        return None


def _evaluacion_demanda(r: Any) -> EvaluacionDemanda:
    """`r`: lo que devuelve `demanda.entrenar_demanda` o el `_Entrenado` del CU-24 (mismos nombres de campo)."""
    avisos = list(r.avisos)
    tamano = _tamano_artefacto(r.artefacto, avisos) if r.estado == "ok" and r.artefacto is not None else None
    return EvaluacionDemanda(r.estado, r.motivo, dict(r.metricas), dict(r.parametros), tamano, avisos)


def _evaluacion_segmentos(
    estado: str, motivo: str | None, metricas: dict, segmentos: list[dict], avisos: list[str], segundos: float
) -> EvaluacionSegmentos:
    limpias = {clave: valor for clave, valor in metricas.items() if clave != "segmentos"}
    return EvaluacionSegmentos(estado, motivo, limpias, list(segmentos), list(avisos), segundos)


def evaluar_desde_base(db: Any, hasta: dt.date):
    """Entrena EN MEMORIA con los datos que ya hay en la base de la empresa de la sesión, con las mismas consultas del
    CU-24. No guarda nada. Devuelve (demanda, segmentos, desde, hasta, ultima_fecha)."""
    from app.comercial import politicas as comercial_politicas
    from app.core.deps import ParametrosPeriodo
    from app.inteligencia.casos_uso.cu24_analizar_con_machine_learning import (
        TIPO_DEMANDA,
        TIPO_SEGMENTOS,
        EntrenarModelosAnaliticos,
    )
    from app.inteligencia.ml.limites import ML_MAX_SEMANAS

    caso = EntrenarModelosAnaliticos()
    r_demanda = caso._calcular(db, TIPO_DEMANDA, hasta)
    inicio = time.perf_counter()
    r_segmentos = caso._calcular(db, TIPO_SEGMENTOS, hasta)
    segundos = time.perf_counter() - inicio
    # El último día con ventas no sale del entrenamiento (que trabaja por semanas completas): se consulta la misma serie.
    periodo = ParametrosPeriodo(desde=hasta - dt.timedelta(weeks=ML_MAX_SEMANAS), hasta=hasta)
    _primero, ultimo = rango_de_filas(comercial_politicas.reporte_ventas_serie_diaria(db, periodo, desglose=("categoria",)))
    segmentos = r_segmentos.metricas.get("segmentos", [])
    return (
        _evaluacion_demanda(r_demanda),
        _evaluacion_segmentos(r_segmentos.estado, r_segmentos.motivo, r_segmentos.metricas, segmentos, r_segmentos.avisos, segundos),
        r_demanda.datos_desde,
        r_demanda.datos_hasta,
        ultimo,
    )


def evaluar_desde_memoria(
    db: Any, codigo_empresa: str, *, semanas: int, clientes: int, perfil: str, semilla: int, fin: dt.date
):
    """Genera el historial sintético EN MEMORIA (catálogo real de la empresa, nada se inserta) y entrena sobre él.
    Devuelve (demanda, segmentos, pureza, desde, hasta, ultima_fecha)."""
    from app.inteligencia.ml import demanda, segmentos, sintetico
    from scripts.seed_ml_sintetico import generar

    catalogo, historial = generar(db, codigo_empresa, semanas=semanas, clientes=clientes, perfil=perfil, semilla=semilla, fin=fin)
    filas_demanda = sintetico.filas_serie_diaria(historial, catalogo)
    r_demanda = demanda.entrenar_demanda(filas_demanda, fin)
    inicio = time.perf_counter()
    r_segmentos = segmentos.segmentar_clientes(sintetico.filas_rfm(historial, fin, dias=VENTANA_RFM_DIAS), fin)
    segundos = time.perf_counter() - inicio
    pureza = calcular_pureza(historial.clientes, r_segmentos.asignaciones, r_segmentos.segmentos) if r_segmentos.estado == "ok" else None
    _primero, ultimo = rango_de_filas(filas_demanda)
    return (
        _evaluacion_demanda(r_demanda),
        _evaluacion_segmentos(r_segmentos.estado, r_segmentos.motivo, r_segmentos.metricas, r_segmentos.segmentos, r_segmentos.avisos, segundos),
        pureza,
        r_demanda.datos_desde,
        r_demanda.datos_hasta,
        ultimo,
    )


def _nombre_del_plan(db: Any) -> str:
    from app.plataforma import politicas as plataforma_politicas

    plan = plataforma_politicas.plan_de_la_empresa(db)
    if plan is None:
        return "sin plan"
    return f"{plan.nombre}" + ("" if plan.analitica_ml else " (sin analitica_ml)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--empresa", required=True, help="Código de la empresa (por ejemplo chaski-sport)")
    parser.add_argument("--fuente", choices=("base", "memoria"), default="base", help="De dónde salen los datos (por defecto, la base)")
    parser.add_argument("--semanas", type=int, help="Solo con --fuente memoria (por defecto, el de seed_ml_sintetico: 78)")
    parser.add_argument("--clientes", type=int, help="Solo con --fuente memoria (por defecto, el de seed_ml_sintetico: 650)")
    parser.add_argument("--perfil", choices=("A", "B"), default="A", help="Solo con --fuente memoria")
    parser.add_argument("--semilla", type=int, default=42, help="Solo con --fuente memoria")
    parser.add_argument("--fin", type=dt.date.fromisoformat, help="Último día de datos (por defecto, ayer)")
    args = parser.parse_args(argv)

    import app.main  # noqa: F401  (registra todos los modelos)
    from app.core.tiempo import hoy_utc
    from scripts import seed_ml_sintetico
    from scripts._empresa import abrir_sesion

    semanas = args.semanas or seed_ml_sintetico.SEMANAS_POR_DEFECTO
    clientes = args.clientes or seed_ml_sintetico.CLIENTES_POR_DEFECTO
    fin = args.fin or hoy_utc() - dt.timedelta(days=1)

    db, empresa = abrir_sesion(args.empresa)
    codigo = empresa.codigo  # antes del rollback: después la sesión se cierra y el objeto queda desligado
    try:
        base, ubicacion = describir_base(db.get_bind().engine.url)
        plan = _nombre_del_plan(db)
        pureza = None
        if args.fuente == "base":
            demanda, segmentos, desde, hasta, ultima = evaluar_desde_base(db, fin)
            detalle = "datos que ya hay en la base (no se escribe nada)"
        else:
            demanda, segmentos, pureza, desde, hasta, ultima = evaluar_desde_memoria(
                db, codigo, semanas=semanas, clientes=clientes, perfil=args.perfil, semilla=args.semilla, fin=fin
            )
            detalle = (
                f"historial sintetico generado en memoria (perfil {args.perfil}, semilla {args.semilla}, "
                f"{semanas} semanas, {clientes} clientes); no se inserta nada"
            )
        db.rollback()  # lectura pura: ni un commit en ningún camino
    finally:
        db.close()

    ctx = Contexto(
        base=base, ubicacion=ubicacion, empresa=codigo, plan=plan, fuente=args.fuente, detalle_fuente=detalle,
        corte=fin, desde=desde, hasta=hasta, ultima_fecha=ultima,
    )  # fmt: skip
    print(formatear_informe(ctx, demanda, segmentos, pureza))


if __name__ == "__main__":
    main()
