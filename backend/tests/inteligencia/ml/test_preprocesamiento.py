"""E11, paso 7: serie semanal y características de la demanda (`ml/preprocesamiento.py`). Cálculo puro, sin base."""

import math
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from app.inteligencia.ml import limites
from app.inteligencia.ml.preprocesamiento import (
    COLUMNAS_NUMERICAS,
    DatosInsuficientesError,
    construir_matriz,
    construir_serie_semanal,
    fila_de_caracteristicas,
    nombres_de_columnas,
    ultimo_lunes_completo,
)

HASTA = date(2026, 10, 25)  # domingo
LUNES_ISO_26 = date(2026, 6, 22)  # semana ISO 26
LUNES_ISO_13 = date(2026, 3, 23)  # semana ISO 13


def _fila(dia, categoria_id, unidades, neto=None, bruto=None, nombre=None):
    bruto = Decimal(bruto if bruto is not None else unidades * 10)
    neto = Decimal(neto) if neto is not None else bruto
    return {
        "dia": dia,
        "categoria_id": categoria_id,
        "categoria": nombre or f"Cat {categoria_id}",
        "transacciones": 1,
        "unidades": unidades,
        "total_ventas": neto,
        "ventas_brutas": bruto,
    }


def _lunes(n_semanas, hasta=HASTA):
    """Lunes de la primera semana de una serie de `n_semanas` completas que termina en `hasta` (domingo)."""
    return hasta - timedelta(days=6) - timedelta(weeks=n_semanas - 1)


def _filas(n_semanas, unidades_por_categoria, hasta=HASTA):
    """Una fila por semana y categoría, el lunes. `unidades_por_categoria`: {id: función(semana) -> unidades}."""
    primero = _lunes(n_semanas, hasta)
    return [
        _fila(primero + timedelta(weeks=j), cid, f(j))
        for cid, f in unidades_por_categoria.items()
        for j in range(n_semanas)
        if f(j) > 0
    ]


def test_la_semana_en_curso_se_descarta_y_el_domingo_cuenta_como_completo():
    miercoles = date(2026, 10, 21)  # la semana del 19 al 25 aún corre
    assert ultimo_lunes_completo(miercoles) == date(2026, 10, 12)
    assert ultimo_lunes_completo(date(2026, 10, 25)) == date(2026, 10, 19)  # el domingo cierra la semana
    assert ultimo_lunes_completo(date(2026, 10, 19)) == date(2026, 10, 12)  # el lunes aún no hay semana nueva

    filas = _filas(26, {1: lambda j: 5, 2: lambda j: 5}, hasta=date(2026, 10, 18))
    filas.append(_fila(date(2026, 10, 20), 1, 999))  # semana en curso: no debe entrar
    serie = construir_serie_semanal(filas, miercoles)
    assert serie.semanas[-1] == date(2026, 10, 12)
    assert serie.unidades.max() == 5


def test_las_semanas_sin_ventas_valen_cero_y_no_se_omiten():
    filas = _filas(30, {1: lambda j: 4, 2: lambda j: 0 if j % 3 else 7})  # la categoría 2 vende cada 3 semanas
    serie = construir_serie_semanal(filas, HASTA)
    assert serie.n_semanas == 30
    cat2 = serie.unidades[1]
    assert cat2[1] == 0 and cat2[2] == 0 and cat2[3] == 7
    assert serie.unidades.shape == (2, 30)
    assert (serie.unidades >= 0).all()


def test_las_semanas_son_lunes_consecutivos():
    serie = construir_serie_semanal(_filas(28, {1: lambda j: 3, 2: lambda j: 2}), HASTA)
    assert all(s.weekday() == 0 for s in serie.semanas)
    assert all((b - a).days == 7 for a, b in zip(serie.semanas, serie.semanas[1:]))
    assert serie.semanas[-1] == date(2026, 10, 19)


def test_los_dias_de_una_semana_se_suman_en_ella():
    filas = _filas(26, {1: lambda j: 1, 2: lambda j: 1})
    ultimo_lunes = date(2026, 10, 19)
    filas += [_fila(ultimo_lunes + timedelta(days=d), 1, 2) for d in (2, 4, 6)]  # +6 en la última semana
    serie = construir_serie_semanal(filas, HASTA)
    assert serie.unidades[0, -1] == 1 + 6


def test_los_rezagos_y_la_tendencia_coinciden_con_un_calculo_a_mano():
    # Categoría 1: 1, 2, 3, ... (la semana j vende j+1). Categoría 2: constante 5.
    serie = construir_serie_semanal(_filas(26, {1: lambda j: j + 1, 2: lambda j: 5}), HASTA)
    matriz = construir_matriz(serie)
    col = {nombre: i for i, nombre in enumerate(matriz.columnas)}
    fila = np.flatnonzero((matriz.indice_semana == 9) & (matriz.indice_categoria == 0))[0]
    x = matriz.X[fila]
    # Semana 9 vende 10; las anteriores (8, 7, 6, 5) venden 9, 8, 7, 6; las 4 previas a esas venden 5, 4, 3, 2.
    assert matriz.y[fila] == 10
    assert [x[col[f"lag_{k}"]] for k in (1, 2, 3, 4)] == [9, 8, 7, 6]
    assert x[col["media_movil_4"]] == 7.5
    assert x[col["tendencia"]] == 7.5 - 3.5
    # La categoría 2 es constante: tendencia 0 y media igual al nivel.
    fila2 = np.flatnonzero((matriz.indice_semana == 9) & (matriz.indice_categoria == 1))[0]
    assert matriz.X[fila2][col["media_movil_4"]] == 5 and matriz.X[fila2][col["tendencia"]] == 0


def test_las_primeras_cuatro_semanas_no_generan_fila():
    serie = construir_serie_semanal(_filas(26, {1: lambda j: j + 1, 2: lambda j: 3}), HASTA)
    matriz = construir_matriz(serie)
    assert matriz.indice_semana.min() == 4
    assert len(matriz.y) == (26 - 4) * 2
    # En la primera fila (semana 4) aún no hay 4 semanas anteriores a las 4 de nivel: la tendencia vale 0.
    col = matriz.columnas.index("tendencia")
    assert matriz.X[0][col] == 0.0


def test_sin_fuga_la_fila_de_la_semana_t_no_contiene_las_unidades_de_t():
    base = _filas(30, {1: lambda j: 10 + j, 2: lambda j: 20})
    modificadas = []
    semana_t = 17
    lunes_t = _lunes(30) + timedelta(weeks=semana_t)
    for f in base:
        g = dict(f)
        if f["categoria_id"] == 1 and f["dia"] == lunes_t:
            g["unidades"] = 5000  # y_t cambia muchísimo; neto y bruto quedan igual (la covariable no se toca)
        modificadas.append(g)
    a = construir_matriz(construir_serie_semanal(base, HASTA))
    b = construir_matriz(construir_serie_semanal(modificadas, HASTA))
    hasta_t = a.indice_semana <= semana_t
    assert np.array_equal(a.X[hasta_t], b.X[hasta_t])  # ninguna fila hasta t ve la cifra alterada de t
    fila_t = np.flatnonzero((a.indice_semana == semana_t) & (a.indice_categoria == 0))[0]
    assert a.y[fila_t] != b.y[fila_t]
    # La semana siguiente sí la ve, como rezago: es información pasada.
    siguiente = np.flatnonzero((a.indice_semana == semana_t + 1) & (a.indice_categoria == 0))[0]
    assert a.X[siguiente][0] != b.X[siguiente][0]


def test_el_one_hot_tiene_orden_estable_por_id_sin_importar_el_orden_de_las_filas():
    filas = _filas(28, {30: lambda j: 3 + j % 4, 7: lambda j: 6, 12: lambda j: 2 + j % 3})
    a = construir_matriz(construir_serie_semanal(filas, HASTA))
    b = construir_matriz(construir_serie_semanal(list(reversed(filas)), HASTA))
    ids = (7, 12, 30)
    assert a.columnas == (
        list(COLUMNAS_NUMERICAS)
        + [f"categoria_{i}" for i in ids]
        + [f"ciclo_sin_{i}" for i in ids]
        + [f"ciclo_cos_{i}" for i in ids]
    )
    assert a.columnas == b.columnas and np.array_equal(a.X, b.X)
    n = len(COLUMNAS_NUMERICAS)
    assert (a.X[:, n : n + 3].sum(axis=1) == 1).all()  # exactamente una categoría activa por fila


def test_cada_categoria_tiene_su_propio_ciclo_anual_y_las_demas_valen_cero():
    """El ciclo anual por categoría (seno y coseno multiplicados por su one-hot): la fase de una no se mezcla con la
    de otra, así las chamarras (invierno) y las poleras (verano) pueden subir y bajar en sentido contrario."""
    n, k = len(COLUMNAS_NUMERICAS), 3
    angulo = 2 * math.pi * LUNES_ISO_13.isocalendar()[1] / 52.0
    for indice in range(k):
        x = fila_de_caracteristicas([1, 2, 3, 4], 10.0, 0.0, LUNES_ISO_13, indice, k)
        seno, coseno = x[n + k : n + 2 * k], x[n + 2 * k : n + 3 * k]
        assert seno[indice] == pytest.approx(math.sin(angulo)) and coseno[indice] == pytest.approx(math.cos(angulo))
        assert [v for i, v in enumerate(seno) if i != indice] == [0.0] * (k - 1)
        assert [v for i, v in enumerate(coseno) if i != indice] == [0.0] * (k - 1)
    assert len(x) == n + 3 * k
    assert nombres_de_columnas([30, 7, 12]) == nombres_de_columnas([7, 12, 30])


def test_semana_sin_y_semana_cos_son_el_ciclo_anual_de_52_semanas():
    for lunes, seno, coseno in ((LUNES_ISO_26, 0.0, -1.0), (LUNES_ISO_13, 1.0, 0.0)):
        x = fila_de_caracteristicas([1, 2, 3, 4], 10.0, 0.0, lunes, 0, 1)
        assert x[COLUMNAS_NUMERICAS.index("semana_sin")] == pytest.approx(seno, abs=1e-9)
        assert x[COLUMNAS_NUMERICAS.index("semana_cos")] == pytest.approx(coseno, abs=1e-9)
    semana = date(2026, 1, 5).isocalendar()[1]
    x = fila_de_caracteristicas([1, 2, 3, 4], 10.0, 0.0, date(2026, 1, 5), 0, 1)
    assert x[COLUMNAS_NUMERICAS.index("semana_sin")] == pytest.approx(math.sin(2 * math.pi * semana / 52))


def test_pct_descuento_y_precio_medio_se_calculan_de_neto_y_bruto():
    primero = _lunes(26)
    filas = _filas(26, {1: lambda j: 10, 2: lambda j: 10})
    # Categoría 1, semana 10: 10 unidades con lista de 100 y cobradas a 80 (20 % de descuento).
    for f in filas:
        if f["categoria_id"] == 1 and f["dia"] == primero + timedelta(weeks=10):
            f["ventas_brutas"], f["total_ventas"] = Decimal("100.00"), Decimal("80.00")
        if f["categoria_id"] == 1 and f["dia"] == primero + timedelta(weeks=12):
            f["unidades"] = 0  # una semana sin ventas
            f["ventas_brutas"] = f["total_ventas"] = Decimal("0")
    serie = construir_serie_semanal(filas, HASTA)
    assert serie.pct_descuento[0, 10] == pytest.approx(0.2)
    assert serie.pct_descuento[0, 9] == 0.0
    assert serie.pct_descuento[0, 12] == 0.0  # sin ventas no hay descuento que medir
    assert serie.precio_medio[0, 10] == pytest.approx(8.0)  # 80 / 10
    assert serie.precio_medio[0, 12] == pytest.approx(10.0)  # semana vacía: arrastra el de la semana 11
    matriz = construir_matriz(serie)
    fila = np.flatnonzero((matriz.indice_semana == 11) & (matriz.indice_categoria == 0))[0]
    col = matriz.columnas.index("precio_medio_lag_1")
    assert matriz.X[fila][col] == pytest.approx(8.0)  # el ticket de la semana ANTERIOR (la 10)


def test_mas_de_104_semanas_se_recortan_a_las_mas_recientes_con_aviso():
    serie = construir_serie_semanal(_filas(110, {1: lambda j: 3, 2: lambda j: 4}), HASTA)
    assert serie.n_semanas == limites.ML_MAX_SEMANAS == 104
    assert serie.semanas[-1] == date(2026, 10, 19)
    assert any("104" in aviso and "110" in aviso for aviso in serie.avisos)


def test_mas_de_30_categorias_se_recortan_por_volumen_con_aviso():
    # La categoría k vende k unidades por semana: las 30 de mayor volumen son las ids 6..35.
    serie = construir_serie_semanal(_filas(26, {k: (lambda j, k=k: k) for k in range(1, 36)}), HASTA)
    assert serie.n_categorias == limites.ML_MAX_CATEGORIAS == 30
    assert [cid for cid, _ in serie.categorias] == list(range(6, 36))
    assert any("30" in aviso and "35" in aviso for aviso in serie.avisos)


def test_con_pocas_semanas_o_pocas_categorias_lanza_datos_insuficientes_con_motivo():
    with pytest.raises(DatosInsuficientesError, match="25 semanas"):
        construir_serie_semanal(_filas(25, {1: lambda j: 3, 2: lambda j: 4}), HASTA)
    with pytest.raises(DatosInsuficientesError, match="categoría"):
        construir_serie_semanal(_filas(40, {1: lambda j: 3}), HASTA)
    with pytest.raises(DatosInsuficientesError):
        construir_serie_semanal([], HASTA)
    with pytest.raises(DatosInsuficientesError):  # todo es posterior a la última semana completa
        construir_serie_semanal([_fila(date(2026, 10, 27), 1, 5)], HASTA)


def test_una_categoria_sin_ventas_en_la_ventana_no_cuenta():
    # La categoría 9 solo vendió hace 150 semanas: queda fuera de las últimas 104 y no cuenta como categoría.
    filas = _filas(60, {1: lambda j: 3, 2: lambda j: 4})
    filas.append(_fila(HASTA - timedelta(weeks=150), 9, 100))
    serie = construir_serie_semanal(filas, HASTA)
    assert [cid for cid, _ in serie.categorias] == [1, 2]
