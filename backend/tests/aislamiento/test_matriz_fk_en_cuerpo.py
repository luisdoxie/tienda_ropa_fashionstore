"""E05, 4.4: cada campo *_id de entrada con un id de B debe dar 404 y no dejar nada.

Para cada caso: (1) el cuerpo válido de A, con UN campo cambiado por un id de B, responde 404
igual que con un id inexistente; (2) ni A ni B cambian (ninguna fila creada o modificada);
(3) con el id propio, la misma petición funciona (evita pruebas verdes por una ruta mal armada).
"""

import copy

import pytest

from .casos_fk import CASOS_FK, PNG, _ruta
from .oraculo import ID_INEXISTENTE
from .plantillas import ESPEJO_ACEPTADO


def _con_valor(cuerpo: dict, campo: tuple, valor) -> dict:
    cuerpo = copy.deepcopy(cuerpo)
    destino = cuerpo
    for paso in campo[:-1]:
        destino = destino[paso]
    ultimo = campo[-1]
    destino[ultimo] = [valor] if isinstance(destino[ultimo], list) else valor
    return cuerpo


def _pedir(mundo, caso, a, ruta, cuerpo):
    argumentos = {"headers": a.headers[caso.token]}
    if caso.multipart:
        argumentos["data"] = {k: str(v) for k, v in cuerpo.items()}
        argumentos["files"] = {"archivo": ("prenda.png", PNG, "image/png")}
    else:
        argumentos["json"] = cuerpo
    return mundo.client.request(caso.metodo, ruta, **argumentos)


@pytest.mark.parametrize("caso", CASOS_FK, ids=[c.nombre for c in CASOS_FK])
def test_id_de_b_en_el_cuerpo_da_404_y_no_deja_filas(mundo, caso):
    a, b = mundo.a, mundo.b
    ruta = _ruta(caso, a)
    base = caso.cuerpo(a)
    ajeno = _con_valor(base, caso.campo, b.ids[caso.ajeno])
    inexistente = _con_valor(base, caso.campo, ID_INEXISTENTE)

    antes_a, antes_b = mundo.instantanea(a.id), mundo.instantanea(b.id)
    respuesta = _pedir(mundo, caso, a, ruta, ajeno)
    despues_a, despues_b = mundo.instantanea(a.id), mundo.instantanea(b.id)
    control = _pedir(mundo, caso, a, ruta, inexistente)

    detalle = f"{caso.metodo} {ruta} -> {respuesta.status_code} {respuesta.text[:300]}"
    assert respuesta.status_code == 404, f"se esperaba 404: {detalle}"
    assert control.status_code == 404, f"con un id inexistente se esperaba 404: {control.status_code} {control.text[:200]}"
    assert control.text.replace(str(ID_INEXISTENTE), "<id>") == respuesta.text.replace(str(b.ids[caso.ajeno]), "<id>"), (
        f"la respuesta distingue un id de otra empresa de uno inexistente: {respuesta.text[:200]} / {control.text[:200]}"
    )
    assert b.m("") not in respuesta.text
    assert mundo.cambios(antes_a, despues_a) == [], f"A cambió con un 404: {mundo.cambios(antes_a, despues_a)}"
    assert mundo.cambios(antes_b, despues_b) == [], f"B cambió: {mundo.cambios(antes_b, despues_b)}"

    if not caso.espejo:
        pytest.skip("la petición positiva llamaría a un servicio externo; el 404 cruzado sí se comprobó")
    propio = _pedir(mundo, caso, a, ruta, caso.cuerpo(a))
    assert propio.status_code in ESPEJO_ACEPTADO, (
        f"con ids propios la petición no funciona (prueba mal armada): {caso.metodo} {ruta} -> {propio.status_code} {propio.text[:300]}"
    )
