"""core/texto.py: la normalización de nombres que comparten plataforma, catalogo y los reportes."""

import pytest

from app.core.texto import normalizar_texto, quitar_tildes
from app.plataforma.politicas import normalizar_nombre_empresa


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Sucursal Centro", "sucursal centro"),
        ("  Sucursal   CENTRÓ ", "sucursal centro"),
        ("Polera Básica", "polera basica"),
        ("ÑANDÚ\tNorte\n", "nandu norte"),
        ("Camisería", "camiseria"),
        ("", ""),
        ("   ", ""),
        (None, ""),
        ("100% algodón", "100% algodon"),  # no escapa nada: son comodines solo en SQL
    ],
)
def test_normalizar_texto(entrada, esperado):
    assert normalizar_texto(entrada) == esperado


def test_quitar_tildes_conserva_mayusculas_y_signos():
    assert quitar_tildes("Árbol Ñoño, ¿qué?") == "Arbol Nono, ¿que?"


def test_normalizar_nombre_empresa_sigue_igual_tras_compartir_quitar_tildes():
    assert normalizar_nombre_empresa("Boutique Andina") == "boutique-andina"
    assert normalizar_nombre_empresa("  Camisería Ñandú S.R.L. ") == "camiseria-nandu-s-r-l"
    assert normalizar_nombre_empresa("¡¡¡") == ""
