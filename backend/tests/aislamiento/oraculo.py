"""E05, 4.3: el oráculo de cada intento cruzado.

Para toda petición de A hacia un recurso de B:
  O1 estado: 404 (nunca 200, 403 ni 500).
  O2 indistinguible: la MISMA petición con un id inexistente da el mismo estado y el mismo
     cuerpo (se normaliza el id que aparezca en el mensaje).
  O3 sin fuga: ninguna cadena "MARCA-B-" en el cuerpo ni en las cabeceras.
  O4 sin efecto: la instantánea de B (filas y huella de cada tabla suya) no cambia.
  O5 (otra función) la misma petición con los ids de A SÍ funciona: evita pruebas verdes
     por una ruta mal armada (el "404 de siempre").
"""

import re

from .plantillas import (
    ARCHIVOS,
    CUERPOS,
    ESPEJO_ACEPTADO,
    NUEVO_PARA_ESPEJO,
    PARAMETROS,
    VALORES_ESPEJO,
    token_de_ruta,
)

ID_INEXISTENTE = 999_999_999


def parametros_de(ruta: str) -> list[str]:
    return re.findall(r"\{(\w+)\}", ruta)


def parametros_de_recurso(ruta: str) -> list[str]:
    """Los parámetros de la ruta que son ids de un recurso de empresa."""
    return [p for p in parametros_de(ruta) if p in PARAMETROS]


def armar(ruta: str, valores: dict) -> str:
    for nombre, valor in valores.items():
        ruta = ruta.replace("{" + nombre + "}", str(valor))
    return ruta


def combinaciones(ruta: str) -> list[tuple[str, ...]]:
    """Qué parámetros llevan el id de B. Un parámetro: solo el de B. Dos: las tres mezclas
    (A+B, B+A, B+B). Devuelve tuplas con los nombres de los parámetros que van con B."""
    parametros = parametros_de_recurso(ruta)
    if len(parametros) == 1:
        return [tuple(parametros)]
    primero, segundo = parametros[0], parametros[1]
    return [(segundo,), (primero,), (primero, segundo)]


def normalizar(texto: str, ids: list[int]) -> str:
    for valor in sorted({str(i) for i in ids}, key=len, reverse=True):
        texto = re.sub(rf"(?<!\d){valor}(?!\d)", "<id>", texto)
    return texto


def _pedir(mundo, metodo: str, ruta_plantilla: str, valores: dict, quien, cuerpo_de):
    """Manda la petición con el token de `quien` y un cuerpo válido para `quien`."""
    cuerpo = None
    if (metodo, ruta_plantilla) in CUERPOS:
        cuerpo = CUERPOS[(metodo, ruta_plantilla)](cuerpo_de)
    token = quien.headers[token_de_ruta(metodo, ruta_plantilla)]
    argumentos = {"headers": token}
    if (metodo, ruta_plantilla) in ARCHIVOS:
        argumentos["files"] = ARCHIVOS[(metodo, ruta_plantilla)]
    elif cuerpo is not None:
        argumentos["json"] = cuerpo
    return mundo.client.request(metodo, armar(ruta_plantilla, valores), **argumentos)


def intento_cruzado(mundo, metodo: str, ruta_plantilla: str, con_b: tuple[str, ...]):
    """Ejecuta O1..O4. Devuelve la respuesta para que la prueba pueda mostrarla."""
    a, b = mundo.a, mundo.b
    valores = {p: (b.ids if p in con_b else a.ids)[PARAMETROS[p]] for p in parametros_de_recurso(ruta_plantilla)}
    inexistentes = {p: (ID_INEXISTENTE if p in con_b else valor) for p, valor in valores.items()}

    antes = mundo.instantanea(b.id)
    respuesta = _pedir(mundo, metodo, ruta_plantilla, valores, a, a)
    despues = mundo.instantanea(b.id)
    control = _pedir(mundo, metodo, ruta_plantilla, inexistentes, a, a)

    detalle = f"{metodo} {armar(ruta_plantilla, valores)} -> {respuesta.status_code} {respuesta.text[:300]}"
    assert respuesta.status_code == 404, f"O1 (404 esperado): {detalle}"
    assert control.status_code == respuesta.status_code, (
        f"O2 (estado distinto con un id inexistente): {detalle} / inexistente -> {control.status_code}"
    )
    ids_usados = [ID_INEXISTENTE, *valores.values()]
    assert normalizar(control.text, ids_usados) == normalizar(respuesta.text, ids_usados), (
        f"O2 (cuerpo distinto con un id inexistente): {respuesta.text[:200]} / {control.text[:200]}"
    )
    assert b.m("") not in respuesta.text, f"O3 (marca de B en el cuerpo): {detalle}"
    assert b.m("") not in str(dict(respuesta.headers)), f"O3 (marca de B en las cabeceras): {detalle}"
    assert mundo.cambios(antes, despues) == [], f"O4 (B cambió): {mundo.cambios(antes, despues)} con {detalle}"
    return respuesta


def valores_propios(a, metodo: str, ruta_plantilla: str) -> dict:
    """Ids de A para el espejo: persistentes en lecturas; instancias desechables si la ruta
    escribe y el recurso se puede crear de nuevo."""
    if (metodo, ruta_plantilla) in VALORES_ESPEJO:
        return VALORES_ESPEJO[(metodo, ruta_plantilla)](a)
    valores = {}
    parametros = parametros_de_recurso(ruta_plantilla)
    for indice, p in enumerate(parametros):
        recurso = PARAMETROS[p]
        es_el_ultimo = indice == len(parametros) - 1
        if metodo != "GET" and es_el_ultimo and recurso in NUEVO_PARA_ESPEJO:
            valores[p] = a.nuevo(NUEVO_PARA_ESPEJO[recurso])
        else:
            valores[p] = a.ids[recurso]
    return valores


def espejo(mundo, metodo: str, ruta_plantilla: str):
    """O5: la misma petición con los ids de A funciona (o aplica una regla de negocio)."""
    a = mundo.a
    valores = valores_propios(a, metodo, ruta_plantilla)
    respuesta = _pedir(mundo, metodo, ruta_plantilla, valores, a, a)
    detalle = f"{metodo} {armar(ruta_plantilla, valores)} -> {respuesta.status_code} {respuesta.text[:300]}"
    assert respuesta.status_code in ESPEJO_ACEPTADO, f"O5 (la ruta no funciona ni con ids propios): {detalle}"
    return respuesta
