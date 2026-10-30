"""Generador determinista de filas de ventas de juguete para las pruebas del modelo de demanda (E11).

Devuelve lo mismo que `comercial.politicas.reporte_ventas_serie_diaria(desglose=("categoria",))` más
`ventas_brutas`: una fila por (día, categoría) CON ventas. La señal es real (estacionalidad anual distinta por
categoría, tendencia suave, efecto del día de la semana y semanas de promoción con descuento visible entre
`ventas_brutas` y `total_ventas`) y el ruido es Poisson. Es independiente del generador de E11 (`sintetico.py`):
sirve para probar el modelo sin depender de él. Usa un `Generator` propio con semilla fija, nunca el azar global.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

# Domingo: la última semana completa termina ahí, así que `hasta` es el cierre exacto de los datos.
HASTA_BASE = date(2026, 10, 25)

# (id, nombre, demanda semanal base, semana ISO del pico anual, amplitud, precio de lista)
CATEGORIAS = (
    (1, "Poleras", 90.0, 3, 0.55, Decimal("80.00")),  # verano austral: enero
    (2, "Camisas", 60.0, 40, 0.20, Decimal("150.00")),
    (3, "Chamarras", 45.0, 28, 0.65, Decimal("320.00")),  # invierno: julio
    (4, "Pantalones", 70.0, 20, 0.15, Decimal("220.00")),
    (5, "Accesorios", 35.0, 49, 0.30, Decimal("45.00")),  # fin de año
)
# Lunes a domingo: el sábado vende más que el martes.
PESO_DIA = np.array([0.10, 0.09, 0.11, 0.12, 0.16, 0.26, 0.16])
DESCUENTO_PROMOCION = Decimal("0.20")
EFECTO_PROMOCION = 1.35


def _centavos(valor: float) -> Decimal:
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def generar_filas(
    n_semanas: int = 78,
    hasta: date = HASTA_BASE,
    semilla: int = 7,
    n_categorias: int = 5,
    semanas_con_promocion: int = 8,
) -> list[dict]:
    """Filas de `n_semanas` semanas completas que terminan en `hasta` (un domingo). Con más de 5 categorías se
    repiten las plantillas con otros ids y nombres."""
    rng = np.random.default_rng(semilla)
    primer_lunes = hasta - timedelta(days=6) - timedelta(weeks=n_semanas - 1)
    # Las semanas con promoción se sortean una vez (misma para todas las categorías: es una campaña de tienda).
    promocion = set(rng.choice(np.arange(n_semanas), size=min(semanas_con_promocion, n_semanas), replace=False).tolist())

    filas: list[dict] = []
    for k in range(n_categorias):
        id_, nombre, base, pico, amplitud, precio = CATEGORIAS[k % len(CATEGORIAS)]
        if k >= len(CATEGORIAS):
            id_, nombre = k + 1, f"{nombre} {k + 1}"
        for semana in range(n_semanas):
            lunes = primer_lunes + timedelta(weeks=semana)
            estacion = 1.0 + amplitud * math.cos(2.0 * math.pi * (lunes.isocalendar()[1] - pico) / 52.0)
            tendencia = 1.0 + 0.25 * semana / max(1, n_semanas - 1)
            promo = semana in promocion
            lam = base * estacion * tendencia * (EFECTO_PROMOCION if promo else 1.0)
            for d in range(7):
                unidades = int(rng.poisson(lam * PESO_DIA[d]))
                if unidades == 0:
                    continue  # el día sin ventas no viene de la base
                bruto = precio * unidades
                neto = bruto * (Decimal(1) - DESCUENTO_PROMOCION) if promo else bruto
                filas.append(
                    {
                        "dia": lunes + timedelta(days=d),
                        "categoria_id": id_,
                        "categoria": nombre,
                        "transacciones": max(1, int(math.ceil(unidades * 0.7))),
                        "unidades": unidades,
                        "total_ventas": _centavos(float(neto)),
                        "ventas_brutas": _centavos(float(bruto)),
                    }
                )
    filas.sort(key=lambda f: (f["dia"], f["categoria_id"]))
    return filas
