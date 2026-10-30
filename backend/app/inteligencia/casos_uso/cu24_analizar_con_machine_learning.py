"""CU-24 — Analizar con Machine Learning

Actor: Administrador de la empresa.
Precondición: sesión con la empresa fijada, suscripción activa y un plan con `analitica_ml` (solo el Profesional,
D23). Postcondición: la empresa tiene modelos VIGENTES entrenados solo con sus datos (D22) y guardados con su
versión, sus métricas y su huella; la acción queda en la bitácora.

E11 implementa el ENTRENAMIENTO; la E12 agrega la CONSULTA (estado, predicción de demanda, segmentos y panel) en este
mismo archivo (un caso de uso del catálogo no se parte en dos).

Clases de control:
- EntrenarModelosAnaliticos: entrena, evalúa y guarda el modelo de demanda semanal por categoría (supervisado) y la
  segmentación de clientes por RFM (no supervisado). Cada tipo en su propia transacción: si uno no tiene datos
  suficientes, el otro igual se entrena.
- ConsultarAnaliticaML: lo que llama el router `/analitica`. Exige plan, suscripción y alcance global (la analítica es
  de toda la empresa: un encargado de sucursal no la ve, D28), carga el modelo vigente de la empresa (con huella y
  versión de scikit-learn) y arma las respuestas listas para graficar. Nunca devuelve el artefacto.

Aislamiento: los datos salen de `comercial.politicas` (que consulta con el alcance automático de la empresa de la
sesión) y el modelo se guarda con `ModeloMLRepository` (que filtra y rellena la empresa por `core/tenant`). Este
archivo nunca recibe ni compara un `empresa_id` del cliente. El cálculo (`app.inteligencia.ml`) es puro: solo ve filas
planas y no puede mezclar empresas.
"""

from __future__ import annotations

import datetime as dt
import importlib.metadata
import logging
import math
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.comercial import politicas as comercial_politicas
from app.core.auditoria import ACCION_ENTRENAR, ENTIDAD_MODELO_ML, ContextoAuditoria
from app.core.deps import ParametrosPeriodo
from app.core.exceptions import DomainError, ErrorFuncional, NoEncontradoError, PermisoDenegadoError
from app.core.planes import verificar_funcionalidad, verificar_suscripcion_activa
from app.core.tenant import exigir_empresa
from app.core.tiempo import hoy_utc
from app.inteligencia import politicas as inteligencia_politicas
from app.inteligencia.ml import anomalias, demanda, persistencia, reposicion, segmentos
from app.inteligencia.ml.limites import (
    ML_DIAS_VIGENCIA,
    ML_MAX_CLIENTES,
    ML_MAX_SEMANAS,
    ML_MIN_CATEGORIAS,
    ML_MIN_CLIENTES,
    ML_MIN_SEMANAS,
    ML_PUNTOS_DISPERSION,
    ML_SEMANAS_NUEVAS_MAX,
)
from app.inteligencia.models import TIPOS_MODELO_ML, ModeloML
from app.inteligencia.repository import ModeloMLRepository
from app.inteligencia.schemas import (
    AnomaliasRespuesta,
    AnomaliaVenta,
    DatosDisponibles,
    DemandaCategoria,
    DemandaRespuesta,
    EntrenarRespuesta,
    EstadoAnalitica,
    EstadoModelo,
    GraficoSugerido,
    ItemReposicion,
    KpiAnalitico,
    MetricasDemanda,
    PanelAnalitico,
    PuntoDispersion,
    PuntoSerie,
    ReposicionRespuesta,
    ResultadoEntrenamiento,
    SegmentoCliente,
    SegmentosRespuesta,
)
from app.plataforma import politicas as plataforma_politicas

logger = logging.getLogger("app.inteligencia.ml")

TIPO_DEMANDA = "demanda_semanal"
TIPO_SEGMENTOS = "segmentos_rfm"
TIPO_ANOMALIAS = "anomalias_ventas"  # E12b (D37): detector de días de ventas inusuales (Isolation Forest + regla robusta)
TIPOS_ENTRENABLES = (TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS)
VENTANA_RFM_DIAS = 365
CLAVE_EMPRESA_EN_ARTEFACTO = "empresa_id"  # dentro del artefacto: a qué empresa pertenece (defensa en profundidad)

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

        # El artefacto lleva la empresa a la que pertenece: al cargarlo se comprueba (una fila copiada de otra empresa no sirve).
        datos, _huella, _tamano = persistencia.serializar({**calculo.artefacto, CLAVE_EMPRESA_EN_ARTEFACTO: empresa_id})
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
        claves = {
            TIPO_DEMANDA: ("mae", "rmse", "r2", "mejora_mae_pct", "modelo_elegido"),
            TIPO_SEGMENTOS: ("k", "silhouette", "n_clientes"),
            TIPO_ANOMALIAS: ("n_dias", "n_sucursales", "n_marcados", "pct_marcados"),
        }[tipo]
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
        if tipo == TIPO_ANOMALIAS:
            periodo = ParametrosPeriodo(desde=hasta - dt.timedelta(days=anomalias.MAX_DIAS), hasta=hasta)
            filas = comercial_politicas.reporte_ventas_serie_diaria(db, periodo, desglose=("sucursal",))
            a = anomalias.entrenar_anomalias(filas, hasta)
            return _Entrenado(
                a.estado, a.motivo, a.avisos, a.metricas, a.parametros, a.filas_entrenamiento, a.datos_desde, a.datos_hasta, a.artefacto
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


# ---- Consulta de la analítica (E12) -----------------------------------------------------------------------------------

TITULOS_MODELO = {
    TIPO_DEMANDA: "Demanda semanal por categoría",
    TIPO_SEGMENTOS: "Segmentos de clientes (RFM)",
    TIPO_ANOMALIAS: "Días de ventas inusuales",
}
MENSAJE_SIN_MODELO = "Aún no hay un modelo entrenado. Un administrador puede entrenarlo en Analítica."
SEMANAS_DE_HISTORICO = 12
HORIZONTE_POR_DEFECTO = 4
DIAS_ANOMALIAS_DEFECTO = 90  # ventana por defecto de GET /anomalias
DIAS_ANOMALIAS_PANEL = 30  # el panel muestra las anomalías de los últimos 30 días
LIMITE_PRODUCTOS_DE_EXISTENCIAS = 10_000  # tope de productos por categoría al sumar existencias
NOMBRES_EN_RIESGO = ("En riesgo", "Por reactivar", "Grandes dormidos")
METRICAS_VISIBLES = {
    TIPO_DEMANDA: ("mae", "rmse", "r2", "mae_base", "rmse_base", "r2_base", "mejora_mae_pct", "modelo_elegido", "filas_train", "filas_test"),
    TIPO_SEGMENTOS: ("k", "silhouette", "n_clientes"),
    TIPO_ANOMALIAS: ("n_dias", "n_sucursales", "n_marcados", "pct_marcados", "umbral", "contamination", "n_marcados_modelo", "n_marcados_regla", "z_regla"),
}


def _version_sklearn_instalada() -> str | None:
    """La versión instalada, SIN importar scikit-learn (importarlo tarda ~1,3 s y esto se llama en cada consulta)."""
    try:
        return importlib.metadata.version("scikit-learn")
    except importlib.metadata.PackageNotFoundError:
        return None


def _version_sklearn_del_modelo(parametros: dict) -> str | None:
    """Con qué scikit-learn se entrenó: la demanda lo guarda en `version_sklearn` y los segmentos en `versiones`."""
    return parametros.get("version_sklearn") or (parametros.get("versiones") or {}).get("sklearn")


def _lunes(dia: dt.date) -> dt.date:
    return dia - dt.timedelta(days=dia.weekday())


def _redondear(valor: float | None, decimales: int = 1) -> float | None:
    return None if valor is None else round(float(valor), decimales)


class ConsultarAnaliticaML:
    """Estado, predicción de demanda, segmentos y panel de la empresa de la sesión. Todos los métodos exigen
    suscripción activa, la funcionalidad `analitica_ml` y alcance global; el router lo pide también, pero aquí se
    repite porque este caso de uso no confía en quien lo llama (defensa en profundidad). `hoy` solo existe para que las
    pruebas fijen la fecha."""

    # -- Acceso y carga del modelo -----------------------------------------------------------------------------------------

    @staticmethod
    def exigir_alcance_global(db: Session, usuario_id: int) -> None:
        """Solo quien no tiene sucursal asignada (el administrador de la empresa) ve la analítica: el modelo no se puede
        acotar por sucursal sin filtrar resultados de otras (D28). Es público para que el router lo pida antes de
        validar los parámetros."""
        if plataforma_politicas.sucursal_asignada(db, usuario_id) is not None:
            raise PermisoDenegadoError("La analítica es de toda la empresa")

    def _exigir_acceso(self, db: Session, usuario_id: int) -> None:
        verificar_suscripcion_activa(db)
        verificar_funcionalidad(db, "analitica_ml")
        self.exigir_alcance_global(db, usuario_id)

    def _estado_modelo(self, db: Session, tipo: str, hoy: dt.date) -> tuple[EstadoModelo, ModeloML | None]:
        """Lee solo la fila (sin el artefacto). `obsoleto` se decide por la versión de scikit-learn guardada; un
        artefacto corrupto se detecta recién al cargarlo."""
        titulo = TITULOS_MODELO[tipo]
        fila = _REPO.obtener_activo(db, tipo)
        if fila is None:
            return EstadoModelo(tipo=tipo, titulo=titulo, entrenado=False, estado="sin_entrenar", mensaje=MENSAJE_SIN_MODELO), None
        entrenado_dia = fila.entrenado_en.date() if fila.entrenado_en else hoy
        dias = max((hoy - entrenado_dia).days, 0)
        guardada, instalada = _version_sklearn_del_modelo(fila.parametros or {}), _version_sklearn_instalada()
        if guardada and instalada and guardada != instalada:
            estado = "obsoleto"
            mensaje = f"Se entrenó con scikit-learn {guardada} y ahora hay {instalada}: hay que reentrenarlo."
        else:
            semanas_nuevas = (hoy - fila.datos_hasta).days // 7 if fila.datos_hasta else 0
            if dias > ML_DIAS_VIGENCIA or semanas_nuevas > ML_SEMANAS_NUEVAS_MAX:
                estado = "desactualizado"
                mensaje = f"Está desactualizado: se entrenó hace {dias} días con datos hasta hace {semanas_nuevas} semanas. Conviene reentrenarlo."
            else:
                estado = "vigente"
                mensaje = f"Vigente: versión {fila.version}, entrenado hace {dias} días."
        metricas = {k: v for k, v in (fila.metricas or {}).items() if k in METRICAS_VISIBLES[tipo]}
        return (
            EstadoModelo(
                tipo=tipo, titulo=titulo, entrenado=True, estado=estado, version=fila.version, entrenado_en=fila.entrenado_en,
                filas_entrenamiento=fila.filas_entrenamiento, datos_desde=fila.datos_desde, datos_hasta=fila.datos_hasta,
                metricas=_a_json(metricas), mensaje=mensaje,
            ),
            fila,
        )  # fmt: skip

    def _cargar(self, db: Session, tipo: str, hoy: dt.date) -> tuple[EstadoModelo, ModeloML, Any]:
        """El modelo VIGENTE ya deserializado. 409 `modelo_no_entrenado` si no hay, 409 `modelo_obsoleto` si es de otra
        versión de scikit-learn o su huella no coincide. Nunca un 500 por un artefacto dañado."""
        estado, fila = self._estado_modelo(db, tipo, hoy)
        if fila is None:
            raise ErrorFuncional("modelo_no_entrenado", MENSAJE_SIN_MODELO, 409, tipo=tipo)
        if estado.estado == "obsoleto":
            raise ErrorFuncional("modelo_obsoleto", estado.mensaje, 409, tipo=tipo)
        empresa_id = exigir_empresa(db)
        artefacto = CACHE_MODELOS.obtener(empresa_id, tipo, fila.version)
        if artefacto is None:
            completa = _REPO.obtener_version(db, tipo, fila.version, con_artefacto=True)
            try:
                artefacto = persistencia.deserializar(completa.artefacto, completa.artefacto_sha256)
            except persistencia.ArtefactoCorrupto as exc:
                logger.warning("ml_modelo_no_cargable tipo=%s version=%d", tipo, fila.version)
                raise ErrorFuncional(
                    "modelo_obsoleto", f"El modelo guardado no se puede usar ({exc}). Hay que reentrenarlo.", 409, tipo=tipo
                ) from exc
            if artefacto.get(CLAVE_EMPRESA_EN_ARTEFACTO) != empresa_id:
                logger.warning("ml_modelo_de_otra_empresa tipo=%s version=%d", tipo, fila.version)
                raise ErrorFuncional("modelo_obsoleto", "El modelo guardado no corresponde a esta empresa. Hay que reentrenarlo.", 409, tipo=tipo)
            CACHE_MODELOS.poner(empresa_id, tipo, fila.version, artefacto)
        return estado, fila, artefacto

    @staticmethod
    def _avisos_de(estado: EstadoModelo) -> list[str]:
        return [estado.mensaje] if estado.estado == "desactualizado" else []

    # -- Estado y entrenamiento -----------------------------------------------------------------------------------------------

    def estado(self, db: Session, usuario_id: int, *, hoy: dt.date | None = None) -> EstadoAnalitica:
        self._exigir_acceso(db, usuario_id)
        hoy = hoy or hoy_utc()
        modelos = [self._estado_modelo(db, tipo, hoy)[0] for tipo in TIPOS_ENTRENABLES]
        ayer = hoy - dt.timedelta(days=1)
        filas = comercial_politicas.reporte_ventas_serie_diaria(
            db, ParametrosPeriodo(desde=ayer - dt.timedelta(weeks=ML_MAX_SEMANAS), hasta=ayer), desglose=("categoria",)
        )
        clientes = len(comercial_politicas.reporte_rfm_clientes(db, ayer, dias=VENTANA_RFM_DIAS, tope=ML_MAX_CLIENTES))
        datos = DatosDisponibles(
            semanas_con_ventas=len({_lunes(f["dia"]) for f in filas}),
            categorias_con_ventas=len({f["categoria_id"] for f in filas}),
            clientes_con_compras=clientes,
        )
        puede = {
            TIPO_DEMANDA: datos.semanas_con_ventas >= ML_MIN_SEMANAS and datos.categorias_con_ventas >= ML_MIN_CATEGORIAS,
            TIPO_SEGMENTOS: datos.clientes_con_compras >= ML_MIN_CLIENTES,
            TIPO_ANOMALIAS: datos.semanas_con_ventas >= anomalias.MIN_DIAS_DATOS // 7,
        }
        frases = inteligencia_politicas.interpretar_estado(
            [
                {
                    "titulo": m.titulo,
                    "estado": m.estado,
                    "version": m.version,
                    "dias_desde_entrenamiento": max((hoy - m.entrenado_en.date()).days, 0) if m.entrenado_en else None,
                }
                for m in modelos
            ]
        )
        return EstadoAnalitica(modelos=modelos, datos=datos, puede_entrenar=puede, interpretacion=frases)

    def entrenar(
        self, db: Session, usuario_id: int, tipos: list[str] | None = None, contexto: ContextoAuditoria | None = None
    ) -> EntrenarRespuesta:
        self._exigir_acceso(db, usuario_id)
        resumen = EntrenarModelosAnaliticos().ejecutar(db, usuario_id, tipos, contexto)
        return EntrenarRespuesta(
            resultados=[
                ResultadoEntrenamiento(
                    tipo=r.tipo,
                    estado="entrenado" if r.estado == "ok" else "datos_insuficientes",
                    version=r.version,
                    metricas=_a_json({k: v for k, v in r.metricas.items() if k in METRICAS_VISIBLES[r.tipo]}),
                    avisos=r.avisos,
                    motivo=r.motivo,
                    duracion_ms=r.duracion_ms,
                )
                for r in resumen.resultados
            ]
        )

    # -- Demanda -----------------------------------------------------------------------------------------------------------------

    def demanda(
        self, db: Session, usuario_id: int, semanas: int = HORIZONTE_POR_DEFECTO, categoria_id: int | None = None, *, hoy: dt.date | None = None
    ) -> DemandaRespuesta:
        self._exigir_acceso(db, usuario_id)  # orden de errores: suscripción, plan, alcance y recién después los parámetros
        if isinstance(semanas, bool) or not isinstance(semanas, int) or not 1 <= semanas <= demanda.MAX_SEMANAS_PREDICCION:
            raise DomainError(f"Las semanas a predecir van de 1 a {demanda.MAX_SEMANAS_PREDICCION}")
        hoy = hoy or hoy_utc()
        estado, fila, artefacto = self._cargar(db, TIPO_DEMANDA, hoy)
        if categoria_id is not None and categoria_id not in {c["id"] for c in artefacto["categorias"]}:
            raise NoEncontradoError("Categoría no encontrada")  # igual que una inexistente o de otra empresa

        historico = self._historico_semanal(db, artefacto)
        predicciones = demanda.predecir_demanda(artefacto, semanas)
        por_categoria: dict[int, list[Any]] = {}
        for p in predicciones:
            por_categoria.setdefault(p.categoria_id, []).append(p)
        nombres = {c["id"]: c["nombre"] for c in artefacto["categorias"]}

        bloques = {cid: self._bloque_categoria(cid, nombres[cid], historico[cid], por_categoria[cid], semanas) for cid in nombres}
        total = self._bloque_total(list(bloques.values()), semanas)
        elegidas = [bloques[cid] for cid in sorted(nombres, key=lambda i: nombres[i].lower()) if categoria_id in (None, cid)]
        metricas = MetricasDemanda(**{k: (fila.metricas or {}).get(k) for k in MetricasDemanda.model_fields})
        supuestos = list(artefacto.get("supuestos", [])) + [
            f"El modelo se entrenó con datos del {fila.datos_desde} al {fila.datos_hasta}.",
            "El total de la empresa suma las predicciones y los rangos de cada categoría.",
        ]
        return DemandaRespuesta(
            horizonte_semanas=semanas,
            modelo=estado,
            categorias=elegidas,
            total_empresa=total,
            metricas=metricas,
            supuestos=supuestos,
            interpretacion=(
                inteligencia_politicas.interpretar_metricas_demanda(metricas.model_dump())
                + inteligencia_politicas.interpretar_demanda(
                    [
                        {"categoria": b.categoria, "total_predicho": b.total_predicho, "variacion_pct": b.variacion_pct_vs_ultimas_semanas}
                        for b in elegidas
                    ],
                    semanas,
                )
            ),
            grafico_sugerido=GraficoSugerido(tipo="linea", eje_x="semana", eje_y="unidades", serie="categoria"),
            avisos=self._avisos_de(estado),
        )

    @staticmethod
    def _historico_semanal(db: Session, artefacto: dict) -> dict[int, list[float]]:
        """Unidades REALES por categoría de las últimas 12 semanas que terminan en la última semana del modelo (se leen de
        `comercial`, con el alcance de la empresa de la sesión). Las semanas sin ventas valen 0."""
        ultima = artefacto["ultima_semana"]
        primera = ultima - dt.timedelta(weeks=SEMANAS_DE_HISTORICO - 1)
        filas = comercial_politicas.reporte_ventas_serie_diaria(
            db, ParametrosPeriodo(desde=primera, hasta=ultima + dt.timedelta(days=6)), desglose=("categoria",)
        )
        indice = {primera + dt.timedelta(weeks=i): i for i in range(SEMANAS_DE_HISTORICO)}
        historico = {c["id"]: [0.0] * SEMANAS_DE_HISTORICO for c in artefacto["categorias"]}
        for fila in filas:
            posicion = indice.get(_lunes(fila["dia"]))
            if posicion is not None and fila["categoria_id"] in historico:
                historico[fila["categoria_id"]][posicion] += float(fila["unidades"])
        return historico

    @staticmethod
    def _puntos_historicos(valores: list[float], ultima: dt.date | None) -> list[PuntoSerie]:
        primera = ultima - dt.timedelta(weeks=len(valores) - 1)
        return [PuntoSerie(etiqueta=(primera + dt.timedelta(weeks=i)).isoformat(), valor=v) for i, v in enumerate(valores)]

    def _bloque_categoria(self, categoria_id: int | None, nombre: str, reales: list[float], predichas: list[Any], semanas: int) -> DemandaCategoria:
        ultima = predichas[0].semana_inicio - dt.timedelta(weeks=1)
        prediccion = [
            PuntoSerie(etiqueta=p.semana_inicio.isoformat(), valor=p.unidades, minimo=p.minimo, maximo=p.maximo, es_prediccion=True)
            for p in predichas
        ]
        total = sum(p.unidades for p in predichas)
        promedio_reciente = sum(reales[-4:]) / len(reales[-4:])
        variacion = None if promedio_reciente <= 0 else _redondear((total / semanas - promedio_reciente) / promedio_reciente * 100)
        return DemandaCategoria(
            categoria_id=categoria_id, categoria=nombre, historico=self._puntos_historicos(reales, ultima), prediccion=prediccion,
            total_predicho=int(total), variacion_pct_vs_ultimas_semanas=variacion,
        )  # fmt: skip

    def _bloque_total(self, bloques: list[DemandaCategoria], semanas: int) -> DemandaCategoria:
        historico = [
            PuntoSerie(etiqueta=bloques[0].historico[i].etiqueta, valor=sum(b.historico[i].valor for b in bloques))
            for i in range(len(bloques[0].historico))
        ]
        prediccion = [
            PuntoSerie(
                etiqueta=bloques[0].prediccion[i].etiqueta,
                valor=sum(b.prediccion[i].valor for b in bloques),
                minimo=sum(b.prediccion[i].minimo for b in bloques),
                maximo=sum(b.prediccion[i].maximo for b in bloques),
                es_prediccion=True,
            )
            for i in range(semanas)
        ]
        total = int(sum(p.valor for p in prediccion))
        reciente = [p.valor for p in historico[-4:]]
        promedio = sum(reciente) / len(reciente)
        variacion = None if promedio <= 0 else _redondear((total / semanas - promedio) / promedio * 100)
        return DemandaCategoria(
            categoria_id=None, categoria="Total de la empresa", historico=historico, prediccion=prediccion, total_predicho=total,
            variacion_pct_vs_ultimas_semanas=variacion,
        )  # fmt: skip

    # -- Segmentos ---------------------------------------------------------------------------------------------------------------

    def segmentos(self, db: Session, usuario_id: int, *, hoy: dt.date | None = None) -> SegmentosRespuesta:
        self._exigir_acceso(db, usuario_id)
        hoy = hoy or hoy_utc()
        estado, fila, artefacto = self._cargar(db, TIPO_SEGMENTOS, hoy)
        metricas = fila.metricas or {}
        guardados = metricas.get("segmentos") or []
        monto_total = sum(float(s["monto_total"]) for s in guardados) or 1.0
        lista = [
            SegmentoCliente(
                id=s["id"], nombre=s["nombre"], descripcion=s["descripcion"], accion_sugerida=s["accion_sugerida"],
                clientes=s["n_clientes"], porcentaje_clientes=float(s["pct_clientes"]), recencia_media_dias=float(s["recencia_media"]),
                frecuencia_media=float(s["frecuencia_media"]), monto_medio=float(s["monto_medio"]), monto_total=float(s["monto_total"]),
                porcentaje_monto=round(float(s["monto_total"]) / monto_total * 100.0, 2),
            )
            for s in guardados
        ]  # fmt: skip
        silhouette = metricas.get("silhouette")
        supuestos = list((fila.parametros or {}).get("supuestos", []))
        return SegmentosRespuesta(
            modelo=estado,
            k=int(metricas.get("k") or len(lista)),
            silhouette=silhouette,
            clientes_segmentados=int(metricas.get("n_clientes") or sum(s.clientes for s in lista)),
            segmentos=lista,
            dispersion=self._dispersion(db, fila, artefacto),
            curva_silhouette=[
                PuntoSerie(etiqueta=str(p["k"]), valor=p["silhouette"]) for p in metricas.get("curva_silhouette", []) if p.get("silhouette") is not None
            ],
            curva_codo=[PuntoSerie(etiqueta=str(p["k"]), valor=p["inercia"]) for p in metricas.get("curva_codo", []) if p.get("inercia") is not None],
            supuestos=supuestos,
            interpretacion=inteligencia_politicas.interpretar_segmentos(guardados, silhouette),
            grafico_sugerido=GraficoSugerido(tipo="torta", eje_x="segmento", eje_y="clientes"),
            avisos=self._avisos_de(estado),
        )  # fmt: skip

    @staticmethod
    def _dispersion(db: Session, fila: ModeloML, modelo: dict) -> list[PuntoDispersion]:
        """Una muestra DETERMINISTA de a lo sumo 300 clientes, SIN su id: se ordenan por id, se toma uno cada tantos y
        solo entonces se les asigna segmento (asignar a todos sería lento con decenas de miles)."""
        hasta = fila.datos_hasta
        if hasta is None:
            return []
        filas = comercial_politicas.reporte_rfm_clientes(db, hasta, dias=VENTANA_RFM_DIAS, tope=ML_MAX_CLIENTES)
        paso = max(1, math.ceil(len(filas) / ML_PUNTOS_DISPERSION))
        muestra = filas[::paso][:ML_PUNTOS_DISPERSION]
        return [
            PuntoDispersion(
                segmento_id=segmentos.asignar_segmento(modelo, f["ultima_compra"], f["frecuencia"], f["monto_total"], hasta),
                frecuencia=int(f["frecuencia"]),
                monto=float(f["monto_total"]),
            )
            for f in muestra
        ]

    # -- Anomalías ---------------------------------------------------------------------------------------------------------------

    def anomalias(self, db: Session, usuario_id: int, dias: int = DIAS_ANOMALIAS_DEFECTO, *, hoy: dt.date | None = None) -> AnomaliasRespuesta:
        """Los días de ventas inusuales por sucursal de los últimos `dias` (7..365) hasta ayer. Se leen también las 8
        semanas anteriores a la ventana: el nivel esperado de cada sucursal se calcula con ellas."""
        self._exigir_acceso(db, usuario_id)
        if isinstance(dias, bool) or not isinstance(dias, int) or not anomalias.DIAS_DETECCION_MIN <= dias <= anomalias.DIAS_DETECCION_MAX:
            raise DomainError(f"Los días a revisar van de {anomalias.DIAS_DETECCION_MIN} a {anomalias.DIAS_DETECCION_MAX}")
        hoy = hoy or hoy_utc()
        estado, _fila, artefacto = self._cargar(db, TIPO_ANOMALIAS, hoy)
        hasta = hoy - dt.timedelta(days=1)
        filas = comercial_politicas.reporte_ventas_serie_diaria(
            db, ParametrosPeriodo(desde=hasta - dt.timedelta(days=dias + 56), hasta=hasta), desglose=("sucursal",)
        )
        detectadas = anomalias.detectar_anomalias(artefacto, filas, hasta, dias)
        lista = [
            AnomaliaVenta(
                fecha=a.fecha, sucursal_id=a.sucursal_id, sucursal=a.sucursal, total_ventas=a.total_ventas, esperado=a.esperado,
                desviacion_pct=a.desviacion_pct, severidad=a.severidad,
            )
            for a in detectadas
        ]  # fmt: skip
        return AnomaliasRespuesta(
            modelo=estado,
            dias=dias,
            desde=hasta - dt.timedelta(days=dias - 1),
            hasta=hasta,
            anomalias=lista,
            total=len(lista),
            fuertes=sum(1 for a in lista if a.severidad == "fuerte"),
            supuestos=list(artefacto.get("supuestos", anomalias.SUPUESTOS)),
            interpretacion=inteligencia_politicas.interpretar_anomalias(
                [{"sucursal": a.sucursal, "desviacion_pct": a.desviacion_pct, "severidad": a.severidad} for a in lista], dias
            ),
            grafico_sugerido=GraficoSugerido(tipo="tabla"),
            avisos=self._avisos_de(estado),
        )

    # -- Reposición ---------------------------------------------------------------------------------------------------------------

    def reposicion(self, db: Session, usuario_id: int, semanas: int = HORIZONTE_POR_DEFECTO, *, hoy: dt.date | None = None) -> ReposicionRespuesta:
        """Cruza la demanda prevista por categoría con el stock disponible actual (toda la empresa, depósito incluido).
        Es orientativa: es por categoría, no descuenta órdenes de compra en camino ni transferencias."""
        self._exigir_acceso(db, usuario_id)
        if isinstance(semanas, bool) or not isinstance(semanas, int) or not reposicion.MIN_SEMANAS <= semanas <= reposicion.MAX_SEMANAS:
            raise DomainError(f"Las semanas van de {reposicion.MIN_SEMANAS} a {reposicion.MAX_SEMANAS}")
        hoy = hoy or hoy_utc()
        estado, _fila, artefacto = self._cargar(db, TIPO_DEMANDA, hoy)
        por_categoria: dict[int, list[int]] = {}
        for p in demanda.predecir_demanda(artefacto, semanas):
            por_categoria.setdefault(p.categoria_id, []).append(p.unidades)
        categorias = [
            {"categoria_id": c["id"], "categoria": c["nombre"], "unidades_semanales": por_categoria[c["id"]]} for c in artefacto["categorias"]
        ]
        disponible = {c["id"]: self._disponible_de(db, c["id"]) for c in artefacto["categorias"]}
        calculados = reposicion.calcular_reposicion(categorias, disponible, semanas)
        items = [
            ItemReposicion(
                categoria_id=i.categoria_id, categoria=i.categoria, disponible=i.disponible,
                demanda_semanal_promedio=i.demanda_semanal_promedio, semanas_cobertura=i.semanas_cobertura,
                agotado_en_semana=i.agotado_en_semana, estado=i.estado, sugerencia_unidades=i.sugerencia_unidades,
            )
            for i in calculados
        ]  # fmt: skip
        return ReposicionRespuesta(
            modelo=estado,
            semanas=semanas,
            items=items,
            criticos=sum(1 for i in items if i.estado == "critico"),
            supuestos=list(reposicion.SUPUESTOS),
            interpretacion=inteligencia_politicas.interpretar_reposicion(
                [{"categoria": i.categoria, "estado": i.estado, "agotado_en_semana": i.agotado_en_semana, "sugerencia_unidades": i.sugerencia_unidades} for i in items],
                semanas,
            ),
            grafico_sugerido=GraficoSugerido(tipo="barras", eje_x="categoria", eje_y="semanas_cobertura"),
            avisos=self._avisos_de(estado),
        )

    @staticmethod
    def _disponible_de(db: Session, categoria_id: int) -> int:
        """Unidades disponibles de una categoría (por id exacto, sin subcategorías: igual que la serie de ventas) en todas
        las sucursales de la empresa, leídas con la política de existencias del catálogo."""
        filas = catalogo_politicas.reporte_existencias_por_producto(db, None, [categoria_id], None, LIMITE_PRODUCTOS_DE_EXISTENCIAS)
        return max(sum(int(f["disponible"]) for f in filas), 0)

    # -- Panel --------------------------------------------------------------------------------------------------------------------

    def panel(self, db: Session, usuario_id: int, *, hoy: dt.date | None = None) -> PanelAnalitico:
        """Estado + KPIs + los bloques de los modelos que están usables. Un modelo sin entrenar u obsoleto no tumba el
        panel: su bloque va en None y el motivo en `avisos`."""
        hoy = hoy or hoy_utc()
        estado = self.estado(db, usuario_id, hoy=hoy)
        avisos: list[str] = []
        bloques: dict[str, Any] = {}
        consultas = (
            ("demanda", "Demanda", lambda: self.demanda(db, usuario_id, hoy=hoy)),
            ("segmentos", "Segmentos", lambda: self.segmentos(db, usuario_id, hoy=hoy)),
            ("anomalias", "Anomalías", lambda: self.anomalias(db, usuario_id, DIAS_ANOMALIAS_PANEL, hoy=hoy)),
            ("reposicion", "Reposición", lambda: self.reposicion(db, usuario_id, hoy=hoy)),
        )
        for clave, titulo, consulta in consultas:
            try:
                bloques[clave] = consulta()
            except ErrorFuncional as exc:
                if exc.codigo not in ("modelo_no_entrenado", "modelo_obsoleto"):
                    raise
                bloques[clave] = None
                avisos.append(f"{titulo}: {exc.mensaje}")
        return PanelAnalitico(
            estado=estado,
            kpis=self._kpis(bloques["demanda"], bloques["segmentos"], bloques["anomalias"], bloques["reposicion"]),
            demanda=bloques["demanda"],
            segmentos=bloques["segmentos"],
            anomalias=bloques["anomalias"],
            reposicion=bloques["reposicion"],
            avisos=avisos,
        )

    @staticmethod
    def _kpis(
        dem: DemandaRespuesta | None, seg: SegmentosRespuesta | None, ano: AnomaliasRespuesta | None = None, rep: ReposicionRespuesta | None = None
    ) -> list[KpiAnalitico]:
        kpis: list[KpiAnalitico] = []
        if dem is not None:
            primera = dem.total_empresa.prediccion[0].valor
            variacion = dem.total_empresa.variacion_pct_vs_ultimas_semanas
            kpis.append(
                KpiAnalitico(
                    clave="demanda_proxima_semana", titulo="Demanda prevista de la próxima semana", valor=primera, unidad="unidades",
                    interpretacion=(
                        None if variacion is None else f"Es {abs(variacion):.1f}% {'más' if variacion >= 0 else 'menos'} que el promedio de las últimas semanas."
                    ),
                )
            )
            mejora = dem.metricas.mejora_mae_pct
            kpis.append(
                KpiAnalitico(
                    clave="mejora_modelo", titulo="Mejora del modelo frente al promedio móvil", valor=_redondear(mejora), unidad="%",
                    interpretacion="Cuánto se equivoca menos el modelo que simplemente promediar las últimas 4 semanas.",
                )
            )  # fmt: skip
        if seg is not None:
            campeones = next((s for s in seg.segmentos if s.nombre.startswith("Campeones")), None)
            en_riesgo = sum(s.clientes for s in seg.segmentos if s.nombre in NOMBRES_EN_RIESGO)
            kpis.append(KpiAnalitico(clave="clientes_segmentados", titulo="Clientes segmentados", valor=seg.clientes_segmentados, unidad="clientes"))
            if campeones is not None:
                kpis.append(
                    KpiAnalitico(
                        clave="pct_campeones", titulo="Clientes Campeones", valor=campeones.porcentaje_clientes, unidad="%",
                        interpretacion=f"Generan el {campeones.porcentaje_monto:.1f}% de las ventas de los clientes segmentados.",
                    )
                )  # fmt: skip
            kpis.append(
                KpiAnalitico(
                    clave="clientes_en_riesgo", titulo="Clientes en riesgo de perderse", valor=en_riesgo, unidad="clientes",
                    interpretacion="Compraban bien y hace tiempo que no vuelven: conviene contactarlos.",
                )
            )  # fmt: skip
        if ano is not None:
            kpis.append(
                KpiAnalitico(
                    clave="anomalias_30_dias", titulo="Días de ventas inusuales (últimos 30 días)", valor=ano.total, unidad="días",
                    interpretacion=f"{ano.fuertes} de ellos son fuertes." if ano.total else "Todas las sucursales vendieron dentro de lo esperado.",
                )
            )  # fmt: skip
        if rep is not None:
            kpis.append(
                KpiAnalitico(
                    clave="categorias_criticas", titulo="Categorías en estado crítico de reposición", valor=rep.criticos, unidad="categorías",
                    interpretacion="Tienen menos de 2 semanas de cobertura con la demanda prevista." if rep.criticos else "Ninguna categoría está por agotarse.",
                )
            )  # fmt: skip
        return kpis
