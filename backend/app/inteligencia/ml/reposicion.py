"""Sugerencia de reposición por categoría (E12b, CU-24): cruza la demanda prevista por el modelo de demanda con lo que
hay disponible. Cálculo PURO y sin numpy: solo aritmética de Python sobre listas y diccionarios; no toca la base de
datos ni importa paquetes de negocio.

Entrada: `demanda_por_categoria`, una fila por categoría con `categoria_id`, `categoria` y `unidades_semanales`
(la predicción de las semanas 1..h, en ese orden), y `disponible`, un diccionario `categoria_id -> unidades` (sin
categoría en el diccionario se toma 0). `semanas` es el horizonte de cobertura que el usuario quiere cubrir (1 a 12).

Reglas:
  * demanda semanal promedio = suma de las semanas previstas / número de semanas previstas.
  * semanas de cobertura = disponible / demanda semanal promedio. Sin demanda prevista (promedio 0) no hay a qué
    dividir: la cobertura es None (infinita) y el estado es "ok".
  * agotado en la semana k = la primera semana en que la demanda ACUMULADA prevista alcanza o supera lo disponible,
    dentro del horizonte previsto; None si no se agota.
  * estado: "critico" si la cobertura es menor de 2 semanas; "atencion" si es menor que `semanas`; "ok" en otro caso.
  * sugerencia = max(0, techo(demanda acumulada total x 1,10 - disponible)): cubrir el horizonte previsto con un
    colchón del 10 %.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

UMBRAL_CRITICO_SEMANAS = 2  # menos de tantas semanas de cobertura -> "critico"
COLCHON = 0.10  # margen sobre la demanda acumulada al sugerir unidades
MIN_SEMANAS = 1
MAX_SEMANAS = 12  # igual que `predecir_demanda`
ESTADO_CRITICO = "critico"
ESTADO_ATENCION = "atencion"
ESTADO_OK = "ok"
_ORDEN_ESTADO = {ESTADO_CRITICO: 0, ESTADO_ATENCION: 1, ESTADO_OK: 2}

SUPUESTOS = [
    "La demanda prevista es la del modelo de demanda por categoría; es una estimación, no una promesa de ventas.",
    "No descuenta órdenes de compra en camino ni transferencias entre sucursales: solo cuenta lo disponible hoy.",
    "Es por categoría, no por variante (talla, color) ni por sucursal: una categoría puede estar bien en total y "
    "faltar en una tienda o en una talla.",
    f"La sugerencia incluye un colchón del {round(COLCHON * 100)} % sobre la demanda prevista y es solo orientativa.",
    "El estado crítico (menos de 2 semanas de cobertura) es el mismo sin importar el horizonte pedido.",
]


@dataclass
class ItemReposicion:
    categoria_id: int
    categoria: str
    disponible: int
    demanda_semanal_promedio: float
    semanas_cobertura: float | None  # None = sin demanda prevista (cobertura infinita)
    agotado_en_semana: int | None  # 1..h, o None si no se agota en el horizonte previsto
    estado: str  # "critico" | "atencion" | "ok"
    sugerencia_unidades: int


def _validar_semanas(semanas: Any) -> None:
    if isinstance(semanas, bool) or not isinstance(semanas, int) or not MIN_SEMANAS <= semanas <= MAX_SEMANAS:
        raise ValueError(f"Las semanas a cubrir van de {MIN_SEMANAS} a {MAX_SEMANAS}")


def _unidades(valor: Any, que: str) -> float:
    """Número finito y no negativo; lanza ValueError con un mensaje claro si no lo es."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor < 0:
        raise ValueError(f"{que} debe ser un número finito mayor o igual a 0 (llegó {valor!r})")
    return float(valor)


def _agotado_en(demanda: list[float], disponible: float) -> int | None:
    """Primera semana (1..h) cuya demanda acumulada alcanza o supera lo disponible. Sin existencias y con alguna demanda
    prevista, ya está agotado en la semana 1; sin demanda prevista no hay semana en que se agote (None)."""
    if sum(demanda) <= 0:
        return None
    if disponible <= 0:
        return 1
    acumulada = 0.0
    for semana, unidades in enumerate(demanda, start=1):
        acumulada += unidades
        if acumulada >= disponible:
            return semana
    return None


def calcular_reposicion(
    demanda_por_categoria: list[dict], disponible: dict[int, int], semanas: int
) -> list[ItemReposicion]:
    """Un `ItemReposicion` por categoría, con los críticos primero, luego los de atención y al final los "ok"; dentro de
    cada estado, por cobertura ascendente (las categorías sin demanda, con cobertura infinita, al final) y luego por id.
    `ValueError` si `semanas` no está entre 1 y 12 o si hay unidades negativas o no numéricas."""
    _validar_semanas(semanas)
    items: list[ItemReposicion] = []
    for fila in demanda_por_categoria:
        try:
            categoria_id, nombre = fila["categoria_id"], fila["categoria"]
            demanda = [_unidades(u, "La demanda semanal") for u in fila["unidades_semanales"]]
        except (KeyError, TypeError) as exc:
            raise ValueError("Cada categoría necesita categoria_id, categoria y unidades_semanales") from exc
        stock = disponible.get(categoria_id, 0)
        if isinstance(stock, bool) or not isinstance(stock, int) or stock < 0:
            raise ValueError(f"El disponible debe ser un entero mayor o igual a 0 (llegó {stock!r})")
        horizonte = len(demanda)
        total = sum(demanda)
        promedio = total / horizonte if horizonte else 0.0
        cobertura = stock / promedio if promedio > 0 else None
        if cobertura is not None and cobertura < UMBRAL_CRITICO_SEMANAS:
            estado = ESTADO_CRITICO
        elif cobertura is not None and cobertura < semanas:
            estado = ESTADO_ATENCION
        else:
            estado = ESTADO_OK
        items.append(
            ItemReposicion(
                categoria_id=categoria_id,
                categoria=nombre,
                disponible=stock,
                demanda_semanal_promedio=round(promedio, 2),
                semanas_cobertura=None if cobertura is None else round(cobertura, 2),
                agotado_en_semana=_agotado_en(demanda, stock),
                estado=estado,
                sugerencia_unidades=max(0, math.ceil(round(total * (1.0 + COLCHON) - stock, 9))),
            )
        )
    items.sort(
        key=lambda i: (
            _ORDEN_ESTADO[i.estado],
            math.inf if i.semanas_cobertura is None else i.semanas_cobertura,
            i.categoria_id,
        )
    )
    return items
