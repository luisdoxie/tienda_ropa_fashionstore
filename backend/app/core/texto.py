"""Normalización de texto para comparar nombres: una sola fuente en el backend."""

import unicodedata


def quitar_tildes(texto: str) -> str:
    """El texto sin marcas diacríticas (NFKD): 'Camisería' -> 'Camiseria', 'Ñandú' -> 'Nandu'."""
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def normalizar_texto(texto: str | None) -> str:
    """Para comparar nombres sin distinguir mayúsculas, tildes ni espacios de más:
    minúsculas, sin tildes y con toda secuencia de espacios colapsada en uno solo y
    sin espacios en los extremos. '  Sucursal   CENTRÓ ' -> 'sucursal centro'. Vacío
    si no hay texto. NO escapa nada: se usa en Python, nunca dentro de un patrón SQL."""
    if not texto:
        return ""
    return " ".join(quitar_tildes(texto).lower().split())
