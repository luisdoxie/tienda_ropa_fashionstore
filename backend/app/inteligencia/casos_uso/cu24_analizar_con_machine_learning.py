"""CU-24 — Analizar con Machine Learning

Actor: Administrador de la empresa.
Precondición: sesión con la empresa fijada, suscripción activa y un plan con `analitica_ml` (solo el Profesional,
D23). Postcondición: la empresa tiene modelos VIGENTES entrenados solo con sus datos (D22) y guardados con su
versión, sus métricas y su huella; la acción queda en la bitácora.

E11 implementa el ENTRENAMIENTO. La consulta de modelos, la predicción y los segmentos por HTTP son de la E12 y se
agregan en este mismo archivo (un caso de uso del catálogo no se parte en dos).

Clases de control:
- EntrenarModelosAnaliticos: entrena, evalúa y guarda el modelo de demanda semanal por categoría (supervisado) y la
  segmentación de clientes por RFM (no supervisado). Cada tipo en su propia transacción: si uno no tiene datos
  suficientes, el otro igual se entrena.

Aislamiento: los datos salen de `comercial.politicas` (que consulta con el alcance automático de la empresa de la
sesión) y el modelo se guarda con `ModeloMLRepository` (que filtra y rellena la empresa por `core/tenant`). Este
archivo nunca recibe ni compara un `empresa_id` del cliente. El cálculo (`app.inteligencia.ml`) es puro: solo ve filas
planas y no puede mezclar empresas.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.comercial import politicas as comercial_politicas
from app.core.auditoria import ACCION_ENTRENAR, ENTIDAD_MODELO_ML, ContextoAuditoria
from app.core.deps import ParametrosPeriodo
from app.core.exceptions import DomainError, ErrorFuncional
from app.core.planes import verificar_funcionalidad, verificar_suscripcion_activa
from app.core.tenant import exigir_empresa
from app.core.tiempo import hoy_utc
from app.inteligencia.ml import demanda, persistencia, segmentos
from app.inteligencia.ml.limites import ML_MAX_CLIENTES, ML_MAX_SEMANAS
from app.inteligencia.models import TIPOS_MODELO_ML
from app.inteligencia.repository import ModeloMLRepository
from app.plataforma import politicas as plataforma_politicas

logger = logging.getLogger("app.inteligencia.ml")

TIPO_DEMANDA = "demanda_semanal"
TIPO_SEGMENTOS = "segmentos_rfm"
# 'anomalias_ventas' existe en la tabla pero NO se entrena todavía (D37).
TIPOS_ENTRENABLES = (TIPO_DEMANDA, TIPO_SEGMENTOS)
VENTANA_RFM_DIAS = 365

# Los modelos ya deserializados que este proceso conserva (clave: empresa, tipo, versión). Se invalida al guardar
# una versión nueva. E12 lo usa para predecir sin deserializar en cada consulta.
CACHE_MODELOS = persistencia.CacheModelos()

_REPO = ModeloMLRepository()


@dataclass
class ResultadoTipo:
    """Qué pasó con UN tipo de modelo. `estado`: 'ok' (se guardó una versión nueva) o 'datos_insuficientes'
    (no se guardó nada; `motivo` dice por qué)."""

    tipo: str
    estado: str
    version: int | None = None
    motivo: str | None = None
    avisos: list[str] = field(default_factory=list)
    metricas: dict = field(default_factory=dict)
    filas_entrenamiento: int = 0
    datos_desde: dt.date | None = None
    datos_hasta: dt.date | None = None
    duracion_ms: int = 0


@dataclass
class ResumenEntrenamiento:
    resultados: list[ResultadoTipo] = field(default_factory=list)

    @property
    def entrenados(self) -> list[str]:
        return [r.tipo for r in self.resultados if r.estado == "ok"]


@dataclass
class _Entrenado:
    """Lo que devuelve el cálculo de un tipo, ya listo para guardar."""

    estado: str
    motivo: str | None
    avisos: list[str]
    metricas: dict
    parametros: dict
    filas_entrenamiento: int
    datos_desde: dt.date | None
    datos_hasta: dt.date | None
    artefacto: Any


def _a_json(valor: Any) -> Any:
    """Deja un valor como JSON simple: fechas en ISO, Decimal y numpy como números de Python, y los no finitos (NaN,
    infinito) como None. Las columnas `metricas` y `parametros` son JSONB y nunca deben guardar un NaN."""
    if isinstance(valor, dict):
        return {str(k): _a_json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_a_json(v) for v in valor]
    if isinstance(valor, (dt.date, dt.datetime)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        valor = float(valor)
    if hasattr(valor, "item") and not isinstance(valor, (str, bytes)):  # escalares de numpy
        valor = valor.item()
    if isinstance(valor, float) and not math.isfinite(valor):
        return None
    return valor


class EntrenarModelosAnaliticos:
    """Entrena los modelos de la empresa de la sesión con SUS datos. Es lo que llama el administrador (E12 lo expone
    por HTTP) y lo que usa `scripts.evaluar_ml`; por eso comprueba el plan por su cuenta y no confía en que el router
    lo haya hecho (defensa en profundidad)."""

    def ejecutar(
        self,
        db: Session,
        usuario_id: int | None,
        tipos: list[str] | tuple[str, ...] | None = None,
        contexto: ContextoAuditoria | None = None,
        hasta: dt.date | None = None,
    ) -> ResumenEntrenamiento:
        """`tipos` por defecto: los dos entrenables. `hasta`: último día de datos que entra (por defecto ayer: el día de
        hoy aún no terminó y subestimaría la demanda). Errores: 403 `suscripcion_no_activa`, 403
        `plan_no_incluye_funcionalidad`, 409 `entrenamiento_en_curso` (ya hay un entrenamiento de ese modelo en
        marcha) y 400 si se pide un tipo desconocido o aún no disponible."""
        verificar_suscripcion_activa(db)
        verificar_funcionalidad(db, "analitica_ml")
        pedidos = list(dict.fromkeys(tipos if tipos else TIPOS_ENTRENABLES))
        for tipo in pedidos:
            if tipo not in TIPOS_MODELO_ML:
                raise DomainError(f"Tipo de modelo desconocido: {tipo}")
            if tipo not in TIPOS_ENTRENABLES:
                raise DomainError(f"El modelo '{tipo}' todavía no está disponible")
        empresa_id = exigir_empresa(db)
        hasta = hasta or hoy_utc() - dt.timedelta(days=1)
        return ResumenEntrenamiento([self._entrenar_tipo(db, empresa_id, usuario_id, tipo, hasta, contexto) for tipo in pedidos])

    # -- Un tipo, en su propia transacción ----------------------------------------------------------------------------------

    def _entrenar_tipo(
        self, db: Session, empresa_id: int, usuario_id: int | None, tipo: str, hasta: dt.date, contexto: ContextoAuditoria | None
    ) -> ResultadoTipo:
        inicio = time.perf_counter()
        if self._candado_ocupado(db, empresa_id, tipo):
            db.rollback()
            raise ErrorFuncional("entrenamiento_en_curso", "Ya hay un entrenamiento de este modelo en curso para su empresa", 409, tipo=tipo)
        calculo = self._calcular(db, tipo, hasta)
        if calculo.estado != "ok":
            db.rollback()  # no se guarda nada; suelta también el candado
            return ResultadoTipo(tipo, calculo.estado, motivo=calculo.motivo, avisos=calculo.avisos, duracion_ms=_ms(inicio))

        datos, _huella, _tamano = persistencia.serializar(calculo.artefacto)
        metricas = _a_json(calculo.metricas)
        modelo = _REPO.guardar_nueva_version(
            db,
            tipo,
            metricas=metricas,
            parametros=_a_json({**calculo.parametros, "hasta": hasta, "ventana_rfm_dias": VENTANA_RFM_DIAS if tipo == TIPO_SEGMENTOS else None}),
            artefacto=datos,
            filas_entrenamiento=calculo.filas_entrenamiento,
            datos_desde=calculo.datos_desde,
            datos_hasta=calculo.datos_hasta,
            entrenado_por=usuario_id,
            commit=False,
        )
        duracion = _ms(inicio)
        # La fila de bitácora va en el MISMO commit que el modelo: si algo falla, no queda ninguna de las dos.
        plataforma_politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_MODELO_ML, modelo.id, ACCION_ENTRENAR, self._datos_de_bitacora(tipo, modelo.version, metricas, calculo, duracion)
        )
        version = modelo.version
        db.commit()
        CACHE_MODELOS.invalidar(empresa_id, tipo)
        logger.info("ml_entrenado tipo=%s version=%d filas=%d duracion_ms=%d", tipo, version, calculo.filas_entrenamiento, duracion)
        return ResultadoTipo(
            tipo, "ok", version=version, avisos=calculo.avisos, metricas=metricas, filas_entrenamiento=calculo.filas_entrenamiento,
            datos_desde=calculo.datos_desde, datos_hasta=calculo.datos_hasta, duracion_ms=duracion,
        )  # fmt: skip

    @staticmethod
    def _datos_de_bitacora(tipo: str, version: int, metricas: dict, calculo: _Entrenado, duracion_ms: int) -> dict:
        """Solo ids y números: ningún dato personal (la bitácora guarda la acción, no el modelo)."""
        datos = {"tipo": tipo, "version": version, "filas": calculo.filas_entrenamiento, "duracion_ms": duracion_ms}
        claves = ("mae", "rmse", "r2", "mejora_mae_pct", "modelo_elegido") if tipo == TIPO_DEMANDA else ("k", "silhouette", "n_clientes")
        datos.update({c: metricas.get(c) for c in claves})
        return datos

    @staticmethod
    def _candado_ocupado(db: Session, empresa_id: int, tipo: str) -> bool:
        """Un solo entrenamiento por (empresa, tipo) a la vez. En PostgreSQL es un candado consultivo de la transacción
        (se suelta solo al terminar: confirmar o revertir); en SQLite (solo pruebas, un proceso) no hay nada que
        proteger. Hay un solo worker, así que el riesgo real es bajo; esto cubre un doble clic o dos pestañas."""
        if db.get_bind().dialect.name != "postgresql":
            return False
        clave_tipo = TIPOS_MODELO_ML.index(tipo) + 1
        return not db.scalar(select(func.pg_try_advisory_xact_lock(empresa_id, clave_tipo)))

    # -- El cálculo de cada tipo: los datos salen de `comercial`, la empresa la pone la sesión ---------------------------------

    def _calcular(self, db: Session, tipo: str, hasta: dt.date) -> _Entrenado:
        if tipo == TIPO_DEMANDA:
            periodo = ParametrosPeriodo(desde=hasta - dt.timedelta(weeks=ML_MAX_SEMANAS), hasta=hasta)
            filas = comercial_politicas.reporte_ventas_serie_diaria(db, periodo, desglose=("categoria",))
            r = demanda.entrenar_demanda(filas, hasta)
            return _Entrenado(
                r.estado, r.motivo, r.avisos, r.metricas, r.parametros, r.filas_entrenamiento, r.datos_desde, r.datos_hasta, r.artefacto
            )
        filas = comercial_politicas.reporte_rfm_clientes(db, hasta, dias=VENTANA_RFM_DIAS, tope=ML_MAX_CLIENTES)
        s = segmentos.segmentar_clientes(filas, hasta)
        # Los segmentos (nombre, tamaño, medias) van en las métricas para mostrarlos sin deserializar el modelo; las
        # asignaciones cliente -> segmento NO se guardan (se recalculan con el modelo y son datos por persona).
        metricas = {**s.metricas, "segmentos": s.segmentos}
        desde = hasta - dt.timedelta(days=VENTANA_RFM_DIAS - 1)
        return _Entrenado(s.estado, s.motivo, s.avisos, metricas, s.parametros, s.filas_entrenamiento, desde, hasta, s.modelo)


def _ms(inicio: float) -> int:
    return int((time.perf_counter() - inicio) * 1000)
