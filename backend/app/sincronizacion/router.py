import datetime as dt
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auditoria import ContextoAuditoria, obtener_contexto_auditoria
from app.core.database import get_db
from app.core.deps import ParametrosPaginacion, parametros_paginacion
from app.core.permisos import PERMISO_SINCRONIZAR
from app.core.planes import FUNC_OPERACION_OFFLINE, exigir_funcionalidad
from app.core.security import get_current_user, require_permission
from app.sincronizacion.casos_uso.cu25_sincronizar_operaciones_offline import ConsultarOperaciones, ProcesarLote
from app.sincronizacion.schemas import (
    FiltrosOperaciones,
    LoteEntrada,
    LoteRespuesta,
    OperacionSyncDetalle,
    OperacionSyncPagina,
)

cu_procesar_lote = ProcesarLote()
cu_consultar_operaciones = ConsultarOperaciones()

# ---- /api/v1/sincronizacion ---------------------------------------------------------------------

sincronizacion_router = APIRouter(prefix="/api/v1/sincronizacion", tags=["sincronizacion"])


# El POST NO usa `exigir_funcionalidad` ni la comprobación de suscripción de `get_current_user`
# (está en RUTAS_SIN_SUSCRIPCION): así puede REGISTRAR el rechazo de cada operación con su
# motivo (suscripcion_no_activa, plan_sin_operacion_offline), como pide D16.
@sincronizacion_router.post(
    "/lote", response_model=LoteRespuesta, dependencies=[Depends(require_permission(PERMISO_SINCRONIZAR))]
)
def sincronizar_lote(
    lote: LoteEntrada,
    usuario=Depends(get_current_user),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
    db: Session = Depends(get_db),
) -> LoteRespuesta:
    return cu_procesar_lote.ejecutar(db, usuario.id, lote, contexto)


def _filtros(
    estado: Literal["confirmada", "rechazada", "en_conflicto"] | None = None,
    tipo: Literal["venta_contado", "reserva"] | None = None,
    sucursal_id: int | None = None,
    usuario_id: int | None = None,
    desde: dt.date | None = Query(default=None),
    hasta: dt.date | None = Query(default=None),
) -> FiltrosOperaciones:
    return FiltrosOperaciones(
        estado=estado, tipo=tipo, sucursal_id=sucursal_id, usuario_id=usuario_id, desde=desde, hasta=hasta
    )


@sincronizacion_router.get(
    "/operaciones",
    response_model=OperacionSyncPagina,
    dependencies=[Depends(exigir_funcionalidad(FUNC_OPERACION_OFFLINE)), Depends(require_permission(PERMISO_SINCRONIZAR))],
)
def listar_operaciones(
    filtros: FiltrosOperaciones = Depends(_filtros),
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OperacionSyncPagina:
    return cu_consultar_operaciones.listar(db, usuario.id, filtros, paginacion)


@sincronizacion_router.get(
    "/operaciones/{operacion_id}",
    response_model=OperacionSyncDetalle,
    dependencies=[Depends(exigir_funcionalidad(FUNC_OPERACION_OFFLINE)), Depends(require_permission(PERMISO_SINCRONIZAR))],
)
def obtener_operacion(
    operacion_id: uuid.UUID, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> OperacionSyncDetalle:
    return cu_consultar_operaciones.obtener(db, usuario.id, operacion_id)


routers = [sincronizacion_router]
