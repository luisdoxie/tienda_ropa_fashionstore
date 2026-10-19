"""CU-22 — Consultar reportes e indicadores

Absorbe los antiguos CU-33 (Consultar reportes de ventas e inventario) y
CU-34 (Visualizar indicadores empresariales).

Actor: Administrador, Encargado de sucursal.
Precondición: sesión con el permiso reportes.ver.
Postcondición: se consultan los reportes de ventas, inventario y reservas
de un período y se ven en un panel los indicadores del negocio del período
elegido: ventas, transacciones, ticket promedio, margen bruto, productos
más vendidos, ventas por canal y por sucursal, valor total del inventario,
variantes bajo mínimo, reservas por estado, conversión de reservas a ventas
y uso del probador virtual.

Caso de uso COMPUESTO: agrupa los reportes (ventas, inventario, reservas) y
el dashboard de indicadores, cada uno con su propia clase. Este caso de uso
SOLO LEE: no escribe en ninguna tabla. Un encargado (sin alcance global) solo
ve su sucursal: ver plataforma.politicas.acotar_sucursal."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.catalogo.casos_uso.cu09_gestionar_inventario import ConsultarInventarioGlobal
from app.catalogo.politicas import reporte_uso_probador
from app.comercial import politicas as comercial_politicas
from app.comercial.politicas import reporte_reservas_por_estado
from app.core.deps import ParametrosPeriodo
from app.inteligencia.politicas import tasa_conversion, ticket_promedio
from app.inteligencia.schemas import (
    DashboardRespuesta,
    FilaReservasPorEstado,
    FilaTopProducto,
    FilaUsoProbador,
    FilaVentasDetalle,
    FilaVentasPorCanal,
    FilaVentasPorSucursal,
    ReporteInventarioRespuesta,
    ReporteReservasRespuesta,
    ReporteVentasRespuesta,
    ResumenVentas,
)
from app.plataforma import politicas as plataforma_politicas

_CERO = Decimal("0")


# ---- Reportes de ventas, inventario y reservas (antiguo CU-33) ----


class ConsultarReportesVentasInventario:
    def __init__(self) -> None:
        self._inventario = ConsultarInventarioGlobal()

    def ventas(
        self,
        db: Session,
        usuario_id: int,
        periodo: ParametrosPeriodo,
        sucursal_id: int | None = None,
        categoria_id: int | None = None,
        canal: str | None = None,
    ) -> ReporteVentasRespuesta:
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        resumen_dict = comercial_politicas.reporte_ventas_resumen(db, periodo, sucursal_id, categoria_id, canal)
        resumen = ResumenVentas(
            transacciones=resumen_dict["transacciones"],
            total_ventas=resumen_dict["total_ventas"],
            margen_bruto=resumen_dict["margen_bruto"],
            ticket_promedio=ticket_promedio(resumen_dict["total_ventas"], resumen_dict["transacciones"]),
        )
        return ReporteVentasRespuesta(
            resumen=resumen,
            top_productos=[
                FilaTopProducto(**fila)
                for fila in comercial_politicas.reporte_ventas_top_productos(db, periodo, sucursal_id, categoria_id, canal)
            ],
            por_canal=[
                FilaVentasPorCanal(**fila)
                for fila in comercial_politicas.reporte_ventas_por_canal(db, periodo, sucursal_id, categoria_id)
            ],
            por_sucursal=[
                FilaVentasPorSucursal(**fila)
                for fila in comercial_politicas.reporte_ventas_por_sucursal(db, periodo, categoria_id, canal, sucursal_id)
            ],
            detalle=[
                FilaVentasDetalle(**fila)
                for fila in comercial_politicas.reporte_ventas_detalle(db, periodo, sucursal_id, categoria_id, canal)
            ],
        )

    def inventario(self, db: Session, usuario_id: int, sucursal_id: int | None = None) -> ReporteInventarioRespuesta:
        return ReporteInventarioRespuesta(
            consolidado=self._inventario.listar_consolidado(db, usuario_id, sucursal_id),
            alertas=self._inventario.listar_alertas(db, usuario_id, sucursal_id),
            valuacion=self._inventario.listar_valuacion(db, usuario_id, sucursal_id),
        )

    def reservas(
        self, db: Session, usuario_id: int, periodo: ParametrosPeriodo, sucursal_id: int | None = None
    ) -> ReporteReservasRespuesta:
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        por_estado = reporte_reservas_por_estado(db, periodo, sucursal_id)
        ventas_con_reserva = comercial_politicas.contar_ventas_con_reserva(db, periodo, sucursal_id)
        return ReporteReservasRespuesta(
            por_estado=[FilaReservasPorEstado(**fila) for fila in por_estado],
            tasa_conversion=tasa_conversion(por_estado, ventas_con_reserva),
        )


# ---- Dashboard de indicadores empresariales (antiguo CU-34: Visualizar indicadores empresariales) ----


class VisualizarDashboardIndicadores:
    def __init__(self) -> None:
        self._inventario = ConsultarInventarioGlobal()

    def ejecutar(
        self, db: Session, usuario_id: int, periodo: ParametrosPeriodo, sucursal_id: int | None = None
    ) -> DashboardRespuesta:
        # Un encargado ve solo su sucursal (también en "ventas por sucursal").
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        resumen_dict = comercial_politicas.reporte_ventas_resumen(db, periodo, sucursal_id)
        top_productos = comercial_politicas.reporte_ventas_top_productos(db, periodo, sucursal_id, limite=5)
        por_canal = comercial_politicas.reporte_ventas_por_canal(db, periodo, sucursal_id)
        por_sucursal = comercial_politicas.reporte_ventas_por_sucursal(db, periodo, sucursal_id=sucursal_id)

        alertas = self._inventario.listar_alertas(db, usuario_id, sucursal_id)
        valuacion = self._inventario.listar_valuacion(db, usuario_id, sucursal_id)
        valor_inventario_total = sum((fila["valor_total"] for fila in valuacion), _CERO)

        por_estado = reporte_reservas_por_estado(db, periodo, sucursal_id)
        ventas_con_reserva = comercial_politicas.contar_ventas_con_reserva(db, periodo, sucursal_id)

        uso_probador = reporte_uso_probador(db, periodo)

        return DashboardRespuesta(
            desde=periodo.desde,
            hasta=periodo.hasta,
            ventas_del_periodo=resumen_dict["total_ventas"],
            transacciones=resumen_dict["transacciones"],
            ticket_promedio=ticket_promedio(resumen_dict["total_ventas"], resumen_dict["transacciones"]),
            margen_bruto=resumen_dict["margen_bruto"],
            top_productos=[FilaTopProducto(**fila) for fila in top_productos],
            ventas_por_canal=[FilaVentasPorCanal(**fila) for fila in por_canal],
            ventas_por_sucursal=[FilaVentasPorSucursal(**fila) for fila in por_sucursal],
            valor_inventario_total=valor_inventario_total,
            variantes_bajo_minimo=len(alertas),
            reservas_por_estado=[FilaReservasPorEstado(**fila) for fila in por_estado],
            tasa_conversion_reservas=tasa_conversion(por_estado, ventas_con_reserva),
            uso_probador=[FilaUsoProbador(**fila) for fila in uso_probador],
        )
