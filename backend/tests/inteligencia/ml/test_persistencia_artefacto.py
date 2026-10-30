"""Serialización de modelos (`ml/persistencia.py`, E11 paso 10): ida y vuelta, huella, versión de
scikit-learn, tope de tamaño y el caché por (empresa, tipo, versión). Sin base de datos."""

import hashlib
import os
import tempfile

import pytest

from app.inteligencia.ml import persistencia
from app.inteligencia.ml.limites import ML_MAX_ARTEFACTO_BYTES, ML_MAX_MODELOS_EN_CACHE
from app.inteligencia.ml.persistencia import (
    ArtefactoCorrupto,
    ArtefactoDemasiadoGrande,
    ArtefactoObsoleto,
    CacheModelos,
    deserializar,
    serializar,
)


def _modelo():
    import numpy as np
    from sklearn.linear_model import Ridge

    x = np.arange(40, dtype=float).reshape(20, 2)
    y = x[:, 0] * 2 + x[:, 1]
    return Ridge(alpha=1.0).fit(x, y), x


def test_un_modelo_serializado_y_cargado_predice_igual():
    import numpy as np

    modelo, x = _modelo()
    datos, sha, tamano = serializar({"modelo": modelo, "columnas": ["a", "b"]})
    assert isinstance(datos, bytes) and tamano == len(datos) and sha == hashlib.sha256(datos).hexdigest()
    cargado = deserializar(datos, sha)
    assert cargado["columnas"] == ["a", "b"]
    assert np.array_equal(cargado["modelo"].predict(x), modelo.predict(x))


def test_serializar_dos_veces_el_mismo_modelo_da_la_misma_huella():
    modelo, _ = _modelo()
    assert serializar(modelo)[1] == serializar(modelo)[1]


def test_un_byte_alterado_o_una_huella_distinta_es_un_artefacto_corrupto():
    modelo, _ = _modelo()
    datos, sha, _ = serializar(modelo)
    alterado = bytearray(datos)
    alterado[len(alterado) // 2] ^= 0xFF
    with pytest.raises(ArtefactoCorrupto, match="huella"):
        deserializar(bytes(alterado), sha)
    with pytest.raises(ArtefactoCorrupto, match="huella"):
        deserializar(datos, "0" * 64)
    with pytest.raises(ArtefactoCorrupto):
        deserializar(datos, None)


def test_bytes_que_no_son_un_artefacto_se_rechazan_sin_cargar_nada():
    basura = b"esto no es joblib"
    with pytest.raises(ArtefactoCorrupto, match="no se pudo leer"):
        deserializar(basura, hashlib.sha256(basura).hexdigest())  # la huella coincide, el contenido no sirve
    with pytest.raises(ArtefactoCorrupto):
        deserializar(None, "x")
    with pytest.raises(ArtefactoCorrupto):
        deserializar(b"", "x")


def test_otra_version_de_scikit_learn_hace_obsoleto_el_modelo(monkeypatch):
    modelo, _ = _modelo()
    datos, sha, _ = serializar(modelo)
    monkeypatch.setattr(persistencia, "_versiones", lambda: {"sklearn": "0.0.1", "numpy": "0"})
    with pytest.raises(ArtefactoObsoleto, match="reentrenar"):
        deserializar(datos, sha)
    assert issubclass(ArtefactoObsoleto, ArtefactoCorrupto)  # quien atrapa "corrupto" también atrapa "obsoleto"


def test_el_artefacto_no_puede_pasar_de_8_mb():
    import numpy as np

    assert ML_MAX_ARTEFACTO_BYTES == 8 * 1024 * 1024
    aleatorio = np.random.default_rng(1).bytes(ML_MAX_ARTEFACTO_BYTES + 1024)  # no se comprime
    with pytest.raises(ArtefactoDemasiadoGrande, match="máximo"):
        serializar(aleatorio)


def test_serializar_y_deserializar_no_escriben_en_disco():
    modelo, _ = _modelo()
    antes = set(os.listdir(tempfile.gettempdir()))
    datos, sha, _ = serializar(modelo)
    deserializar(datos, sha)
    assert set(os.listdir(tempfile.gettempdir())) - antes == set()


def test_el_cache_guarda_por_empresa_tipo_y_version():
    cache = CacheModelos()
    cache.poner(1, "demanda_semanal", 1, "modelo-A")
    cache.poner(2, "demanda_semanal", 1, "modelo-B")
    assert cache.obtener(1, "demanda_semanal", 1) == "modelo-A"
    assert cache.obtener(2, "demanda_semanal", 1) == "modelo-B"  # la empresa es parte de la clave
    assert cache.obtener(1, "demanda_semanal", 2) is None and cache.obtener(1, "segmentos_rfm", 1) is None


def test_el_cache_se_invalida_al_guardar_una_version_nueva_solo_de_esa_empresa():
    cache = CacheModelos()
    cache.poner(1, "demanda_semanal", 1, "A1")
    cache.poner(1, "segmentos_rfm", 1, "A-seg")
    cache.poner(2, "demanda_semanal", 1, "B1")
    cache.invalidar(1, "demanda_semanal")
    assert cache.obtener(1, "demanda_semanal", 1) is None
    assert cache.obtener(1, "segmentos_rfm", 1) == "A-seg" and cache.obtener(2, "demanda_semanal", 1) == "B1"
    cache.invalidar(1)
    assert cache.obtener(1, "segmentos_rfm", 1) is None and cache.obtener(2, "demanda_semanal", 1) == "B1"


def test_el_cache_guarda_como_maximo_8_y_saca_el_menos_usado():
    assert ML_MAX_MODELOS_EN_CACHE == 8
    cache = CacheModelos()
    for n in range(8):
        cache.poner(n, "demanda_semanal", 1, f"m{n}")
    assert len(cache) == 8
    cache.obtener(0, "demanda_semanal", 1)  # el 0 pasa a ser el más reciente
    cache.poner(99, "demanda_semanal", 1, "nuevo")
    assert len(cache) == 8
    assert cache.obtener(1, "demanda_semanal", 1) is None  # salió el menos usado (el 1)
    assert cache.obtener(0, "demanda_semanal", 1) == "m0" and cache.obtener(99, "demanda_semanal", 1) == "nuevo"
