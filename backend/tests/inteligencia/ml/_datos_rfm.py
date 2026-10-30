"""Datos de juguete para probar la segmentación RFM (E11, paso 8): clientes con ARQUETIPOS CONOCIDOS.

Cada cliente se simula como una serie de compras dentro de una ventana de 365 días; de ahí salen las
tres columnas que recibe `segmentar_clientes` (`cliente_id`, `ultima_compra`, `frecuencia`,
`monto_total`) y la "verdad" (cliente_id -> arquetipo) para medir la pureza de los segmentos.

Determinista (numpy con semilla fija, sin random global) y rápido (< 1 s para 300 clientes). Son datos
inventados por este archivo: que el modelo los separe prueba el flujo, no su utilidad con datos reales.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

HASTA = date(2026, 10, 1)  # fecha de corte de las pruebas
VENTANA_DIAS = 365

# arquetipo -> proporción de clientes (suman 1,00; paso 8)
PROPORCIONES = {
    "campeon": 0.08,
    "leal": 0.17,
    "ocasional": 0.35,
    "nuevo": 0.12,
    "dormido": 0.20,
    "cazaofertas": 0.08,
}

# arquetipo -> (días entre compras, ticket medio en Bs)
RITMO = {
    "campeon": (12.0, 320.0),
    "leal": (25.0, 140.0),
    "ocasional": (70.0, 110.0),
    "cazaofertas": (28.0, 45.0),
    "dormido": (20.0, 170.0),
}


def _eventos_por_ritmo(rng: np.random.Generator, cada: float, desde: float, hasta: float) -> list[float]:
    """Edades (días hacia atrás desde HASTA) de las compras de un cliente con un ritmo medio `cada`,
    entre las edades `desde` (más antigua) y `hasta` (más reciente). La separación entre compras es
    exponencial: así hay clientes algo más regulares y otros más irregulares."""
    edades = []
    edad = desde - rng.uniform(0, cada)
    while edad >= hasta:
        edades.append(edad)
        edad -= max(1.0, rng.exponential(cada))
    return edades


def _compras(rng: np.random.Generator, arquetipo: str) -> tuple[list[float], float]:
    """Edades de las compras y ticket medio del cliente."""
    if arquetipo == "nuevo":
        ticket = rng.lognormal(np.log(100.0), 0.3)
        n = int(rng.integers(1, 4))
        alta = rng.uniform(1, 42)  # se dio de alta en las últimas 6 semanas
        edades = sorted(rng.uniform(0, alta, size=n), reverse=True)
        return list(edades), ticket
    cada, ticket_medio = RITMO[arquetipo]
    ticket = rng.lognormal(np.log(ticket_medio), 0.3)
    if arquetipo == "dormido":
        # Compró mucho hace 6 a 12 meses y dejó de comprar hace 4 o más.
        desde = rng.uniform(300, VENTANA_DIAS)
        hasta = rng.uniform(120, 200)
        edades = _eventos_por_ritmo(rng, cada, desde, hasta)
    else:
        edades = _eventos_por_ritmo(rng, cada, VENTANA_DIAS - 1, 0)
    if not edades:  # todo cliente de la lista tiene al menos una compra
        edades = [rng.uniform(0, VENTANA_DIAS - 1)]
    return edades, ticket


def generar_filas_rfm(n_clientes: int = 300, semilla: int = 7) -> tuple[list[dict], dict[int, str]]:
    """Filas con el contrato de entrada de `segmentar_clientes` y la verdad `cliente_id -> arquetipo`.
    Los ids empiezan en 1000 para que no se confundan con posiciones de lista."""
    rng = np.random.default_rng(semilla)
    cantidades = {a: int(round(p * n_clientes)) for a, p in PROPORCIONES.items()}
    cantidades["ocasional"] += n_clientes - sum(cantidades.values())  # el resto del redondeo va al más grande
    filas: list[dict] = []
    verdad: dict[int, str] = {}
    cliente_id = 1000
    for arquetipo, cantidad in cantidades.items():
        for _ in range(cantidad):
            edades, ticket = _compras(rng, arquetipo)
            montos = rng.lognormal(np.log(ticket), 0.25, size=len(edades))
            monto_total = Decimal(str(round(float(montos.sum()), 2))).quantize(Decimal("0.01"), ROUND_HALF_UP)
            filas.append(
                {
                    "cliente_id": cliente_id,
                    "ultima_compra": HASTA - timedelta(days=int(min(edades))),
                    "frecuencia": len(edades),
                    "monto_total": monto_total,
                }
            )
            verdad[cliente_id] = arquetipo
            cliente_id += 1
    return filas, verdad
