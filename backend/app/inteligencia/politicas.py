"""Soporte de `inteligencia` que el catálogo no numera como casos de uso:

- Registrar el historial de navegación no es un caso de uso (no tiene un
  actor que lo "haga" con un objetivo propio: es una traza que queda como
  efecto secundario de navegar, probar o comprar). Soporta CU-20
  (recomendar productos).
- Redactar la respuesta en lenguaje natural de CU-23 (reporte por comando de
  voz). Es una plantilla en español armada con las cifras reales del
  reporte: ningún dato del negocio sale a un tercero y ninguna cifra la
  inventa un modelo.
"""

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.core.tiempo import inicio_de_semana, restar_meses
from app.inteligencia import registro_reportes
from app.inteligencia.repository import HistorialNavegacionRepository
from app.inteligencia.schemas import (
    ColumnaReporte,
    DashboardRespuesta,
    DocumentoReporte,
    EventoCrear,
    FechaParcial,
    PeriodoSolicitado,
    ReporteGenerativoRespuesta,
    ReporteInventarioRespuesta,
    ReporteReservasRespuesta,
    ReporteVentasRespuesta,
    SeccionReporte,
    SolicitudReporte,
    SolicitudResuelta,
)
from app.plataforma.politicas import obtener_perfil_cliente

# ---- Inteligencia ----

historial_repo = HistorialNavegacionRepository()


def registrar_evento(db: Session, datos: EventoCrear, usuario) -> None:
    """POST /api/v1/ia/eventos. `usuario` es `None` en navegación anónima."""
    cliente_id = obtener_perfil_cliente(db, usuario.id).id if usuario else None
    # producto_id y variante_id llegan del cliente y se guardan como FK: se
    # resuelven con una búsqueda filtrada por empresa (404 si no existen o son
    # de otra empresa). Sin esto un evento anónimo apuntaría a otra empresa.
    if datos.producto_id is not None:
        catalogo_politicas.obtener_producto(db, datos.producto_id)
    if datos.variante_id is not None:
        catalogo_politicas.obtener_variante(db, datos.variante_id)
    historial_repo.crear(db, cliente_id, None, datos.producto_id, datos.variante_id, datos.tipo_evento)


# ---- Respuesta en lenguaje natural de CU-23 -----------------------------------------

ResultadoReporte = ReporteVentasRespuesta | ReporteInventarioRespuesta | ReporteReservasRespuesta | DashboardRespuesta

_AVISO_NO_ENTENDIDO = "No identifiqué qué reporte pedías, así que te muestro el resumen general. "


def formato_numero(valor, decimales: int = 2) -> str:
    """12.400,50: miles con punto, decimales con coma (sin símbolo de moneda)."""
    formateado = f"{Decimal(str(valor)):,.{decimales}f}"  # 12,400.50
    return formateado.replace(",", "\0").replace(".", ",").replace("\0", ".")


def formato_bs(valor: Decimal) -> str:
    """Bs 12.400,50."""
    return "Bs " + formato_numero(valor)


def formato_fecha(fecha: dt.date) -> str:
    return fecha.strftime("%d/%m/%Y")


# Los nombres con guion bajo se conservan: los usa el resto de este módulo y sus pruebas.
_bs = formato_bs
_fecha = formato_fecha


def _porcentaje(fraccion: float) -> str:
    """La tasa de conversión viene como fracción (0.25 = 25%)."""
    texto = f"{fraccion * 100:.1f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",") + "%"


def _cantidad(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _filtros(*, sucursal: str | None = None, categoria: str | None = None, canal: str | None = None) -> str:
    """Solo los filtros que ese reporte realmente aplicó, entre paréntesis."""
    partes = []
    if sucursal:
        partes.append(f"en {sucursal}")
    if categoria:
        partes.append(f"categoría {categoria}")
    if canal:
        partes.append(f"canal {canal}")
    return f" ({', '.join(partes)})" if partes else ""


def _texto_ventas(periodo: str, resultado: ReporteVentasRespuesta) -> str:
    resumen = resultado.resumen
    if resumen.transacciones == 0:
        return f"{periodo} no hubo ventas."
    texto = (
        f"{periodo} hubo {_cantidad(resumen.transacciones, 'venta', 'ventas')} por {_bs(resumen.total_ventas)}, "
        f"con un ticket promedio de {_bs(resumen.ticket_promedio)} y un margen bruto de {_bs(resumen.margen_bruto)}."
    )
    if resultado.top_productos:
        top = resultado.top_productos[0]
        texto += f" Lo más vendido fue {top.producto} ({_cantidad(top.cantidad_vendida, 'unidad', 'unidades')})."
    return texto


def _texto_inventario(inicio: str, resultado: ReporteInventarioRespuesta) -> str:
    if not resultado.consolidado:
        return f"{inicio} no hay existencias registradas."
    unidades = sum(fila.cantidad_disponible for fila in resultado.consolidado)
    variantes = len({fila.variante_id for fila in resultado.consolidado})
    valor = sum((fila.valor_total for fila in resultado.valuacion), Decimal("0"))
    bajo_minimo = len({fila.variante_id for fila in resultado.alertas})
    texto = (
        f"{inicio} hay {_cantidad(unidades, 'unidad disponible', 'unidades disponibles')} en "
        f"{_cantidad(variantes, 'variante', 'variantes')}, con un valor de inventario de {_bs(valor)}."
    )
    if bajo_minimo:
        texto += f" {_cantidad(bajo_minimo, 'variante está', 'variantes están')} por debajo del stock mínimo."
    else:
        texto += " Ninguna variante está por debajo del stock mínimo."
    return texto


def _texto_reservas(periodo: str, resultado: ReporteReservasRespuesta) -> str:
    total = sum(fila.cantidad for fila in resultado.por_estado)
    if total == 0:
        return f"{periodo} no hubo reservas."
    desglose = ", ".join(f"{fila.cantidad} {fila.nombre.lower()}" for fila in resultado.por_estado if fila.cantidad > 0)
    return (
        f"{periodo} hubo {_cantidad(total, 'reserva', 'reservas')} ({desglose}); "
        f"la tasa de conversión a venta fue de {_porcentaje(resultado.tasa_conversion)}."
    )


def _texto_dashboard(periodo: str, resultado: DashboardRespuesta) -> str:
    bajo_minimo = resultado.variantes_bajo_minimo
    alerta = (
        f"hay {_cantidad(bajo_minimo, 'variante', 'variantes')} por debajo del stock mínimo"
        if bajo_minimo
        else "ninguna variante está por debajo del stock mínimo"
    )
    return (
        f"{periodo} las ventas sumaron {_bs(resultado.ventas_del_periodo)} en "
        f"{_cantidad(resultado.transacciones, 'transacción', 'transacciones')} "
        f"(ticket promedio {_bs(resultado.ticket_promedio)}). El inventario vale {_bs(resultado.valor_inventario_total)} "
        f"y {alerta}. La tasa de conversión de reservas es de {_porcentaje(resultado.tasa_conversion_reservas)}."
    )


def redactar_respuesta_reporte(
    *,
    tipo_reporte: str,
    entendida: bool,
    desde: dt.date,
    hasta: dt.date,
    sucursal: str | None,
    categoria: str | None,
    canal: str | None,
    resultado: ResultadoReporte,
) -> str:
    """Para CU-23: convierte el reporte ya consultado en una respuesta en
    español. `entendida=False` (Groq falló, sin API key o tipo inválido)
    antepone el aviso de que se muestra el resumen general."""
    rango = f"El {_fecha(desde)}" if desde == hasta else f"Entre el {_fecha(desde)} y el {_fecha(hasta)}"
    if tipo_reporte == "ventas":
        texto = _texto_ventas(rango + _filtros(sucursal=sucursal, categoria=categoria, canal=canal), resultado)
    elif tipo_reporte == "inventario":
        texto = _texto_inventario("Al día de hoy" + _filtros(sucursal=sucursal), resultado)
    elif tipo_reporte == "reservas":
        texto = _texto_reservas(rango + _filtros(sucursal=sucursal), resultado)
    else:
        texto = _texto_dashboard(rango + _filtros(sucursal=sucursal), resultado)
    return texto if entendida else _AVISO_NO_ENTENDIDO + texto


# ---- Reportes ----
# Cálculos compartidos entre los reportes y el dashboard (CU-22): no son un
# caso de uso aparte, son fórmulas de una línea que ambos necesitan.

_CERO = Decimal("0")


def ticket_promedio(total_ventas: Decimal, transacciones: int) -> Decimal:
    if transacciones == 0:
        return _CERO
    return (total_ventas / transacciones).quantize(Decimal("0.01"))


def tasa_conversion(por_estado: list[dict], ventas_con_reserva: int) -> float:
    total_reservas = sum(fila["cantidad"] for fila in por_estado)
    if total_reservas == 0:
        return 0.0
    return round(ventas_con_reserva / total_reservas, 4)


# ---- Reportes generativos (CU-23, E09) ----
# Funciones puras: reciben filas ya consultadas por comercial y catalogo y las dejan listas para
# mostrar. No tocan la base.

_DOS_DECIMALES = Decimal("0.01")
_AGRUPACIONES = ("dia", "semana", "mes")


def a_decimal(valor) -> Decimal:
    """Un total de la base como Decimal de 2 decimales (SQLite devuelve float en SUM())."""
    return Decimal(str(valor if valor is not None else 0)).quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)


def a_numero(valor: Decimal) -> float:
    """El Decimal como número JSON de 2 decimales: sirve para mostrar, no para calcular."""
    return float(Decimal(valor).quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP))


def calcular_participacion(valores: list[Decimal], total: Decimal | None = None) -> list[float]:
    """Porcentaje (0 a 100, 1 decimal) que representa cada valor sobre `total` (por defecto, la
    suma de `valores`). Con total 0 todo es 0."""
    base = sum(valores, Decimal("0")) if total is None else Decimal(total)
    if base <= 0:
        return [0.0 for _ in valores]
    return [float((Decimal(v) * 100 / base).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) for v in valores]


def armar_resumen(filas: list[dict], claves: list[str]) -> dict:
    """Totales de las columnas sumables indicadas (enteros como int, montos como número de 2
    decimales)."""
    resumen: dict = {}
    for clave in claves:
        valores = [fila.get(clave) for fila in filas if fila.get(clave) is not None]
        if valores and all(isinstance(v, int) and not isinstance(v, bool) for v in valores):
            resumen[clave] = sum(valores)
        else:
            resumen[clave] = a_numero(sum((Decimal(str(v)) for v in valores), Decimal("0")))
    return resumen


def etiqueta_periodo(desde: dt.date, hasta: dt.date) -> str:
    return _fecha(desde) if desde == hasta else f"{_fecha(desde)} al {_fecha(hasta)}"


def _inicio_de_bucket(dia: dt.date, agrupacion: str) -> dt.date:
    if agrupacion == "semana":
        return inicio_de_semana(dia)
    if agrupacion == "mes":
        return dia.replace(day=1)
    return dia


def _siguiente_bucket(inicio: dt.date, agrupacion: str) -> dt.date:
    if agrupacion == "semana":
        return inicio + dt.timedelta(days=7)
    if agrupacion == "mes":
        return restar_meses(inicio, -1)
    return inicio + dt.timedelta(days=1)


def etiqueta_bucket(inicio: dt.date, agrupacion: str) -> str:
    """'14/09/2026' (día), 'S38 (14/09)' (semana ISO, lunes a domingo) o '09/2026' (mes)."""
    if agrupacion == "semana":
        return f"S{inicio.isocalendar().week} ({inicio:%d/%m})"
    if agrupacion == "mes":
        return f"{inicio:%m/%Y}"
    return _fecha(inicio)


def agrupar_serie(
    filas: list[dict], agrupacion: str, desde: dt.date, hasta: dt.date, *, serie: str | None = None
) -> list[dict]:
    """Suma las filas diarias por día, semana (lunes a domingo) o mes, e incluye con ceros los
    periodos sin ventas entre `desde` y `hasta`. Con `serie` (p. ej. "sucursal") hay una fila por
    periodo y por cada valor de esa serie que aparece en los datos. Cada fila: `periodo`
    (etiqueta), `desde` (inicio del periodo, sin salir del rango pedido), `transacciones`,
    `unidades`, `total_ventas` (Decimal) y la `serie` si se pidió."""
    if agrupacion not in _AGRUPACIONES:
        raise ValueError(f"Agrupación desconocida: {agrupacion}")
    series = sorted({fila[serie] for fila in filas}) if serie else [None]
    acumulado: dict[tuple[dt.date, str | None], list] = {}
    for fila in filas:
        clave = (_inicio_de_bucket(fila["dia"], agrupacion), fila[serie] if serie else None)
        suma = acumulado.setdefault(clave, [0, 0, Decimal("0")])
        suma[0] += int(fila["transacciones"])
        suma[1] += int(fila["unidades"])
        suma[2] += Decimal(fila["total_ventas"])
    salida: list[dict] = []
    inicio = _inicio_de_bucket(desde, agrupacion)
    while inicio <= hasta:
        for valor in series:
            transacciones, unidades, total = acumulado.get((inicio, valor), (0, 0, Decimal("0")))
            fila_nueva = {
                "periodo": etiqueta_bucket(inicio, agrupacion),
                "desde": max(inicio, desde),
                "transacciones": transacciones,
                "unidades": unidades,
                "total_ventas": total,
            }
            if serie:
                fila_nueva[serie] = valor
            salida.append(fila_nueva)
        inicio = _siguiente_bucket(inicio, agrupacion)
    return salida


def _vendio(filas: list[dict], clave: str) -> str:
    return _bs(Decimal(str(filas[0][clave])))


def redactar_narrativa_reporte(codigo: str, periodo: str | None, filas: list[dict], resumen: dict) -> str:
    """Resumen corto en español de un reporte generativo, por plantilla. Las cifras salen del
    resultado ya calculado: ningún dato sale a un tercero y ninguna cifra la inventa un modelo."""
    cuando = f"Entre el {periodo.replace(' al ', ' y el ')}" if periodo and " al " in periodo else f"El {periodo}"
    if codigo != "productos_menor_existencia" and not filas:
        return f"{cuando} no hubo ventas con esos filtros."
    if codigo == "ventas_por_sucursal":
        mejor = max(filas, key=lambda f: f["total_ventas"])
        return (
            f"{cuando} se vendió {_bs(Decimal(str(resumen['total_ventas'])))} en "
            f"{_cantidad(len(filas), 'sucursal', 'sucursales')}. La que más vendió fue {mejor['sucursal']} "
            f"con {_bs(Decimal(str(mejor['total_ventas'])))} ({_porcentaje_100(mejor['participacion'])} del total)."
        )
    if codigo == "productos_mas_vendidos":
        primero = filas[0]
        return (
            f"{cuando}, {primero['producto']} encabeza la lista con "
            f"{_cantidad(primero['unidades'], 'unidad', 'unidades')} y {_bs(Decimal(str(primero['total_vendido'])))}. "
            f"Se muestran {_cantidad(len(filas), 'producto', 'productos')} que suman "
            f"{_bs(Decimal(str(resumen['total_vendido'])))}."
        )
    if codigo == "ventas_por_periodo":
        mejor = max(filas, key=lambda f: f["total_ventas"])
        return (
            f"{cuando} se vendió {_bs(Decimal(str(resumen['total_ventas'])))} en "
            f"{_cantidad(resumen['transacciones'], 'venta', 'ventas')}. El mejor periodo fue {mejor['periodo']} "
            f"con {_bs(Decimal(str(mejor['total_ventas'])))}."
        )
    if codigo == "comparacion_sucursales":
        sucursales = sorted({f["sucursal"] for f in filas})
        mejor = max(filas, key=lambda f: f["total_ventas"])
        return (
            f"{cuando} se compararon {_cantidad(len(sucursales), 'sucursal', 'sucursales')} con un total de "
            f"{_bs(Decimal(str(resumen['total_ventas'])))}. El mayor monto fue de {mejor['sucursal']} en "
            f"{mejor['periodo']}: {_bs(Decimal(str(mejor['total_ventas'])))}."
        )
    if codigo == "productos_menor_existencia":
        if not filas:
            return "No hay productos con existencias registradas con esos filtros."
        bajos = sum(1 for f in filas if f["bajo_minimo"])
        primero = filas[0]
        texto = (
            f"El producto con menos existencia es {primero['producto']} "
            f"({_cantidad(primero['disponible'], 'unidad disponible', 'unidades disponibles')})."
        )
        texto += (
            f" {_cantidad(bajos, 'producto está', 'productos están')} por debajo del stock mínimo."
            if bajos
            else " Ninguno está por debajo del stock mínimo."
        )
        return texto
    if codigo == "ingresos_por_categoria":
        primera = filas[0]
        return (
            f"{cuando} la categoría con más ingresos fue {primera['categoria']} con "
            f"{_bs(Decimal(str(primera['total_vendido'])))} ({_porcentaje_100(primera['participacion'])} del total). "
            f"En conjunto las {len(filas)} categorías mostradas suman {_bs(Decimal(str(resumen['total_vendido'])))}."
        )
    return "Reporte generado."


def _porcentaje_100(valor: float) -> str:
    """Un porcentaje que ya viene de 0 a 100 (45.5 -> '45,5%')."""
    return f"{valor:.1f}".rstrip("0").rstrip(".").replace(".", ",") + "%"


# ---- Exportación (E10) -------------------------------------------------------------------
# Adaptadores de un reporte a DocumentoReporte. El constructor de archivos no sabe de dónde
# viene el reporte; los de CU-22 y los de ML (E12) agregan aquí su propio adaptador.

# Columnas cuya suma tiene sentido (ventas, existencias y valores del inventario, reservas). Las
# demás (ticket promedio, precio y costo unitarios, participación, variación, posición, stock
# mínimo) no se totalizan.
COLUMNAS_SUMABLES = frozenset(
    {
        "transacciones",
        "unidades",
        "total_ventas",
        "total_vendido",
        "margen_bruto",
        "cantidad_fisica",
        "cantidad_reservada",
        "cantidad_disponible",
        "valor_inventario",
        "valor_total",
        "cantidad",
    }
)

_ETIQUETA_CANAL = {"digital": "digital", "presencial": "presencial"}
_ETIQUETA_AGRUPACION = {"dia": "por día", "semana": "por semana", "mes": "por mes"}
_ETIQUETA_ORDEN = {"mayor_a_menor": "de mayor a menor", "menor_a_mayor": "de menor a mayor"}


def calcular_totales(columnas: list[ColumnaReporte], filas: list[dict]) -> dict | None:
    """Suma, con Decimal, las columnas sumables de las filas (enteros como int, montos con 2
    decimales). `None` si no hay filas o ninguna columna se suma."""
    if not filas:
        return None
    totales: dict = {}
    for columna in columnas:
        if columna.clave not in COLUMNAS_SUMABLES:
            continue
        valores = [f.get(columna.clave) for f in filas if f.get(columna.clave) is not None]
        if not valores:
            continue
        if columna.tipo == "entero":
            totales[columna.clave] = sum(int(v) for v in valores)
        else:
            totales[columna.clave] = sum((Decimal(str(v)) for v in valores), Decimal("0")).quantize(
                _DOS_DECIMALES, rounding=ROUND_HALF_UP
            )
    return totales or None


def _nombres(referencias) -> str:
    return ", ".join(r.nombre for r in referencias)


def lineas_de_filtros(solicitud: SolicitudResuelta) -> list[str]:
    """Los filtros que el reporte admite, redactados para el encabezado del archivo. Un filtro
    admitido pero sin valor se muestra como "todas"/"todos": que el archivo diga qué abarca."""
    definicion = registro_reportes.obtener(solicitud.tipo_reporte)
    admitidos = definicion.filtros if definicion else {}
    lineas: list[str] = []
    if solicitud.periodo is not None:
        lineas.append(f"Periodo: {solicitud.periodo.etiqueta}")
    if "sucursales" in admitidos:
        lineas.append(f"Sucursales: {_nombres(solicitud.sucursales) or 'todas'}")
    if "categorias" in admitidos:
        lineas.append(f"Categorías: {_nombres(solicitud.categorias) or 'todas'}")
    if "productos" in admitidos and solicitud.productos:
        lineas.append(f"Productos: {_nombres(solicitud.productos)}")
    if "canal" in admitidos:
        lineas.append(f"Canal: {_ETIQUETA_CANAL.get(solicitud.canal, 'todos')}")
    if solicitud.agrupacion:
        lineas.append(f"Agrupación: {_ETIQUETA_AGRUPACION.get(solicitud.agrupacion, solicitud.agrupacion)}")
    if "orden" in admitidos and solicitud.orden:
        lineas.append(f"Orden: {_ETIQUETA_ORDEN.get(solicitud.orden, solicitud.orden)}")
    if solicitud.limite is not None:
        lineas.append(f"Máximo de filas: {solicitud.limite}")
    return lineas


def documento_desde_reporte(
    respuesta: ReporteGenerativoRespuesta, empresa_nombre: str, ahora: dt.datetime
) -> DocumentoReporte:
    """Convierte un reporte generativo ya ejecutado (estado "ok") en el documento que se
    descarga. Las columnas de dinero llevan "(Bs)" en el título; los totales solo se ponen
    si el reporte está completo (con filas recortadas, la suma sería de otra cosa)."""
    reporte = respuesta.reporte
    if reporte is None or respuesta.solicitud is None:
        raise ValueError("Solo se puede exportar un reporte ejecutado (estado ok).")
    columnas = [
        c.model_copy(update={"titulo": f"{c.titulo} (Bs)"}) if c.tipo == "moneda" else c for c in reporte.columnas
    ]
    seccion = SeccionReporte(
        titulo=reporte.titulo,
        columnas=columnas,
        filas=reporte.filas,
        totales=None if reporte.truncado else calcular_totales(columnas, reporte.filas),
        grafico=reporte.grafico_sugerido,
    )
    return DocumentoReporte(
        titulo=reporte.titulo,
        subtitulo=respuesta.narrativa,
        empresa_nombre=empresa_nombre,
        filtros=lineas_de_filtros(respuesta.solicitud),
        generado_en=ahora,
        secciones=[seccion],
        truncado=reporte.truncado,
        avisos=list(respuesta.avisos),
    )


def solicitud_desde_resuelta(resuelta: SolicitudResuelta) -> SolicitudReporte:
    """La solicitud resuelta que devolvió /ejecutar, vuelta a una SolicitudReporte para
    ejecutarla otra vez SIN intérprete. El periodo se reenvía como el rango de fechas ya
    calculado (la descarga trae el mismo periodo que la vista previa aunque pase la medianoche)
    y los ids se descartan: los nombres se resuelven de nuevo contra la empresa de la sesión."""
    periodo = None
    if resuelta.periodo is not None:
        desde, hasta = resuelta.periodo.desde, resuelta.periodo.hasta
        periodo = PeriodoSolicitado(
            tipo="rango_fechas",
            desde=FechaParcial(dia=desde.day, mes=desde.month, anio=desde.year),
            hasta=FechaParcial(dia=hasta.day, mes=hasta.month, anio=hasta.year),
        )
    return SolicitudReporte(
        tipo_reporte=resuelta.tipo_reporte,
        periodo=periodo,
        sucursales=[r.nombre for r in resuelta.sucursales],
        categorias=[r.nombre for r in resuelta.categorias],
        productos=[r.nombre for r in resuelta.productos],
        canal=resuelta.canal,
        agrupacion=resuelta.agrupacion,
        orden=resuelta.orden,
        limite=resuelta.limite,
    )
