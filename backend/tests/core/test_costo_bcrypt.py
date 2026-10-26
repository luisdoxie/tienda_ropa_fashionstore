"""El costo de bcrypt sale de `bcrypt_rounds`: 12 por defecto (producción) y 4 solo en las pruebas."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import hash_password, verificar_password


def test_el_costo_por_defecto_es_12_y_las_pruebas_lo_bajan_a_4():
    assert Settings.model_fields["bcrypt_rounds"].default == 12  # lo que corre en producción
    assert hash_password("claveSegura123").startswith("$2b$04$")  # lo que fija tests/conftest.py


def test_un_hash_se_verifica_con_el_costo_con_que_se_creo():
    hash_caro = "$2b$12$d1ru1mgPSWsBsc/AHIyMHeWrDeAVeESRlnXjY52JXjnR/XOLoWB22"  # el dummy de producción
    assert verificar_password("x", hash_caro) is False  # no falla por tener otro costo
    assert verificar_password("claveSegura123", hash_password("claveSegura123"))


@pytest.mark.parametrize("valor", [3, 17, 0, -1])
def test_un_costo_fuera_de_4_a_16_se_rechaza(valor):
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite://", jwt_secret_key="x", bcrypt_rounds=valor)
