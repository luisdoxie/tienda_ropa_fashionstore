"""Segmentación de clientes por RFM (E11, paso 8): k, silhouette, nombres, determinismo, asignación de un
cliente nuevo y bordes (pocos clientes, clientes idénticos, demasiados clientes). Cálculo puro: sin base de
datos ni red. Los datos son de juguete, con arquetipos conocidos (`_datos_rfm.py`)."""

import json
import statistics
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.inteligencia.ml import limites, persistencia
from app.inteligencia.ml.segmentos import (
    NOMBRES_POR_REGLA,
    PLANTILLAS,
    ResultadoSegmentacion,
    _desambiguar,
    _nombrar,
    asignar_segmento,
    segmentar_clientes,
)
from tests.inteligencia.ml._datos_rfm import HASTA, generar_filas_rfm


@pytest.fixture(scope="module")
def datos():
    return generar_filas_rfm()


@pytest.fixture(scope="module")
def filas(datos):
    return datos[0]


@pytest.fixture(scope="module")
def verdad(datos):
    return datos[1]


@pytest.fixture(scope="module")
def resultado(filas) -> ResultadoSegmentacion:
    # Es costoso (varios KMeans): se calcula una vez para todo el módulo y las pruebas solo lo leen.
    return segmentar_clientes(filas, HASTA)


def _por_nombre(resultado, prefijo):
    return {s["id"] for s in resultado.segmentos if s["nombre"].startswith(prefijo)}


def _identicos(n=40):
    return [
        {"cliente_id": i, "ultima_compra": HASTA - timedelta(days=10), "frecuencia": 3, "monto_total": Decimal("250.00")}
        for i in range(1, n + 1)
    ]


# ---- Calidad sobre los datos de juguete ----------------------------------------------------------


def test_el_resultado_es_ok_con_k_entre_2_y_6_y_silhouette_suficiente(resultado):
    assert resultado.estado == "ok" and resultado.motivo is None
    assert 2 <= resultado.metricas["k"] <= 6
    assert resultado.metricas["k"] == len(resultado.segmentos)
    assert resultado.metricas["silhouette"] >= 0.25
    assert resultado.metricas["n_clientes"] == resultado.filas_entrenamiento == 300


def test_las_curvas_del_codo_y_de_silhouette_cubren_de_k_2_a_6(resultado):
    codo, sil = resultado.metricas["curva_codo"], resultado.metricas["curva_silhouette"]
    assert [p["k"] for p in codo] == [p["k"] for p in sil] == [2, 3, 4, 5, 6]
    inercias = [p["inercia"] for p in codo]
    assert inercias == sorted(inercias, reverse=True)  # más grupos, menos inercia
    # La regla de elección: el menor k entre los que quedan a menos de 0,02 de la mejor silhouette.
    mejor = max(p["silhouette"] for p in sil)
    esperado = min(p["k"] for p in sil if mejor - p["silhouette"] < 0.02)
    assert resultado.metricas["k"] == esperado


def test_la_suma_de_clientes_de_los_segmentos_es_el_total(resultado, filas):
    assert sum(s["n_clientes"] for s in resultado.segmentos) == len(filas)
    assert len(resultado.asignaciones) == len(filas)
    assert set(resultado.asignaciones) == {f["cliente_id"] for f in filas}
    assert sum(s["pct_clientes"] for s in resultado.segmentos) == pytest.approx(100.0, abs=0.1)
    por_id = {s["id"]: s["n_clientes"] for s in resultado.segmentos}
    for segmento_id, cantidad in por_id.items():
        assert list(resultado.asignaciones.values()).count(segmento_id) == cantidad
    # El monto de cada segmento está en unidades originales: entre todos suman el total vendido.
    assert sum(s["monto_total"] for s in resultado.segmentos) == pytest.approx(
        float(sum(f["monto_total"] for f in filas)), abs=0.05 * len(resultado.segmentos)
    )


def test_los_nombres_son_unicos_y_cada_segmento_trae_descripcion_y_accion(resultado):
    nombres = [s["nombre"] for s in resultado.segmentos]
    assert len(set(nombres)) == len(nombres)
    for segmento in resultado.segmentos:
        assert segmento["descripcion"] and segmento["accion_sugerida"]
        assert segmento["nombre"].split(" ")[0] in {n.split(" ")[0] for n in PLANTILLAS}


def test_la_mayoria_de_los_campeones_cae_en_el_segmento_campeones(resultado, verdad):
    campeones = _por_nombre(resultado, "Campeones")
    reales = [c for c, a in verdad.items() if a == "campeon"]
    aciertos = sum(1 for c in reales if resultado.asignaciones[c] in campeones)
    assert aciertos / len(reales) >= 0.75


def test_la_mayoria_de_los_dormidos_cae_en_segmentos_de_recencia_antigua(resultado, verdad, filas):
    mediana = statistics.median((HASTA - f["ultima_compra"]).days for f in filas)
    antiguos = {s["id"] for s in resultado.segmentos if s["recencia_media"] > mediana}
    reales = [c for c, a in verdad.items() if a == "dormido"]
    aciertos = sum(1 for c in reales if resultado.asignaciones[c] in antiguos)
    assert aciertos / len(reales) >= 0.75


def test_los_ids_son_estables_y_van_ordenados_por_valor(resultado):
    assert [s["id"] for s in resultado.segmentos] == list(range(len(resultado.segmentos)))
    montos = [s["monto_total"] for s in resultado.segmentos]
    assert montos == sorted(montos, reverse=True)  # id 0 = el de mayor monto_total
    assert max(montos) == montos[0]


# ---- Determinismo, serialización y asignación ----------------------------------------------------


def test_dos_corridas_iguales_dan_exactamente_el_mismo_resultado(resultado, filas):
    assert segmentar_clientes(filas, HASTA) == resultado
    assert segmentar_clientes(list(reversed(filas)), HASTA).asignaciones == resultado.asignaciones  # el orden de entrada no importa


def test_un_cliente_nuevo_se_asigna_con_el_modelo_guardado(resultado, filas):
    modelo = resultado.modelo
    # Los clientes que ya estaban caen en el mismo segmento que dice `asignaciones`.
    for fila in filas:
        esperado = resultado.asignaciones[fila["cliente_id"]]
        assert asignar_segmento(modelo, fila["ultima_compra"], fila["frecuencia"], fila["monto_total"], HASTA) == esperado
    # Uno nuevo y muy activo cae en Campeones; uno que no vuelve hace casi un año, en un segmento más antiguo.
    activo = asignar_segmento(modelo, HASTA - timedelta(days=2), 40, Decimal("14000.00"), HASTA)
    dormido = asignar_segmento(modelo, HASTA - timedelta(days=300), 2, Decimal("400.00"), HASTA)
    segmentos = {s["id"]: s for s in resultado.segmentos}
    assert segmentos[activo]["nombre"].startswith("Campeones")
    assert segmentos[dormido]["recencia_media"] > segmentos[activo]["recencia_media"]
    # monto como float o int también vale
    assert asignar_segmento(modelo, HASTA - timedelta(days=2), 40, 14000.0, HASTA) == activo


def test_el_modelo_pasa_por_serializar_y_deserializar_y_asigna_igual(resultado, filas):
    datos_serializados, huella, tamano = persistencia.serializar(resultado.modelo)
    assert tamano == len(datos_serializados) and tamano < limites.ML_MAX_ARTEFACTO_BYTES
    recuperado = persistencia.deserializar(datos_serializados, huella)
    assert recuperado == resultado.modelo
    for fila in filas[::7]:
        assert asignar_segmento(
            recuperado, fila["ultima_compra"], fila["frecuencia"], fila["monto_total"], HASTA
        ) == resultado.asignaciones[fila["cliente_id"]]
    assert [s["nombre"] for s in recuperado["segmentos"]] == [s["nombre"] for s in resultado.segmentos]


def test_metricas_segmentos_y_parametros_se_serializan_a_json_sin_nan(resultado):
    # allow_nan=False falla si hubiera NaN o infinitos en cualquier parte.
    for parte in (resultado.metricas, resultado.segmentos, resultado.parametros, resultado.avisos, resultado.modelo):
        json.dumps(parte, allow_nan=False)
    parametros = resultado.parametros
    assert parametros["semilla"] == 42 and parametros["hasta"] == HASTA.isoformat()
    assert parametros["versiones"]["sklearn"] and parametros["versiones"]["numpy"]
    assert parametros["supuestos"] and all(isinstance(s, str) for s in parametros["supuestos"])
    assert parametros["ventana"]["ultima_compra_desde"] <= parametros["ventana"]["ultima_compra_hasta"]


# ---- Reglas de nombres ----------------------------------------------------------------------------


def test_las_ocho_reglas_de_nombre_y_la_desambiguacion():
    # mediana R = 50 dias, F = 4, M = 1000
    for (reciente, f_alta, m_alto), nombre in NOMBRES_POR_REGLA.items():
        r = 10 if reciente else 90
        f = 9 if f_alta else 1
        m = 5000 if m_alto else 100
        assert _nombrar(r, f, m, 50, 4, 1000) == nombre
    # los límites son estrictos: igual a la mediana no es "reciente" ni "alto"
    assert _nombrar(50, 4, 1000, 50, 4, 1000) == "Hibernando"
    assert _desambiguar(["Leales", "Hibernando", "Leales", "Leales"]) == ["Leales", "Hibernando", "Leales 2", "Leales 3"]


# ---- Bordes ----------------------------------------------------------------------------------------


def test_con_menos_de_30_clientes_devuelve_datos_insuficientes_sin_excepcion(filas):
    r = segmentar_clientes(filas[:29], HASTA)
    assert (r.estado, r.modelo, r.segmentos, r.asignaciones) == ("datos_insuficientes", None, [], {})
    assert "30" in r.motivo and "29" in r.motivo
    assert r.filas_entrenamiento == 0
    assert segmentar_clientes([], HASTA).estado == "datos_insuficientes"
    assert segmentar_clientes(filas[:30], HASTA).estado == "ok"  # justo el mínimo alcanza
    json.dumps(r.metricas, allow_nan=False)


def test_clientes_identicos_no_rompen_y_forman_un_unico_segmento():
    r = segmentar_clientes(_identicos(), HASTA)
    assert r.estado == "ok" and r.metricas["k"] == 1 and len(r.segmentos) == 1
    assert r.metricas["silhouette"] is None and r.metricas["curva_silhouette"] == []
    assert r.segmentos[0]["nombre"] == "Todos los clientes" and r.segmentos[0]["n_clientes"] == 40
    assert set(r.asignaciones.values()) == {0}
    assert any("mismo comportamiento" in aviso for aviso in r.avisos)
    json.dumps([r.metricas, r.segmentos, r.modelo], allow_nan=False)
    assert asignar_segmento(r.modelo, HASTA - timedelta(days=500), 99, Decimal("1.00"), HASTA) == 0


def test_con_solo_dos_perfiles_distintos_se_separan_en_dos_segmentos():
    filas = _identicos(20) + [
        {"cliente_id": 100 + i, "ultima_compra": HASTA - timedelta(days=300), "frecuencia": 1, "monto_total": Decimal("30.00")}
        for i in range(20)
    ]
    r = segmentar_clientes(filas, HASTA)
    assert r.estado == "ok" and r.metricas["k"] == 2
    assert sorted(s["n_clientes"] for s in r.segmentos) == [20, 20]
    json.dumps([r.metricas, r.segmentos], allow_nan=False)


def test_con_mas_clientes_que_el_maximo_se_recorta_por_recencia_con_aviso(filas, monkeypatch):
    monkeypatch.setattr(limites, "ML_MAX_CLIENTES", 100)
    r = segmentar_clientes(filas, HASTA)
    assert r.estado == "ok" and r.metricas["n_clientes"] == r.filas_entrenamiento == 100
    assert len(r.asignaciones) == 100 and sum(s["n_clientes"] for s in r.segmentos) == 100
    assert any("máximo" in aviso for aviso in r.avisos)
    # se quedaron los 100 de compra más reciente
    dias = {f["cliente_id"]: (HASTA - f["ultima_compra"]).days for f in filas}
    peor_conservado = max(dias[c] for c in r.asignaciones)
    mejor_descartado = min(dias[c] for c in dias if c not in r.asignaciones)
    assert peor_conservado <= mejor_descartado


def test_entradas_raras_se_corrigen_con_aviso_en_lugar_de_romper(filas):
    raras = [dict(f) for f in filas]
    raras[0]["ultima_compra"] = HASTA + timedelta(days=3)  # compra "futura"
    raras[1]["monto_total"] = Decimal("-5.00")
    raras.append(dict(raras[2]))  # cliente repetido
    r = segmentar_clientes(raras, HASTA)
    assert r.estado == "ok" and r.metricas["n_clientes"] == len(filas)
    assert len(r.avisos) >= 3
    json.dumps(r.metricas, allow_nan=False)


def test_semillas_distintas_siguen_siendo_validas_y_la_semilla_queda_registrada(filas):
    r = segmentar_clientes(filas, HASTA, semilla=7)
    assert r.estado == "ok" and r.parametros["semilla"] == 7
    assert segmentar_clientes(filas, HASTA, semilla=7) == r


def test_los_segmentos_solo_traen_agregados_sin_datos_personales(resultado):
    # El resultado solo trae ids de cliente, ids de segmento y agregados: ningún nombre ni correo.
    claves = {"id", "nombre", "descripcion", "accion_sugerida", "n_clientes", "pct_clientes", "recencia_media",
              "frecuencia_media", "monto_medio", "monto_total"}  # fmt: skip
    assert all(set(s) == claves for s in resultado.segmentos)
    assert date.fromisoformat(resultado.parametros["hasta"]) == HASTA
