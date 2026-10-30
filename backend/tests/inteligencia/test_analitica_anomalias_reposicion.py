"""CU-24 (E12b): las rutas nuevas de la analítica, `GET /api/v1/analitica/anomalias` y `GET /api/v1/analitica/reposicion`,
más lo que el tercer modelo (`anomalias_ventas`) cambia en `/estado`, `/entrenar` y `/panel`.

Cada prueba compara contra algo calculado por otro camino: el detector llamado directamente sobre el artefacto guardado
y sobre las filas que lee `comercial` (o sobre filas armadas a mano desde el historial sintético, sin base de datos), el
stock sumado con el ORM desde `cantidad_fisica - cantidad_reservada` (sin la columna generada ni la vista de
inventario), y la regla de reposición recalculada aquí con la demanda que devuelve `/demanda`. Escenario: el de
`_analitica_comun` (FashionStore, 40 semanas, 80 clientes, fin el 25/10/2026; la aplicación cree que hoy es `HOY`).

Los 409 de `/anomalias` y `/reposicion` ("modelo_no_entrenado") dependen cada uno de SU modelo: el de anomalías no usa
el de demanda, y la reposición no usa el de anomalías."""

import datetime as dt
import math
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.catalogo import politicas as catalogo_politicas
from app.catalogo.models import Producto, ProductoVariante, Stock
from app.comercial import politicas as comercial_politicas
from app.core.deps import ParametrosPeriodo
from app.core.rate_limit import limiter
from app.core.tenant import en_empresa
from app.inteligencia.casos_uso import cu24_analizar_con_machine_learning as cu24
from app.inteligencia.casos_uso.cu24_analizar_con_machine_learning import (
    CACHE_MODELOS,
    TIPO_ANOMALIAS,
    TIPO_DEMANDA,
    TIPO_SEGMENTOS,
)
from app.inteligencia.ml import anomalias as ml_anomalias
from app.inteligencia.ml import persistencia
from app.inteligencia.models import ModeloML
from app.inteligencia.repository import ModeloMLRepository
from app.plataforma.models import Sucursal
from tests.inteligencia._analitica_comun import FIN, HOY, cabeceras_de, cargar_historia, entrenar, id_de, poblar_mundo
from tests.inteligencia.test_analitica_endpoints import _fila_modelo, _get, _ok, _sin_artefacto, _sin_datos_de_cliente

BASE = "/api/v1/analitica"
TIPOS = [TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS]
CAMPOS_ANOMALIA = {"fecha", "sucursal_id", "sucursal", "total_ventas", "esperado", "desviacion_pct", "severidad"}
CAMPOS_ITEM = {
    "categoria_id", "categoria", "disponible", "demanda_semanal_promedio", "semanas_cobertura", "agotado_en_semana",
    "estado", "sugerencia_unidades",
}  # fmt: skip
ORDEN_ESTADO = {"critico": 0, "atencion": 1, "ok": 2}


# ---- Escenario ---------------------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fecha_fija_y_cache_limpia(monkeypatch):
    """La fecha de la aplicación es HOY (FIN + 1) y el caché de modelos arranca y termina vacío."""
    monkeypatch.setattr(cu24, "hoy_utc", lambda: HOY)
    for empresa_id in range(1, 12):
        CACHE_MODELOS.invalidar(empresa_id)
    yield
    for empresa_id in range(1, 12):
        CACHE_MODELOS.invalidar(empresa_id)


@pytest.fixture()
def mundo(db_session, tmp_path):
    poblar_mundo(db_session, tmp_path)
    return db_session


@pytest.fixture()
def fs(mundo):
    """FashionStore con su historial sintético cargado y SIN modelos."""
    empresa_id, catalogo, historial, _ = cargar_historia(mundo, "fashionstore")
    return SimpleNamespace(
        db=mundo, id=empresa_id, h=cabeceras_de(mundo, "fashionstore"), catalogo=catalogo, historial=historial
    )


@pytest.fixture()
def entrenado(fs):
    """FashionStore con los TRES modelos entrenados (versión 1) hasta `FIN`."""
    resumen = entrenar(fs.db, "fashionstore")
    assert resumen.entrenados == TIPOS
    return fs


# ---- Ayudas: el cálculo independiente ----------------------------------------------------------------------------------


def _nombres_de_sucursales(db, empresa_id) -> dict[int, str]:
    with en_empresa(db, empresa_id):
        return {s.id: s.nombre for s in db.scalars(select(Sucursal))}


def _filas_de_comercial(db, empresa_id, dias: int, hasta: dt.date = FIN) -> list[dict]:
    """Lo que lee el detector: la serie diaria por sucursal, `dias` + 56 días hacia atrás, hasta `hasta` (por defecto `FIN`)."""
    with en_empresa(db, empresa_id):
        periodo = ParametrosPeriodo(desde=hasta - dt.timedelta(days=dias + 56), hasta=hasta)
        return comercial_politicas.reporte_ventas_serie_diaria(db, periodo, desglose=("sucursal",))


def _filas_sinteticas(fs) -> list[dict]:
    """La serie diaria por sucursal armada a mano desde el historial sintético: ni base de datos ni `comercial`."""
    nombres = _nombres_de_sucursales(fs.db, fs.id)
    acumulado: dict[tuple[dt.date, int], dict] = {}
    for venta in fs.historial.ventas:
        if venta.estado not in ("pagada", "entregada"):
            continue
        fila = acumulado.setdefault((venta.fecha, venta.sucursal_id), {"transacciones": 0, "unidades": 0, "total": Decimal("0")})
        fila["transacciones"] += 1
        for linea in venta.lineas:
            fila["unidades"] += linea.cantidad
            fila["total"] += linea.precio_unitario * linea.cantidad - linea.descuento
    return [
        {
            "dia": dia, "sucursal_id": sucursal_id, "sucursal": nombres[sucursal_id], "transacciones": f["transacciones"],
            "unidades": f["unidades"], "total_ventas": f["total"].quantize(Decimal("0.01")),
        }
        for (dia, sucursal_id), f in sorted(acumulado.items())
    ]  # fmt: skip


def _artefacto(db, empresa_id, tipo) -> dict:
    fila = _fila_modelo(db, empresa_id, tipo, con_artefacto=True)
    return persistencia.deserializar(fila.artefacto, fila.artefacto_sha256)


def _como_dicts(detectadas) -> list[dict]:
    return [
        {
            "fecha": a.fecha.isoformat(), "sucursal_id": a.sucursal_id, "sucursal": a.sucursal, "total_ventas": a.total_ventas,
            "esperado": a.esperado, "desviacion_pct": a.desviacion_pct, "severidad": a.severidad,
        }
        for a in detectadas
    ]  # fmt: skip


def _stock_de_categoria(db, empresa_id, categoria_id) -> list[Stock]:
    """Las filas de stock de las variantes ACTIVAS de productos ACTIVOS de la categoría (por id exacto)."""
    with en_empresa(db, empresa_id):
        consulta = (
            select(Stock)
            .join(ProductoVariante, ProductoVariante.id == Stock.variante_id)
            .join(Producto, Producto.id == ProductoVariante.producto_id)
            .where(Producto.categoria_id == categoria_id, Producto.activo.is_(True), ProductoVariante.activo.is_(True))
            .order_by(Stock.id)
        )
        filas = list(db.scalars(consulta))
        for fila in filas:
            _ = fila.cantidad_fisica  # cargadas antes de salir del alcance de la empresa
        return filas


def _disponible_a_mano(db, empresa_id, categoria_id) -> int:
    """Unidades disponibles (física menos reservada) de la categoría en todas las sucursales, sin pasar por la columna
    generada ni por la vista de inventario."""
    with en_empresa(db, empresa_id):
        ids = [s.id for s in _stock_de_categoria(db, empresa_id, categoria_id)]
        filas = db.scalars(select(Stock).where(Stock.id.in_(ids))).all() if ids else []
        return max(sum(s.cantidad_fisica - s.cantidad_reservada for s in filas), 0)


def _fijar_disponible(db, empresa_id, categoria_id, unidades: int) -> None:
    """Deja la categoría con EXACTAMENTE `unidades` disponibles: todo en cero y el total en la primera fila de stock."""
    with en_empresa(db, empresa_id):
        ids = [s.id for s in _stock_de_categoria(db, empresa_id, categoria_id)]
        assert ids, "la categoría no tiene filas de stock"
        for i, fila in enumerate(db.scalars(select(Stock).where(Stock.id.in_(ids)).order_by(Stock.id))):
            fila.cantidad_reservada = 0
            fila.cantidad_fisica = unidades if i == 0 else 0
        db.commit()
    assert _disponible_a_mano(db, empresa_id, categoria_id) == unidades


def _categorias_con_demanda(client, cabeceras, semanas: int) -> list[dict]:
    cuerpo = _ok(_get(client, "demanda", cabeceras, semanas=semanas))
    return [c for c in cuerpo["categorias"] if c["total_predicho"] > 0]


# ---- /anomalias --------------------------------------------------------------------------------------------------------


def test_sin_el_modelo_de_anomalias_da_409_aunque_esten_los_otros_dos(client_por_peticion, fs):
    entrenar(fs.db, "fashionstore", [TIPO_DEMANDA, TIPO_SEGMENTOS])

    respuesta = _get(client_por_peticion, "anomalias", fs.h)

    assert respuesta.status_code == 409, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "modelo_no_entrenado" and cuerpo["tipo"] == TIPO_ANOMALIAS
    assert cuerpo["mensaje"] == cu24.MENSAJE_SIN_MODELO
    assert "anomalias" not in cuerpo  # y tampoco hay lista parcial


def test_anomalias_trae_la_estructura_completa_y_la_ventana_de_90_dias_hasta_ayer(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "anomalias", entrenado.h))

    assert cuerpo["dias"] == 90
    assert cuerpo["hasta"] == FIN.isoformat() == (HOY - dt.timedelta(days=1)).isoformat()
    assert cuerpo["desde"] == (FIN - dt.timedelta(days=89)).isoformat()
    assert cuerpo["modelo"]["tipo"] == TIPO_ANOMALIAS and cuerpo["modelo"]["estado"] == "vigente" and cuerpo["modelo"]["version"] == 1
    assert cuerpo["avisos"] == [] and cuerpo["grafico_sugerido"]["tipo"] == "tabla"
    assert len(cuerpo["supuestos"]) >= 5 and all(isinstance(s, str) and s.strip() for s in cuerpo["supuestos"])
    assert cuerpo["interpretacion"] and all(isinstance(f, str) and len(f.strip()) > 10 for f in cuerpo["interpretacion"])
    assert set(cuerpo) == {
        "modelo", "dias", "desde", "hasta", "anomalias", "total", "fuertes", "supuestos", "interpretacion", "grafico_sugerido", "avisos",
    }  # fmt: skip
    for anomalia in cuerpo["anomalias"]:
        assert set(anomalia) == CAMPOS_ANOMALIA
        assert isinstance(anomalia["sucursal"], str) and anomalia["sucursal"].strip()
        assert anomalia["total_ventas"] >= 0 and anomalia["esperado"] > 0


def test_las_anomalias_estan_ordenadas_dentro_de_la_ventana_y_total_y_fuertes_cuadran(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "anomalias", entrenado.h, dias=365))
    lista = cuerpo["anomalias"]
    desde, hasta = dt.date.fromisoformat(cuerpo["desde"]), dt.date.fromisoformat(cuerpo["hasta"])

    assert lista, "con 365 días el escenario debe marcar al menos un día (la liquidación inyectada)"
    fechas = [dt.date.fromisoformat(a["fecha"]) for a in lista]
    assert all(desde <= f <= hasta for f in fechas)
    assert fechas == sorted(fechas, reverse=True)  # de la fecha más reciente a la más antigua
    for anterior, actual in zip(lista, lista[1:]):  # dentro de un mismo día, las fuertes primero
        if anterior["fecha"] == actual["fecha"]:
            assert not (anterior["severidad"] == "leve" and actual["severidad"] == "fuerte")
    assert {a["severidad"] for a in lista} <= {"leve", "fuerte"}
    assert cuerpo["total"] == len(lista)
    assert cuerpo["fuertes"] == sum(1 for a in lista if a["severidad"] == "fuerte") >= 1
    assert len({(a["fecha"], a["sucursal_id"]) for a in lista}) == len(lista)  # un día-sucursal no se repite


def test_la_severidad_y_la_desviacion_se_recalculan_a_mano_desde_el_total_y_lo_esperado(client_por_peticion, entrenado):
    lista = _ok(_get(client_por_peticion, "anomalias", entrenado.h, dias=365))["anomalias"]
    assert lista

    for a in lista:
        desviacion = (a["total_ventas"] - a["esperado"]) / a["esperado"] * 100
        assert a["desviacion_pct"] == pytest.approx(desviacion, abs=0.1 + 100.0 / a["esperado"] * 0.01), a
        # El signo cuenta la dirección y la severidad la magnitud (límite de 60 %; la banda evita el redondeo).
        if abs(a["desviacion_pct"]) >= 60.1:
            assert a["severidad"] == "fuerte", a
        if abs(a["desviacion_pct"]) <= 59.9:
            assert a["severidad"] == "leve", a
    assert {a["severidad"] for a in lista} <= {"leve", "fuerte"}


@pytest.mark.parametrize(
    "hoy, dias",
    [
        pytest.param(HOY, 90, id="hoy-90"),
        pytest.param(HOY, 365, id="hoy-365"),
        pytest.param(dt.date(2026, 9, 20), 30, id="20sep-30"),
        pytest.param(dt.date(2026, 7, 15), 30, id="15jul-30"),
        pytest.param(dt.date(2026, 9, 16), 7, id="16sep-7"),  # cubre el día de liquidación del 14/09
    ],
)
def test_la_respuesta_http_es_lo_que_da_el_detector_sobre_el_artefacto_guardado_y_las_mismas_filas(
    client_por_peticion, entrenado, monkeypatch, hoy, dias
):
    """Con la fecha de la aplicación movida hacia atrás, las ventanas de 7 y 30 días caen sobre días marcados (con la
    de hoy están vacías en este escenario): así la igualdad no es entre dos listas vacías."""
    monkeypatch.setattr(cu24, "hoy_utc", lambda: hoy)
    hasta = hoy - dt.timedelta(days=1)
    artefacto = _artefacto(entrenado.db, entrenado.id, TIPO_ANOMALIAS)
    esperadas = _como_dicts(
        ml_anomalias.detectar_anomalias(artefacto, _filas_de_comercial(entrenado.db, entrenado.id, dias, hasta), hasta, dias)
    )
    assert esperadas, "la ventana elegida debe contener días marcados"

    cuerpo = _ok(_get(client_por_peticion, "anomalias", entrenado.h, dias=dias))

    assert cuerpo["hasta"] == hasta.isoformat() and cuerpo["desde"] == (hasta - dt.timedelta(days=dias - 1)).isoformat()
    assert cuerpo["anomalias"] == esperadas
    assert cuerpo["total"] == len(esperadas)
    assert cuerpo["fuertes"] == sum(1 for a in esperadas if a["severidad"] == "fuerte")


def test_con_filas_armadas_a_mano_desde_el_historial_sintetico_el_detector_marca_los_mismos_dias(client_por_peticion, entrenado):
    """Tercer camino: ni la base ni `comercial`. Si la serie leída de la base se desviara del historial, esto falla."""
    cuerpo = _ok(_get(client_por_peticion, "anomalias", entrenado.h, dias=365))
    sinteticas = _filas_sinteticas(entrenado)

    detectadas = ml_anomalias.detectar_anomalias(_artefacto(entrenado.db, entrenado.id, TIPO_ANOMALIAS), sinteticas, FIN, 365)

    assert detectadas
    assert {(a["fecha"], a["sucursal_id"], a["severidad"]) for a in cuerpo["anomalias"]} == {
        (a.fecha.isoformat(), a.sucursal_id, a.severidad) for a in detectadas
    }
    assert [a["total_ventas"] for a in cuerpo["anomalias"]] == [a.total_ventas for a in detectadas]


def test_la_liquidacion_inyectada_en_el_historial_se_detecta_como_un_pico_fuerte(client_por_peticion, entrenado):
    inyectadas = {a.tipo: a for a in entrenado.historial.anomalias}
    liquidacion = inyectadas["liquidacion"]

    lista = _ok(_get(client_por_peticion, "anomalias", entrenado.h, dias=365))["anomalias"]

    encontrada = [a for a in lista if a["fecha"] == liquidacion.fecha.isoformat() and a["sucursal_id"] == liquidacion.sucursal_id]
    assert len(encontrada) == 1, (liquidacion, lista)
    assert encontrada[0]["severidad"] == "fuerte" and encontrada[0]["desviacion_pct"] > 60  # vendió MÁS de lo esperado
    assert encontrada[0]["total_ventas"] > encontrada[0]["esperado"]
    # Y el cierre, si se ve, es una caída (nunca un pico).
    cierre = inyectadas["cierre"]
    visto = [a for a in lista if a["fecha"] == cierre.fecha.isoformat() and a["sucursal_id"] == cierre.sucursal_id]
    assert all(a["desviacion_pct"] < 0 for a in visto)


def test_no_se_ven_anomalias_donde_no_hay_ventas_ni_se_marca_casi_todo(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "anomalias", entrenado.h, dias=365))
    con_ventas = {v.sucursal_id for v in entrenado.historial.ventas}
    todas = _nombres_de_sucursales(entrenado.db, entrenado.id)
    assert set(todas) - con_ventas, "el escenario debe tener sucursales sin ventas (el depósito) para que la prueba valga"

    assert {a["sucursal_id"] for a in cuerpo["anomalias"]} <= con_ventas
    assert {a["sucursal"] for a in cuerpo["anomalias"]} <= {todas[i] for i in con_ventas}
    # Solo una fracción pequeña de los días-sucursal se marca (el detector apunta a ~2,5 %).
    dias_sucursal = len({(v.fecha, v.sucursal_id) for v in entrenado.historial.ventas})
    assert cuerpo["total"] <= 0.08 * dias_sucursal, (cuerpo["total"], dias_sucursal)


def test_una_ventana_corta_es_lo_mismo_que_recortar_la_larga_y_dias_mueve_desde(client_por_peticion, entrenado, monkeypatch):
    monkeypatch.setattr(cu24, "hoy_utc", lambda: dt.date(2026, 9, 20))  # hasta = 19/09: la ventana de 30 días tiene días marcados
    hasta = dt.date(2026, 9, 19)
    larga = _ok(_get(client_por_peticion, "anomalias", entrenado.h, dias=365))
    corta = _ok(_get(client_por_peticion, "anomalias", entrenado.h, dias=30))

    assert corta["dias"] == 30 and corta["desde"] == (hasta - dt.timedelta(days=29)).isoformat() and corta["hasta"] == larga["hasta"]
    assert larga["dias"] == 365 and larga["desde"] == (hasta - dt.timedelta(days=364)).isoformat()
    recortada = [a for a in larga["anomalias"] if a["fecha"] >= corta["desde"]]
    assert corta["anomalias"] == recortada
    assert 1 <= corta["total"] < larga["total"]  # la corta tiene lo suyo y la larga, además, lo anterior


@pytest.mark.parametrize("dias, esperado", [(6, 422), (7, 200), (365, 200), (366, 422), (0, 422), (-5, 422), ("abc", 422), ("", 422)])
def test_los_limites_de_dias_son_7_y_365(client_por_peticion, entrenado, dias, esperado):
    respuesta = client_por_peticion.get(f"{BASE}/anomalias", headers=entrenado.h, params={"dias": dias})

    assert respuesta.status_code == esperado, respuesta.text
    if esperado == 200:
        assert respuesta.json()["dias"] == dias


def test_el_modelo_de_anomalias_funciona_sin_el_de_demanda_ni_el_de_segmentos(client_por_peticion, fs):
    entrenar(fs.db, "fashionstore", [TIPO_ANOMALIAS])

    cuerpo = _ok(_get(client_por_peticion, "anomalias", fs.h, dias=365))

    assert cuerpo["modelo"]["tipo"] == TIPO_ANOMALIAS and cuerpo["total"] >= 1
    # Control: los otros dos siguen sin modelo, y el detector no los necesita.
    assert _get(client_por_peticion, "demanda", fs.h).status_code == 409
    assert _get(client_por_peticion, "segmentos", fs.h).status_code == 409
    assert _get(client_por_peticion, "reposicion", fs.h).status_code == 409


def test_anomalias_no_usa_el_modelo_de_demanda_aunque_este_vigente(client_por_peticion, fs):
    entrenar(fs.db, "fashionstore", [TIPO_DEMANDA])

    respuesta = _get(client_por_peticion, "anomalias", fs.h)

    assert respuesta.status_code == 409 and respuesta.json()["tipo"] == TIPO_ANOMALIAS


def test_un_artefacto_de_anomalias_alterado_da_409_modelo_obsoleto_y_los_otros_modelos_siguen(client_por_peticion, entrenado):
    with en_empresa(entrenado.db, entrenado.id):
        fila = ModeloMLRepository().obtener_activo(entrenado.db, TIPO_ANOMALIAS, con_artefacto=True)
        fila.artefacto_sha256 = "0" * 64
        entrenado.db.commit()
    CACHE_MODELOS.invalidar(entrenado.id)

    respuesta = _get(client_por_peticion, "anomalias", entrenado.h)

    assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "modelo_obsoleto"
    assert respuesta.json()["tipo"] == TIPO_ANOMALIAS
    assert _get(client_por_peticion, "demanda", entrenado.h).status_code == 200
    assert _get(client_por_peticion, "reposicion", entrenado.h).status_code == 200


# ---- Entrenar, estado y datos insuficientes --------------------------------------------------------------------------


def test_el_estado_lista_los_tres_modelos_y_las_tres_claves_de_puede_entrenar(client_por_peticion, fs):
    sin_entrenar = _ok(_get(client_por_peticion, "estado", fs.h))
    assert [m["tipo"] for m in sin_entrenar["modelos"]] == TIPOS
    assert sin_entrenar["modelos"][2]["titulo"] == "Días de ventas inusuales"
    assert all(m["estado"] == "sin_entrenar" for m in sin_entrenar["modelos"])
    assert sin_entrenar["puede_entrenar"] == {TIPO_DEMANDA: True, TIPO_SEGMENTOS: True, TIPO_ANOMALIAS: True}

    entrenar(fs.db, "fashionstore")
    entrenado = _ok(_get(client_por_peticion, "estado", fs.h))
    ano = entrenado["modelos"][2]
    fila = _fila_modelo(fs.db, fs.id, TIPO_ANOMALIAS)
    assert ano["estado"] == "vigente" and ano["version"] == 1 and ano["datos_hasta"] == FIN.isoformat()
    assert ano["filas_entrenamiento"] == fila.filas_entrenamiento > 0
    # Solo las métricas visibles (sin artefacto ni parámetros).
    assert set(ano["metricas"]) == {
        "n_dias", "n_sucursales", "n_marcados", "pct_marcados", "umbral", "contamination", "n_marcados_modelo", "n_marcados_regla", "z_regla",
    }  # fmt: skip
    m = ano["metricas"]  # el marcado es el "o" del bosque y la regla: nunca menos que el mayor ni más que la suma
    assert max(m["n_marcados_modelo"], m["n_marcados_regla"]) <= m["n_marcados"] <= m["n_marcados_modelo"] + m["n_marcados_regla"]
    assert m["pct_marcados"] == pytest.approx(100 * m["n_marcados"] / m["n_dias"], abs=0.001)


def test_entrenar_sin_cuerpo_entrena_los_tres_y_cada_tipo_se_puede_pedir_solo(client_por_peticion, fs):
    sin_cuerpo = _ok(client_por_peticion.post(f"{BASE}/entrenar", headers=fs.h))

    assert [(r["tipo"], r["estado"], r["version"]) for r in sin_cuerpo["resultados"]] == [(t, "entrenado", 1) for t in TIPOS]
    ano = sin_cuerpo["resultados"][2]["metricas"]
    guardado = _fila_modelo(fs.db, fs.id, TIPO_ANOMALIAS)
    assert ano["n_marcados"] == guardado.metricas["n_marcados"] and ano["n_sucursales"] == guardado.metricas["n_sucursales"] >= 2
    assert ano["pct_marcados"] == guardado.metricas["pct_marcados"] and "sucursales" not in ano  # sin líneas base
    # Pedir solo uno entrena solo ese (versión 2) y deja los otros en la 1.
    solo = _ok(client_por_peticion.post(f"{BASE}/entrenar", headers=fs.h, json={"tipos": [TIPO_ANOMALIAS]}))
    assert [(r["tipo"], r["version"]) for r in solo["resultados"]] == [(TIPO_ANOMALIAS, 2)]
    assert [m["version"] for m in _ok(_get(client_por_peticion, "estado", fs.h))["modelos"]] == [1, 1, 2]
    assert _fila_modelo(fs.db, fs.id, TIPO_ANOMALIAS, version=1).activo is False


def test_anomalias_ventas_ya_es_un_tipo_valido_y_un_tipo_inventado_o_un_cuarto_siguen_dando_422(client_por_peticion, fs):
    valido = client_por_peticion.post(f"{BASE}/entrenar", headers=fs.h, json={"tipos": ["anomalias_ventas"]})
    assert valido.status_code == 200, valido.text
    assert [r["tipo"] for r in valido.json()["resultados"]] == [TIPO_ANOMALIAS]

    invalidos = [
        {"tipos": ["bola_de_cristal"]},
        {"tipos": [TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS, TIPO_DEMANDA]},  # más de tres
        {"tipos": [TIPO_ANOMALIAS, "anomalias"]},
    ]
    for cuerpo in invalidos:
        limiter.reset()
        respuesta = client_por_peticion.post(f"{BASE}/entrenar", headers=fs.h, json=cuerpo)
        assert respuesta.status_code == 422, (cuerpo, respuesta.text)
    assert [m["version"] for m in _ok(_get(client_por_peticion, "estado", fs.h))["modelos"]] == [None, None, 1]  # nada más se entrenó


def test_con_menos_de_56_dias_de_ventas_anomalias_da_datos_insuficientes_sin_romper_ni_guardar(client_por_peticion, mundo):
    cargar_historia(mundo, "chaski-sport", semanas=7, perfil="B")  # 49 días: menos de las 8 semanas que pide el detector
    cabeceras = cabeceras_de(mundo, "chaski-sport")
    empresa_id = id_de(mundo, "chaski-sport")

    estado = _ok(_get(client_por_peticion, "estado", cabeceras))
    assert estado["puede_entrenar"][TIPO_ANOMALIAS] is False and estado["datos"]["semanas_con_ventas"] < 8

    cuerpo = _ok(client_por_peticion.post(f"{BASE}/entrenar", headers=cabeceras, json={"tipos": [TIPO_ANOMALIAS]}))

    (resultado,) = cuerpo["resultados"]
    assert resultado["tipo"] == TIPO_ANOMALIAS and resultado["estado"] == "datos_insuficientes"
    assert resultado["version"] is None and resultado["metricas"] == {}
    assert "semanas" in resultado["motivo"] and "49" in resultado["motivo"]
    with en_empresa(mundo, empresa_id):
        assert mundo.scalars(select(ModeloML)).all() == []  # no se guardó ninguna versión
    assert _ok(_get(client_por_peticion, "estado", cabeceras))["modelos"][2]["estado"] == "sin_entrenar"
    assert _get(client_por_peticion, "anomalias", cabeceras).status_code == 409  # no quedó ninguna versión


def test_entrenar_sin_cuerpo_con_poca_historia_deja_los_modelos_sin_datos_en_insuficientes_y_entrena_el_que_si_puede(
    client_por_peticion, mundo
):
    cargar_historia(mundo, "chaski-sport", semanas=7, perfil="B")  # 7 semanas: faltan para demanda (26) y anomalías (8)
    cabeceras = cabeceras_de(mundo, "chaski-sport")

    cuerpo = _ok(client_por_peticion.post(f"{BASE}/entrenar", headers=cabeceras))

    # Los segmentos (RFM) necesitan clientes, no semanas: con 80 clientes se entrenan. Cada tipo en su propia transacción.
    assert [(r["tipo"], r["estado"]) for r in cuerpo["resultados"]] == [
        (TIPO_DEMANDA, "datos_insuficientes"), (TIPO_SEGMENTOS, "entrenado"), (TIPO_ANOMALIAS, "datos_insuficientes"),
    ]  # fmt: skip
    insuficientes = [r for r in cuerpo["resultados"] if r["estado"] == "datos_insuficientes"]
    assert all(r["motivo"] and r["version"] is None and r["metricas"] == {} for r in insuficientes)
    estados = {m["tipo"]: m["estado"] for m in _ok(_get(client_por_peticion, "estado", cabeceras))["modelos"]}
    assert estados == {TIPO_DEMANDA: "sin_entrenar", TIPO_SEGMENTOS: "vigente", TIPO_ANOMALIAS: "sin_entrenar"}


# ---- /reposicion ---------------------------------------------------------------------------------------------------------


def test_sin_el_modelo_de_demanda_la_reposicion_da_409_aunque_esten_los_otros_dos(client_por_peticion, fs):
    entrenar(fs.db, "fashionstore", [TIPO_SEGMENTOS, TIPO_ANOMALIAS])

    respuesta = _get(client_por_peticion, "reposicion", fs.h)

    assert respuesta.status_code == 409, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "modelo_no_entrenado" and cuerpo["tipo"] == TIPO_DEMANDA
    assert "items" not in cuerpo


def test_la_reposicion_funciona_solo_con_el_modelo_de_demanda(client_por_peticion, fs):
    entrenar(fs.db, "fashionstore", [TIPO_DEMANDA])

    cuerpo = _ok(_get(client_por_peticion, "reposicion", fs.h))

    assert cuerpo["modelo"]["tipo"] == TIPO_DEMANDA and cuerpo["items"]
    assert _get(client_por_peticion, "anomalias", fs.h).status_code == 409  # control: el otro modelo no está


def test_la_reposicion_trae_la_estructura_y_una_fila_por_categoria_del_modelo_de_demanda(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "reposicion", entrenado.h))
    artefacto = _artefacto(entrenado.db, entrenado.id, TIPO_DEMANDA)

    assert cuerpo["semanas"] == 4
    assert set(cuerpo) == {"modelo", "semanas", "items", "criticos", "supuestos", "interpretacion", "grafico_sugerido", "avisos"}
    assert cuerpo["modelo"]["tipo"] == TIPO_DEMANDA and cuerpo["modelo"]["estado"] == "vigente" and cuerpo["avisos"] == []
    assert cuerpo["grafico_sugerido"]["tipo"] == "barras"
    assert len(cuerpo["supuestos"]) >= 4 and cuerpo["interpretacion"]
    assert {i["categoria_id"] for i in cuerpo["items"]} == {c["id"] for c in artefacto["categorias"]}
    assert {i["categoria"] for i in cuerpo["items"]} == {c["nombre"] for c in artefacto["categorias"]}
    assert len(cuerpo["items"]) == len(artefacto["categorias"]) >= 2
    assert all(set(i) == CAMPOS_ITEM for i in cuerpo["items"])
    assert all(i["estado"] in ORDEN_ESTADO for i in cuerpo["items"])


def test_el_disponible_de_cada_categoria_es_la_suma_de_su_stock_leida_por_dos_caminos(client_por_peticion, entrenado):
    cuerpo = _ok(_get(client_por_peticion, "reposicion", entrenado.h))

    for item in cuerpo["items"]:
        with en_empresa(entrenado.db, entrenado.id):
            por_politica = sum(
                f["disponible"]
                for f in catalogo_politicas.reporte_existencias_por_producto(entrenado.db, None, [item["categoria_id"]], None, 10_000)
            )
        a_mano = _disponible_a_mano(entrenado.db, entrenado.id, item["categoria_id"])
        assert item["disponible"] == por_politica == a_mano, item["categoria"]
    assert sum(i["disponible"] for i in cuerpo["items"]) > 0  # el escenario sí tiene stock: no es una suma de ceros


@pytest.mark.parametrize("semanas", [1, 4, 12])
def test_cada_fila_de_reposicion_coincide_con_la_regla_aplicada_a_mano_sobre_la_demanda_del_modelo(
    client_por_peticion, entrenado, semanas
):
    """Se fija el stock de tres categorías (cero, ~3 semanas de cobertura y enorme) para ejercitar los tres estados, y se
    recalcula todo con las predicciones semanales que devuelve `/demanda` (valores enteros) y el stock leído del ORM."""
    con_demanda = _categorias_con_demanda(client_por_peticion, entrenado.h, 12)
    assert len(con_demanda) >= 3, "hacen falta 3 categorías con demanda prevista"
    cero, medio, enorme = (c["categoria_id"] for c in con_demanda[:3])
    medio_promedio = sum(p["valor"] for p in next(c for c in con_demanda if c["categoria_id"] == medio)["prediccion"][:semanas]) / semanas
    _fijar_disponible(entrenado.db, entrenado.id, cero, 0)
    _fijar_disponible(entrenado.db, entrenado.id, medio, max(1, math.ceil(medio_promedio * 3)))
    _fijar_disponible(entrenado.db, entrenado.id, enorme, 1_000_000)

    cuerpo = _ok(_get(client_por_peticion, "reposicion", entrenado.h, semanas=semanas))
    demanda = {c["categoria_id"]: c for c in _ok(_get(client_por_peticion, "demanda", entrenado.h, semanas=semanas))["categorias"]}

    estados = {}
    for item in cuerpo["items"]:
        semanal = [p["valor"] for p in demanda[item["categoria_id"]]["prediccion"]]
        assert len(semanal) == semanas
        total, disponible = sum(semanal), _disponible_a_mano(entrenado.db, entrenado.id, item["categoria_id"])
        promedio = total / semanas
        assert item["disponible"] == disponible
        assert item["demanda_semanal_promedio"] == pytest.approx(promedio, abs=0.006)
        if promedio > 0:
            cobertura = disponible / promedio
            assert item["semanas_cobertura"] == pytest.approx(cobertura, abs=0.006)
            esperado = "critico" if cobertura < 2 else ("atencion" if cobertura < semanas else "ok")
            acumulada, agotado = 0.0, None
            for numero, unidades in enumerate(semanal, start=1):
                acumulada += unidades
                if acumulada >= disponible:
                    agotado = numero
                    break
            assert item["agotado_en_semana"] == agotado, item
        else:
            assert item["semanas_cobertura"] is None and item["agotado_en_semana"] is None
            esperado = "ok"
        assert item["estado"] == esperado, item
        assert item["sugerencia_unidades"] == max(0, math.ceil(round(total * 1.10 - disponible, 9))), item
        estados[item["categoria_id"]] = item
    # Las tres categorías fijadas cubren los tres estados (con horizonte 1 el "medio" ya no es atención: 3 >= 1).
    assert estados[cero]["estado"] == "critico" and estados[enorme]["estado"] == "ok"
    assert estados[medio]["estado"] == ("atencion" if semanas > 3 else "ok")
    assert cuerpo["criticos"] == sum(1 for i in cuerpo["items"] if i["estado"] == "critico") >= 1


def test_una_categoria_sin_stock_es_critica_y_se_agota_la_semana_1_con_la_sugerencia_de_toda_su_demanda(client_por_peticion, entrenado):
    elegida = _categorias_con_demanda(client_por_peticion, entrenado.h, 4)[0]
    antes = _ok(_get(client_por_peticion, "reposicion", entrenado.h))
    assert next(i for i in antes["items"] if i["categoria_id"] == elegida["categoria_id"])["disponible"] > 0  # control de partida

    _fijar_disponible(entrenado.db, entrenado.id, elegida["categoria_id"], 0)
    cuerpo = _ok(_get(client_por_peticion, "reposicion", entrenado.h))

    item = next(i for i in cuerpo["items"] if i["categoria_id"] == elegida["categoria_id"])
    assert item["disponible"] == 0 and item["estado"] == "critico"
    assert item["agotado_en_semana"] == 1 and item["semanas_cobertura"] == 0
    assert item["sugerencia_unidades"] == math.ceil(round(elegida["total_predicho"] * 1.10, 9)) > 0
    assert item["demanda_semanal_promedio"] == pytest.approx(elegida["total_predicho"] / 4, abs=0.006)
    assert cuerpo["items"][0]["estado"] == "critico" and item in [i for i in cuerpo["items"] if i["estado"] == "critico"]
    assert cuerpo["criticos"] >= 1 and cuerpo["criticos"] >= antes["criticos"]


def test_una_categoria_con_stock_enorme_esta_ok_no_se_agota_y_no_sugiere_comprar(client_por_peticion, entrenado):
    elegida = _categorias_con_demanda(client_por_peticion, entrenado.h, 4)[0]
    _fijar_disponible(entrenado.db, entrenado.id, elegida["categoria_id"], 1_000_000)

    cuerpo = _ok(_get(client_por_peticion, "reposicion", entrenado.h))

    item = next(i for i in cuerpo["items"] if i["categoria_id"] == elegida["categoria_id"])
    assert item["disponible"] == 1_000_000 and item["estado"] == "ok"
    assert item["agotado_en_semana"] is None and item["sugerencia_unidades"] == 0
    assert item["semanas_cobertura"] == pytest.approx(1_000_000 / (elegida["total_predicho"] / 4), rel=0.001)
    assert item["semanas_cobertura"] > 12
    assert cuerpo["items"][-1]["categoria_id"] == elegida["categoria_id"] or cuerpo["items"][-1]["estado"] == "ok"


def test_el_orden_es_criticos_primero_luego_atencion_y_al_final_ok_por_cobertura_ascendente(client_por_peticion, entrenado):
    con_demanda = _categorias_con_demanda(client_por_peticion, entrenado.h, 6)
    assert len(con_demanda) >= 3
    promedios = {c["categoria_id"]: c["total_predicho"] / 6 for c in con_demanda}
    ids = list(promedios)
    # Coberturas de partida distintas y cruzadas con el orden de los ids: 8 semanas, 0 semanas y 3 semanas.
    _fijar_disponible(entrenado.db, entrenado.id, ids[0], math.ceil(promedios[ids[0]] * 8))
    _fijar_disponible(entrenado.db, entrenado.id, ids[1], 0)
    _fijar_disponible(entrenado.db, entrenado.id, ids[2], math.ceil(promedios[ids[2]] * 3))

    items = _ok(_get(client_por_peticion, "reposicion", entrenado.h, semanas=6))["items"]

    clave = lambda i: (ORDEN_ESTADO[i["estado"]], math.inf if i["semanas_cobertura"] is None else i["semanas_cobertura"], i["categoria_id"])  # noqa: E731
    assert [clave(i) for i in items] == sorted(clave(i) for i in items)
    posicion = {i["categoria_id"]: n for n, i in enumerate(items)}
    assert items[0]["categoria_id"] == ids[1] and items[0]["estado"] == "critico"  # el sin stock va primero
    assert items[posicion[ids[2]]]["estado"] == "atencion" and posicion[ids[2]] < posicion[ids[0]]
    assert items[posicion[ids[0]]]["estado"] == "ok"
    assert len({i["estado"] for i in items}) >= 3


def test_la_sugerencia_nunca_es_negativa_y_las_semanas_son_el_horizonte_pedido(client_por_peticion, entrenado):
    for semanas in (1, 2, 6, 12):
        cuerpo = _ok(_get(client_por_peticion, "reposicion", entrenado.h, semanas=semanas))
        assert cuerpo["semanas"] == semanas
        assert all(i["sugerencia_unidades"] >= 0 and i["disponible"] >= 0 for i in cuerpo["items"])
        assert all(i["agotado_en_semana"] is None or 1 <= i["agotado_en_semana"] <= semanas for i in cuerpo["items"])
        assert cuerpo["criticos"] == sum(1 for i in cuerpo["items"] if i["estado"] == "critico")


@pytest.mark.parametrize("semanas, esperado", [(0, 422), (13, 422), (-1, 422), ("abc", 422), ("", 422), (1, 200), (12, 200)])
def test_los_limites_de_semanas_de_la_reposicion_son_1_y_12(client_por_peticion, entrenado, semanas, esperado):
    respuesta = client_por_peticion.get(f"{BASE}/reposicion", headers=entrenado.h, params={"semanas": semanas})

    assert respuesta.status_code == esperado, respuesta.text
    if esperado == 200:
        assert respuesta.json()["semanas"] == semanas


def test_las_dos_rutas_nuevas_no_dejan_salir_el_artefacto_ni_la_huella(client_por_peticion, entrenado):
    huellas = {
        _fila_modelo(entrenado.db, entrenado.id, t).artefacto_sha256 for t in (TIPO_DEMANDA, TIPO_ANOMALIAS)
    }
    assert len(huellas) == 2
    for respuesta in (
        _get(client_por_peticion, "anomalias", entrenado.h, dias=365),
        _get(client_por_peticion, "reposicion", entrenado.h, semanas=12),
    ):
        cuerpo = _ok(respuesta)
        _sin_artefacto(cuerpo)
        _sin_datos_de_cliente(cuerpo)
        assert not any(h in respuesta.text for h in huellas)
        assert "IsolationForest" not in respuesta.text and "joblib" not in respuesta.text


# ---- Panel con los cuatro bloques ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hoy, hay_anomalias",
    [(HOY, False), (dt.date(2026, 9, 20), True)],
    ids=["ultimos-30-dias-normales", "ultimos-30-dias-con-anomalias"],
)
def test_el_panel_con_los_tres_modelos_trae_los_cuatro_bloques_y_los_kpis_nuevos_coinciden_con_las_rutas(
    client_por_peticion, entrenado, monkeypatch, hoy, hay_anomalias
):
    monkeypatch.setattr(cu24, "hoy_utc", lambda: hoy)
    panel = _ok(_get(client_por_peticion, "panel", entrenado.h))
    anomalias_30 = _ok(_get(client_por_peticion, "anomalias", entrenado.h, dias=30))
    reposicion = _ok(_get(client_por_peticion, "reposicion", entrenado.h))

    assert (anomalias_30["total"] > 0) == hay_anomalias  # el escenario cubre los dos textos del KPI
    assert panel["avisos"] == []
    assert all(panel[b] is not None for b in ("demanda", "segmentos", "anomalias", "reposicion"))
    assert panel["anomalias"] == anomalias_30 and panel["anomalias"]["dias"] == 30
    assert panel["reposicion"] == reposicion and panel["reposicion"]["semanas"] == 4
    kpis = {k["clave"]: k for k in panel["kpis"]}
    assert len(kpis) == len(panel["kpis"]) == 7
    assert kpis["anomalias_30_dias"]["valor"] == anomalias_30["total"] and kpis["anomalias_30_dias"]["unidad"] == "días"
    assert kpis["categorias_criticas"]["valor"] == reposicion["criticos"] and kpis["categorias_criticas"]["unidad"] == "categorías"
    if anomalias_30["total"]:
        assert f"{anomalias_30['fuertes']} de ellos son fuertes" in kpis["anomalias_30_dias"]["interpretacion"]
    else:
        assert kpis["anomalias_30_dias"]["interpretacion"] == "Todas las sucursales vendieron dentro de lo esperado."


def test_los_kpis_de_anomalias_y_criticas_siguen_a_los_datos_cuando_cambia_el_stock(client_por_peticion, entrenado):
    antes = {k["clave"]: k["valor"] for k in _ok(_get(client_por_peticion, "panel", entrenado.h))["kpis"]}
    for categoria in _categorias_con_demanda(client_por_peticion, entrenado.h, 4):
        _fijar_disponible(entrenado.db, entrenado.id, categoria["categoria_id"], 0)

    despues = _ok(_get(client_por_peticion, "panel", entrenado.h))

    kpis = {k["clave"]: k for k in despues["kpis"]}
    con_demanda = len(_categorias_con_demanda(client_por_peticion, entrenado.h, 4))
    assert kpis["categorias_criticas"]["valor"] == con_demanda >= antes["categorias_criticas"]
    assert con_demanda >= 2 and kpis["categorias_criticas"]["interpretacion"].startswith("Tienen menos de 2 semanas")
    assert kpis["anomalias_30_dias"]["valor"] == antes["anomalias_30_dias"]  # el stock no cambia las ventas


def test_el_panel_con_solo_anomalias_deja_los_otros_tres_bloques_en_null_con_sus_avisos(client_por_peticion, fs):
    entrenar(fs.db, "fashionstore", [TIPO_ANOMALIAS])

    panel = _ok(_get(client_por_peticion, "panel", fs.h))

    assert panel["anomalias"] is not None and panel["demanda"] is None and panel["segmentos"] is None and panel["reposicion"] is None
    assert panel["avisos"] == [f"{t}: {cu24.MENSAJE_SIN_MODELO}" for t in ("Demanda", "Segmentos", "Reposición")]
    assert [k["clave"] for k in panel["kpis"]] == ["anomalias_30_dias"]
    assert [m["estado"] for m in panel["estado"]["modelos"]] == ["sin_entrenar", "sin_entrenar", "vigente"]


def test_el_panel_con_solo_demanda_trae_reposicion_pero_no_anomalias(client_por_peticion, fs):
    entrenar(fs.db, "fashionstore", [TIPO_DEMANDA])

    panel = _ok(_get(client_por_peticion, "panel", fs.h))

    assert panel["demanda"] is not None and panel["reposicion"] is not None
    assert panel["anomalias"] is None and panel["segmentos"] is None
    assert panel["avisos"] == [f"Segmentos: {cu24.MENSAJE_SIN_MODELO}", f"Anomalías: {cu24.MENSAJE_SIN_MODELO}"]
    claves = {k["clave"] for k in panel["kpis"]}
    assert {"demanda_proxima_semana", "categorias_criticas"} <= claves
    assert "anomalias_30_dias" not in claves and "clientes_segmentados" not in claves


def test_el_panel_sin_ningun_modelo_trae_cuatro_avisos_en_orden_y_ningun_kpi(client_por_peticion, fs):
    panel = _ok(_get(client_por_peticion, "panel", fs.h))

    assert panel["kpis"] == []
    assert panel["avisos"] == [f"{t}: {cu24.MENSAJE_SIN_MODELO}" for t in ("Demanda", "Segmentos", "Anomalías", "Reposición")]
    assert all(panel[b] is None for b in ("demanda", "segmentos", "anomalias", "reposicion"))
    assert panel["estado"]["puede_entrenar"] == {TIPO_DEMANDA: True, TIPO_SEGMENTOS: True, TIPO_ANOMALIAS: True}


def test_un_modelo_de_anomalias_obsoleto_no_tumba_el_panel_y_se_avisa(client_por_peticion, entrenado):
    with en_empresa(entrenado.db, entrenado.id):
        fila = ModeloMLRepository().obtener_activo(entrenado.db, TIPO_ANOMALIAS)
        fila.parametros = {**fila.parametros, "version_sklearn": "0.0.1"}
        entrenado.db.commit()
    CACHE_MODELOS.invalidar(entrenado.id)

    estado = {m["tipo"]: m for m in _ok(_get(client_por_peticion, "estado", entrenado.h))["modelos"]}
    assert estado[TIPO_ANOMALIAS]["estado"] == "obsoleto" and "0.0.1" in estado[TIPO_ANOMALIAS]["mensaje"]
    assert estado[TIPO_DEMANDA]["estado"] == estado[TIPO_SEGMENTOS]["estado"] == "vigente"
    assert _get(client_por_peticion, "anomalias", entrenado.h).json()["codigo"] == "modelo_obsoleto"
    panel = _ok(_get(client_por_peticion, "panel", entrenado.h))
    assert panel["anomalias"] is None and panel["reposicion"] is not None and panel["demanda"] is not None
    assert len(panel["avisos"]) == 1 and panel["avisos"][0].startswith("Anomalías: ")
    assert "anomalias_30_dias" not in {k["clave"] for k in panel["kpis"]}
