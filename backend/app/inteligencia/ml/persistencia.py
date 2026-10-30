"""Serialización de los modelos entrenados (E11, paso 10): a memoria, nunca a disco, con huella SHA-256 y la
versión de scikit-learn guardada junto al modelo.

Seguridad: `joblib` carga un pickle. Aquí SOLO se carga lo que escribió este mismo backend en su propia base
(columna `modelo_ml.artefacto`), nunca entrada del usuario ni archivos subidos, y la huella se verifica ANTES de
cargar. Quien pudiera reemplazar el artefacto en la base ya tendría control total de ella.

Compatibilidad: un artefacto depende de la versión de scikit-learn con la que se entrenó. Si cambia, el modelo
se considera OBSOLETO (`ArtefactoObsoleto`) y hay que reentrenarlo: no se intenta cargar.
"""

from __future__ import annotations

import hashlib
import io
from collections import OrderedDict
from typing import Any

from app.inteligencia.ml.limites import ML_MAX_ARTEFACTO_BYTES, ML_MAX_MODELOS_EN_CACHE


class ArtefactoCorrupto(Exception):
    """La huella no coincide, o los bytes no son un artefacto válido."""


class ArtefactoObsoleto(ArtefactoCorrupto):
    """El artefacto se entrenó con otra versión de scikit-learn: hay que reentrenar."""


class ArtefactoDemasiadoGrande(ValueError):
    """El modelo serializado pesa más que `ML_MAX_ARTEFACTO_BYTES`."""


def huella(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def _versiones() -> dict[str, str]:
    import numpy
    import sklearn

    return {"sklearn": sklearn.__version__, "numpy": numpy.__version__}


def serializar(objeto: Any) -> tuple[bytes, str, int]:
    """El objeto (un modelo, un escalador, un diccionario con lo que haga falta...) como bytes comprimidos,
    su SHA-256 y su tamaño. Todo en memoria."""
    import joblib

    buffer = io.BytesIO()
    joblib.dump({"versiones": _versiones(), "objeto": objeto}, buffer, compress=3)
    datos = buffer.getvalue()
    if len(datos) > ML_MAX_ARTEFACTO_BYTES:
        raise ArtefactoDemasiadoGrande(
            f"El modelo serializado pesa {len(datos)} bytes y el máximo es {ML_MAX_ARTEFACTO_BYTES}"
        )
    return datos, huella(datos), len(datos)


def deserializar(datos: bytes | None, sha256_esperado: str | None) -> Any:
    """Verifica la huella ANTES de cargar y la versión de scikit-learn después. `ArtefactoCorrupto` si no
    coincide; `ArtefactoObsoleto` si se entrenó con otra versión de scikit-learn."""
    import joblib

    if not datos:
        raise ArtefactoCorrupto("El modelo no tiene artefacto (una versión podada o un entrenamiento incompleto)")
    if sha256_esperado is None or huella(datos) != sha256_esperado:
        raise ArtefactoCorrupto("La huella del artefacto no coincide: el modelo fue alterado o está dañado")
    try:
        paquete = joblib.load(io.BytesIO(datos))
        guardadas, objeto = paquete["versiones"], paquete["objeto"]
    except Exception as exc:  # noqa: BLE001 -- cualquier fallo al leer es un artefacto inválido
        raise ArtefactoCorrupto("El artefacto no se pudo leer") from exc
    if guardadas.get("sklearn") != _versiones()["sklearn"]:
        raise ArtefactoObsoleto(
            f"El modelo se entrenó con scikit-learn {guardadas.get('sklearn')} y ahora hay {_versiones()['sklearn']}: reentrenar"
        )
    return objeto


class CacheModelos:
    """Modelos ya deserializados que el proceso conserva (clave: (empresa_id, tipo, versión)), para no
    deserializar en cada consulta. Máximo `ML_MAX_MODELOS_EN_CACHE`; sale el menos usado. Se invalida al guardar
    una versión nueva. Hay un solo worker (scripts/start.sh), así que no hay coherencia entre procesos que resolver.
    Es memoria de este proceso: nunca mezcla empresas porque la empresa es parte de la clave."""

    def __init__(self, maximo: int = ML_MAX_MODELOS_EN_CACHE) -> None:
        self._maximo = maximo
        self._modelos: OrderedDict[tuple[int, str, int], Any] = OrderedDict()

    def __len__(self) -> int:
        return len(self._modelos)

    def obtener(self, empresa_id: int, tipo: str, version: int) -> Any | None:
        clave = (empresa_id, tipo, version)
        if clave not in self._modelos:
            return None
        self._modelos.move_to_end(clave)
        return self._modelos[clave]

    def poner(self, empresa_id: int, tipo: str, version: int, modelo: Any) -> None:
        self._modelos[(empresa_id, tipo, version)] = modelo
        self._modelos.move_to_end((empresa_id, tipo, version))
        while len(self._modelos) > self._maximo:
            self._modelos.popitem(last=False)

    def invalidar(self, empresa_id: int, tipo: str | None = None) -> None:
        """Olvida los modelos de la empresa (o solo de un tipo)."""
        for clave in [c for c in self._modelos if c[0] == empresa_id and (tipo is None or c[1] == tipo)]:
            del self._modelos[clave]
