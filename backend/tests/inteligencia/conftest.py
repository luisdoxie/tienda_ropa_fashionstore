"""Fixtures de tests/inteligencia: ninguna prueba de este paquete toca la red."""

import httpx
import pytest


class LlamadaRedGroqBloqueada(AssertionError):
    """Una prueba intentó llamar a Groq de verdad. Reemplaza el intérprete o el
    cliente HTTP por uno falso (monkeypatch) en vez de salir a la red."""


def _es_groq(url) -> bool:
    return "groq.com" in str(url).lower()


def _mensaje(url) -> str:
    return (
        f"Llamada de red a Groq bloqueada en las pruebas ({url}). "
        "Usa un intérprete/cliente falso."
    )


@pytest.fixture(autouse=True)
def sin_red_groq(monkeypatch):
    """Hace fallar con una excepción explícita cualquier httpx.post, httpx.Client.post o
    httpx.AsyncClient.post hacia groq.com. Lo demás pasa al original. Un cliente armado
    con httpx.MockTransport se deja pasar (no sale a la red). Si una prueba reemplaza
    httpx.post con su propio falso, el suyo se aplica después y manda."""
    post_original = httpx.post
    client_post_original = httpx.Client.post
    async_post_original = httpx.AsyncClient.post

    def post(url, *args, **kwargs):
        if _es_groq(url):
            raise LlamadaRedGroqBloqueada(_mensaje(url))
        return post_original(url, *args, **kwargs)

    def client_post(self, url, *args, **kwargs):
        if _es_groq(url) or _es_groq(getattr(self, "base_url", "")):
            if not isinstance(getattr(self, "_transport", None), httpx.MockTransport):
                raise LlamadaRedGroqBloqueada(_mensaje(url))
        return client_post_original(self, url, *args, **kwargs)

    async def async_post(self, url, *args, **kwargs):
        if _es_groq(url) or _es_groq(getattr(self, "base_url", "")):
            if not isinstance(getattr(self, "_transport", None), httpx.MockTransport):
                raise LlamadaRedGroqBloqueada(_mensaje(url))
        return await async_post_original(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx.Client, "post", client_post)
    monkeypatch.setattr(httpx.AsyncClient, "post", async_post)


# Fixtures de los reportes generativos (E09): se registran aquí para que las vea todo el paquete.
from tests.inteligencia.ayudas_reportes_generativos import (  # noqa: E402,F401
    _limpiar_limite,
    _sin_clave_groq,
    dos_profesionales,
    hoy_fijo,
    interprete_falso,
    mundo_ia,
)
