import datetime as dt
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.core.auditoria import ContextoAuditoria, obtener_contexto_auditoria
from app.core.database import get_db
from app.core.deps import ParametrosPaginacion, parametros_paginacion
from app.core.permisos import PERMISO_SINCRONIZACION_RESOLVER, PERMISO_SINCRONIZAR
from app.core.planes import FUNC_OPERACION_OFFLINE, exigir_funcionalidad
from app.core.security import get_current_user, require_permission
from app.sincronizacion import politicas
from app.sincronizacion.casos_uso.cu25_sincronizar_operaciones_offline import (
    ConsultarOperaciones,
    DescargarPaquete,
    ProcesarLote,
    ResolverConflicto,
)
from app.sincronizacion.schemas import (
    FiltrosOperaciones,
    LoteEntrada,
    LoteRespuesta,
    OperacionSyncDetalle,
    OperacionSyncPagina,
    PaqueteCatalogo,
    PaqueteClientes,
    PaqueteManifiesto,
    PaqueteStock,
    ResolverEntrada,
)

cu_procesar_lote = ProcesarLote()
cu_consultar_operaciones = ConsultarOperaciones()
cu_resolver_conflicto = ResolverConflicto()
cu_descargar_paquete = DescargarPaquete()

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


# ---- paquete de descarga (E08) ----
# Plan con operación sin conexión y suscripción activa (aquí SÍ se responde 403: no hay nada que guardar).
# Cada respuesta lleva ETag (huella del contenido sin `generado_en`): con `If-None-Match` igual, 304 sin cuerpo.

_PAQUETE = [Depends(exigir_funcionalidad(FUNC_OPERACION_OFFLINE)), Depends(require_permission(PERMISO_SINCRONIZAR))]
_CABECERA_CACHE = "private, max-age=0, must-revalidate"


def _coincide(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidatos = {parte.strip().removeprefix("W/").strip('"') for parte in if_none_match.split(",")}
    return etag in candidatos or "*" in candidatos


def _con_etag(paquete, if_none_match: str | None, response: Response):
    """El paquete con su ETag y `Cache-Control`, o un 304 vacío si el cliente ya tiene esta versión."""
    etag = politicas.calcular_etag(paquete)
    cabeceras = {"ETag": f'"{etag}"', "Cache-Control": _CABECERA_CACHE}
    if _coincide(if_none_match, etag):
        return Response(status_code=304, headers=cabeceras)
    response.headers.update(cabeceras)
    return paquete


@sincronizacion_router.get("/paquete", response_model=PaqueteManifiesto, dependencies=_PAQUETE)
def paquete_manifiesto(
    response: Response,
    sucursal_id: int | None = Query(default=None, ge=1),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaqueteManifiesto:
    """Manifiesto: empresa, sucursales autorizadas con horario, referencias, promociones y reglas.
    Sin ETag: es chico y trae datos que cambian por día."""
    response.headers["Cache-Control"] = _CABECERA_CACHE
    return cu_descargar_paquete.manifiesto(db, usuario.id, sucursal_id)


@sincronizacion_router.get("/paquete/catalogo", response_model=PaqueteCatalogo, dependencies=_PAQUETE)
def paquete_catalogo(
    response: Response,
    desde_id: int = Query(default=0, ge=0),
    limite: int = Query(default=200, ge=1, le=500),
    if_none_match: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    return _con_etag(cu_descargar_paquete.catalogo(db, desde_id, limite), if_none_match, response)


@sincronizacion_router.get("/paquete/stock", response_model=PaqueteStock, dependencies=_PAQUETE)
def paquete_stock(
    response: Response,
    sucursal_id: int | None = Query(default=None, ge=1),
    desde: dt.datetime | None = Query(default=None),
    desde_variante_id: int = Query(default=0, ge=0),
    limite: int = Query(default=500, ge=1, le=1000),
    if_none_match: str | None = Header(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    paquete = cu_descargar_paquete.stock(db, usuario.id, sucursal_id, desde, desde_variante_id, limite)
    return _con_etag(paquete, if_none_match, response)


@sincronizacion_router.get("/paquete/clientes", response_model=PaqueteClientes, dependencies=_PAQUETE)
def paquete_clientes(
    response: Response,
    desde_id: int = Query(default=0, ge=0),
    limite: int = Query(default=500, ge=1, le=1000),
    if_none_match: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    return _con_etag(cu_descargar_paquete.clientes(db, desde_id, limite), if_none_match, response)


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


@sincronizacion_router.post(
    "/operaciones/{operacion_id}/resolver",
    response_model=OperacionSyncDetalle,
    dependencies=[
        Depends(exigir_funcionalidad(FUNC_OPERACION_OFFLINE)),
        Depends(require_permission(PERMISO_SINCRONIZACION_RESOLVER)),
    ],
)
def resolver_conflicto(
    operacion_id: uuid.UUID,
    datos: ResolverEntrada,
    usuario=Depends(get_current_user),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
    db: Session = Depends(get_db),
) -> OperacionSyncDetalle:
    return cu_resolver_conflicto.ejecutar(db, usuario.id, operacion_id, datos, contexto)


routers = [sincronizacion_router]
