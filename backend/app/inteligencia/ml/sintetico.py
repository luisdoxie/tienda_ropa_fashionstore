"""Generador de historial de ventas sintético (E11, paso 5). CÁLCULO PURO: no toca la base de datos,
no lee el reloj y no usa el `random` global. Todo sale de `numpy.random.default_rng(semilla_derivada)`,
así que el mismo (catálogo, configuración) produce SIEMPRE el mismo historial, byte a byte, en cualquier
máquina y aunque cambie `PYTHONHASHSEED` (no se usa `hash()` ni se recorren conjuntos de textos).

La carga a la base la hace `scripts/seed_ml_sintetico.py`; este módulo solo entrega objetos inmutables.
numpy se importa DENTRO de las funciones (el arranque de la aplicación no lo carga).

Modelo de la demanda. La tasa de unidades de la categoría `c`, el día `d`, en la sucursal `s` es

    tasa[d, s, c] = popularidad[c] * estacion[d, c] * evento[d] * promocion[d, c] * preferencia[s, c]

y las ventas de ese día se reparten así: el número de ventas sigue la suma de la tasa de todas las
categorías (por eso una promoción sube las ventas totales), y la categoría de cada línea se elige en
proporción a la tasa. Sobre eso se aplican el día de la semana, la quincena y la tendencia. El efecto
es que cada factor (estacionalidad, promoción, tendencia) se refleja de verdad en las unidades
semanales por categoría, con un ruido de Poisson moderado: un modelo supervisado puede aprenderlas.

Cada efecto es una constante con nombre en este archivo; no hay números mágicos dentro de las funciones.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------------------------------------
# Contrato de datos (entrada)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class VarianteCat:
    variante_id: int
    producto_id: int
    categoria_id: int
    precio: Decimal
    costo: Decimal


@dataclass(frozen=True)
class SucursalCat:
    sucursal_id: int
    cajero_id: int
    factor_tamano: float


@dataclass(frozen=True)
class CategoriaCat:
    categoria_id: int
    nombre: str


@dataclass(frozen=True)
class CatalogoSintetico:
    variantes: tuple[VarianteCat, ...]
    sucursales: tuple[SucursalCat, ...]
    categorias: tuple[CategoriaCat, ...]


@dataclass(frozen=True)
class ConfigSintetico:
    semilla: int = 42
    fin: dt.date = None  # type: ignore[assignment]  # OBLIGATORIO: último día del historial
    semanas: int = 78
    n_clientes: int = 300
    perfil: str = "A"  # "A" | "B": pesos de categorías, tendencia y mezcla de clientes
    codigo_empresa: str = ""


# ---------------------------------------------------------------------------------------------
# Contrato de datos (salida)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LineaSintetica:
    variante_id: int
    cantidad: int
    precio_unitario: Decimal  # precio de lista del catálogo (sin ruido)
    descuento: Decimal  # MONTO total de descuento de la línea (no por unidad)


@dataclass(frozen=True)
class VentaSintetica:
    indice: int
    fecha: dt.date
    sucursal_id: int
    cajero_id: int | None  # None en las ventas digitales (no pasan por caja)
    cliente_n: int | None  # 0..n_clientes-1; None = venta anónima (solo presencial)
    canal: str  # "presencial" | "digital"
    estado: str  # "pagada" | "entregada" | "anulada"
    metodo_pago: str
    lineas: tuple[LineaSintetica, ...]


@dataclass(frozen=True)
class DevolucionSintetica:
    venta_indice: int
    fecha: dt.date
    lineas: tuple[tuple[int, int], ...]  # (variante_id, cantidad)


@dataclass(frozen=True)
class PromocionSintetica:
    nombre: str  # con prefijo "[SIN] "
    porcentaje: Decimal
    fecha_inicio: dt.date
    fecha_fin: dt.date
    alcance: str  # "categoria" | "producto"
    alcance_id: int


@dataclass(frozen=True)
class ClienteSintetico:
    n: int
    arquetipo: str
    alta: dt.date


@dataclass(frozen=True)
class AnomaliaInyectada:
    fecha: dt.date
    sucursal_id: int
    tipo: str  # "cierre" | "liquidacion" | "devoluciones"


@dataclass(frozen=True)
class HistorialSintetico:
    ventas: tuple[VentaSintetica, ...]
    devoluciones: tuple[DevolucionSintetica, ...]
    promociones: tuple[PromocionSintetica, ...]
    clientes: tuple[ClienteSintetico, ...]
    anomalias: tuple[AnomaliaInyectada, ...]
    config: ConfigSintetico


# ---------------------------------------------------------------------------------------------
# Parámetros del modelo (cada efecto, documentado)
# ---------------------------------------------------------------------------------------------

ESTADOS_EFECTIVOS = ("pagada", "entregada")
ARQUETIPOS = ("campeon", "leal", "ocasional", "nuevo", "dormido", "cazaofertas")

# Día de la semana (lunes a domingo): viernes y sábado +35 %, domingo -25 %, lunes -10 %.
FACTOR_DIA_SEMANA = (0.90, 1.00, 1.00, 1.00, 1.35, 1.35, 0.75)
# Cobro de sueldos: los días 1-5 y 15-20 de cada mes venden +20 %.
FACTOR_QUINCENA = 1.20
# Estacionalidad anual (hemisferio sur). El coseno vale 1 a mediados de julio y -1 a mediados de enero.
PICO_INVIERNO_DIA_DEL_ANO = 196
AMPLITUD_INVIERNO = 0.60  # chamarras: ~ +50 % en mayo-agosto y ~ -45 % en diciembre-febrero
AMPLITUD_VERANO = 0.45  # poleras y camisas livianas: al revés
AMPLITUD_SUAVE = 0.15  # el resto de las categorías: ondas suaves, con una fase distinta cada una
MINIMO_ESTACIONAL = 0.15
PALABRAS_INVIERNO = ("chamarra", "abrigo", "chaqueta", "campera", "buzo", "sudadera", "casaca")
PALABRAS_VERANO = ("polera", "polo", "camiseta", "camisa", "remera", "short")
# Picos de +40 % en las semanas previas: (mes, día, días previos). Día del Padre (19/3) y de la Madre
# (27/5) de Bolivia, y Navidad.
EVENTOS = ((3, 19, 7), (5, 27, 7), (12, 25, 12))
FACTOR_EVENTO = 1.40
# Crecimiento lineal anual de la demanda por perfil, y hacia qué extremo del catálogo se inclina la
# popularidad de las categorías (así las dos empresas de prueba tienen una mezcla distinta).
PERFILES = {
    "A": {"tendencia": 0.08, "inclinacion": 1.0},
    "B": {"tendencia": 0.18, "inclinacion": -1.0},
}
TILT_POPULARIDAD = (1.5, 0.7)  # factor de la primera y de la última categoría (se invierte en el perfil B)
RUIDO_POPULARIDAD = 0.25  # desviación de la gamma que reparte la popularidad (media 1)
DESVIACION_PREFERENCIA_SUCURSAL = 0.25  # desfase de gusto de cada sucursal por categoría (lognormal)
# Proporciones de clientes por arquetipo, en el orden de ARQUETIPOS (suman 1).
PROPORCIONES_ARQUETIPOS = {
    "A": (0.08, 0.17, 0.35, 0.12, 0.20, 0.08),
    "B": (0.06, 0.14, 0.37, 0.13, 0.22, 0.08),
}
INTERVALO_COMPRA_DIAS = {"campeon": 12.0, "leal": 25.0, "ocasional": 70.0, "dormido": 15.0}
NUEVO_ALTA_MAX_DIAS = 42  # "nuevo": alta en las últimas 6 semanas
NUEVO_COMPRAS = (1, 3)  # de 1 a 3 compras
DORMIDO_VENTANA_DIAS = 365  # compró mucho hace 6-12 meses...
DORMIDO_CORTE_DIAS = (125, 200)  # ...y dejó de comprar hace 4 o más meses (nunca menos de 120 días)
PROB_DIA_CAZAOFERTAS = 0.06  # probabilidad diaria de compra en un día con promoción
ANONIMAS_BASE_POR_DIA = 0.55 # ventas anónimas por día de una sucursal de factor 1 (Poisson)
PROB_SUCURSAL_PROPIA = 0.85  # el cliente compra casi siempre en su sucursal
FRACCION_DIGITAL = 0.30  # del total de ventas
PROB_ANULADA = 0.02
LINEAS_LAMBDA = 0.6  # 1 + Poisson(0,6) líneas, hasta 4
LINEAS_LAMBDA_CAMPEON = 1.1  # ticket alto
LINEAS_MAX = 4
CANTIDADES = ((0.80, 1), (0.95, 2), (1.00, 3))  # cantidad 1/2/3 con 80/15/5 (acumulado)
EXPONENTE_ZIPF = 1.0
ENTREGA_DIGITAL_DIAS = (2, 5)
PAGO_PRESENCIAL = (("efectivo", 0.55), ("qr", 0.80), ("tarjeta", 1.00))  # acumulado
PAGO_DIGITAL = (("qr_online", 0.40), ("libelula", 0.75), ("paypal", 1.00))
TASA_DEVOLUCION = 0.05  # promedio sobre las ventas efectivas; la categoría problemática la duplica
DEVOLUCION_DIAS = (1, 10)
PROMOCIONES_POR_ANIO = (4, 6)
PROMOCION_PORCENTAJES = (10, 15, 20, 25, 30)
PROMOCION_DURACION_DIAS = (7, 21)
PROMOCION_SUBIDA = (1.3, 1.8)  # multiplicador de las unidades durante la promoción
PROMOCION_PROB_CATEGORIA = 0.70
PREFIJO_PROMOCION = "[SIN] "
# Anomalías: ventas -70 % (cierre), +200 % (liquidación) y devoluciones 6x, siempre en la sucursal más
# grande (donde la señal se distingue del ruido) y en un día martes a jueves, ni de quincena ni de evento.
ANOMALIA_CIERRE = 0.30  # fracción de las ventas habituales que quedan el día del cierre
ANOMALIA_LIQUIDACION = 3.0  # múltiplo de las ventas habituales
ANOMALIA_DEVOLUCIONES = 6.0  # múltiplo de las devoluciones diarias habituales
ANOMALIA_DEVOLUCIONES_MIN = 4
ANOMALIA_MARGEN_DIAS = 30  # no se inyectan en el primer ni en el último mes

_DOS_DECIMALES = Decimal("0.01")


# ---------------------------------------------------------------------------------------------
# Utilidades públicas
# ---------------------------------------------------------------------------------------------


def semilla_derivada(cfg: ConfigSintetico) -> int:
    """Semilla de la empresa: estable entre procesos (sha256, nunca `hash()`)."""
    resumen = hashlib.sha256(f"{cfg.semilla}:{cfg.codigo_empresa}".encode()).digest()
    return int.from_bytes(resumen[:8], "big")


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def tipo_estacional(nombre_categoria: str) -> str:
    """"invierno" (chamarras, abrigos), "verano" (poleras, polos, camisetas, camisas) o "suave"."""
    nombre = _sin_tildes(nombre_categoria)
    if any(palabra in nombre for palabra in PALABRAS_INVIERNO):
        return "invierno"
    if any(palabra in nombre for palabra in PALABRAS_VERANO):
        return "verano"
    return "suave"


def _dinero(valor: Decimal) -> Decimal:
    return valor.quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)


def _validar(catalogo: CatalogoSintetico, cfg: ConfigSintetico) -> None:
    if cfg.fin is None:
        raise ValueError("ConfigSintetico.fin es obligatorio: es el último día del historial.")
    if cfg.perfil not in PERFILES:
        raise ValueError(f"Perfil desconocido '{cfg.perfil}'. Usa 'A' o 'B'.")
    if cfg.semanas < 1 or cfg.n_clientes < 0:
        raise ValueError("semanas debe ser al menos 1 y n_clientes no puede ser negativo.")
    if not catalogo.variantes or not catalogo.sucursales:
        raise ValueError("El catálogo necesita al menos una variante y una sucursal.")
    ids_categoria = {c.categoria_id for c in catalogo.categorias}
    huerfanas = sorted({v.categoria_id for v in catalogo.variantes} - ids_categoria)
    if huerfanas:
        raise ValueError(f"Hay variantes de categorías que no están en el catálogo: {huerfanas}")


# ---------------------------------------------------------------------------------------------
# Generación
# ---------------------------------------------------------------------------------------------


def generar_historial(catalogo: CatalogoSintetico, cfg: ConfigSintetico) -> HistorialSintetico:
    """Historial completo de la empresa. Función pura: ver el docstring del módulo."""
    import numpy as np

    _validar(catalogo, cfg)
    rng = np.random.default_rng(semilla_derivada(cfg))
    perfil = PERFILES[cfg.perfil]
    n_dias = cfg.semanas * 7
    inicio = cfg.fin - dt.timedelta(days=n_dias - 1)
    fechas = [inicio + dt.timedelta(days=i) for i in range(n_dias)]

    # -- Categorías con variantes, popularidad y Zipf dentro de cada una --------------------
    categorias = [
        c for c in catalogo.categorias if any(v.categoria_id == c.categoria_id for v in catalogo.variantes)
    ]
    n_cat = len(categorias)
    n_suc = len(catalogo.sucursales)
    variantes_de = [[v for v in catalogo.variantes if v.categoria_id == c.categoria_id] for c in categorias]
    prob_variante = []  # por categoría: probabilidad base de cada variante (Zipf)
    for vs in variantes_de:
        rangos = np.empty(len(vs))
        rangos[rng.permutation(len(vs))] = np.arange(1, len(vs) + 1)
        pesos = 1.0 / rangos**EXPONENTE_ZIPF
        prob_variante.append(pesos / pesos.sum())

    tilt = np.linspace(TILT_POPULARIDAD[0], TILT_POPULARIDAD[1], n_cat) if n_cat > 1 else np.ones(1)
    if perfil["inclinacion"] < 0:
        tilt = tilt[::-1]
    ruido = rng.gamma(1.0 / RUIDO_POPULARIDAD**2, RUIDO_POPULARIDAD**2, size=n_cat)
    popularidad = tilt * ruido
    popularidad = popularidad / popularidad.sum()

    # -- Calendario y factores diarios -------------------------------------------------------
    dow = np.array([f.weekday() for f in fechas])
    dom = np.array([f.day for f in fechas])
    angulo = np.array([2 * np.pi * (f.timetuple().tm_yday - PICO_INVIERNO_DIA_DEL_ANO) / 365.0 for f in fechas])
    estacion = np.ones((n_dias, n_cat))
    for c, cat in enumerate(categorias):
        tipo = tipo_estacional(cat.nombre)
        if tipo == "invierno":
            estacion[:, c] = 1 + AMPLITUD_INVIERNO * np.cos(angulo)
        elif tipo == "verano":
            estacion[:, c] = 1 - AMPLITUD_VERANO * np.cos(angulo)
        else:
            estacion[:, c] = 1 + AMPLITUD_SUAVE * np.cos(angulo + 2 * np.pi * c / max(n_cat, 1))
    estacion = np.maximum(estacion, MINIMO_ESTACIONAL)
    evento = np.ones(n_dias)
    for i, f in enumerate(fechas):
        for mes, dia, previos in EVENTOS:
            if 0 <= (dt.date(f.year, mes, dia) - f).days <= previos:
                evento[i] = FACTOR_EVENTO
    preferencia = np.exp(rng.normal(0.0, DESVIACION_PREFERENCIA_SUCURSAL, size=(n_suc, n_cat)))
    preferencia = preferencia / preferencia.mean(axis=1, keepdims=True)
    factores_suc = np.array([s.factor_tamano for s in catalogo.sucursales], dtype=float)

    # -- Promociones (franjas separadas: no se pisan entre sí) ------------------------------
    promos = _generar_promociones(np, rng, catalogo, categorias, variantes_de, prob_variante, fechas, cfg)
    promocion = np.ones((n_dias, n_cat))
    promos_dia: list[list[dict]] = [[] for _ in range(n_dias)]
    for p in promos:
        promocion[p["ini"] : p["fin"] + 1, p["cat"]] *= p["efecto"]
        for d in range(p["ini"], p["fin"] + 1):
            promos_dia[d].append(p)
    hay_promo = np.array([bool(lista) for lista in promos_dia])

    # -- Tasa de unidades y factor de ventas por (día, sucursal) -----------------------------
    tasa = (
        popularidad[None, None, :]
        * estacion[:, None, :]
        * evento[:, None, None]
        * promocion[:, None, :]
        * preferencia[None, :, :]
    )
    suma_tasa = tasa.sum(axis=2)
    suma_tasa = suma_tasa / suma_tasa.mean()
    tendencia = 1.0 + perfil["tendencia"] * np.arange(n_dias) / 365.0
    global_dia = np.array([FACTOR_DIA_SEMANA[w] for w in dow]) * np.where(
        ((dom >= 1) & (dom <= 5)) | ((dom >= 15) & (dom <= 20)), FACTOR_QUINCENA, 1.0
    )
    global_dia = global_dia * tendencia
    global_dia = global_dia / global_dia.mean()
    factor_ventas = global_dia[:, None] * suma_tasa  # media ~1; (n_dias, n_suc)
    factor_cliente = (factor_ventas * factores_suc[None, :]).sum(axis=1) / factores_suc.sum()

    # -- Clientes y sus arquetipos -----------------------------------------------------------
    arq_de = _asignar_arquetipos(np, rng, cfg)
    cli_cliente, cli_dia = _compras_de_clientes(np, rng, cfg, arq_de, n_dias, factor_cliente, hay_promo)
    peso_suc = factores_suc / factores_suc.sum()
    # Cada cliente tiene su sucursal (más probable la grande); casi siempre compra en ella.
    home = rng.choice(n_suc, size=max(cfg.n_clientes, 1), p=peso_suc)
    otra = rng.random(len(cli_dia)) >= PROB_SUCURSAL_PROPIA
    azar = rng.choice(n_suc, size=len(cli_dia), p=peso_suc)
    cli_suc = np.where(otra, azar, home[cli_cliente]).astype(int)

    # -- Ventas anónimas ----------------------------------------------------------------------
    lam = ANONIMAS_BASE_POR_DIA * factores_suc[None, :] * factor_ventas
    n_anon = rng.poisson(lam)  # (n_dias, n_suc)
    anon_d, anon_s = np.nonzero(n_anon)
    repeticiones = n_anon[anon_d, anon_s]
    anon_d, anon_s = np.repeat(anon_d, repeticiones), np.repeat(anon_s, repeticiones)

    d_all = np.concatenate([anon_d, cli_dia]).astype(int)
    s_all = np.concatenate([anon_s, cli_suc]).astype(int)
    c_all = np.concatenate([np.full(len(anon_d), -1), cli_cliente]).astype(int)

    # -- Anomalías sobre las ventas (cierre y liquidación) -----------------------------------
    anomalias, d_all, s_all, c_all = _inyectar_anomalias_de_ventas(
        np, rng, catalogo, fechas, dow, dom, evento, hay_promo, d_all, s_all, c_all
    )

    # -- Orden final, canal y número de líneas ------------------------------------------------
    orden = np.lexsort((c_all, s_all, d_all))
    d_all, s_all, c_all = d_all[orden], s_all[orden], c_all[orden]
    n_ventas = len(d_all)
    n_con_cliente = int((c_all >= 0).sum())
    prob_digital = min(0.90, FRACCION_DIGITAL * n_ventas / n_con_cliente) if n_con_cliente else 0.0
    digital = (c_all >= 0) & (rng.random(n_ventas) < prob_digital)
    arq_venta = np.array([arq_de[c] if c >= 0 else -1 for c in c_all], dtype=int)
    es_campeon = arq_venta == ARQUETIPOS.index("campeon")
    k = np.minimum(
        LINEAS_MAX, 1 + rng.poisson(np.where(es_campeon, LINEAS_LAMBDA_CAMPEON, LINEAS_LAMBDA))
    ).astype(int)
    total_lineas = int(k.sum())
    u_cat, u_var, u_cant = rng.random(total_lineas), rng.random(total_lineas), rng.random(total_lineas)
    u_estado, u_pago = rng.random(n_ventas), rng.random(n_ventas)
    dias_entrega = rng.integers(ENTREGA_DIGITAL_DIAS[0], ENTREGA_DIGITAL_DIAS[1] + 1, size=n_ventas)

    # -- Líneas de cada venta -----------------------------------------------------------------
    cum_cat = np.cumsum(tasa / tasa.sum(axis=2, keepdims=True), axis=2)
    cum_cat[:, :, -1] = 1.0
    cum_cat = cum_cat.tolist()
    cum_var_base = [np.cumsum(p).tolist() for p in prob_variante]
    cache_cum: dict = {}
    prod_promos_dia_cat = _promos_de_producto_por_dia(promos)
    caza = ARQUETIPOS.index("cazaofertas")
    ventas_lineas: list[tuple[tuple[LineaSintetica, ...], tuple[int, ...]]] = []
    pos_linea = 0
    for i in range(n_ventas):
        d, s = int(d_all[i]), int(s_all[i])
        acumuladas: dict[int, list] = {}
        categorias_usadas: list[int] = []
        for j in range(int(k[i])):
            forzada = promos_dia[d][0] if (j == 0 and arq_venta[i] == caza and promos_dia[d]) else None
            if forzada is not None:
                c = forzada["cat"]
            else:
                c = min(bisect_right(cum_cat[d][s], u_cat[pos_linea]), n_cat - 1)
            clave = prod_promos_dia_cat.get((d, c), ())
            vs = variantes_de[c]
            if forzada is not None and forzada["alcance"] == "producto":
                candidatas = [idx for idx, v in enumerate(vs) if v.producto_id == forzada["alcance_id"]]
                v_idx = candidatas[min(int(u_var[pos_linea] * len(candidatas)), len(candidatas) - 1)]
            else:
                if clave:
                    if (c, clave) not in cache_cum:
                        pesos = prob_variante[c].copy()
                        for idx, v in enumerate(vs):
                            for producto_id, efecto in clave:
                                if v.producto_id == producto_id:
                                    pesos[idx] *= efecto
                        cache_cum[(c, clave)] = np.cumsum(pesos / pesos.sum()).tolist()
                    cum = cache_cum[(c, clave)]
                else:
                    cum = cum_var_base[c]
                v_idx = min(bisect_right(cum, u_var[pos_linea]), len(vs) - 1)
            cantidad = _cantidad(float(u_cant[pos_linea]))
            pos_linea += 1
            variante = vs[v_idx]
            if variante.variante_id in acumuladas:
                acumuladas[variante.variante_id][1] += cantidad
            else:
                acumuladas[variante.variante_id] = [variante, cantidad, c]
                categorias_usadas.append(c)
        lineas = []
        for variante, cantidad, _c in acumuladas.values():
            pct = _mejor_descuento(promos_dia[d], variante)
            bruto = variante.precio * cantidad
            descuento = _dinero(bruto * Decimal(pct) / Decimal(100)) if pct else Decimal("0.00")
            lineas.append(LineaSintetica(variante.variante_id, cantidad, variante.precio, descuento))
        ventas_lineas.append((tuple(lineas), tuple(categorias_usadas)))

    # -- Ventas completas ---------------------------------------------------------------------
    ventas = []
    for i in range(n_ventas):
        d, s = int(d_all[i]), int(s_all[i])
        es_digital = bool(digital[i])
        if u_estado[i] < PROB_ANULADA:
            estado = "anulada"
        elif es_digital and d + int(dias_entrega[i]) <= n_dias - 1:
            estado = "entregada"
        else:
            estado = "pagada"
        ventas.append(
            VentaSintetica(
                indice=i,
                fecha=fechas[d],
                sucursal_id=catalogo.sucursales[s].sucursal_id,
                cajero_id=None if es_digital else catalogo.sucursales[s].cajero_id,
                cliente_n=int(c_all[i]) if c_all[i] >= 0 else None,
                canal="digital" if es_digital else "presencial",
                estado=estado,
                metodo_pago=_elegir(PAGO_DIGITAL if es_digital else PAGO_PRESENCIAL, u_pago[i]),
                lineas=ventas_lineas[i][0],
            )
        )

    devoluciones = _generar_devoluciones(
        np, rng, catalogo, cfg, categorias, variantes_de, ventas, ventas_lineas, fechas, anomalias
    )

    # -- Clientes (con su fecha de alta) y promociones ----------------------------------------
    primera_compra: dict[int, dt.date] = {}
    for v in ventas:  # las ventas ya van por orden de fecha
        if v.cliente_n is not None and v.cliente_n not in primera_compra:
            primera_compra[v.cliente_n] = v.fecha
    clientes = []
    for n in range(cfg.n_clientes):
        arquetipo = ARQUETIPOS[arq_de[n]]
        if n in primera_compra:
            retraso = 0 if arquetipo == "nuevo" else int(rng.integers(0, 31))
            alta = primera_compra[n] - dt.timedelta(days=retraso)
        else:
            alta = inicio - dt.timedelta(days=int(rng.integers(30, 201)))
        clientes.append(ClienteSintetico(n=n, arquetipo=arquetipo, alta=alta))
    promociones = tuple(
        PromocionSintetica(
            nombre=p["nombre"],
            porcentaje=Decimal(p["pct"]).quantize(_DOS_DECIMALES),
            fecha_inicio=fechas[p["ini"]],
            fecha_fin=fechas[p["fin"]],
            alcance=p["alcance"],
            alcance_id=p["alcance_id"],
        )
        for p in promos
    )
    return HistorialSintetico(
        ventas=tuple(ventas),
        devoluciones=tuple(devoluciones),
        promociones=promociones,
        clientes=tuple(clientes),
        anomalias=tuple(anomalias),
        config=cfg,
    )


# ---------------------------------------------------------------------------------------------
# Piezas de la generación
# ---------------------------------------------------------------------------------------------


def _elegir(opciones: tuple[tuple[str, float], ...], u: float) -> str:
    for valor, tope in opciones:
        if u < tope:
            return valor
    return opciones[-1][0]


def _cantidad(u: float) -> int:
    """Unidades de una línea: 1 (80 %), 2 (15 %) o 3 (5 %)."""
    for tope, cantidad in CANTIDADES:
        if u < tope:
            return cantidad
    return CANTIDADES[-1][1]


def _mejor_descuento(promos_del_dia: list[dict], variante: VarianteCat) -> int:
    """El mayor porcentaje entre las promociones vigentes que alcanzan a la variante (misma regla
    que `comercial.politicas.mejor_descuento`: no se suman)."""
    mejor = 0
    for p in promos_del_dia:
        alcanza = (p["alcance"] == "categoria" and p["alcance_id"] == variante.categoria_id) or (
            p["alcance"] == "producto" and p["alcance_id"] == variante.producto_id
        )
        if alcanza and p["pct"] > mejor:
            mejor = p["pct"]
    return mejor


def _promos_de_producto_por_dia(promos: list[dict]) -> dict:
    """(día, categoría) -> ((producto_id, efecto), ...) de las promociones por producto vigentes."""
    resultado: dict = {}
    for p in promos:
        if p["alcance"] != "producto":
            continue
        for d in range(p["ini"], p["fin"] + 1):
            resultado[(d, p["cat"])] = resultado.get((d, p["cat"]), ()) + ((p["alcance_id"], p["subida"]),)
    return resultado


def _generar_promociones(np, rng, catalogo, categorias, variantes_de, prob_variante, fechas, cfg) -> list[dict]:
    """4 a 6 promociones por año. El historial se parte en tantas franjas como promociones y cada una
    cae dentro de la suya: nunca se pisan. `subida` es el multiplicador de las unidades del alcance;
    `efecto` es el que recibe la categoría (igual a `subida` si la promoción es de toda la categoría,
    y menor si es de un solo producto, que pesa solo lo que pesa dentro de su categoría)."""
    n_dias = len(fechas)
    por_anio = int(rng.integers(PROMOCIONES_POR_ANIO[0], PROMOCIONES_POR_ANIO[1] + 1))
    cantidad = max(1, int(round(cfg.semanas / 52.0 * por_anio)))
    largo_franja = n_dias // cantidad
    promos = []
    for k in range(cantidad):
        duracion = int(rng.integers(PROMOCION_DURACION_DIAS[0], PROMOCION_DURACION_DIAS[1] + 1))
        duracion = max(1, min(duracion, largo_franja - 6))
        desde = k * largo_franja + 3
        hasta_inicio = max(desde, (k + 1) * largo_franja - duracion - 3)
        ini = int(rng.integers(desde, hasta_inicio + 1))
        fin = min(ini + duracion - 1, n_dias - 1)
        ini = min(ini, fin)
        pct = int(rng.choice(PROMOCION_PORCENTAJES))
        subida = round(float(rng.uniform(PROMOCION_SUBIDA[0], PROMOCION_SUBIDA[1])), 2)
        es_categoria = rng.random() < PROMOCION_PROB_CATEGORIA
        c = int(rng.integers(0, len(categorias)))
        if es_categoria:
            alcance, alcance_id, efecto = "categoria", categorias[c].categoria_id, subida
            nombre_alcance = categorias[c].nombre
        else:
            vs = variantes_de[c]
            producto_id = vs[int(rng.integers(0, len(vs)))].producto_id
            peso = float(sum(p for v, p in zip(vs, prob_variante[c]) if v.producto_id == producto_id))
            alcance, alcance_id, efecto = "producto", producto_id, 1.0 + peso * (subida - 1.0)
            nombre_alcance = f"producto {producto_id}"
        nombre = f"{PREFIJO_PROMOCION}{k + 1:02d} {nombre_alcance} {pct}%"[:80]
        promos.append(
            dict(
                nombre=nombre, pct=pct, ini=ini, fin=fin, alcance=alcance, alcance_id=alcance_id,
                cat=c, subida=subida, efecto=efecto,
            )
        )
    return promos


def _asignar_arquetipos(np, rng, cfg) -> list[int]:
    """Índice de ARQUETIPOS de cada cliente. Los cupos salen de las proporciones del perfil por el
    método del mayor resto (la suma es exactamente `n_clientes`) y el orden se mezcla con la semilla."""
    n = cfg.n_clientes
    proporciones = PROPORCIONES_ARQUETIPOS[cfg.perfil]
    exactos = [p * n for p in proporciones]
    cupos = [int(x) for x in exactos]
    faltan = n - sum(cupos)
    por_resto = sorted(range(len(exactos)), key=lambda i: (-(exactos[i] - cupos[i]), i))
    for i in por_resto[:faltan]:
        cupos[i] += 1
    lista = [a for a, cupo in enumerate(cupos) for _ in range(cupo)]
    return [int(lista[i]) for i in rng.permutation(n)] if n else []


def _compras_de_clientes(np, rng, cfg, arq_de, n_dias, factor_cliente, hay_promo):
    """(cliente, día) de cada compra, por adelgazamiento: cada cliente tiene una probabilidad diaria
    igual a su frecuencia habitual por el peso del día. Devuelve dos arreglos de enteros."""
    n = cfg.n_clientes
    if n == 0:
        return np.zeros(0, dtype=int), np.zeros(0, dtype=int)
    arq = np.array(arq_de, dtype=int)
    idx_dia = np.arange(n_dias)
    prob = np.zeros((n, n_dias))
    for a, nombre in enumerate(ARQUETIPOS):
        filas = np.nonzero(arq == a)[0]
        if len(filas) == 0:
            continue
        if nombre in ("campeon", "leal", "ocasional"):
            prob[filas, :] = factor_cliente[None, :] / INTERVALO_COMPRA_DIAS[nombre]
        elif nombre == "dormido":
            inicio_activo = max(0, n_dias - 1 - DORMIDO_VENTANA_DIAS)
            for fila in filas:
                corte = n_dias - 1 - int(rng.integers(DORMIDO_CORTE_DIAS[0], DORMIDO_CORTE_DIAS[1] + 1))
                activo = (idx_dia >= inicio_activo) & (idx_dia <= corte)
                prob[fila, :] = np.where(activo, factor_cliente / INTERVALO_COMPRA_DIAS["dormido"], 0.0)
        elif nombre == "cazaofertas":
            prob[filas, :] = np.where(hay_promo, PROB_DIA_CAZAOFERTAS * factor_cliente, 0.0)[None, :]
    prob = np.clip(prob, 0.0, 0.9)
    golpes = rng.random((n, n_dias)) < prob
    cli, dia = np.nonzero(golpes)
    cli, dia = list(cli), list(dia)
    # Los nuevos: alta en las últimas 6 semanas y de 1 a 3 compras, la primera el día del alta.
    nuevo = ARQUETIPOS.index("nuevo")
    for fila in np.nonzero(arq == nuevo)[0]:
        espera = min(NUEVO_ALTA_MAX_DIAS, n_dias) - 1
        alta = n_dias - 1 - int(rng.integers(0, espera + 1))
        compras = int(rng.integers(NUEVO_COMPRAS[0], NUEVO_COMPRAS[1] + 1))
        dias = [alta]
        posteriores = n_dias - 1 - alta
        if posteriores > 0 and compras > 1:
            extra = rng.choice(np.arange(alta + 1, n_dias), size=min(compras - 1, posteriores), replace=False)
            dias += sorted(int(x) for x in extra)
        cli += [int(fila)] * len(dias)
        dia += dias
    return np.array(cli, dtype=int), np.array(dia, dtype=int)


def _inyectar_anomalias_de_ventas(np, rng, catalogo, fechas, dow, dom, evento, hay_promo, d_all, s_all, c_all):
    """Elige los 3 días de anomalía y aplica las dos que cambian las ventas: el cierre (quedan 30 % de
    las ventas habituales de la sucursal) y la liquidación (3x lo habitual, con ventas anónimas
    nuevas). La de devoluciones se aplica después, con las devoluciones. Devuelve las anomalías
    (ya con las tres) y las ventas modificadas."""
    n_dias = len(fechas)
    grande = max(range(len(catalogo.sucursales)), key=lambda i: (catalogo.sucursales[i].factor_tamano, -i))
    sucursal = catalogo.sucursales[grande]
    margen = min(ANOMALIA_MARGEN_DIAS, max(0, n_dias // 4))
    dia_sin_quincena = ~(((dom >= 1) & (dom <= 5)) | ((dom >= 15) & (dom <= 20)))
    ideal = (np.isin(dow, (1, 2, 3))) & dia_sin_quincena & (evento == 1.0) & (~hay_promo)
    rango = (np.arange(n_dias) >= margen) & (np.arange(n_dias) < n_dias - margen)
    for candidatos in (ideal & rango, np.isin(dow, (1, 2, 3)) & rango, rango, np.ones(n_dias, dtype=bool)):
        dias = np.nonzero(candidatos)[0]
        if len(dias) >= 3:
            break
    elegidos = sorted(int(x) for x in rng.choice(dias, size=min(3, len(dias)), replace=False))
    # El orden en que se reparten los tipos también depende de la semilla.
    tipos = ["cierre", "liquidacion", "devoluciones"]
    tipos = [tipos[i] for i in rng.permutation(3)][: len(elegidos)]
    dia_de = dict(zip(tipos, elegidos))
    habitual = float((s_all == grande).sum()) / n_dias  # ventas diarias medias de la sucursal grande

    if "cierre" in dia_de:
        d = dia_de["cierre"]
        quedan = int(round(ANOMALIA_CIERRE * habitual))
        posiciones = np.nonzero((d_all == d) & (s_all == grande))[0]
        if len(posiciones) > quedan:
            quitar = rng.choice(posiciones, size=len(posiciones) - quedan, replace=False)
            conservar = np.ones(len(d_all), dtype=bool)
            conservar[quitar] = False
            d_all, s_all, c_all = d_all[conservar], s_all[conservar], c_all[conservar]
    if "liquidacion" in dia_de:
        d = dia_de["liquidacion"]
        objetivo = int(round(ANOMALIA_LIQUIDACION * habitual))
        actuales = int(((d_all == d) & (s_all == grande)).sum())
        if actuales < objetivo:
            extra = objetivo - actuales
            d_all = np.concatenate([d_all, np.full(extra, d)])
            s_all = np.concatenate([s_all, np.full(extra, grande)])
            c_all = np.concatenate([c_all, np.full(extra, -1)])
    anomalias = [
        AnomaliaInyectada(fecha=fechas[dia_de[t]], sucursal_id=sucursal.sucursal_id, tipo=t)
        for t in ("cierre", "liquidacion", "devoluciones")
        if t in dia_de
    ]
    return anomalias, d_all, s_all, c_all


def _generar_devoluciones(np, rng, catalogo, cfg, categorias, variantes_de, ventas, ventas_lineas, fechas, anomalias):
    """4 a 6 % de las ventas efectivas, con una categoría problemática de tasa doble, y la anomalía de
    devoluciones 6x en la sucursal grande. La fecha de la devolución es de 1 a 10 días después de la
    venta; si cae después del último día del historial, no se registra."""
    n_cat = len(categorias)
    problematica = int(rng.integers(0, n_cat))
    ids_problematica = {v.variante_id for v in variantes_de[problematica]}
    efectivas = [v for v in ventas if v.estado in ESTADOS_EFECTIVOS]
    tiene_problematica = [any(l.variante_id in ids_problematica for l in v.lineas) for v in efectivas]
    fraccion = sum(tiene_problematica) / len(efectivas) if efectivas else 0.0
    base = TASA_DEVOLUCION / (1.0 + fraccion)  # así el promedio global queda en TASA_DEVOLUCION
    n = len(efectivas)
    u = rng.random(n)
    demora = rng.integers(DEVOLUCION_DIAS[0], DEVOLUCION_DIAS[1] + 1, size=n)
    elige = rng.random(n)
    fin = fechas[-1]
    devueltas: dict[int, DevolucionSintetica] = {}
    for i, venta in enumerate(efectivas):
        prob = base * (2.0 if tiene_problematica[i] else 1.0)
        if u[i] >= prob:
            continue
        fecha = venta.fecha + dt.timedelta(days=int(demora[i]))
        if fecha > fin:
            continue
        devueltas[venta.indice] = _devolucion_de(venta, fecha, ids_problematica, float(elige[i]), rng)

    # Anomalía de devoluciones: 6x las devoluciones diarias habituales de la sucursal, en un solo día.
    ancla = next((a for a in anomalias if a.tipo == "devoluciones"), None)
    if ancla is not None:
        por_sucursal = [d for d in devueltas.values() if ventas[d.venta_indice].sucursal_id == ancla.sucursal_id]
        habitual = len(por_sucursal) / len(fechas)
        cantidad = max(ANOMALIA_DEVOLUCIONES_MIN, int(round(ANOMALIA_DEVOLUCIONES * habitual)))
        candidatas = [
            v
            for v in efectivas
            if v.sucursal_id == ancla.sucursal_id
            and v.indice not in devueltas
            and 1 <= (ancla.fecha - v.fecha).days <= DEVOLUCION_DIAS[1]
        ]
        if candidatas:
            tomadas = rng.choice(len(candidatas), size=min(cantidad, len(candidatas)), replace=False)
            for t in sorted(int(x) for x in tomadas):
                venta = candidatas[t]
                devueltas[venta.indice] = _devolucion_de(venta, ancla.fecha, ids_problematica, float(rng.random()), rng)
    return sorted(devueltas.values(), key=lambda d: (d.fecha, d.venta_indice))


def _devolucion_de(venta, fecha, ids_problematica, u, rng) -> DevolucionSintetica:
    """Devuelve una línea de la venta (la de la categoría problemática si la hay)."""
    problematicas = [l for l in venta.lineas if l.variante_id in ids_problematica]
    lineas = problematicas or list(venta.lineas)
    linea = lineas[min(int(u * len(lineas)), len(lineas) - 1)]
    cantidad = int(rng.integers(1, linea.cantidad + 1))
    return DevolucionSintetica(venta_indice=venta.indice, fecha=fecha, lineas=((linea.variante_id, cantidad),))


# ---------------------------------------------------------------------------------------------
# Ayudantes: la misma forma de filas que devuelven las consultas de la base
# ---------------------------------------------------------------------------------------------


def _bruto_y_total(venta: VentaSintetica) -> tuple[Decimal, Decimal]:
    bruto = sum((l.precio_unitario * l.cantidad for l in venta.lineas), Decimal("0"))
    descuento = sum((l.descuento for l in venta.lineas), Decimal("0"))
    return bruto, bruto - descuento


def filas_serie_diaria(historial: HistorialSintetico, catalogo: CatalogoSintetico) -> list[dict]:
    """Una fila por (día, categoría) con ventas EFECTIVAS (las anuladas no cuentan), con las mismas
    claves que `comercial.politicas.reporte_ventas_serie_diaria(desglose=("categoria",))`: `dia`,
    `categoria_id`, `categoria`, `transacciones`, `unidades`, `total_ventas` y `ventas_brutas`
    (Decimal de 2 decimales). Ordenadas por (día, categoría); solo salen los días y categorías con ventas."""
    variante_a_categoria = {v.variante_id: v.categoria_id for v in catalogo.variantes}
    nombres = {c.categoria_id: c.nombre for c in catalogo.categorias}
    acumulado: dict[tuple[dt.date, int], dict] = {}
    for venta in historial.ventas:
        if venta.estado not in ESTADOS_EFECTIVOS:
            continue
        for linea in venta.lineas:
            categoria_id = variante_a_categoria[linea.variante_id]
            fila = acumulado.setdefault(
                (venta.fecha, categoria_id),
                {"ventas": set(), "unidades": 0, "total": Decimal("0"), "bruto": Decimal("0")},
            )
            fila["ventas"].add(venta.indice)
            fila["unidades"] += linea.cantidad
            fila["bruto"] += linea.precio_unitario * linea.cantidad
            fila["total"] += linea.precio_unitario * linea.cantidad - linea.descuento
    return [
        {
            "dia": dia,
            "categoria_id": categoria_id,
            "categoria": nombres[categoria_id],
            "transacciones": len(fila["ventas"]),
            "unidades": fila["unidades"],
            "total_ventas": _dinero(fila["total"]),
            "ventas_brutas": _dinero(fila["bruto"]),
        }
        for (dia, categoria_id), fila in sorted(acumulado.items())
    ]


def filas_rfm(historial: HistorialSintetico, hasta: dt.date, dias: int = 365) -> list[dict]:
    """Una fila por cliente con compras efectivas en la ventana `(hasta - dias, hasta]`, con las mismas
    claves que `comercial.politicas.reporte_rfm_clientes`: `cliente_id` (= `cliente_n`), `ultima_compra`,
    `frecuencia` y `monto_total` (Decimal de 2 decimales). Ordenadas por cliente; las anónimas no entran."""
    desde = hasta - dt.timedelta(days=dias - 1)
    por_cliente: dict[int, dict] = {}
    for venta in historial.ventas:
        if venta.cliente_n is None or venta.estado not in ESTADOS_EFECTIVOS:
            continue
        if not (desde <= venta.fecha <= hasta):
            continue
        fila = por_cliente.setdefault(
            venta.cliente_n, {"ultima": venta.fecha, "frecuencia": 0, "monto": Decimal("0")}
        )
        fila["ultima"] = max(fila["ultima"], venta.fecha)
        fila["frecuencia"] += 1
        fila["monto"] += _bruto_y_total(venta)[1]
    return [
        {
            "cliente_id": cliente,
            "ultima_compra": f["ultima"],
            "frecuencia": f["frecuencia"],
            "monto_total": _dinero(f["monto"]),
        }
        for cliente, f in sorted(por_cliente.items())
    ]
