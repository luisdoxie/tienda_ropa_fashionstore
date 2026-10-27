"""E10: lo que prepara el documento antes de construir el archivo. Todo es puro (sin base ni red):
totales con Decimal, líneas de filtros, adaptador del reporte generativo, la solicitud resuelta de
vuelta a solicitud, y los datos del gráfico (tope de categorías y pivote de barras agrupadas)."""

import datetime as dt
from decimal import Decimal

import pytest

from app.core.tiempo import ZONA_BOLIVIA, ahora_bolivia
from app.inteligencia.exportacion_comun import (
    ETIQUETA_OTROS,
    MAX_CATEGORIAS_GRAFICO,
    MAX_PERIODOS_AGRUPADAS,
    datos_de_grafico,
    texto_de_generacion,
)
from app.inteligencia.politicas import (
    calcular_totales,
    documento_desde_reporte,
    formato_bs,
    formato_fecha,
    formato_numero,
    lineas_de_filtros,
    solicitud_desde_resuelta,
)
from app.inteligencia.registro_reportes import REGISTRO
from app.inteligencia.schemas import (
    ColumnaReporte,
    GraficoSugerido,
    PeriodoResuelto,
    ReferenciaResuelta,
    ReporteEjecutado,
    ReporteGenerativoRespuesta,
    SeccionReporte,
    SolicitudReporte,
    SolicitudResuelta,
)

AHORA = dt.datetime(2026, 9, 20, 14, 5, tzinfo=ZONA_BOLIVIA)


# ---- Formatos y reloj -------------------------------------------------------------------------


def test_los_formatos_son_los_de_bolivia():
    assert formato_numero(1250.5) == "1.250,50"
    assert formato_numero(1250, 0) == "1.250"
    assert formato_numero(Decimal("1234567.891"), 2) == "1.234.567,89"
    assert formato_bs(Decimal("12400.5")) == "Bs 12.400,50"
    assert formato_fecha(dt.date(2026, 9, 1)) == "01/09/2026"


def test_ahora_bolivia_es_utc_menos_4():
    ahora = ahora_bolivia()

    assert ahora.utcoffset() == dt.timedelta(hours=-4)
    assert abs(ahora - dt.datetime.now(dt.timezone.utc)) < dt.timedelta(seconds=5)
    assert texto_de_generacion(AHORA) == "20/09/2026 14:05 (hora de Bolivia)"


# ---- Totales ----------------------------------------------------------------------------------

COLUMNAS = [
    ColumnaReporte(clave="sucursal", titulo="Sucursal", tipo="texto"),
    ColumnaReporte(clave="transacciones", titulo="Transacciones", tipo="entero"),
    ColumnaReporte(clave="total_ventas", titulo="Total", tipo="moneda"),
    ColumnaReporte(clave="ticket_promedio", titulo="Ticket", tipo="moneda"),
    ColumnaReporte(clave="participacion", titulo="Participación", tipo="porcentaje"),
]


def test_los_totales_suman_solo_las_columnas_sumables_con_decimal():
    filas = [
        {"sucursal": "A", "transacciones": 2, "total_ventas": 0.1, "ticket_promedio": 0.05, "participacion": 50.0},
        {"sucursal": "B", "transacciones": 3, "total_ventas": 0.2, "ticket_promedio": 0.07, "participacion": 50.0},
    ]

    totales = calcular_totales(COLUMNAS, filas)

    assert totales == {"transacciones": 5, "total_ventas": Decimal("0.30")}  # 0.1 + 0.2 = 0.30 exacto, no 0.30000000000000004
    assert isinstance(totales["transacciones"], int)


def test_sin_filas_o_sin_columnas_sumables_no_hay_totales():
    assert calcular_totales(COLUMNAS, []) is None
    assert calcular_totales(COLUMNAS[:1] + COLUMNAS[3:], [{"sucursal": "A", "ticket_promedio": 1.0}]) is None


def test_los_valores_vacios_no_rompen_los_totales():
    filas = [{"transacciones": None, "total_ventas": 10.5}, {"transacciones": 4, "total_ventas": None}]

    assert calcular_totales(COLUMNAS, filas) == {"transacciones": 4, "total_ventas": Decimal("10.50")}


# ---- Filtros y adaptador ----------------------------------------------------------------------


def _resuelta(**cambios) -> SolicitudResuelta:
    base = dict(
        tipo_reporte="ventas_por_sucursal",
        periodo=PeriodoResuelto(desde=dt.date(2026, 9, 1), hasta=dt.date(2026, 9, 20), etiqueta="01/09/2026 al 20/09/2026"),
    )
    return SolicitudResuelta(**{**base, **cambios})


def test_las_lineas_de_filtros_dicen_lo_que_abarca_el_reporte():
    lineas = lineas_de_filtros(_resuelta())

    assert lineas == [
        "Periodo: 01/09/2026 al 20/09/2026",
        "Sucursales: todas",
        "Categorías: todas",
        "Canal: todos",
    ]


def test_las_lineas_de_filtros_con_valores():
    lineas = lineas_de_filtros(
        _resuelta(
            tipo_reporte="productos_mas_vendidos",
            sucursales=[ReferenciaResuelta(id=1, nombre="Norte"), ReferenciaResuelta(id=2, nombre="Centro")],
            categorias=[ReferenciaResuelta(id=3, nombre="Camisas")],
            canal="presencial",
            orden="menor_a_mayor",
            limite=5,
        )
    )

    assert "Sucursales: Norte, Centro" in lineas and "Categorías: Camisas" in lineas
    assert "Canal: presencial" in lineas
    assert "Orden: de menor a mayor" in lineas and "Máximo de filas: 5" in lineas


def test_un_reporte_sin_periodo_no_pone_linea_de_periodo():
    lineas = lineas_de_filtros(SolicitudResuelta(tipo_reporte="productos_menor_existencia", limite=10))

    assert not any(linea.startswith("Periodo") for linea in lineas)
    assert "Máximo de filas: 10" in lineas


def _respuesta(filas, *, truncado=False, avisos=None) -> ReporteGenerativoRespuesta:
    definicion = REGISTRO["ventas_por_sucursal"]
    return ReporteGenerativoRespuesta(
        estado="ok",
        mensaje="Listo",
        avisos=avisos or [],
        solicitud=_resuelta(),
        reporte=ReporteEjecutado(
            codigo=definicion.codigo,
            titulo=definicion.titulo,
            columnas=list(definicion.columnas),
            filas=filas,
            resumen={},
            grafico_sugerido=definicion.grafico,
            truncado=truncado,
            generado_en=dt.datetime(2026, 9, 20, 18, 5, tzinfo=dt.timezone.utc),
        ),
        narrativa="Se vendió Bs 740,00.",
    )


FILAS = [
    {"sucursal": "Norte", "transacciones": 2, "total_ventas": 390.0, "ticket_promedio": 195.0, "participacion": 52.7},
    {"sucursal": "Centro", "transacciones": 2, "total_ventas": 350.0, "ticket_promedio": 175.0, "participacion": 47.3},
]


def test_el_documento_trae_titulo_empresa_filtros_narrativa_y_totales():
    doc = documento_desde_reporte(_respuesta(FILAS, avisos=["Un aviso"]), "FashionStore", AHORA)

    assert doc.titulo == "Ventas por sucursal" and doc.empresa_nombre == "FashionStore"
    assert doc.generado_en == AHORA and doc.subtitulo == "Se vendió Bs 740,00."
    assert doc.filtros[0] == "Periodo: 01/09/2026 al 20/09/2026" and doc.avisos == ["Un aviso"]
    seccion = doc.secciones[0]
    assert seccion.totales == {"transacciones": 4, "total_ventas": Decimal("740.00")}
    assert seccion.grafico.tipo == "barras" and seccion.filas == FILAS


def test_las_columnas_de_dinero_llevan_bs_en_el_titulo_y_las_demas_no():
    seccion = documento_desde_reporte(_respuesta(FILAS), "FashionStore", AHORA).secciones[0]

    titulos = {c.clave: c.titulo for c in seccion.columnas}
    assert titulos["total_ventas"] == "Total vendido (Bs)" and titulos["ticket_promedio"] == "Ticket promedio (Bs)"
    assert titulos["sucursal"] == "Sucursal" and titulos["participacion"] == "Participación"


def test_un_reporte_recortado_no_lleva_totales_y_marca_truncado():
    doc = documento_desde_reporte(_respuesta(FILAS, truncado=True), "FashionStore", AHORA)

    assert doc.truncado is True and doc.secciones[0].totales is None


def test_solo_se_adapta_un_reporte_ejecutado():
    sin_reporte = ReporteGenerativoRespuesta(estado="ambigua", mensaje="No encontré")

    with pytest.raises(ValueError):
        documento_desde_reporte(sin_reporte, "FashionStore", AHORA)


# ---- La solicitud resuelta de vuelta a solicitud ----------------------------------------------


def test_la_resuelta_vuelve_a_ser_una_solicitud_con_nombres_y_rango_de_fechas():
    resuelta = _resuelta(
        sucursales=[ReferenciaResuelta(id=99, nombre="Norte")],
        categorias=[ReferenciaResuelta(id=7, nombre="Camisas")],
        productos=[ReferenciaResuelta(id=5, nombre="Camisa Oxford")],
        canal="digital",
        agrupacion="mes",
        orden="mayor_a_menor",
        limite=3,
    )

    solicitud = solicitud_desde_resuelta(resuelta)

    assert isinstance(solicitud, SolicitudReporte)
    assert solicitud.sucursales == ["Norte"] and solicitud.categorias == ["Camisas"] and solicitud.productos == ["Camisa Oxford"]
    assert solicitud.periodo.tipo == "rango_fechas"
    assert (solicitud.periodo.desde.dia, solicitud.periodo.desde.mes, solicitud.periodo.desde.anio) == (1, 9, 2026)
    assert (solicitud.periodo.hasta.dia, solicitud.periodo.hasta.mes, solicitud.periodo.hasta.anio) == (20, 9, 2026)
    assert (solicitud.canal, solicitud.agrupacion, solicitud.orden, solicitud.limite) == ("digital", "mes", "mayor_a_menor", 3)
    assert "id" not in solicitud.model_dump_json()  # los ids no viajan


def test_la_resuelta_sin_periodo_queda_sin_periodo():
    assert solicitud_desde_resuelta(SolicitudResuelta(tipo_reporte="productos_menor_existencia")).periodo is None


# ---- Datos del gráfico ------------------------------------------------------------------------


def _seccion(grafico, filas, columnas=None) -> SeccionReporte:
    columnas = columnas or [
        ColumnaReporte(clave="x", titulo="Eje X", tipo="texto"),
        ColumnaReporte(clave="y", titulo="Valor", tipo="moneda"),
        ColumnaReporte(clave="serie", titulo="Serie", tipo="texto"),
    ]
    return SeccionReporte(titulo="T", columnas=columnas, filas=filas, grafico=grafico)


@pytest.mark.parametrize("tipo", ["tabla"])
def test_sin_grafico_cuando_es_tabla_o_no_hay_nada_que_dibujar(tipo):
    filas = [{"x": "a", "y": 1}]
    assert datos_de_grafico(_seccion(GraficoSugerido(tipo=tipo, eje_x="x", eje_y="y"), filas)) is None
    assert datos_de_grafico(_seccion(None, filas)) is None
    assert datos_de_grafico(_seccion(GraficoSugerido(tipo="barras", eje_x="x", eje_y="y"), [])) is None
    assert datos_de_grafico(_seccion(GraficoSugerido(tipo="barras", eje_x="nada", eje_y="y"), filas)) is None
    assert datos_de_grafico(_seccion(GraficoSugerido(tipo="barras", eje_x="x", eje_y="y"), [{"x": "a", "y": "texto"}])) is None


def test_barras_con_pocas_categorias_van_tal_cual():
    filas = [{"x": "Norte", "y": 390.0}, {"x": "Centro", "y": 350.0}]

    datos = datos_de_grafico(_seccion(GraficoSugerido(tipo="barras", eje_x="x", eje_y="y"), filas))

    assert datos.categorias == ["Norte", "Centro"] and datos.series == {"Valor": [390.0, 350.0]}
    assert datos.recortado is False and datos.titulo_categorias == "Eje X"


def test_mas_de_12_categorias_agrupa_las_menores_en_otros():
    filas = [{"x": f"c{i:02d}", "y": float(i)} for i in range(1, 21)]  # 20 categorías, 1..20

    datos = datos_de_grafico(_seccion(GraficoSugerido(tipo="torta", eje_x="x", eje_y="y"), filas))

    assert len(datos.categorias) == MAX_CATEGORIAS_GRAFICO and datos.categorias[-1] == ETIQUETA_OTROS
    assert datos.recortado is True
    valores = datos.series["Valor"]
    assert sum(valores) == sum(range(1, 21))  # nada se pierde
    assert valores[-1] == sum(range(1, 10))  # Otros = las 9 menores (1..9); quedan 11 mayores (10..20)
    assert "c01" not in datos.categorias and "c20" in datos.categorias


def test_la_linea_conserva_todos_los_puntos_en_orden():
    filas = [{"x": f"d{i}", "y": float(i)} for i in range(40)]

    datos = datos_de_grafico(_seccion(GraficoSugerido(tipo="linea", eje_x="x", eje_y="y"), filas))

    assert len(datos.categorias) == 40 and datos.categorias[0] == "d0" and datos.recortado is False


def test_barras_agrupadas_hacen_un_pivote_periodo_por_serie():
    filas = [
        {"x": "07/2026", "serie": "Norte", "y": 100.0},
        {"x": "07/2026", "serie": "Centro", "y": 80.0},
        {"x": "08/2026", "serie": "Norte", "y": 120.0},
        {"x": "08/2026", "serie": "Centro", "y": None},
        {"x": "09/2026", "serie": "Centro", "y": 90.0},
    ]

    datos = datos_de_grafico(_seccion(GraficoSugerido(tipo="barras_agrupadas", eje_x="x", eje_y="y", serie="serie"), filas))

    assert datos.categorias == ["07/2026", "08/2026", "09/2026"]
    assert datos.series == {"Centro": [80.0, 0.0, 90.0], "Norte": [100.0, 120.0, 0.0]}  # lo que falta vale 0


def test_barras_agrupadas_dibuja_solo_los_ultimos_periodos():
    filas = [{"x": f"p{i:02d}", "serie": "A", "y": float(i)} for i in range(20)]

    datos = datos_de_grafico(_seccion(GraficoSugerido(tipo="barras_agrupadas", eje_x="x", eje_y="y", serie="serie"), filas))

    assert len(datos.categorias) == MAX_PERIODOS_AGRUPADAS and datos.categorias[-1] == "p19" and datos.recortado is True
