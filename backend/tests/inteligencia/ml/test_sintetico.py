"""Generador de historial sintético (E11, paso 5; pruebas del paso 12). Puro: sin base de datos, sin red.

El catálogo de prueba se parece al de las organizaciones de demostración (5 categorías, 20 variantes con
precios de 119 a 459 y 3 sucursales de distinto tamaño). Las propiedades estadísticas se miden sobre el
historial por defecto (78 semanas, 300 clientes): con ese volumen el ruido de Poisson es pequeño frente a los
márgenes que se exigen, y como la semilla es fija el resultado es el mismo en cada corrida.
"""

import ast
import datetime as dt
import hashlib
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from app.inteligencia.ml import sintetico
from app.inteligencia.ml.sintetico import (
    ARQUETIPOS,
    PROPORCIONES_ARQUETIPOS,
    CategoriaCat,
    CatalogoSintetico,
    ConfigSintetico,
    SucursalCat,
    VarianteCat,
    filas_rfm,
    filas_serie_diaria,
    generar_historial,
    semilla_derivada,
    tipo_estacional,
)

FIN = dt.date(2026, 10, 28)
BACKEND = Path(__file__).resolve().parents[3]

_CATEGORIAS = ((1, "Poleras"), (2, "Polos"), (3, "Camisetas deportivas"), (4, "Chamarras"), (5, "Camisas"))
_PRECIOS = {
    1: (119, 129, 149, 179),
    2: (129, 139, 169, 189),
    3: (159, 189, 219, 249),
    4: (299, 359, 399, 459),
    5: (169, 199, 229, 259),
}


def catalogo_de_prueba() -> CatalogoSintetico:
    """5 categorías, 20 variantes (2 por producto), 3 sucursales con factores 1.0, 0.75 y 2.2."""
    variantes = []
    variante_id = 1
    for categoria_id, _ in _CATEGORIAS:
        for k, precio in enumerate(_PRECIOS[categoria_id]):
            variantes.append(
                VarianteCat(variante_id, categoria_id * 100 + k // 2, categoria_id, Decimal(precio), Decimal(precio) / 2)
            )
            variante_id += 1
    return CatalogoSintetico(
        variantes=tuple(variantes),
        sucursales=(SucursalCat(1, 11, 1.0), SucursalCat(2, 12, 0.75), SucursalCat(3, 13, 2.2)),
        categorias=tuple(CategoriaCat(i, n) for i, n in _CATEGORIAS),
    )


def config(**cambios) -> ConfigSintetico:
    datos = {"fin": FIN, "codigo_empresa": "fashionstore"}
    datos.update(cambios)
    return ConfigSintetico(**datos)


def digest(historial) -> str:
    """Huella de todo el historial: el repr de los dataclasses congelados es determinista."""
    return hashlib.sha256(repr(historial).encode()).hexdigest()


def digest_por_defecto() -> str:
    """Lo que ejecutan los subprocesos de la prueba de PYTHONHASHSEED."""
    return digest(generar_historial(catalogo_de_prueba(), config()))


@pytest.fixture(scope="module")
def catalogo():
    return catalogo_de_prueba()


@pytest.fixture(scope="module")
def historial(catalogo):
    return generar_historial(catalogo, config())


@pytest.fixture(scope="module")
def historial_b(catalogo):
    return generar_historial(catalogo, config(perfil="B"))


def efectivas(historial):
    return [v for v in historial.ventas if v.estado in ("pagada", "entregada")]


def promedio_diario_por_categoria(historial, catalogo, meses) -> dict[str, float]:
    """Unidades por día de cada categoría en los días del historial cuyo mes está en `meses`."""
    inicio = FIN - dt.timedelta(days=78 * 7 - 1)
    dias = [inicio + dt.timedelta(days=i) for i in range(78 * 7)]
    n_dias = sum(1 for d in dias if d.month in meses)
    unidades: dict[str, int] = defaultdict(int)
    for fila in filas_serie_diaria(historial, catalogo):
        if fila["dia"].month in meses:
            unidades[fila["categoria"]] += fila["unidades"]
    return {nombre: unidades[nombre] / n_dias for _, nombre in _CATEGORIAS}


# ---- Determinismo y semilla -------------------------------------------------------------------


def test_mismo_catalogo_y_config_dan_un_historial_identico_byte_a_byte(catalogo, historial):
    otra_vez = generar_historial(catalogo_de_prueba(), config())
    assert digest(otra_vez) == digest(historial)
    assert otra_vez == historial


def test_semilla_empresa_o_perfil_distintos_dan_historiales_distintos(catalogo, historial):
    base = digest(historial)
    assert digest(generar_historial(catalogo, config(semilla=43))) != base
    assert digest(generar_historial(catalogo, config(codigo_empresa="boutique-andina"))) != base
    assert digest(generar_historial(catalogo, config(perfil="B"))) != base
    # La semilla derivada es la del contrato (sha256 de "semilla:codigo", 8 bytes) y varía con ambos datos.
    esperada = int.from_bytes(hashlib.sha256(b"42:fashionstore").digest()[:8], "big")
    assert semilla_derivada(config()) == esperada
    assert semilla_derivada(config(semilla=1)) != semilla_derivada(config(semilla=2))


def test_el_resultado_no_depende_de_pythonhashseed():
    """Dos procesos con PYTHONHASHSEED distintos producen el mismo digest (no se usa `hash()`)."""
    codigo = "from tests.inteligencia.ml.test_sintetico import digest_por_defecto as d; print(d())"
    resultados = []
    for semilla_hash in ("1", "98765"):
        entorno = {**os.environ, "PYTHONHASHSEED": semilla_hash, "PYTHONPATH": "."}
        proceso = subprocess.run(
            [sys.executable, "-c", codigo], cwd=BACKEND, env=entorno, capture_output=True, text=True, timeout=120
        )
        assert proceso.returncode == 0, proceso.stderr
        resultados.append(proceso.stdout.strip().splitlines()[-1])
    assert resultados[0] == resultados[1] == digest_por_defecto()


def test_no_usa_el_random_global_ni_hash(catalogo, historial):
    # (a) Por código: ni `import random`, ni `hash()`, ni funciones sueltas de numpy.random (solo default_rng).
    arbol = ast.parse(Path(sintetico.__file__).read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            assert "random" not in [a.name for a in nodo.names]
        if isinstance(nodo, ast.ImportFrom):
            assert nodo.module != "random"
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
            assert nodo.func.id != "hash"
        if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Attribute):
            if nodo.value.attr == "random":  # np.random.<algo>
                assert nodo.attr == "default_rng", f"np.random.{nodo.attr} usa estado global"
    # (b) Por comportamiento: el estado global de `random` y de numpy no cambia el resultado.
    import numpy as np

    random.seed(1)
    np.random.seed(1)
    a = digest(generar_historial(catalogo, config()))
    random.seed(999)
    np.random.seed(999)
    assert a == digest(generar_historial(catalogo, config())) == digest(historial)


# ---- Fechas y volumen ----------------------------------------------------------------------------


def test_ninguna_fecha_cae_fuera_del_historial_ni_en_el_futuro(historial):
    inicio = FIN - dt.timedelta(days=78 * 7 - 1)
    assert min(v.fecha for v in historial.ventas) >= inicio
    assert max(v.fecha for v in historial.ventas) <= FIN
    assert all(inicio <= d.fecha <= FIN for d in historial.devoluciones)
    assert all(inicio <= p.fecha_inicio <= p.fecha_fin <= FIN for p in historial.promociones)
    assert all(c.alta <= FIN for c in historial.clientes)
    assert all(inicio <= a.fecha <= FIN for a in historial.anomalias)
    por_indice = {v.indice: v for v in historial.ventas}
    assert all(d.fecha > por_indice[d.venta_indice].fecha for d in historial.devoluciones)


def test_el_volumen_por_defecto_es_el_esperado_y_las_reglas_basicas_se_cumplen(historial):
    ventas = historial.ventas
    n_lineas = sum(len(v.lineas) for v in ventas)
    assert 4_000 <= len(ventas) <= 6_000
    assert 8_000 <= n_lineas <= 12_000
    assert [v.indice for v in ventas] == list(range(len(ventas)))
    digitales = sum(v.canal == "digital" for v in ventas) / len(ventas)
    assert 0.26 <= digitales <= 0.34
    assert 0.01 <= sum(v.estado == "anulada" for v in ventas) / len(ventas) <= 0.035
    assert 4 <= len(historial.promociones) <= 9
    for v in ventas:
        assert (v.cliente_n is not None) or v.canal == "presencial"  # el digital exige cliente
        assert (v.cajero_id is not None) == (v.canal == "presencial")
        assert 1 <= len(v.lineas) <= 4
        assert v.estado != "entregada" or v.canal == "digital"
    # Cantidad 1/2/3 (80/15/5); si una venta repite la variante, las cantidades se suman en una sola línea.
    cantidades = Counter(l.cantidad for v in ventas for l in v.lineas)
    assert min(cantidades) >= 1 and sum(q for c, q in cantidades.items() if c <= 3) / sum(cantidades.values()) > 0.97
    assert 0.75 <= cantidades[1] / sum(cantidades.values()) <= 0.85


def test_el_descuento_sale_de_una_promocion_vigente(catalogo, historial):
    """El descuento de cada línea es el porcentaje de una promoción vigente de su categoría o producto."""
    por_variante = {v.variante_id: v for v in catalogo.variantes}
    con_descuento = 0
    for venta in historial.ventas:
        vigentes = [p for p in historial.promociones if p.fecha_inicio <= venta.fecha <= p.fecha_fin]
        for linea in venta.lineas:
            variante = por_variante[linea.variante_id]
            assert linea.precio_unitario == variante.precio
            porcentajes = [
                p.porcentaje
                for p in vigentes
                if (p.alcance == "categoria" and p.alcance_id == variante.categoria_id)
                or (p.alcance == "producto" and p.alcance_id == variante.producto_id)
            ]
            if not porcentajes:
                assert linea.descuento == Decimal("0.00")
                continue
            con_descuento += 1
            esperado = (variante.precio * linea.cantidad * max(porcentajes) / 100).quantize(Decimal("0.01"))
            assert linea.descuento == esperado
    assert con_descuento > 100
    assert all(p.nombre.startswith("[SIN] ") and len(p.nombre) <= 80 for p in historial.promociones)


# ---- Efectos modelados --------------------------------------------------------------------------------


def test_el_sabado_vende_mas_de_15_por_ciento_que_el_martes(historial):
    inicio = FIN - dt.timedelta(days=78 * 7 - 1)
    ventas_por_dia = Counter(v.fecha for v in historial.ventas)
    dias = [inicio + dt.timedelta(days=i) for i in range(78 * 7)]
    sabados = [ventas_por_dia[d] for d in dias if d.weekday() == 5]
    martes = [ventas_por_dia[d] for d in dias if d.weekday() == 1]
    assert (sum(sabados) / len(sabados)) > 1.15 * (sum(martes) / len(martes))


def test_chamarras_suben_en_invierno_y_poleras_al_reves(catalogo, historial):
    invierno = promedio_diario_por_categoria(historial, catalogo, {5, 6, 7, 8})
    verano = promedio_diario_por_categoria(historial, catalogo, {12, 1, 2})
    assert invierno["Chamarras"] > 1.5 * verano["Chamarras"]
    for nombre in ("Poleras", "Polos", "Camisetas deportivas"):
        assert verano[nombre] > 1.2 * invierno[nombre], nombre
    assert tipo_estacional("Chamárras de invierno") == "invierno"
    assert tipo_estacional("Camisetas deportivas") == "verano"
    assert tipo_estacional("Accesorios") == "suave"


def test_las_semanas_con_promocion_venden_al_menos_1_2_veces_mas(catalogo, historial):
    """Para cada promoción de categoría: unidades diarias de esa categoría dentro de la promoción contra
    las de los 28 días antes y después (sin otras promociones). El promedio de los cocientes es >= 1,2."""
    por_dia: dict[tuple[dt.date, int], int] = defaultdict(int)
    for fila in filas_serie_diaria(historial, catalogo):
        por_dia[(fila["dia"], fila["categoria_id"])] = fila["unidades"]
    en_promo = {
        (p.alcance_id, p.fecha_inicio + dt.timedelta(days=i))
        for p in historial.promociones
        if p.alcance == "categoria"
        for i in range((p.fecha_fin - p.fecha_inicio).days + 1)
    }
    inicio = FIN - dt.timedelta(days=78 * 7 - 1)
    cocientes = []
    for p in historial.promociones:
        if p.alcance != "categoria":
            continue
        dentro = [p.fecha_inicio + dt.timedelta(days=i) for i in range((p.fecha_fin - p.fecha_inicio).days + 1)]
        fuera = [
            d
            for k in range(1, 29)
            for d in (p.fecha_inicio - dt.timedelta(days=k), p.fecha_fin + dt.timedelta(days=k))
            if inicio <= d <= FIN and (p.alcance_id, d) not in en_promo
        ]
        con = sum(por_dia[(d, p.alcance_id)] for d in dentro) / len(dentro)
        sin = sum(por_dia[(d, p.alcance_id)] for d in fuera) / len(fuera)
        cocientes.append(con / sin)
    assert len(cocientes) >= 3
    assert sum(cocientes) / len(cocientes) >= 1.2, cocientes
    assert sum(c > 1.0 for c in cocientes) >= len(cocientes) - 1


def test_devoluciones_entre_2_y_8_por_ciento_con_una_categoria_problematica(catalogo, historial):
    tasa = len(historial.devoluciones) / len(efectivas(historial))
    assert 0.02 <= tasa <= 0.08
    por_indice = {v.indice: v for v in historial.ventas}
    assert all(por_indice[d.venta_indice].estado != "anulada" for d in historial.devoluciones)
    assert len({d.venta_indice for d in historial.devoluciones}) == len(historial.devoluciones)  # una por venta
    # Cada devolución devuelve a lo sumo lo que se compró.
    for d in historial.devoluciones:
        compradas = {l.variante_id: l.cantidad for l in por_indice[d.venta_indice].lineas}
        assert all(1 <= cantidad <= compradas[variante] for variante, cantidad in d.lineas)
    # La categoría problemática devuelve más: su tasa por línea vendida es la mayor y casi el doble de la menor.
    categoria = {v.variante_id: v.categoria_id for v in catalogo.variantes}
    vendidas, devueltas = Counter(), Counter()
    for v in efectivas(historial):
        for l in v.lineas:
            vendidas[categoria[l.variante_id]] += 1
    for d in historial.devoluciones:
        for variante, _ in d.lineas:
            devueltas[categoria[variante]] += 1
    tasas = {c: devueltas[c] / vendidas[c] for c in vendidas}
    assert max(tasas.values()) > 1.5 * min(tasas.values())


@pytest.mark.parametrize("perfil", ["A", "B"])
def test_las_proporciones_de_arquetipos_estan_a_menos_de_3_puntos(catalogo, historial, historial_b, perfil):
    h = historial if perfil == "A" else historial_b
    assert len(h.clientes) == 300
    conteo = Counter(c.arquetipo for c in h.clientes)
    objetivo_paso_5 = dict(zip(ARQUETIPOS, (0.08, 0.17, 0.35, 0.12, 0.20, 0.08)))
    for nombre, proporcion in zip(ARQUETIPOS, PROPORCIONES_ARQUETIPOS[perfil]):
        assert abs(conteo[nombre] / 300 - proporcion) < 0.005
        assert abs(conteo[nombre] / 300 - objetivo_paso_5[nombre]) <= 0.03


def test_el_comportamiento_de_cada_arquetipo(historial):
    clientes = {c.n: c for c in historial.clientes}
    limite_dormido = FIN - dt.timedelta(days=120)
    por_cliente = defaultdict(list)
    for v in historial.ventas:
        if v.cliente_n is not None:
            por_cliente[v.cliente_n].append(v)
    for n, c in clientes.items():
        compras = por_cliente.get(n, [])
        if c.arquetipo == "dormido":
            assert all(v.fecha <= limite_dormido for v in compras), "un dormido compró en los últimos 120 días"
        if c.arquetipo == "nuevo":
            assert c.alta >= FIN - dt.timedelta(days=41)
            assert 1 <= len(compras) <= 3
            assert all(v.fecha >= c.alta for v in compras)
        if c.arquetipo == "cazaofertas":
            en_promo = lambda f: any(p.fecha_inicio <= f <= p.fecha_fin for p in historial.promociones)
            assert all(en_promo(v.fecha) for v in compras)
    dormidos = [n for n, c in clientes.items() if c.arquetipo == "dormido"]
    assert sum(len(por_cliente.get(n, [])) for n in dormidos) > 100  # "compró mucho" antes de dejar de comprar
    campeones = [len(por_cliente.get(n, [])) for n, c in clientes.items() if c.arquetipo == "campeon"]
    ocasionales = [len(por_cliente.get(n, [])) for n, c in clientes.items() if c.arquetipo == "ocasional"]
    assert sum(campeones) / len(campeones) > 3 * sum(ocasionales) / len(ocasionales)


def test_tres_anomalias_inyectadas_y_presentes_en_los_datos(historial):
    anomalias = {a.tipo: a for a in historial.anomalias}
    assert set(anomalias) == {"cierre", "liquidacion", "devoluciones"} and len(historial.anomalias) == 3
    assert len({a.fecha for a in historial.anomalias}) == 3
    inicio = FIN - dt.timedelta(days=78 * 7 - 1)
    assert all(inicio < a.fecha < FIN for a in historial.anomalias)
    por_indice = {v.indice: v for v in historial.ventas}

    def ventas_del_dia(a):
        return sum(1 for v in historial.ventas if v.fecha == a.fecha and v.sucursal_id == a.sucursal_id)

    def media_diaria(a):
        return sum(1 for v in historial.ventas if v.sucursal_id == a.sucursal_id) / (78 * 7)

    cierre, liquidacion, devs = anomalias["cierre"], anomalias["liquidacion"], anomalias["devoluciones"]
    assert ventas_del_dia(cierre) <= 0.5 * media_diaria(cierre)  # ventas -70 %
    assert ventas_del_dia(liquidacion) >= 2.5 * media_diaria(liquidacion)  # +200 %
    devoluciones_del_dia = sum(
        1 for d in historial.devoluciones
        if d.fecha == devs.fecha and por_indice[d.venta_indice].sucursal_id == devs.sucursal_id
    )
    media_devoluciones = sum(
        1 for d in historial.devoluciones if por_indice[d.venta_indice].sucursal_id == devs.sucursal_id
    ) / (78 * 7)
    assert devoluciones_del_dia >= 4 and devoluciones_del_dia >= 6 * media_devoluciones


def test_los_perfiles_a_y_b_difieren_en_mezcla_de_categorias_y_clientes(catalogo, historial, historial_b):
    def participacion(h):
        unidades = defaultdict(int)
        for fila in filas_serie_diaria(h, catalogo):
            unidades[fila["categoria_id"]] += fila["unidades"]
        total = sum(unidades.values())
        return {c: unidades[c] / total for c, _ in _CATEGORIAS}

    a, b = participacion(historial), participacion(historial_b)
    distancia = sum(abs(a[c] - b[c]) for c in a) / 2
    assert distancia > 0.05, (a, b)
    assert Counter(c.arquetipo for c in historial.clientes) != Counter(c.arquetipo for c in historial_b.clientes)


# ---- Ayudantes que imitan las consultas de la base --------------------------------------------------


def test_filas_serie_diaria_coincide_con_las_ventas(catalogo, historial):
    filas = filas_serie_diaria(historial, catalogo)
    assert filas and [(f["dia"], f["categoria_id"]) for f in filas] == sorted((f["dia"], f["categoria_id"]) for f in filas)
    assert set(filas[0]) == {
        "dia", "categoria_id", "categoria", "transacciones", "unidades", "total_ventas", "ventas_brutas"
    }
    assert len({(f["dia"], f["categoria_id"]) for f in filas}) == len(filas)
    # Los totales cuadran con las líneas de las ventas efectivas (las anuladas no cuentan).
    bruto = sum(l.precio_unitario * l.cantidad for v in efectivas(historial) for l in v.lineas)
    descuento = sum(l.descuento for v in efectivas(historial) for l in v.lineas)
    assert sum(f["ventas_brutas"] for f in filas) == bruto
    assert sum(f["total_ventas"] for f in filas) == bruto - descuento
    assert sum(f["unidades"] for f in filas) == sum(l.cantidad for v in efectivas(historial) for l in v.lineas)
    assert all(f["ventas_brutas"] >= f["total_ventas"] and f["transacciones"] >= 1 for f in filas)
    assert all(f["total_ventas"] == f["total_ventas"].quantize(Decimal("0.01")) for f in filas)
    # Una fila concreta, calculada a mano desde las ventas.
    cualquiera = filas[len(filas) // 2]
    categoria = {v.variante_id: v.categoria_id for v in catalogo.variantes}
    propias = [
        (v, l)
        for v in efectivas(historial)
        for l in v.lineas
        if v.fecha == cualquiera["dia"] and categoria[l.variante_id] == cualquiera["categoria_id"]
    ]
    assert cualquiera["transacciones"] == len({v.indice for v, _ in propias})
    assert cualquiera["unidades"] == sum(l.cantidad for _, l in propias)


def test_filas_rfm_coincide_con_las_ventas_y_respeta_la_ventana(historial):
    filas = filas_rfm(historial, FIN)
    assert [f["cliente_id"] for f in filas] == sorted(f["cliente_id"] for f in filas)
    assert set(filas[0]) == {"cliente_id", "ultima_compra", "frecuencia", "monto_total"}
    con_cliente = [v for v in efectivas(historial) if v.cliente_n is not None]
    ventana = [v for v in con_cliente if v.fecha > FIN - dt.timedelta(days=365)]
    assert sum(f["frecuencia"] for f in filas) == len(ventana)
    # Ventana más corta: (hasta - dias, hasta].
    hasta = FIN - dt.timedelta(days=100)
    cortas = filas_rfm(historial, hasta, dias=30)
    esperadas = [v for v in con_cliente if hasta - dt.timedelta(days=30) < v.fecha <= hasta]
    assert sum(f["frecuencia"] for f in cortas) == len(esperadas)
    assert all(hasta - dt.timedelta(days=30) < f["ultima_compra"] <= hasta for f in cortas)
    # Un cliente concreto, calculado a mano.
    fila = filas[len(filas) // 2]
    propias = [v for v in ventana if v.cliente_n == fila["cliente_id"]]
    assert fila["frecuencia"] == len(propias)
    assert fila["ultima_compra"] == max(v.fecha for v in propias)
    assert fila["monto_total"] == sum(
        (l.precio_unitario * l.cantidad - l.descuento for v in propias for l in v.lineas), Decimal("0")
    )


# ---- Tamaño, bordes y rendimiento --------------------------------------------------------------------


def test_genera_el_volumen_por_defecto_en_menos_de_5_segundos(catalogo):
    inicio = time.perf_counter()
    generar_historial(catalogo, config(codigo_empresa="reloj"))
    assert time.perf_counter() - inicio < 5.0


def test_funciona_con_una_sola_categoria_una_sucursal_y_pocos_clientes():
    catalogo = CatalogoSintetico(
        variantes=(VarianteCat(1, 1, 1, Decimal("100"), Decimal("50")),),
        sucursales=(SucursalCat(1, 11, 1.0),),
        categorias=(CategoriaCat(1, "Chamarras"),),
    )
    historial = generar_historial(catalogo, config(semanas=40, n_clientes=20))
    assert historial.ventas and len(historial.clientes) == 20
    assert filas_serie_diaria(historial, catalogo)
    assert len({a.tipo for a in historial.anomalias}) == 3
    assert 0 < len(historial.devoluciones) < len(historial.ventas) * 0.09
    sin_clientes = generar_historial(catalogo, config(semanas=10, n_clientes=0))
    assert sin_clientes.ventas and all(v.cliente_n is None and v.canal == "presencial" for v in sin_clientes.ventas)


def test_rechaza_una_configuracion_invalida(catalogo):
    with pytest.raises(ValueError, match="fin"):
        generar_historial(catalogo, ConfigSintetico())
    with pytest.raises(ValueError, match="Perfil"):
        generar_historial(catalogo, config(perfil="C"))
    with pytest.raises(ValueError, match="variante"):
        generar_historial(CatalogoSintetico((), catalogo.sucursales, catalogo.categorias), config())
