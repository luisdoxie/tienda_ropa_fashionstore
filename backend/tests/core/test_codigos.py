"""core/codigos.py: generar_codigo (antes duplicado en comercial/politicas.py y
en cu12). El formato de los códigos no debe cambiar: PREFIJO-8 hex mayúsculas."""

import re

import pytest

from app.core.codigos import generar_codigo
from app.core.exceptions import DomainError


def test_el_codigo_lleva_el_prefijo_y_ocho_hexadecimales_en_mayuscula():
    codigo = generar_codigo(None, "RES", lambda db, c: None)

    assert re.fullmatch(r"RES-[0-9A-F]{8}", codigo)


def test_cada_prefijo_se_respeta():
    for prefijo in ("RES", "VTA", "DEV"):
        assert generar_codigo(None, prefijo, lambda db, c: None).startswith(f"{prefijo}-")


def test_reintenta_si_el_codigo_ya_existe():
    intentos: list[str] = []

    def existe(db, codigo):
        intentos.append(codigo)
        return object() if len(intentos) < 3 else None

    codigo = generar_codigo(None, "VTA", existe)

    assert len(intentos) == 3
    assert codigo == intentos[-1]


def test_tras_cinco_colisiones_lanza_domain_error():
    llamadas = []

    def siempre_existe(db, codigo):
        llamadas.append(codigo)
        return object()

    with pytest.raises(DomainError, match="No se pudo generar un código único"):
        generar_codigo(None, "DEV", siempre_existe)

    assert len(llamadas) == 5


def test_los_codigos_generados_son_distintos():
    assert len({generar_codigo(None, "RES", lambda db, c: None) for _ in range(50)}) == 50
