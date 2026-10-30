"""Frases de interpretación de la analítica ML (CU-24, E12): funciones puras, sin base ni red."""

import itertools
import math
import re

import pytest

from app.inteligencia.politicas import (
    interpretar_demanda,
    interpretar_estado,
    interpretar_metricas_demanda,
    interpretar_segmentos,
)

PROHIBIDAS = re.compile(r"\bnone\b|\bnan\b|\binf\b|\bnull\b", re.IGNORECASE)


def _verificar_frases(frases):
    assert isinstance(frases, list)
    for frase in frases:
        assert isinstance(frase, str)
        assert frase.strip() == frase and frase
        assert "\n" not in frase and "\r" not in frase and "\t" not in frase
        assert "  " not in frase
        assert not PROHIBIDAS.search(frase), frase
        assert frase.endswith("."), frase


METRICAS_BUENAS = {
    "mae": 3.4,
    "rmse": 4.8,
    "r2": 0.63,
    "mae_base": 5.1,
    "rmse_base": 6.9,
    "r2_base": 0.21,
    "mejora_mae_pct": 33.3,
    "modelo_elegido": "ridge",
}


# ---------------------------------------------------------------- métricas de demanda


def test_metricas_buenas_dicen_errores_mejora_y_r2():
    frases = interpretar_metricas_demanda(METRICAS_BUENAS)
    _verificar_frases(frases)
    unidas = " ".join(frases)
    assert "se equivoca en promedio 3,40 unidades por categoría y semana" in unidas
    assert "promedio móvil de 4 semanas se equivoca 5,10" in unidas
    assert "es 33,3% más preciso" in unidas
    assert "explica el 63% de la variación" in unidas
    assert "promedio móvil explica el 21%" in unidas
    assert "Ridge" in unidas
    assert "pequeña" not in unidas


def test_mejora_pequena_se_dice_pequena():
    frases = interpretar_metricas_demanda({**METRICAS_BUENAS, "mejora_mae_pct": 2.0})
    assert "es 2% más preciso, una mejora pequeña" in " ".join(frases)


def test_mejora_negativa_dice_que_no_mejora_sin_inventar_precision():
    frases = interpretar_metricas_demanda({**METRICAS_BUENAS, "mae": 6.0, "mae_base": 5.0, "mejora_mae_pct": -20.0})
    _verificar_frases(frases)
    unidas = " ".join(frases)
    assert "no mejora a la línea base" in unidas
    assert "20% menos preciso" in unidas
    assert "más preciso" not in unidas.replace("menos preciso", "")


def test_mejora_cero_es_empate_y_no_mejora():
    unidas = " ".join(interpretar_metricas_demanda({**METRICAS_BUENAS, "mejora_mae_pct": 0.0}))
    assert "no mejora a la línea base" in unidas
    assert "empatan" in unidas
    assert "más preciso" not in unidas


def test_mejora_none_no_afirma_ninguna_mejora():
    frases = interpretar_metricas_demanda({**METRICAS_BUENAS, "mejora_mae_pct": None})
    _verificar_frases(frases)
    unidas = " ".join(frases)
    assert "No se pudo medir con certeza si el modelo mejora" in unidas
    assert "más preciso" not in unidas


def test_r2_negativo_se_dice_con_honestidad():
    frases = interpretar_metricas_demanda({**METRICAS_BUENAS, "r2": -0.15})
    _verificar_frases(frases)
    unidas = " ".join(frases)
    assert "R2 es negativo (-0,15)" in unidas
    assert "explica el" not in unidas


def test_r2_base_negativo_no_se_presenta_como_porcentaje():
    unidas = " ".join(interpretar_metricas_demanda({**METRICAS_BUENAS, "r2_base": -0.4}))
    assert "el promedio móvil no logra explicarla" in unidas
    assert "-40" not in unidas


def test_metricas_vacias_o_none_devuelven_lista_vacia():
    assert interpretar_metricas_demanda({}) == []
    assert interpretar_metricas_demanda(None) == []
    assert interpretar_metricas_demanda({"mae": None, "r2": None, "modelo_elegido": None}) == []


def test_mae_base_cero_no_divide_ni_revienta():
    frases = interpretar_metricas_demanda({"mae": 1.0, "mae_base": 0.0, "mejora_mae_pct": None, "r2": 0.5})
    _verificar_frases(frases)
    assert any("No se pudo medir" in f for f in frases)


def test_solo_mae_sin_base_no_compara():
    frases = interpretar_metricas_demanda({"mae": 2.0})
    assert frases == ["El modelo se equivoca en promedio 2,00 unidades por categoría y semana."]


def test_solo_base_sin_mae_del_modelo():
    frases = interpretar_metricas_demanda({"mae_base": 4.0})
    _verificar_frases(frases)
    assert "promedio móvil de 4 semanas se equivoca en promedio 4,00" in frases[0]


def test_modelo_elegido_desconocido_se_muestra_legible():
    unidas = " ".join(interpretar_metricas_demanda({"modelo_elegido": "gradient_boosting"}))
    assert "gradient boosting" in unidas
    assert " ".join(interpretar_metricas_demanda({"modelo_elegido": "mezcla"})).count("Ridge y Random Forest") == 1
    assert interpretar_metricas_demanda({"modelo_elegido": "None"}) == []
    assert interpretar_metricas_demanda({"modelo_elegido": ""}) == []


def test_metricas_con_valores_no_finitos_o_basura_se_ignoran():
    basura = {"mae": float("nan"), "mae_base": float("inf"), "r2": "abc", "r2_base": True, "mejora_mae_pct": float("-inf")}
    assert interpretar_metricas_demanda(basura) == []


def test_metricas_combinaciones_nunca_producen_none_nan_inf():
    valores = [None, 0, 0.0, 1.5, -2.0, 100.0, float("nan"), float("inf")]
    claves = ["mae", "mae_base", "r2", "r2_base", "mejora_mae_pct"]
    vistas = 0
    for combo in itertools.product(valores, repeat=len(claves)):
        metricas = dict(zip(claves, combo, strict=True))
        metricas["modelo_elegido"] = "ridge" if vistas % 2 else None
        _verificar_frases(interpretar_metricas_demanda(metricas))
        vistas += 1
    assert vistas == len(valores) ** len(claves)


# ---------------------------------------------------------------- demanda prevista

CATEGORIAS = [
    {"categoria": "Poleras", "total_predicho": 120, "variacion_pct": 18.5},
    {"categoria": "Camisas", "total_predicho": 60, "variacion_pct": -12.0},
    {"categoria": "Chamarras", "total_predicho": 20, "variacion_pct": 2.0},
]


def test_demanda_dice_total_horizonte_lider_y_extremos():
    frases = interpretar_demanda(CATEGORIAS, 4)
    _verificar_frases(frases)
    unidas = " ".join(frases)
    assert "las próximas 4 semanas se prevén 200 unidades en total, repartidas en 3 categorías" in unidas
    assert "con más demanda prevista es Poleras: 120 unidades, el 60% del total" in unidas
    assert "La que más crece es Poleras: 18,5% más que las últimas 4 semanas reales" in unidas
    assert "La que más cae es Camisas: 12% menos que las últimas 4 semanas reales" in unidas


def test_demanda_lista_vacia():
    assert interpretar_demanda([], 4) == []
    assert interpretar_demanda(None, 4) == []


def test_demanda_variaciones_pequenas_se_dicen_estables():
    categorias = [
        {"categoria": "Poleras", "total_predicho": 10, "variacion_pct": 3.0},
        {"categoria": "Camisas", "total_predicho": 10, "variacion_pct": -4.9},
    ]
    unidas = " ".join(interpretar_demanda(categorias, 2))
    assert "se mantiene estable" in unidas
    assert "ninguna categoría cambia más de 5%" in unidas
    assert "más crece" not in unidas and "más cae" not in unidas


def test_demanda_solo_crece_o_solo_cae():
    solo_crece = [
        {"categoria": "A", "total_predicho": 5, "variacion_pct": 30.0},
        {"categoria": "B", "total_predicho": 5, "variacion_pct": 10.0},
    ]
    unidas = " ".join(interpretar_demanda(solo_crece, 4))
    assert "La que más crece es A" in unidas and "más cae" not in unidas
    solo_cae = [
        {"categoria": "A", "total_predicho": 5, "variacion_pct": -30.0},
        {"categoria": "B", "total_predicho": 5, "variacion_pct": -10.0},
    ]
    unidas = " ".join(interpretar_demanda(solo_cae, 4))
    assert "La que más cae es A" in unidas and "más crece" not in unidas


def test_demanda_sin_variaciones_no_habla_de_cambios():
    categorias = [
        {"categoria": "A", "total_predicho": 8, "variacion_pct": None},
        {"categoria": "B", "total_predicho": 2, "variacion_pct": None},
    ]
    frases = interpretar_demanda(categorias, 4)
    _verificar_frases(frases)
    unidas = " ".join(frases)
    assert "10 unidades en total" in unidas
    assert "crece" not in unidas and "cae" not in unidas and "estable" not in unidas


def test_demanda_empate_de_lideres_se_nombra_a_ambos_en_orden():
    categorias = [
        {"categoria": "Zapatos", "total_predicho": 30, "variacion_pct": None},
        {"categoria": "Camisas", "total_predicho": 30, "variacion_pct": None},
        {"categoria": "Poleras", "total_predicho": 5, "variacion_pct": None},
    ]
    unidas = " ".join(interpretar_demanda(categorias, 4))
    assert "Las categorías Camisas y Zapatos empatan con más demanda prevista: 30 unidades cada una" in unidas


def test_demanda_empate_en_variacion_es_determinista():
    categorias = [
        {"categoria": "B", "total_predicho": 10, "variacion_pct": 20.0},
        {"categoria": "A", "total_predicho": 10, "variacion_pct": 20.0},
    ]
    primera = interpretar_demanda(categorias, 4)
    segunda = interpretar_demanda(list(reversed(categorias)), 4)
    assert primera[2:] == segunda[2:]


def test_demanda_una_sola_categoria_no_dice_lider():
    frases = interpretar_demanda([{"categoria": "Poleras", "total_predicho": 1, "variacion_pct": 50.0}], 1)
    _verificar_frases(frases)
    unidas = " ".join(frases)
    assert "la próxima semana se prevén 1 unidad en total, repartidas en 1 categoría" in unidas
    assert "con más demanda" not in unidas
    assert "50% más que las últimas 4 semanas reales" in unidas  # aunque el horizonte sea 1, la base son 4 semanas reales


def test_demanda_total_cero():
    categorias = [{"categoria": "A", "total_predicho": 0, "variacion_pct": 10.0}]
    assert interpretar_demanda(categorias, 4) == ["No se prevén ventas para las próximas 4 semanas."]


def test_demanda_horizonte_invalido_usa_texto_generico():
    for horizonte in (0, -3, None, float("nan")):
        frases = interpretar_demanda(CATEGORIAS, horizonte)
        _verificar_frases(frases)
        assert "el periodo previsto" in frases[0]
        assert "las últimas 4 semanas reales" in " ".join(frases)


def test_demanda_datos_sucios_no_revientan():
    categorias = [
        {"categoria": None, "total_predicho": None, "variacion_pct": float("nan")},
        {"categoria": "  Poleras \n", "total_predicho": "12", "variacion_pct": float("inf")},
        {},
        {"categoria": "Camisas", "total_predicho": -7, "variacion_pct": "x"},
    ]
    frases = interpretar_demanda(categorias, 4)
    _verificar_frases(frases)
    assert "12 unidades en total" in frases[0]
    assert "Poleras" in " ".join(frases)


def test_demanda_combinaciones_nunca_producen_none_nan_inf():
    totales = [0, 1, 50]
    variaciones = [None, 0.0, 5.0, 5.01, -5.01, 40.0, float("nan")]
    for t1, t2, v1, v2 in itertools.product(totales, totales, variaciones, variaciones):
        categorias = [
            {"categoria": "A", "total_predicho": t1, "variacion_pct": v1},
            {"categoria": "B", "total_predicho": t2, "variacion_pct": v2},
        ]
        _verificar_frases(interpretar_demanda(categorias, 4))


# ---------------------------------------------------------------- segmentos


def _seg(nombre, n, pct, monto, recencia=10.0, frecuencia=3.0):
    return {
        "nombre": nombre,
        "n_clientes": n,
        "pct_clientes": pct,
        "monto_total": monto,
        "recencia_media": recencia,
        "frecuencia_media": frecuencia,
    }


SEGMENTOS = [
    _seg("Campeones", 120, 12.0, 41000.0, recencia=15.0, frecuencia=8.5),
    _seg("Leales", 380, 38.0, 35000.0),
    _seg("En riesgo", 300, 30.0, 14000.0, recencia=120.0),
    _seg("Por reactivar", 200, 20.0, 10000.0, recencia=200.0),
]


def test_segmentos_frase_de_campeones_con_porcentaje_de_ventas():
    frases = interpretar_segmentos(SEGMENTOS, 0.62)
    _verificar_frases(frases)
    assert frases[0] == "El 12% de tus clientes (Campeones) genera el 41% de las ventas."
    unidas = " ".join(frases)
    assert "compró en promedio 8,5 veces" in unidas
    assert "hace 15 días" in unidas


def test_segmentos_porcentaje_de_ventas_usa_la_suma_de_montos_no_100():
    segmentos = [_seg("Campeones", 10, 10.0, 300.0), _seg("Leales", 90, 90.0, 100.0)]
    assert interpretar_segmentos(segmentos, 0.6)[0] == "El 10% de tus clientes (Campeones) genera el 75% de las ventas."


def test_segmentos_sin_campeones_usa_el_de_mayor_monto():
    segmentos = [_seg("Leales", 50, 50.0, 100.0), _seg("Nuevos", 50, 50.0, 900.0)]
    assert interpretar_segmentos(segmentos, 0.6)[0] == "El 50% de tus clientes (Nuevos) genera el 90% de las ventas."


def test_segmentos_menciona_el_grupo_en_riesgo_mas_grande_y_el_total():
    frases = interpretar_segmentos(SEGMENTOS, 0.62)
    unidas = " ".join(frases)
    assert "El grupo en riesgo más grande es En riesgo, con 300 clientes (30% de tus clientes)" in unidas
    assert "no compra hace 120 días en promedio" in unidas
    assert "En total, 500 clientes están en riesgo o dormidos." in unidas


def test_segmentos_nombre_desambiguado_se_reconoce_como_riesgo():
    segmentos = [_seg("Campeones", 10, 10.0, 500.0), _seg("Grandes dormidos (2)", 90, 90.0, 100.0)]
    unidas = " ".join(interpretar_segmentos(segmentos, 0.5))
    assert "El grupo en riesgo más grande es Grandes dormidos (2)" in unidas


def test_segmentos_sin_riesgo_lo_dice():
    segmentos = [_seg("Campeones", 10, 10.0, 500.0), _seg("Leales", 90, 90.0, 400.0)]
    unidas = " ".join(interpretar_segmentos(segmentos, 0.5))
    assert "Ningún segmento aparece en riesgo" in unidas
    assert "grupo en riesgo más grande" not in unidas


def test_segmentos_un_solo_segmento():
    frases = interpretar_segmentos([_seg("Todos los clientes", 650, 100.0, 90000.0)], None)
    _verificar_frases(frases)
    assert len(frases) == 1
    assert "Todos tus clientes (650 clientes) se comportan de forma parecida" in frases[0]
    assert "silhouette" not in frases[0]


def test_segmentos_lista_vacia():
    assert interpretar_segmentos([], 0.5) == []
    assert interpretar_segmentos(None, 0.5) == []


@pytest.mark.parametrize(
    ("silhouette", "esperado"),
    [
        (0.5, "bien separados (silhouette de 0,50)"),
        (0.9, "bien separados (silhouette de 0,90)"),
        (0.25, "se separan de forma aceptable (silhouette de 0,25)"),
        (0.49, "se separan de forma aceptable (silhouette de 0,49)"),
        (0.24, "poco separados (silhouette de 0,24)"),
        (-0.1, "poco separados (silhouette de -0,10)"),
        (None, "No se pudo medir qué tan separados están los grupos"),
        (float("nan"), "No se pudo medir qué tan separados están los grupos"),
    ],
)
def test_segmentos_frase_de_silhouette(silhouette, esperado):
    frases = interpretar_segmentos(SEGMENTOS, silhouette)
    _verificar_frases(frases)
    assert esperado in frases[-1]


def test_segmentos_sin_monto_no_divide_por_cero():
    segmentos = [_seg("Leales", 50, 50.0, 0.0), _seg("Nuevos", 50, 50.0, 0.0)]
    frases = interpretar_segmentos(segmentos, 0.4)
    _verificar_frases(frases)
    assert frases[0] == "Todavía no hay montos de compra para repartir entre los grupos."
    assert "genera el" not in " ".join(frases)
    assert "Ningún segmento aparece en riesgo" in " ".join(frases)


def test_segmentos_calcula_porcentaje_de_clientes_si_falta():
    segmentos = [_seg("Campeones", 25, None, 100.0), _seg("Leales", 75, None, 100.0)]
    assert interpretar_segmentos(segmentos, 0.6)[0] == "El 25% de tus clientes (Campeones) genera el 50% de las ventas."


def test_segmentos_sin_recencia_ni_frecuencia_omite_ese_detalle():
    segmentos = [
        {"nombre": "Campeones", "n_clientes": 5, "pct_clientes": 5.0, "monto_total": 80.0},
        {"nombre": "En riesgo", "n_clientes": 95, "pct_clientes": 95.0, "monto_total": 20.0},
    ]
    frases = interpretar_segmentos(segmentos, 0.6)
    _verificar_frases(frases)
    unidas = " ".join(frases)
    assert "Cada cliente de" not in unidas
    assert "no compra hace" not in unidas


def test_segmentos_combinaciones_nunca_producen_none_nan_inf():
    valores_pct = [None, 0.0, 33.3, float("nan")]
    valores_monto = [None, 0.0, 10.0, float("inf")]
    nombres = ["Campeones", "En riesgo", "Leales", None, "Todos los clientes"]
    for nombre, pct, monto, silhouette in itertools.product(nombres, valores_pct, valores_monto, [None, 0.1, 0.3, 0.8]):
        segmentos = [
            {"nombre": nombre, "n_clientes": 4, "pct_clientes": pct, "monto_total": monto, "recencia_media": None, "frecuencia_media": float("nan")},
            _seg("Leales", 6, 60.0, 50.0),
        ]
        _verificar_frases(interpretar_segmentos(segmentos, silhouette))


# ---------------------------------------------------------------- estado de los modelos


def _mod(estado, version=3, dias=5, titulo="Demanda por categoría"):
    return {"titulo": titulo, "estado": estado, "version": version, "dias_desde_entrenamiento": dias}


def test_estado_sin_entrenar_orienta_a_entrenar():
    frases = interpretar_estado([_mod("sin_entrenar", version=None, dias=None)])
    assert frases == ["Demanda por categoría: aún no está entrenado. Entrénalo desde Analítica para ver resultados."]


def test_estado_vigente_dice_antiguedad():
    assert "está al día (versión 3), entrenado hace 5 días" in interpretar_estado([_mod("vigente")])[0]
    assert "entrenado hoy" in interpretar_estado([_mod("vigente", dias=0)])[0]
    assert "entrenado hace 1 día." in interpretar_estado([_mod("vigente", dias=1)])[0]


def test_estado_desactualizado_y_obsoleto():
    desactualizado = interpretar_estado([_mod("desactualizado", dias=45)])[0]
    assert "Tiene 45 días" in desactualizado and "conviene reentrenarlo" in desactualizado
    obsoleto = interpretar_estado([_mod("obsoleto", dias=200)])[0]
    assert "Lleva 200 días sin entrenarse" in obsoleto and "reentrénalo pronto" in obsoleto


def test_estado_una_frase_por_modelo_en_orden():
    modelos = [_mod("vigente", titulo="Demanda"), _mod("obsoleto", titulo="Segmentos")]
    frases = interpretar_estado(modelos)
    assert len(frases) == 2
    assert frases[0].startswith("Demanda:") and frases[1].startswith("Segmentos:")


def test_estado_lista_vacia_y_estado_desconocido():
    assert interpretar_estado([]) == []
    assert interpretar_estado(None) == []
    frases = interpretar_estado([_mod("raro")])
    _verificar_frases(frases)
    assert "no se pudo determinar su estado" in frases[0]


def test_estado_combinaciones_nunca_producen_none_nan_inf():
    estados = ["sin_entrenar", "vigente", "desactualizado", "obsoleto", None, "x"]
    versiones = [None, 1, float("nan")]
    dias = [None, 0, 1, 30, -2, float("inf")]
    titulos = ["Demanda", None, ""]
    for estado, version, d, titulo in itertools.product(estados, versiones, dias, titulos):
        frases = interpretar_estado([{"titulo": titulo, "estado": estado, "version": version, "dias_desde_entrenamiento": d}])
        _verificar_frases(frases)
        assert len(frases) == 1
        assert not any(math.isnan(float(c)) for c in re.findall(r"\d+", frases[0]))


def test_ninguna_funcion_modifica_sus_entradas():
    copia = [dict(s) for s in SEGMENTOS]
    interpretar_segmentos(SEGMENTOS, 0.5)
    assert SEGMENTOS == copia
    cats = [dict(c) for c in CATEGORIAS]
    interpretar_demanda(CATEGORIAS, 4)
    assert CATEGORIAS == cats
    metricas = dict(METRICAS_BUENAS)
    interpretar_metricas_demanda(METRICAS_BUENAS)
    assert METRICAS_BUENAS == metricas
