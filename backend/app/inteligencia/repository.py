import datetime as dt
import hashlib
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, undefer

from app.core.exceptions import ConflictoError, DomainError
from app.core.repository import confirmar
from app.inteligencia.ml.limites import ML_MAX_ARTEFACTO_BYTES, ML_VERSIONES_CON_ARTEFACTO
from app.inteligencia.models import TIPOS_MODELO_ML, ConsultaVoz, HistorialNavegacion, ModeloML, Recomendacion

# ---- Inteligencia ----


class ConsultaVozRepository:
    """Sin `activo`: es un log de auditoría, nunca se desactiva ni se lista
    de vuelta desde una pantalla administrable (igual criterio que
    NotificacionRepository en plataforma/repository.py)."""

    def crear(
        self,
        db: Session,
        cliente_id: int | None,
        texto_transcrito: str,
        filtros_json: dict | None,
        cantidad_resultados: int,
    ) -> ConsultaVoz:
        consulta = ConsultaVoz(
            cliente_id=cliente_id,
            texto_transcrito=texto_transcrito,
            filtros_json=filtros_json,
            cantidad_resultados=cantidad_resultados,
        )
        db.add(consulta)
        db.commit()
        db.refresh(consulta)
        return consulta


class HistorialNavegacionRepository:
    """Mismo criterio que ConsultaVozRepository: log de auditoría, sin
    `activo`, nunca se edita ni se lista de vuelta en una pantalla
    administrable -- solo lo consume el propio recomendador."""

    def crear(
        self,
        db: Session,
        cliente_id: int | None,
        sesion_anonima: str | None,
        producto_id: int | None,
        variante_id: int | None,
        tipo_evento: str,
    ) -> HistorialNavegacion:
        evento = HistorialNavegacion(
            cliente_id=cliente_id,
            sesion_anonima=sesion_anonima,
            producto_id=producto_id,
            variante_id=variante_id,
            tipo_evento=tipo_evento,
        )
        db.add(evento)
        db.commit()
        db.refresh(evento)
        return evento

    def listar_reciente_por_cliente(self, db: Session, cliente_id: int, limite: int) -> list[HistorialNavegacion]:
        consulta = (
            select(HistorialNavegacion)
            .where(HistorialNavegacion.cliente_id == cliente_id)
            .order_by(HistorialNavegacion.creado_en.desc())
            .limit(limite)
        )
        return list(db.scalars(consulta))


class RecomendacionRepository:
    """Log histórico: cada corrida del recomendador inserta una fila por
    recomendación final, nunca sobreescribe ni borra las anteriores."""

    def crear_lote(
        self, db: Session, cliente_id: int, items: list[tuple[int, Decimal | None, str]]
    ) -> list[Recomendacion]:
        filas = [
            Recomendacion(cliente_id=cliente_id, variante_id=variante_id, puntaje=puntaje, motivo=motivo)
            for variante_id, puntaje, motivo in items
        ]
        db.add_all(filas)
        db.commit()
        for fila in filas:
            db.refresh(fila)
        return filas


# ---- Analítica ML ----


class ModeloMLRepository:
    """Versiones de los modelos entrenados de la empresa. Nunca recibe `empresa_id`: el alcance de
    empresa lo pone `core/tenant` (filtra toda consulta y rellena el alta), así que el modelo de una
    empresa no aparece en otra y entrenar sin empresa en la sesión falla cerrado. El artefacto es
    `deferred`: solo se trae pidiéndolo (`con_artefacto=True`)."""

    def _consulta(self, tipo: str, con_artefacto: bool):
        consulta = select(ModeloML).where(ModeloML.tipo == tipo)
        return consulta.options(undefer(ModeloML.artefacto)) if con_artefacto else consulta

    def obtener_activo(self, db: Session, tipo: str, *, con_artefacto: bool = False) -> ModeloML | None:
        return db.scalars(self._consulta(tipo, con_artefacto).where(ModeloML.activo.is_(True))).first()

    def obtener_version(
        self, db: Session, tipo: str, version: int, *, con_artefacto: bool = False
    ) -> ModeloML | None:
        return db.scalars(self._consulta(tipo, con_artefacto).where(ModeloML.version == version)).first()

    def listar_versiones(self, db: Session, tipo: str) -> list[ModeloML]:
        """De la más nueva a la más vieja, SIN el artefacto."""
        return list(db.scalars(self._consulta(tipo, False).order_by(ModeloML.version.desc())))

    def ultima_version(self, db: Session, tipo: str) -> int:
        return db.scalar(select(func.max(ModeloML.version)).where(ModeloML.tipo == tipo)) or 0

    def guardar_nueva_version(
        self,
        db: Session,
        tipo: str,
        *,
        metricas: dict,
        parametros: dict,
        artefacto: bytes | None,
        filas_entrenamiento: int,
        datos_desde: dt.date | None = None,
        datos_hasta: dt.date | None = None,
        entrenado_por: int | None = None,
        commit: bool = True,
    ) -> ModeloML:
        """Crea la versión siguiente, la deja vigente y desactiva la anterior; después poda las viejas.
        Todo en un SAVEPOINT: si la base rechaza algo (por ejemplo, dos entrenamientos que escogieron
        la misma versión), solo se revierte esto y se lanza ConflictoError. El hash y el tamaño los
        calcula el repositorio a partir de los bytes, así nunca quedan desalineados. `commit=False`
        deja la transacción al llamador (el caso de uso la cierra junto con la bitácora)."""
        if tipo not in TIPOS_MODELO_ML:
            raise DomainError(f"Tipo de modelo no soportado: {tipo}")
        if artefacto is not None and len(artefacto) > ML_MAX_ARTEFACTO_BYTES:
            raise DomainError(
                f"El modelo serializado pesa {len(artefacto)} bytes y el máximo es {ML_MAX_ARTEFACTO_BYTES}"
            )
        sha256 = hashlib.sha256(artefacto).hexdigest() if artefacto is not None else None
        try:
            with db.begin_nested():
                vigente = self.obtener_activo(db, tipo)
                if vigente is not None:
                    vigente.activo = False
                    db.flush()  # antes del alta, para no chocar con el índice parcial único
                modelo = ModeloML(
                    tipo=tipo,
                    version=self.ultima_version(db, tipo) + 1,
                    activo=True,
                    metricas=metricas,
                    parametros=parametros,
                    artefacto=artefacto,
                    artefacto_sha256=sha256,
                    artefacto_bytes=len(artefacto) if artefacto is not None else None,
                    filas_entrenamiento=filas_entrenamiento,
                    datos_desde=datos_desde,
                    datos_hasta=datos_hasta,
                    entrenado_por=entrenado_por,
                )
                db.add(modelo)
                db.flush()
        except IntegrityError as exc:
            raise ConflictoError("Otro entrenamiento guardó una versión de este modelo al mismo tiempo") from exc
        self.podar(db, tipo)
        confirmar(db, commit)
        return modelo

    def podar(self, db: Session, tipo: str, conservar: int = ML_VERSIONES_CON_ARTEFACTO) -> int:
        """Deja el artefacto solo en las `conservar` versiones más nuevas. Las demás quedan con
        `artefacto` NULL pero conservan sus métricas y su hash (no hay DELETE físico). Devuelve
        cuántas podó."""
        con_artefacto = db.scalars(
            select(ModeloML)
            .where(ModeloML.tipo == tipo, ModeloML.artefacto.is_not(None))
            .order_by(ModeloML.version.desc())
            .offset(conservar)
        ).all()
        for modelo in con_artefacto:
            modelo.artefacto = None
        db.flush()
        return len(con_artefacto)


# ---- Reportes ----
# Los reportes no consultan ninguna tabla ni vista directamente: toda su
# lectura pasa por las `politicas` y los casos de uso de `comercial` (ventas y
# reservas) y de `catalogo` (inventario y probador). Este bloque existe por
# consistencia con la estructura del paquete y no define ningún acceso a datos
# propio.
