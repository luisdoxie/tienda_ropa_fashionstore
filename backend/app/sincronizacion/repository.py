import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.sincronizacion.models import OperacionSync


class OperacionSyncRepository:
    """No hereda `CRUDBase`: es un registro técnico, sin `activo`, que no se edita
    desde la API ni se borra. El filtro automático por empresa aplica a todas las
    consultas (la tabla lleva `EmpresaMixin`)."""

    def obtener_por_operacion(self, db: Session, operacion_id: uuid.UUID) -> OperacionSync | None:
        return db.scalar(select(OperacionSync).where(OperacionSync.operacion_id == operacion_id))

    def obtener_bloqueada(self, db: Session, operacion_id: uuid.UUID) -> OperacionSync | None:
        """La operación con SELECT ... FOR UPDATE (solo PostgreSQL; en SQLite se omite) y
        releída (`populate_existing`): dos encargados que la resuelven a la vez se ponen en fila
        y el segundo ve el estado que dejó el primero."""
        consulta = select(OperacionSync).where(OperacionSync.operacion_id == operacion_id)
        if db.get_bind().dialect.name == "postgresql":
            consulta = consulta.with_for_update()
        return db.scalar(consulta.execution_options(populate_existing=True))

    def reservar_clave(self, db: Session, **campos) -> OperacionSync | None:
        """Inserta la operación en estado `en_proceso` dentro de un SAVEPOINT. Si la clave
        (empresa, operación) ya existía devuelve `None`: es un reenvío. En PostgreSQL, si
        OTRA transacción está insertando la misma clave, este INSERT espera a que termine y
        luego cae en el error de unicidad: así dos lotes simultáneos con la misma operación
        no la procesan dos veces.

        Un error de integridad que NO sea de esa clave (una FK, un CHECK) no se toma por
        reenvío: si después de fallar la fila no existe, el error se propaga."""
        fila = OperacionSync(**campos)
        try:
            with db.begin_nested():
                db.add(fila)
                db.flush()
        except IntegrityError:
            if self.obtener_por_operacion(db, campos["operacion_id"]) is None:
                raise
            return None
        return fila

    def sumar_intento(self, db: Session, fila: OperacionSync) -> None:
        """`intentos = intentos + 1` en SQL (sin carrera entre reenvíos simultáneos)."""
        db.execute(
            update(OperacionSync)
            .where(OperacionSync.id == fila.id)
            .values(intentos=OperacionSync.intentos + 1)
            .execution_options(synchronize_session=False)
        )
        db.refresh(fila)

    def listar(
        self,
        db: Session,
        *,
        usuario_id: int | None,
        sucursal_id: int | None,
        estado: str | None,
        tipo: str | None,
        desde,
        hasta,
        offset: int,
        limite: int,
    ) -> tuple[list[OperacionSync], int]:
        condiciones = []
        if usuario_id is not None:
            condiciones.append(OperacionSync.usuario_id == usuario_id)
        if sucursal_id is not None:
            condiciones.append(OperacionSync.sucursal_id == sucursal_id)
        if estado is not None:
            condiciones.append(OperacionSync.estado == estado)
        if tipo is not None:
            condiciones.append(OperacionSync.tipo == tipo)
        if desde is not None:
            condiciones.append(OperacionSync.recibida_en >= desde)
        if hasta is not None:
            condiciones.append(OperacionSync.recibida_en < hasta)
        total = db.scalar(select(func.count()).select_from(OperacionSync).where(*condiciones)) or 0
        filas = db.scalars(
            select(OperacionSync)
            .where(*condiciones)
            .order_by(OperacionSync.recibida_en.desc(), OperacionSync.id.desc())
            .offset(offset)
            .limit(limite)
        )
        return list(filas), total
