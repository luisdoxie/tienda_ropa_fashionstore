from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.inteligencia.models import ConsultaVoz, HistorialNavegacion, Recomendacion

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


# ---- Reportes ----
# Los reportes no consultan ninguna tabla ni vista directamente: toda su
# lectura pasa por las `politicas` y los casos de uso de `comercial` (ventas y
# reservas) y de `catalogo` (inventario y probador). Este bloque existe por
# consistencia con la estructura del paquete y no define ningún acceso a datos
# propio.
