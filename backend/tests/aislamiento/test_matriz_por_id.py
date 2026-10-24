"""E05, 4.4: matriz por id. Para cada ruta con un id de recurso en el path, A usa el id de B
(y las mezclas A+B, B+A, B+B si hay dos ids) y se aplica el oráculo (4.3)."""

import pytest

from .oraculo import combinaciones, espejo, intento_cruzado, parametros_de_recurso
from .plantillas import SIN_ESPEJO
from .rutas_esperadas import MATRIZ, POR_ID, RUTAS

RUTAS_POR_ID = sorted(
    clave for clave, ruta in RUTAS.items() if ruta.clase == POR_ID and ruta.cobertura == MATRIZ and parametros_de_recurso(clave[1])
)
CASOS = [(m, r, c) for (m, r) in RUTAS_POR_ID for c in combinaciones(r)]


def _id(caso):
    metodo, ruta, con_b = caso
    return f"{metodo} {ruta.removeprefix('/api/v1')} [B:{','.join(con_b)}]"


@pytest.mark.parametrize("caso", CASOS, ids=[_id(c) for c in CASOS])
def test_a_no_alcanza_el_recurso_de_b(mundo, caso):
    metodo, ruta, con_b = caso
    intento_cruzado(mundo, metodo, ruta, con_b)


@pytest.mark.parametrize("clave", RUTAS_POR_ID, ids=[f"{m} {r.removeprefix('/api/v1')}" for m, r in RUTAS_POR_ID])
def test_espejo_con_el_id_propio_si_funciona(mundo, clave):
    metodo, ruta = clave
    if clave in SIN_ESPEJO:
        pytest.skip(SIN_ESPEJO[clave])
    espejo(mundo, metodo, ruta)
