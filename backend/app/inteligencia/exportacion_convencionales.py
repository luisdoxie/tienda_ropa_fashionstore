"""E10, paso 8 — Adaptadores de los reportes convencionales de CU-22 (ventas, inventario y
reservas) al documento que se descarga.

Son funciones puras: reciben la respuesta que ya calculó CU-22 y devuelven un DocumentoReporte
con una sección por tabla. Las tablas largas (el detalle de ventas, el stock por variante) se
recortan al tope del formato y la sección lo dice en su nota; no se marca `doc.truncado`, porque
ese aviso es del documento entero y las demás tablas están completas."""

import datetime as dt

from app.core.tiempo import ZONA_BOLIVIA
from app.inteligencia.politicas import calcular_totales, formato_fecha, formato_numero
from app.inteligencia.schemas import (
    ColumnaReporte,
    DocumentoReporte,
    GraficoSugerido,
    ReporteInventarioRespuesta,
    ReporteReservasRespuesta,
    ReporteVentasRespuesta,
    SeccionReporte,
)


def _col(clave: str, titulo: str, tipo: str) -> ColumnaReporte:
    return ColumnaReporte(clave=clave, titulo=titulo, tipo=tipo)


def _seccion(
    titulo: str,
    columnas: list[ColumnaReporte],
    filas: list[dict],
    *,
    grafico: GraficoSugerido | None = None,
    max_filas: int | None = None,
    totalizar: bool = True,
) -> SeccionReporte:
    """Una tabla. Con `max_filas` se queda con las primeras y lo anota; una tabla recortada no
    lleva totales (la suma sería de otra cosa)."""
    nota = None
    recortada = max_filas is not None and len(filas) > max_filas
    if recortada:
        nota = f"Se muestran las primeras {formato_numero(max_filas, 0)} de {formato_numero(len(filas), 0)} filas."
        filas = filas[:max_filas]
    return SeccionReporte(
        titulo=titulo,
        columnas=columnas,
        filas=filas,
        totales=calcular_totales(columnas, filas) if totalizar and not recortada else None,
        grafico=grafico,
        nota=nota,
    )


def _documento(
    titulo: str, subtitulo: str | None, empresa_nombre: str, ahora: dt.datetime, filtros: list[str], secciones
) -> DocumentoReporte:
    return DocumentoReporte(
        titulo=titulo,
        subtitulo=subtitulo,
        empresa_nombre=empresa_nombre,
        filtros=filtros,
        generado_en=ahora,
        secciones=list(secciones),
    )


def _fecha_hora_bolivia(fecha: dt.datetime) -> str:
    """`venta.fecha` es UTC sin zona: en el archivo se muestra en hora de Bolivia."""
    local = fecha.replace(tzinfo=dt.timezone.utc).astimezone(ZONA_BOLIVIA) if fecha.tzinfo is None else fecha.astimezone(ZONA_BOLIVIA)
    return f"{formato_fecha(local.date())} {local:%H:%M}"


# ---- Ventas ---------------------------------------------------------------------------------


def documento_ventas(
    reporte: ReporteVentasRespuesta, empresa_nombre: str, ahora: dt.datetime, filtros: list[str], max_filas: int
) -> DocumentoReporte:
    resumen = reporte.resumen
    secciones = [
        _seccion(
            "Resumen",
            [
                _col("transacciones", "Transacciones", "entero"),
                _col("total_ventas", "Total vendido (Bs)", "moneda"),
                _col("ticket_promedio", "Ticket promedio (Bs)", "moneda"),
                _col("margen_bruto", "Margen bruto (Bs)", "moneda"),
            ],
            [
                {
                    "transacciones": resumen.transacciones,
                    "total_ventas": resumen.total_ventas,
                    "ticket_promedio": resumen.ticket_promedio,
                    "margen_bruto": resumen.margen_bruto,
                }
            ],
            totalizar=False,
        ),
        _seccion(
            "Productos más vendidos",
            [_col("producto", "Producto", "texto"), _col("unidades", "Unidades", "entero"), _col("total_vendido", "Total vendido (Bs)", "moneda")],
            [
                {"producto": f.producto, "unidades": f.cantidad_vendida, "total_vendido": f.total_vendido}
                for f in reporte.top_productos
            ],
            grafico=GraficoSugerido(tipo="barras_horizontales", eje_x="producto", eje_y="total_vendido"),
        ),
        _seccion(
            "Ventas por canal",
            [_col("canal", "Canal", "texto"), _col("transacciones", "Transacciones", "entero"), _col("total_ventas", "Total vendido (Bs)", "moneda")],
            [{"canal": f.canal, "transacciones": f.transacciones, "total_ventas": f.total_ventas} for f in reporte.por_canal],
            grafico=GraficoSugerido(tipo="torta", eje_x="canal", eje_y="total_ventas"),
        ),
        _seccion(
            "Ventas por sucursal",
            [_col("sucursal", "Sucursal", "texto"), _col("transacciones", "Transacciones", "entero"), _col("total_ventas", "Total vendido (Bs)", "moneda")],
            [{"sucursal": f.sucursal, "transacciones": f.transacciones, "total_ventas": f.total_ventas} for f in reporte.por_sucursal],
            grafico=GraficoSugerido(tipo="barras", eje_x="sucursal", eje_y="total_ventas"),
        ),
        _seccion(
            "Detalle de ventas",
            [
                _col("codigo", "Venta", "texto"),
                _col("fecha", "Fecha (hora de Bolivia)", "texto"),
                _col("sucursal", "Sucursal", "texto"),
                _col("producto", "Producto", "texto"),
                _col("categoria", "Categoría", "texto"),
                _col("canal", "Canal", "texto"),
                _col("unidades", "Cantidad", "entero"),
                _col("precio_unitario", "Precio unitario (Bs)", "moneda"),
                _col("total_vendido", "Subtotal (Bs)", "moneda"),
                _col("margen_bruto", "Margen (Bs)", "moneda"),
            ],
            [
                {
                    "codigo": f.codigo,
                    "fecha": _fecha_hora_bolivia(f.fecha),
                    "sucursal": f.sucursal,
                    "producto": f.producto,
                    "categoria": f.categoria,
                    "canal": f.canal,
                    "unidades": f.cantidad,
                    "precio_unitario": f.precio_unitario,
                    "total_vendido": f.subtotal,
                    "margen_bruto": f.margen,
                }
                for f in reporte.detalle
            ],
            max_filas=max_filas,
        ),
    ]
    subtitulo = (
        f"Se vendió Bs {formato_numero(resumen.total_ventas)} en {formato_numero(resumen.transacciones, 0)} "
        f"{'transacción' if resumen.transacciones == 1 else 'transacciones'}."
        if resumen.transacciones
        else "No hubo ventas con estos filtros."
    )
    return _documento("Reporte de ventas", subtitulo, empresa_nombre, ahora, filtros, secciones)


# ---- Inventario -----------------------------------------------------------------------------


def documento_inventario(
    reporte: ReporteInventarioRespuesta, empresa_nombre: str, ahora: dt.datetime, filtros: list[str], max_filas: int
) -> DocumentoReporte:
    secciones = [
        _seccion(
            "Stock por variante",
            [
                _col("producto", "Producto", "texto"),
                _col("sku", "SKU", "texto"),
                _col("talla", "Talla", "texto"),
                _col("color", "Color", "texto"),
                _col("sucursal", "Sucursal", "texto"),
                _col("cantidad_fisica", "Físico", "entero"),
                _col("cantidad_reservada", "Reservado", "entero"),
                _col("cantidad_disponible", "Disponible", "entero"),
                _col("stock_minimo", "Mínimo", "entero"),
                _col("costo_promedio", "Costo promedio (Bs)", "moneda"),
                _col("valor_inventario", "Valor (Bs)", "moneda"),
            ],
            [f.model_dump(include=_CAMPOS_CONSOLIDADO) for f in reporte.consolidado],
            max_filas=max_filas,
        ),
        _seccion(
            "Alertas de stock bajo el mínimo",
            [
                _col("producto", "Producto", "texto"),
                _col("sku", "SKU", "texto"),
                _col("talla", "Talla", "texto"),
                _col("color", "Color", "texto"),
                _col("sucursal", "Sucursal", "texto"),
                _col("cantidad_disponible", "Disponible", "entero"),
                _col("stock_minimo", "Mínimo", "entero"),
            ],
            [f.model_dump(include=_CAMPOS_ALERTA) for f in reporte.alertas],
            max_filas=max_filas,
        ),
        _seccion(
            "Valuación por sucursal",
            [_col("sucursal", "Sucursal", "texto"), _col("valor_total", "Valor total (Bs)", "moneda")],
            [{"sucursal": f.sucursal, "valor_total": f.valor_total} for f in reporte.valuacion],
            grafico=GraficoSugerido(tipo="barras", eje_x="sucursal", eje_y="valor_total"),
        ),
    ]
    valor = sum((f.valor_total for f in reporte.valuacion), 0)
    subtitulo = (
        f"Valor del inventario: Bs {formato_numero(valor)}. "
        f"{formato_numero(len(reporte.alertas), 0)} {'variante' if len(reporte.alertas) == 1 else 'variantes'} bajo el mínimo."
    )
    return _documento("Reporte de inventario", subtitulo, empresa_nombre, ahora, filtros, secciones)


_CAMPOS_CONSOLIDADO = {
    "producto", "sku", "talla", "color", "sucursal", "cantidad_fisica", "cantidad_reservada",
    "cantidad_disponible", "stock_minimo", "costo_promedio", "valor_inventario",
}
_CAMPOS_ALERTA = {"producto", "sku", "talla", "color", "sucursal", "cantidad_disponible", "stock_minimo"}


# ---- Reservas -------------------------------------------------------------------------------


def documento_reservas(
    reporte: ReporteReservasRespuesta, empresa_nombre: str, ahora: dt.datetime, filtros: list[str]
) -> DocumentoReporte:
    seccion = _seccion(
        "Reservas por estado",
        [_col("nombre", "Estado", "texto"), _col("cantidad", "Reservas", "entero")],
        [{"nombre": f.nombre, "cantidad": f.cantidad} for f in reporte.por_estado],
        grafico=GraficoSugerido(tipo="barras", eje_x="nombre", eje_y="cantidad"),
    )
    subtitulo = f"Tasa de conversión de reservas a ventas: {formato_numero(reporte.tasa_conversion * 100, 1)}%."
    return _documento("Reporte de reservas", subtitulo, empresa_nombre, ahora, filtros, [seccion])
