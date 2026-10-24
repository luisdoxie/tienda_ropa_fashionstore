"""E06: el sanitizador de la bitácora (`core/auditoria.py`) es una función pura:
nada de lo que guarda la bitácora puede traer secretos ni datos personales."""

import copy
import datetime as dt
import enum
import json
import uuid
from decimal import Decimal

import pytest

from app.core.auditoria import (
    ACCION_ASIGNAR_PERMISOS,
    ACCION_CONTRASENA_RESTABLECIDA,
    BYTES_MAXIMOS,
    MARCA_OMITIDO,
    diff_campos,
    sanear_datos,
)


@pytest.mark.parametrize(
    "clave",
    ["password", "PASSWORD", "Contraseña", "contrasena_nueva", "token", "access_token", "refresh_token",
     "password_hash", "hash", "Authorization", "jwt", "api_key", "apiKey", "clave", "client_secret",
     "cvv", "tarjeta", "numero_card"],
)  # fmt: skip
def test_oculta_secretos_conservando_la_clave(clave):
    assert sanear_datos({clave: "valor-secreto", "otro": 1}) == {clave: MARCA_OMITIDO, "otro": 1}


@pytest.mark.parametrize(
    "clave",
    ["email", "Correo", "telefono", "celular", "direccion", "ci_nit", "nit", "NIT", "ci", "fecha_nacimiento",
     "estatura", "razon_social", "latitud", "longitud"],
)  # fmt: skip
def test_oculta_datos_personales(clave):
    assert sanear_datos({clave: "dato"}) == {clave: MARCA_OMITIDO}


def test_no_confunde_ciudad_ni_unidades_con_ci_o_nit():
    datos = {"ciudad_id": 3, "ciudad": "La Paz", "unidades": 4, "monitor": "x"}
    assert sanear_datos(datos) == datos


def test_un_id_de_referencia_no_es_dato_personal():
    # `direccion_id` y `cliente_id` son referencias numéricas, no la dirección en sí.
    assert sanear_datos({"direccion_id": 5}) == {"direccion_id": 5}
    assert sanear_datos({"direccion_id": "Calle Falsa 123"}) == {"direccion_id": MARCA_OMITIDO}


def test_oculta_un_valor_con_forma_de_jwt_de_bcrypt_o_de_correo_aunque_la_clave_sea_inocente():
    datos = {
        "nota": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.firma",
        "marca": "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ01234",
        "texto": "escribir a persona@example.com urgente",
        "precio": "$2.50",
    }
    assert sanear_datos(datos) == {
        "nota": MARCA_OMITIDO,
        "marca": MARCA_OMITIDO,
        "texto": MARCA_OMITIDO,
        "precio": "$2.50",
    }


def test_anida_dict_en_lista_en_dict():
    datos = {"usuarios": [{"id": 1, "password": "x", "roles": ["admin"]}, {"id": 2, "email": "a@b.co"}]}
    assert sanear_datos(datos) == {
        "usuarios": [
            {"id": 1, "password": MARCA_OMITIDO, "roles": ["admin"]},
            {"id": 2, "email": MARCA_OMITIDO},
        ]
    }


def test_convierte_a_tipos_json():
    class Estado(enum.Enum):
        PAGADA = "pagada"

    class Prioridad(enum.IntEnum):
        ALTA = 2

    identificador = uuid.UUID("12345678-1234-5678-1234-567812345678")
    resultado = sanear_datos(
        {
            "monto": Decimal("12.50"),
            "dia": dt.date(2026, 10, 23),
            "instante": dt.datetime(2026, 10, 23, 8, 30, 15),
            "id": identificador,
            "estado": Estado.PAGADA,
            "prioridad": Prioridad.ALTA,
            "conjunto": {3, 1, 2},
            "tupla": (1, 2),
            "objeto": object(),
            "infinito": float("inf"),
        }
    )
    assert resultado["monto"] == "12.50"
    assert resultado["dia"] == "2026-10-23"
    assert resultado["instante"] == "2026-10-23T08:30:15"
    assert resultado["id"] == "12345678-1234-5678-1234-567812345678"
    assert resultado["estado"] == "pagada"
    assert resultado["prioridad"] == 2
    assert resultado["conjunto"] == [1, 2, 3]
    assert resultado["tupla"] == [1, 2]
    assert resultado["objeto"].startswith("<object object")
    assert resultado["infinito"] == "inf"
    json.dumps(resultado)  # todo es serializable


def test_corta_cadenas_largas_a_200_caracteres():
    resultado = sanear_datos({"descripcion": "x" * 500})
    assert len(resultado["descripcion"]) == 200


def test_limita_las_listas_a_50_elementos_con_marcador():
    resultado = sanear_datos({"ids": list(range(80))})
    assert len(resultado["ids"]) == 51
    assert resultado["ids"][:50] == list(range(50))
    assert resultado["ids"][-1] == "...+30"


def test_limita_la_profundidad_a_4():
    datos = {"a": {"b": {"c": {"d": {"e": "hondo"}}}}}
    assert sanear_datos(datos) == {"a": {"b": {"c": {"d": "[profundo]"}}}}


def test_si_supera_los_4096_bytes_guarda_solo_las_claves():
    datos = {f"campo_{i}": "y" * 150 for i in range(40)}
    resultado = sanear_datos(datos)
    assert resultado["truncado"] is True
    assert resultado["claves"] == [f"campo_{i}" for i in range(20)]
    assert len(json.dumps(resultado).encode()) < BYTES_MAXIMOS


def test_none_da_none_y_un_vacio_da_vacio():
    assert sanear_datos(None) is None
    assert sanear_datos({}) == {}


def test_un_valor_que_no_es_diccionario_se_envuelve():
    assert sanear_datos([1, 2]) == {"valor": [1, 2]}


def test_no_modifica_el_diccionario_de_entrada():
    original = {"password": "secreta", "anidado": {"token": "t", "lista": [1, 2]}, "monto": Decimal("1")}
    copia = copy.deepcopy(original)
    sanear_datos(original)
    assert original == copia


def test_las_claves_que_no_son_texto_se_convierten():
    assert sanear_datos({1: "a", 2: {"x": 1}}) == {"1": "a", "2": {"x": 1}}


def test_diff_campos_lista_solo_nombres_y_muestra_los_visibles():
    antes = {"telefono": "70000000", "activo": True, "cargo": "Cajero"}
    despues = {"telefono": "71111111", "activo": False, "cargo": "Cajero"}
    resultado = diff_campos(antes, despues, campos_visibles=["activo", "cargo"])
    assert resultado == {"campos": ["telefono", "activo"], "antes": {"activo": True}, "despues": {"activo": False}}
    assert "70000000" not in json.dumps(resultado) and "71111111" not in json.dumps(resultado)


def test_diff_campos_sin_cambios_y_con_objetos():
    class Fila:
        activo = True

    assert diff_campos(Fila(), {"activo": True}) == {"campos": []}
    assert diff_campos(Fila(), {"activo": False}, ["activo"])["despues"] == {"activo": False}


def test_las_acciones_caben_en_la_columna():
    # `accion` es VARCHAR(40); la más larga reservada tiene 23 letras.
    assert len(ACCION_CONTRASENA_RESTABLECIDA) == 23
    assert len(ACCION_ASIGNAR_PERMISOS) <= 40
