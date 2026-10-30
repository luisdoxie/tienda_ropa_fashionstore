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
import math
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
    if "horizonte_semanas" in admitidos and solicitud.horizonte_semanas is not None:
        lineas.append(f"Horizonte: {_cantidad(solicitud.horizonte_semanas, 'semana', 'semanas')}")
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
        horizonte_semanas=resuelta.horizonte_semanas,
    )


# ---- Interpretación de analítica ML --------------------------------------------------------
# Frases en español, con tuteo, para un administrador de tienda. Son funciones PURAS: reciben
# diccionarios simples y devuelven listas de frases. No tocan la base, no importan numpy ni
# scikit-learn y no usan IA: cada cifra que se dice viene de los datos recibidos. Nunca salen
# "None", "nan" ni "inf": un dato ausente o no finito simplemente no se menciona.

# Una variación de la demanda dentro de este margen (en puntos porcentuales) se considera ruido.
UMBRAL_VARIACION_SIGNIFICATIVA_PCT = 5.0
# Una mejora menor a esto sobre la línea base se dice como "pequeña".
UMBRAL_MEJORA_PEQUENA_PCT = 5.0
# Silhouette: a partir de qué valor los grupos de clientes se consideran bien o aceptablemente separados.
SILHOUETTE_BIEN_SEPARADOS = 0.5
SILHOUETTE_ACEPTABLE = 0.25

_NOMBRES_ALGORITMO = {
    "ridge": "Ridge (una regresión lineal regularizada)",
    "random_forest": "Random Forest (un bosque de árboles de decisión)",
    "mezcla": "una mezcla de Ridge y Random Forest",
}
_SEGMENTOS_EN_RIESGO = ("En riesgo", "Por reactivar", "Grandes dormidos")
_SEGMENTO_CAMPEONES = "Campeones"


def _finito_o_none(valor) -> float | None:
    """El número como float, o None si falta, no es número o no es finito (nan, inf)."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None


def _entero_no_negativo(valor) -> int:
    numero = _finito_o_none(valor)
    return 0 if numero is None else max(0, int(round(numero)))


def _nombre_o(valor, por_defecto: str) -> str:
    nombre = " ".join(str(valor).split()) if valor is not None else ""
    return nombre if nombre and nombre.lower() not in ("none", "nan") else por_defecto


def _unidades(n: float) -> str:
    """12 unidades / 1 unidad / 2,5 unidades."""
    if float(n).is_integer():
        return _cantidad(int(n), "unidad", "unidades")
    return f"{formato_numero(n, 2)} unidades"


def _dias(n: float) -> str:
    entero = int(round(n))
    return _cantidad(entero, "día", "días")


def _horizonte_texto(horizonte_semanas) -> tuple[str, str]:
    """('las próximas 4 semanas', 'las últimas 4 semanas reales'); sin horizonte válido, texto genérico para lo previsto.
    La variación de cada categoría siempre se mide contra el promedio de sus últimas 4 semanas REALES (no contra un
    periodo del tamaño del horizonte): así lo calcula `ConsultarAnaliticaML`."""
    semanas = _finito_o_none(horizonte_semanas)
    base = "las últimas 4 semanas reales"
    if semanas is None or semanas < 1:
        return "el periodo previsto", base
    n = int(semanas)
    return ("la próxima semana" if n == 1 else f"las próximas {n} semanas"), base


def interpretar_metricas_demanda(metricas: dict) -> list[str]:
    """Explica las métricas del modelo de demanda contra la línea base (media móvil de 4 semanas).

    Cualquier clave puede faltar o ser None: solo se dice lo que se puede sostener con los datos."""
    metricas = metricas or {}
    mae = _finito_o_none(metricas.get("mae"))
    mae_base = _finito_o_none(metricas.get("mae_base"))
    r2 = _finito_o_none(metricas.get("r2"))
    r2_base = _finito_o_none(metricas.get("r2_base"))
    mejora = _finito_o_none(metricas.get("mejora_mae_pct"))
    frases: list[str] = []

    if mae is not None:
        frase = f"El modelo se equivoca en promedio {formato_numero(mae, 2)} unidades por categoría y semana"
        if mae_base is not None:
            frase += f"; el promedio móvil de 4 semanas se equivoca {formato_numero(mae_base, 2)}"
            if mejora is not None and mejora > 0:
                frase += f": es {_porcentaje_100(mejora)} más preciso"
                if mejora < UMBRAL_MEJORA_PEQUENA_PCT:
                    frase += ", una mejora pequeña"
        frases.append(frase + ".")
        if mae_base is not None:
            if mejora is None:
                frases.append("No se pudo medir con certeza si el modelo mejora al promedio móvil de 4 semanas.")
            elif mejora <= 0:
                frases.append(
                    "El modelo no mejora a la línea base (el promedio móvil de 4 semanas)"
                    + (f": es {_porcentaje_100(abs(mejora))} menos preciso." if mejora < 0 else ": empatan.")
                    + " Toma sus previsiones como orientativas."
                )
    elif mae_base is not None:
        frases.append(f"El promedio móvil de 4 semanas se equivoca en promedio {formato_numero(mae_base, 2)} unidades por categoría y semana.")

    if r2 is not None:
        if r2 < 0:
            frases.append(
                f"El R2 es negativo ({formato_numero(r2, 2)}): el modelo no explica la variación de la demanda mejor que un promedio simple."
            )
        else:
            frase = f"El modelo explica el {_porcentaje_100(min(r2, 1.0) * 100)} de la variación de la demanda semanal en datos que no vio al entrenarse"
            if r2_base is not None:
                if r2_base >= 0:
                    frase += f"; el promedio móvil explica el {_porcentaje_100(min(r2_base, 1.0) * 100)}"
                else:
                    frase += "; el promedio móvil no logra explicarla"
            frases.append(frase + ".")

    elegido = metricas.get("modelo_elegido")
    if isinstance(elegido, str) and elegido.strip() and elegido.strip().lower() not in ("none", "nan"):
        clave = elegido.strip().lower()
        nombre = _NOMBRES_ALGORITMO.get(clave, clave.replace("_", " "))
        frases.append(f"El algoritmo que mejor funcionó en la validación fue {nombre}.")
    return frases


def interpretar_demanda(categorias: list[dict], horizonte_semanas: int) -> list[str]:
    """Resume la demanda prevista: total, categoría líder y la que más crece y la que más cae.

    Cada dict: {"categoria", "total_predicho", "variacion_pct"} (la variación puede ser None). Una
    categoría solo se señala como "la que más crece" o "la que más cae" si su variación supera
    UMBRAL_VARIACION_SIGNIFICATIVA_PCT puntos; si ninguna lo hace se dice que la demanda se mantiene estable."""
    if not categorias:
        return []
    prevision, anterior = _horizonte_texto(horizonte_semanas)
    filas = []
    for fila in categorias:
        fila = fila or {}
        filas.append(
            (
                _nombre_o(fila.get("categoria"), "Sin categoría"),
                _entero_no_negativo(fila.get("total_predicho")),
                _finito_o_none(fila.get("variacion_pct")),
            )
        )
    total = sum(f[1] for f in filas)
    frases: list[str] = []

    if total == 0:
        frases.append(f"No se prevén ventas para {prevision}.")
        return frases
    frases.append(
        f"Para {prevision} se prevén {_unidades(total)} en total, repartidas en {_cantidad(len(filas), 'categoría', 'categorías')}."
    )

    maximo = max(f[1] for f in filas)
    lideres = sorted(f[0] for f in filas if f[1] == maximo)
    participacion = _porcentaje_100(maximo * 100 / total)
    if len(filas) > 1:
        if len(lideres) == 1:
            frases.append(f"La categoría con más demanda prevista es {lideres[0]}: {_unidades(maximo)}, el {participacion} del total.")
        else:
            frases.append(
                f"Las categorías {', '.join(lideres[:-1])} y {lideres[-1]} empatan con más demanda prevista: "
                f"{_unidades(maximo)} cada una."
            )

    con_variacion = [f for f in filas if f[2] is not None]
    # Desempate determinista: la de mayor volumen previsto y, si persiste, el nombre.
    crece = max(con_variacion, key=lambda f: (f[2], f[1], f[0]), default=None)
    cae = min(con_variacion, key=lambda f: (f[2], -f[1], f[0]), default=None)
    sube = crece is not None and crece[2] > UMBRAL_VARIACION_SIGNIFICATIVA_PCT
    baja = cae is not None and cae[2] < -UMBRAL_VARIACION_SIGNIFICATIVA_PCT
    if sube:
        frases.append(f"La que más crece es {crece[0]}: {_porcentaje_100(crece[2])} más que {anterior}.")
    if baja:
        frases.append(f"La que más cae es {cae[0]}: {_porcentaje_100(abs(cae[2]))} menos que {anterior}.")
    if con_variacion and not sube and not baja:
        frases.append(
            f"La demanda se mantiene estable: ninguna categoría cambia más de {_porcentaje_100(UMBRAL_VARIACION_SIGNIFICATIVA_PCT)} "
            f"frente a {anterior}."
        )
    return frases


def _es_segmento(nombre: str, base: str) -> bool:
    """'Campeones' o 'Campeones (2)': el nombre base, con o sin el sufijo que desambigua."""
    return nombre == base or nombre.startswith(base + " ")


def interpretar_segmentos(segmentos: list[dict], silhouette: float | None) -> list[str]:
    """Explica los segmentos de clientes (RFM): quién genera las ventas, quién está en riesgo y
    qué tan separados quedaron los grupos.

    Cada dict trae las claves del modelo guardado: nombre, n_clientes, pct_clientes, monto_total,
    recencia_media y frecuencia_media (esta última y la recencia pueden faltar)."""
    if not segmentos:
        return []
    filas = []
    for s in segmentos:
        s = s or {}
        filas.append(
            {
                "nombre": _nombre_o(s.get("nombre"), "Sin nombre"),
                "n": _entero_no_negativo(s.get("n_clientes")),
                "pct": _finito_o_none(s.get("pct_clientes")),
                "monto": max(0.0, _finito_o_none(s.get("monto_total")) or 0.0),
                "recencia": _finito_o_none(s.get("recencia_media")),
                "frecuencia": _finito_o_none(s.get("frecuencia_media")),
            }
        )
    total_clientes = sum(f["n"] for f in filas)
    total_monto = sum(f["monto"] for f in filas)
    for f in filas:  # sin porcentaje guardado, se calcula con los conteos
        if f["pct"] is None and total_clientes > 0:
            f["pct"] = f["n"] * 100 / total_clientes
        f["pct_monto"] = f["monto"] * 100 / total_monto if total_monto > 0 else None

    if len(filas) == 1:
        unico = filas[0]
        cuantos = f" ({_cantidad(unico['n'], 'cliente', 'clientes')})" if unico["n"] else ""
        return [
            f"Todos tus clientes{cuantos} se comportan de forma parecida: hay un solo segmento ({unico['nombre']}) "
            "y no hay grupos distintos que separar."
        ]

    frases: list[str] = []

    # 1) Quién genera las ventas: Campeones si existen; si no, el segmento de mayor monto.
    campeones = [f for f in filas if _es_segmento(f["nombre"], _SEGMENTO_CAMPEONES)]
    candidatos = campeones or filas
    estrella = max(candidatos, key=lambda f: (f["monto"], f["n"], f["nombre"]))
    if estrella["pct_monto"] is not None and estrella["monto"] > 0:
        sujeto = (
            f"El {_porcentaje_100(estrella['pct'])} de tus clientes ({estrella['nombre']})"
            if estrella["pct"] is not None
            else f"Tus clientes del grupo {estrella['nombre']}"
        )
        frases.append(f"{sujeto} genera el {_porcentaje_100(estrella['pct_monto'])} de las ventas.")
        detalle = []
        if estrella["frecuencia"] is not None:
            detalle.append(f"compró en promedio {formato_numero(estrella['frecuencia'], 1)} veces")
        if estrella["recencia"] is not None:
            detalle.append(f"su última compra fue hace {_dias(estrella['recencia'])} en promedio")
        if detalle:
            frases.append(f"Cada cliente de {estrella['nombre']} " + " y ".join(detalle) + ".")
    else:
        frases.append("Todavía no hay montos de compra para repartir entre los grupos.")

    # 2) El grupo más numeroso, si no es el que ya se nombró.
    numeroso = max(filas, key=lambda f: (f["n"], f["monto"], f["nombre"]))
    if numeroso is not estrella and numeroso["n"] > 0:
        pct = f", el {_porcentaje_100(numeroso['pct'])} de tus clientes" if numeroso["pct"] is not None else ""
        frases.append(f"El grupo más numeroso es {numeroso['nombre']}: {_cantidad(numeroso['n'], 'cliente', 'clientes')}{pct}.")

    # 3) Clientes en riesgo de irse.
    en_riesgo = [f for f in filas if any(_es_segmento(f["nombre"], base) for base in _SEGMENTOS_EN_RIESGO) and f["n"] > 0]
    if en_riesgo:
        peor = max(en_riesgo, key=lambda f: (f["n"], f["monto"], f["nombre"]))
        pct = f" ({_porcentaje_100(peor['pct'])} de tus clientes)" if peor["pct"] is not None else ""
        frase = f"El grupo en riesgo más grande es {peor['nombre']}, con {_cantidad(peor['n'], 'cliente', 'clientes')}{pct}"
        if peor["recencia"] is not None:
            frase += f", que no compra hace {_dias(peor['recencia'])} en promedio"
        frases.append(frase + ". Conviene contactarlos antes de perderlos.")
        if len(en_riesgo) > 1:
            suma = sum(f["n"] for f in en_riesgo)
            frases.append(f"En total, {_cantidad(suma, 'cliente', 'clientes')} están en riesgo o dormidos.")
    else:
        frases.append("Ningún segmento aparece en riesgo de abandono entre los grupos actuales.")

    # 4) Qué tan separados quedaron los grupos.
    s = _finito_o_none(silhouette)
    if s is None:
        frases.append("No se pudo medir qué tan separados están los grupos, así que toma la segmentación como orientativa.")
    elif s >= SILHOUETTE_BIEN_SEPARADOS:
        frases.append(f"Los grupos están bien separados (silhouette de {formato_numero(s, 2)}): la segmentación es confiable.")
    elif s >= SILHOUETTE_ACEPTABLE:
        frases.append(f"Los grupos se separan de forma aceptable (silhouette de {formato_numero(s, 2)}): úsalos como guía.")
    else:
        frases.append(
            f"Los grupos están poco separados (silhouette de {formato_numero(s, 2)}): "
            "hay clientes que podrían estar en más de un grupo, así que toma la segmentación como orientativa."
        )
    return frases


def interpretar_anomalias(anomalias: list[dict], dias: int) -> list[str]:
    """Frases sobre los días de ventas inusuales. Cada dict: {"sucursal", "desviacion_pct", "severidad"}."""
    ventana = f"los últimos {int(dias)} días" if _finito_o_none(dias) else "el periodo consultado"
    if not anomalias:
        return [f"No se detectaron días de ventas inusuales en {ventana}: todas las sucursales vendieron dentro de lo esperado."]
    fuertes = [a for a in anomalias if (a or {}).get("severidad") == "fuerte"]
    frases = [
        f"Se detectaron {_cantidad(len(anomalias), 'día inusual', 'días inusuales')} de ventas en {ventana}, "
        f"{_cantidad(len(fuertes), 'de ellos fuerte', 'de ellos fuertes')}."
    ]
    por_sucursal: dict[str, int] = {}
    for a in anomalias:
        nombre = _nombre_o((a or {}).get("sucursal"), "una sucursal")
        por_sucursal[nombre] = por_sucursal.get(nombre, 0) + 1
    nombre, cantidad = max(sorted(por_sucursal.items()), key=lambda par: par[1])
    frases.append(f"La sucursal con más días inusuales es {nombre} ({cantidad}).")
    sube = [a for a in anomalias if (_finito_o_none((a or {}).get("desviacion_pct")) or 0) > 0]
    baja = [a for a in anomalias if (_finito_o_none((a or {}).get("desviacion_pct")) or 0) < 0]
    frases.append(f"{_cantidad(len(sube), 'día vendió', 'días vendieron')} más de lo esperado y {_cantidad(len(baja), 'vendió', 'vendieron')} menos.")
    frases.append("Un día inusual no es un error: revisa si hubo una promoción, un feriado, un cierre o un problema en la tienda.")
    return frases


def interpretar_reposicion(items: list[dict], semanas: int) -> list[str]:
    """Frases sobre qué categorías se pueden agotar. Cada dict: {"categoria", "estado", "agotado_en_semana",
    "sugerencia_unidades"}."""
    if not items:
        return ["No hay categorías con demanda prevista para evaluar la reposición."]
    criticos = [i for i in items if (i or {}).get("estado") == "critico"]
    atencion = [i for i in items if (i or {}).get("estado") == "atencion"]
    if not criticos and not atencion:
        return [f"Con la demanda prevista para las próximas {int(semanas)} semanas, ninguna categoría corre riesgo de agotarse."]
    frases = []
    if criticos:
        nombres = ", ".join(_nombre_o((i or {}).get("categoria"), "una categoría") for i in criticos)
        frases.append(f"{_cantidad(len(criticos), 'categoría está', 'categorías están')} en estado crítico (menos de 2 semanas de cobertura): {nombres}.")
    if atencion:
        nombres = ", ".join(_nombre_o((i or {}).get("categoria"), "una categoría") for i in atencion)
        frases.append(f"{_cantidad(len(atencion), 'categoría requiere', 'categorías requieren')} atención (no alcanzan para las {int(semanas)} semanas): {nombres}.")
    sugeridas = sum(_entero_no_negativo((i or {}).get("sugerencia_unidades")) for i in criticos + atencion)
    frases.append(f"La reposición orientativa suma {_cantidad(sugeridas, 'unidad', 'unidades')}, con un colchón de 10%.")
    return frases


def interpretar_estado(modelos: list[dict]) -> list[str]:
    """Una frase por modelo que orienta qué hacer según su vigencia.

    Cada dict: {"titulo", "estado" ('sin_entrenar'|'vigente'|'desactualizado'|'obsoleto'), "version",
    "dias_desde_entrenamiento"}."""
    frases = []
    for modelo in modelos or []:
        modelo = modelo or {}
        titulo = _nombre_o(modelo.get("titulo"), "El modelo")
        estado = modelo.get("estado")
        version = _finito_o_none(modelo.get("version"))
        dias = _finito_o_none(modelo.get("dias_desde_entrenamiento"))
        dias = None if dias is None else max(0, int(dias))
        sufijo_version = f" (versión {int(version)})" if version is not None else ""
        if estado == "sin_entrenar":
            frases.append(f"{titulo}: aún no está entrenado. Entrénalo desde Analítica para ver resultados.")
        elif estado == "vigente":
            cuando = "hoy" if dias == 0 else f"hace {_dias(dias)}" if dias is not None else None
            detalle = f", entrenado {cuando}" if cuando else ""
            frases.append(f"{titulo}: está al día{sufijo_version}{detalle}. No necesitas hacer nada.")
        elif estado == "desactualizado":
            tiene = f"Tiene {_dias(dias)}" if dias is not None else "Lleva un tiempo sin entrenarse"
            frases.append(f"{titulo}: {tiene}{sufijo_version}; conviene reentrenarlo para incluir las ventas recientes.")
        elif estado == "obsoleto":
            tiene = f"Lleva {_dias(dias)} sin entrenarse" if dias is not None else "Lleva mucho tiempo sin entrenarse"
            frases.append(
                f"{titulo}: {tiene}{sufijo_version}. Sus resultados pueden no reflejar cómo vende tu tienda hoy; reentrénalo pronto."
            )
        else:
            frases.append(f"{titulo}: no se pudo determinar su estado. Revisa o reentrena el modelo desde Analítica.")
    return frases
