"""CU-23 — Generar reportes con IA

Absorbe el antiguo CU-38 (Generar reporte por comando de voz).

Actor: Administrador, Servicio de inteligencia artificial.
Precondición: sesión con el permiso reportes.ver.
Postcondición: se responde en lenguaje natural una pregunta sobre los
reportes del negocio.

Groq solo elige `tipo_reporte` (uno de 4 valores fijos) y filtros ya
conocidos (fechas, nombres) -- nunca genera SQL ni texto que se ejecute;
si falla o no valida, cae al dashboard con el período por defecto, nunca
a un error. Llama al caso de uso CU-22 (reportes e indicadores) del mismo
paquete, que es de solo lectura.

Hoy resuelve el reporte por comando de voz (el antiguo CU-38); será ampliado a
reportes generativos con filtros variables, gráficos y exportación."""

import datetime as dt

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.core.deps import DIAS_PERIODO_POR_DEFECTO, ParametrosPeriodo
from app.core.tiempo import hoy_utc
from app.inteligencia.groq_cliente import obtener_parser_reporte_voz
from app.inteligencia.politicas import redactar_respuesta_reporte
from app.inteligencia.schemas import TIPOS_REPORTE_VALIDOS, ReporteVozRespuesta
from app.plataforma import politicas as plataforma_politicas
from app.inteligencia.casos_uso.cu22_consultar_reportes_indicadores import (
    ConsultarReportesVentasInventario,
    VisualizarDashboardIndicadores,
)


MAX_DIAS_PERIODO = 366


def _acotar_periodo(desde: dt.date, hasta: dt.date, hoy: dt.date) -> tuple[dt.date, dt.date]:
    """Las fechas que devuelve el modelo no son confiables: `hasta` futuro se
    ajusta a hoy, y un rango que queda vacío o de más de 366 días se descarta
    a favor del período por defecto."""
    hasta = min(hasta, hoy)
    if desde > hasta or (hasta - desde).days > MAX_DIAS_PERIODO:
        return hasta - dt.timedelta(days=DIAS_PERIODO_POR_DEFECTO), hasta
    return desde, hasta


class GenerarReporteComandoVoz:
    def __init__(self) -> None:
        self._reportes = ConsultarReportesVentasInventario()
        self._dashboard = VisualizarDashboardIndicadores()

    def ejecutar(self, db: Session, usuario_id: int, texto: str) -> ReporteVozRespuesta:
        """POST /api/v1/ia/reporte-voz. Requiere `reportes.ver` (verificado
        en el router, no acá)."""
        filtros_voz = obtener_parser_reporte_voz().parsear(texto)

        # Sin interpretación válida (Groq falló, sin API key o tipo desconocido)
        # se muestra el dashboard y la respuesta lo avisa.
        entendida = filtros_voz is not None and filtros_voz.tipo_reporte in TIPOS_REPORTE_VALIDOS
        tipo_reporte = filtros_voz.tipo_reporte if entendida else "dashboard"

        hasta = filtros_voz.hasta if filtros_voz and filtros_voz.hasta else hoy_utc()
        desde = (
            filtros_voz.desde
            if filtros_voz and filtros_voz.desde
            else hasta - dt.timedelta(days=DIAS_PERIODO_POR_DEFECTO)
        )
        if desde > hasta:
            # Groq mandó un rango invertido: se intercambia en vez de romper.
            desde, hasta = hasta, desde
        desde, hasta = _acotar_periodo(desde, hasta, hoy_utc())
        periodo = ParametrosPeriodo(desde=desde, hasta=hasta)

        sucursal_id = plataforma_politicas.resolver_sucursal_por_nombre(db, filtros_voz.sucursal) if filtros_voz else None
        # Un encargado solo puede consultar su sucursal: si dictó otra (o
        # ninguna), se usa la suya en vez de fallar -- este CU nunca termina
        # en error por lo que interpretó Groq.
        propia = plataforma_politicas.sucursal_asignada(db, usuario_id)
        if propia is not None:
            sucursal_id = propia
        categoria_id = catalogo_politicas.resolver_categoria_por_nombre(db, filtros_voz.categoria) if filtros_voz else None
        canal = filtros_voz.canal if filtros_voz and filtros_voz.canal in {"digital", "presencial"} else None

        if tipo_reporte == "ventas":
            resultado = self._reportes.ventas(db, usuario_id, periodo, sucursal_id, categoria_id, canal)
        elif tipo_reporte == "inventario":
            resultado = self._reportes.inventario(db, usuario_id, sucursal_id)
        elif tipo_reporte == "reservas":
            resultado = self._reportes.reservas(db, usuario_id, periodo, sucursal_id)
        else:
            resultado = self._dashboard.ejecutar(db, usuario_id, periodo, sucursal_id)

        filtros_aplicados = {
            "desde": str(periodo.desde),
            "hasta": str(periodo.hasta),
            "sucursal_id": sucursal_id,
            "categoria_id": categoria_id,
            "canal": canal,
        }
        # Nombres para la frase: el de la sucursal aplicada (puede ser la propia
        # del encargado, no la que dictó) y la categoría tal como se dictó, solo
        # si se resolvió a un id.
        sucursal_nombre = (
            plataforma_politicas.obtener_sucursal(db, sucursal_id).nombre if sucursal_id is not None else None
        )
        categoria_nombre = filtros_voz.categoria if filtros_voz and categoria_id is not None else None
        respuesta = redactar_respuesta_reporte(
            tipo_reporte=tipo_reporte,
            entendida=entendida,
            desde=periodo.desde,
            hasta=periodo.hasta,
            sucursal=sucursal_nombre,
            categoria=categoria_nombre,
            canal=canal,
            resultado=resultado,
        )
        return ReporteVozRespuesta(
            respuesta=respuesta,
            tipo_reporte=tipo_reporte,
            filtros_aplicados=filtros_aplicados,
            resultado=resultado.model_dump(mode="json"),
        )
