from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import ParametrosPeriodo, periodo_reportes
from app.core.permisos import PERMISO_REPORTES_VER
from app.core.rate_limit import limiter
from app.core.security import get_current_user, get_current_user_opcional, require_permission
from app.inteligencia.casos_uso.cu20_recomendar_productos import RecomendarProductos
from app.inteligencia.casos_uso.cu21_buscar_prendas_por_voz import BuscarComandoVoz
from app.inteligencia.casos_uso.cu22_consultar_reportes_indicadores import (
    ConsultarReportesVentasInventario,
    VisualizarDashboardIndicadores,
)
from app.inteligencia.casos_uso.cu23_generar_reportes_con_ia import GenerarReporteComandoVoz
from app.inteligencia.politicas import registrar_evento
from app.inteligencia.schemas import (
    DashboardRespuesta,
    EventoCrear,
    RecomendacionesRespuesta,
    ReporteInventarioRespuesta,
    ReporteReservasRespuesta,
    ReporteVentasRespuesta,
    ReporteVozRequest,
    ReporteVozRespuesta,
    VozRequest,
    VozRespuesta,
)

# ---- Inteligencia ----

cu_recomendar_productos = RecomendarProductos()
cu_buscar_voz = BuscarComandoVoz()
cu_reporte_voz = GenerarReporteComandoVoz()

inteligencia_router = APIRouter(prefix="/api/v1/ia", tags=["inteligencia"])


@inteligencia_router.post("/voz", response_model=VozRespuesta)
@limiter.limit("15/minute")
def buscar_por_voz(
    request: Request,
    datos: VozRequest,
    usuario=Depends(get_current_user_opcional),
    db: Session = Depends(get_db),
) -> VozRespuesta:
    return cu_buscar_voz.ejecutar(db, datos.texto, usuario)


@inteligencia_router.post("/recomendaciones", response_model=RecomendacionesRespuesta)
@limiter.limit("20/minute")
def obtener_recomendaciones(
    request: Request,
    excluir_producto_id: int | None = None,
    usuario=Depends(get_current_user_opcional),
    db: Session = Depends(get_db),
) -> RecomendacionesRespuesta:
    return cu_recomendar_productos.ejecutar(db, usuario, excluir_producto_id)


@inteligencia_router.post("/eventos", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
def registrar_evento_endpoint(
    request: Request,
    datos: EventoCrear,
    usuario=Depends(get_current_user_opcional),
    db: Session = Depends(get_db),
) -> dict:
    registrar_evento(db, datos, usuario)
    return {"registrado": True}


@inteligencia_router.post(
    "/reporte-voz", response_model=ReporteVozRespuesta, dependencies=[Depends(require_permission(PERMISO_REPORTES_VER))]
)
@limiter.limit("15/minute")
def generar_reporte_por_voz(
    request: Request, datos: ReporteVozRequest, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReporteVozRespuesta:
    return cu_reporte_voz.ejecutar(db, usuario.id, datos.texto)


_routers_inteligencia = [inteligencia_router]


# ---- Reportes ----

ver_requerido = Depends(require_permission(PERMISO_REPORTES_VER))

cu_consultar_reportes = ConsultarReportesVentasInventario()
cu_dashboard = VisualizarDashboardIndicadores()

reportes_router = APIRouter(prefix="/api/v1/reportes", tags=["reportes"], dependencies=[ver_requerido])


@reportes_router.get("/ventas", response_model=ReporteVentasRespuesta)
def reporte_ventas(
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    sucursal_id: int | None = Query(default=None),
    categoria_id: int | None = Query(default=None),
    canal: str | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReporteVentasRespuesta:
    return cu_consultar_reportes.ventas(db, usuario.id, periodo, sucursal_id, categoria_id, canal)


@reportes_router.get("/inventario", response_model=ReporteInventarioRespuesta)
def reporte_inventario(
    sucursal_id: int | None = Query(default=None), usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReporteInventarioRespuesta:
    return cu_consultar_reportes.inventario(db, usuario.id, sucursal_id)


@reportes_router.get("/reservas", response_model=ReporteReservasRespuesta)
def reporte_reservas(
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    sucursal_id: int | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReporteReservasRespuesta:
    return cu_consultar_reportes.reservas(db, usuario.id, periodo, sucursal_id)


@reportes_router.get("/dashboard", response_model=DashboardRespuesta)
def reporte_dashboard(
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    sucursal_id: int | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardRespuesta:
    return cu_dashboard.ejecutar(db, usuario.id, periodo, sucursal_id)


_routers_reportes = [reportes_router]

# ---- /api/v1/public/{codigo} (tienda pública por empresa) --------------------------
# Los MISMOS handlers públicos de /ia (voz, recomendaciones, eventos) bajo el
# código de la tienda (D02, D10). La empresa la fija `contexto_empresa`
# (core/tenant.py) desde el código de la ruta; `_codigo_tienda` solo documenta el
# parámetro en OpenAPI. No se copian handlers: los `@limiter.limit` viajan con la
# función.


def _codigo_tienda(codigo: str) -> str:
    return codigo


publico_tienda_router = APIRouter(
    prefix="/api/v1/public/{codigo}", tags=["tienda-publica"], dependencies=[Depends(_codigo_tienda)]
)
publico_tienda_router.add_api_route(
    "/ia/voz", buscar_por_voz, methods=["POST"], response_model=VozRespuesta
)
publico_tienda_router.add_api_route(
    "/ia/recomendaciones", obtener_recomendaciones, methods=["POST"], response_model=RecomendacionesRespuesta
)
publico_tienda_router.add_api_route(
    "/ia/eventos", registrar_evento_endpoint, methods=["POST"], status_code=status.HTTP_201_CREATED
)


routers = _routers_inteligencia + _routers_reportes + [publico_tienda_router]
