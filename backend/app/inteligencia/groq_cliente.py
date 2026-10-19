"""Cliente del parser de voz vía Groq.

Todo lo que sabe llamar al proveedor externo que interpreta la frase
transcrita vive detrás de `ParserVozBase`. El resto del paquete
(`cu21_buscar_prendas_por_voz.py`) solo conoce esta interfaz, nunca al proveedor concreto --
mismo patrón que `catalogo/generativo.py` usa para Vertex AI.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from abc import ABC, abstractmethod

import httpx
from pydantic import ValidationError

from app.catalogo.schemas import ValoresReferenciaCatalogo
from app.core.config import get_settings
from app.core.tiempo import hoy_utc
from app.inteligencia.schemas import (
    CandidatoRecomendacion,
    FiltrosReporteVoz,
    FiltrosVoz,
    PerfilClienteRecomendacion,
    RecomendacionGroq,
)

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT_SEG = 10


def _armar_prompt(valores: ValoresReferenciaCatalogo) -> str:
    return (
        "Sos el intérprete de búsqueda por voz de una tienda de ropa. A partir "
        "de la frase del usuario, devolvé ÚNICAMENTE un JSON con esta forma "
        "exacta, sin texto adicional ni markdown:\n"
        '{"categoria": null, "temporada": null, "material": null, "color": null, '
        '"talla": null, "genero": null, "precio_max": null, "sucursal": null}\n\n'
        "Reglas:\n"
        "- Cada valor debe ser uno de los valores válidos listados abajo, o null "
        "si la frase no lo menciona o ninguno corresponde. Mapeá sinónimos al "
        'valor real más parecido (ej. "hilo" -> el material más parecido de la '
        "lista).\n"
        f"- categoria: uno de {valores.categorias}\n"
        f"- material: uno de {valores.materiales}\n"
        f"- color: uno de {valores.colores}\n"
        f"- talla: uno de {valores.tallas}\n"
        f"- temporada: uno de {valores.temporadas}\n"
        '- genero: uno de ["hombre", "mujer", "unisex", "nino"]\n'
        "- precio_max: un número (el precio máximo que menciona la frase, sin "
        "moneda), o null\n"
        "- sucursal: el nombre de una sucursal si la frase la menciona "
        "explícitamente, o null"
    )


class ParserVozBase(ABC):
    nombre: str

    @abstractmethod
    def parsear(self, texto: str, valores: ValoresReferenciaCatalogo) -> FiltrosVoz | None:
        """Devuelve los filtros interpretados, o `None` si el proveedor
        falló o su respuesta no se pudo validar -- nunca lanza excepción,
        el llamador decide el fallback a búsqueda de texto plano."""
        raise NotImplementedError


class GroqParserVoz(ParserVozBase):
    nombre = "groq"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.groq_api_key
        self._modelo = settings.groq_modelo

    def parsear(self, texto: str, valores: ValoresReferenciaCatalogo) -> FiltrosVoz | None:
        if not self._api_key:
            logger.warning("GROQ_API_KEY no configurado, se usa fallback de texto plano")
            return None
        try:
            respuesta = httpx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._modelo,
                    "messages": [
                        {"role": "system", "content": _armar_prompt(valores)},
                        {"role": "user", "content": texto},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
                timeout=TIMEOUT_SEG,
            )
            respuesta.raise_for_status()
            contenido = respuesta.json()["choices"][0]["message"]["content"]
            return FiltrosVoz.model_validate(json.loads(contenido))
        except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError):
            # Cualquier falla del proveedor externo (red, formato de la
            # respuesta, JSON inválido, o JSON válido que no matchea
            # FiltrosVoz) cae al fallback -- nunca se propaga al request.
            logger.exception("Groq falló al interpretar la búsqueda por voz, se usa fallback de texto plano")
            return None


def obtener_parser_voz() -> ParserVozBase:
    return GroqParserVoz()


# ---- Recomendador -------------------------------------------------------


def _armar_prompt_recomendacion(candidatos: list[CandidatoRecomendacion], perfil: PerfilClienteRecomendacion) -> str:
    lista_candidatos = "\n".join(
        f"- variante_id={c.variante_id}, nombre=\"{c.nombre}\", categoria_id={c.categoria_id}, "
        f"precio_base={c.precio_base}"
        for c in candidatos
    )
    contexto = (
        "El cliente tiene historial de navegación real (vistas, favoritos, uso del "
        "probador, búsquedas) detrás de esta lista -- priorizá lo más afín a esos "
        "patrones."
        if perfil.hay_historial
        else "El cliente es nuevo o navega como invitado, sin historial -- esta "
        "lista ya viene ordenada por popularidad de la temporada vigente."
    )
    return (
        "Sos el motor de recomendaciones de una tienda de ropa. Te paso hasta 20 "
        "prendas candidatas, ya filtradas por stock disponible y temporada vigente. "
        "Elegí las 6 mejores para mostrar en un carrusel y devolvé ÚNICAMENTE un "
        'JSON con esta forma exacta, sin texto adicional ni markdown:\n'
        '{"recomendaciones": [{"variante_id": 0, "motivo": ""}, ...]}\n\n'
        f"{contexto}\n\n"
        "Reglas:\n"
        "- Como máximo 6 elementos, ordenados del más al menos recomendado.\n"
        "- `variante_id` tiene que ser exactamente uno de los que aparecen abajo, "
        "sin inventar ni repetir.\n"
        "- `motivo` es una frase corta en español (máximo 15 palabras), en lenguaje "
        'natural dirigida al cliente (ej. "Combina con lo que viste últimamente"), '
        "nunca un dato técnico como un id o un puntaje.\n\n"
        f"Candidatos:\n{lista_candidatos}"
    )


class RankeadorRecomendacionBase(ABC):
    nombre: str

    @abstractmethod
    def rankear(
        self, candidatos: list[CandidatoRecomendacion], perfil: PerfilClienteRecomendacion
    ) -> list[RecomendacionGroq] | None:
        """Devuelve hasta 6 recomendaciones ordenadas, o `None` si el
        proveedor falló o su respuesta no se pudo validar -- nunca lanza
        excepción, el llamador decide el fallback a un ranking genérico."""
        raise NotImplementedError


class GroqRankeadorRecomendacion(RankeadorRecomendacionBase):
    nombre = "groq"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.groq_api_key
        self._modelo = settings.groq_modelo

    def rankear(
        self, candidatos: list[CandidatoRecomendacion], perfil: PerfilClienteRecomendacion
    ) -> list[RecomendacionGroq] | None:
        if not self._api_key or not candidatos:
            return None
        try:
            respuesta = httpx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._modelo,
                    "messages": [
                        {"role": "system", "content": _armar_prompt_recomendacion(candidatos, perfil)},
                        {"role": "user", "content": "Recomendame."},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.3,
                },
                timeout=TIMEOUT_SEG,
            )
            respuesta.raise_for_status()
            contenido = respuesta.json()["choices"][0]["message"]["content"]
            cuerpo = json.loads(contenido)
            filas = [RecomendacionGroq.model_validate(fila) for fila in cuerpo["recomendaciones"]]
            return filas or None
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError):
            # Cualquier falla del proveedor externo (red, formato de la
            # respuesta, JSON inválido, o JSON válido que no matchea el
            # contrato) cae al fallback -- nunca se propaga al request.
            logger.exception("Groq falló al rankear recomendaciones, se usa fallback de ranking genérico")
            return None


def obtener_rankeador_recomendacion() -> RankeadorRecomendacionBase:
    return GroqRankeadorRecomendacion()


# ---- Reporte por voz -----------------------------------------------------


def _armar_prompt_reporte_voz(hoy: dt.date) -> str:
    return (
        "Sos el intérprete de reportes por voz del back office de una tienda "
        f"de ropa. Hoy es {hoy.isoformat()}. A partir de la frase de un "
        "empleado, devolvé ÚNICAMENTE un "
        "JSON con esta forma exacta, sin texto adicional ni markdown:\n"
        '{"tipo_reporte": "dashboard", "desde": null, "hasta": null, '
        '"sucursal": null, "categoria": null, "canal": null}\n\n'
        "Reglas:\n"
        '- tipo_reporte: uno de "ventas", "inventario", "reservas" o '
        '"dashboard" -- el que mejor matchee la frase. Si no queda claro, '
        '"dashboard".\n'
        "- desde/hasta: fechas en formato ISO (AAAA-MM-DD) si la frase "
        'menciona un período (ej. "el último mes", "esta semana"), calculado '
        "a partir de la fecha de hoy y nunca posterior a ella, o null si no.\n"
        "- sucursal/categoria: el nombre tal como lo dice la frase, o null.\n"
        '- canal: "digital", "presencial", o null.\n\n'
        "Nunca generes SQL ni ningún otro código: solo este JSON."
    )


class ParserReporteVozBase(ABC):
    nombre: str

    @abstractmethod
    def parsear(self, texto: str) -> FiltrosReporteVoz | None:
        """Devuelve los filtros interpretados, o `None` si el proveedor
        falló o su respuesta no se pudo validar -- nunca lanza excepción,
        el llamador decide el fallback (dashboard, período por defecto)."""
        raise NotImplementedError


class GroqParserReporteVoz(ParserReporteVozBase):
    nombre = "groq"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.groq_api_key
        self._modelo = settings.groq_modelo

    def parsear(self, texto: str) -> FiltrosReporteVoz | None:
        if not self._api_key:
            logger.warning("GROQ_API_KEY no configurado, se usa el dashboard por defecto")
            return None
        try:
            respuesta = httpx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._modelo,
                    "messages": [
                        {"role": "system", "content": _armar_prompt_reporte_voz(hoy_utc())},
                        {"role": "user", "content": texto},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
                timeout=TIMEOUT_SEG,
            )
            respuesta.raise_for_status()
            contenido = respuesta.json()["choices"][0]["message"]["content"]
            return FiltrosReporteVoz.model_validate(json.loads(contenido))
        except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError):
            logger.exception("Groq falló al interpretar el reporte por voz, se usa el dashboard por defecto")
            return None


def obtener_parser_reporte_voz() -> ParserReporteVozBase:
    return GroqParserReporteVoz()
