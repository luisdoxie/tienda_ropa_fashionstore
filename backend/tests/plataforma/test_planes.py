"""E04 / CU-04: el superadministrador administra los planes. Los límites y las
funcionalidades viven en la tabla `plan`: editarlos cambia el comportamiento sin
tocar el código. Usan `client_por_peticion` y `dos_empresas` (A = 'tienda-a'
Profesional, B = 'tienda-b' Básico)."""

import pytest

from tests.plataforma.ayudas_empresas import PLATAFORMA

API = "/api/v1"


def _id_del_plan(client, headers, codigo: str) -> int:
    planes = client.get(f"{PLATAFORMA}/planes", headers=headers).json()
    return next(p["id"] for p in planes if p["codigo"] == codigo)


def _ciudad(client, headers) -> int:
    return client.post(f"{API}/ciudades", json={"nombre": "Ciudad de prueba"}, headers=headers).json()["id"]


def _sucursal(client, headers, ciudad_id: int, codigo: str):
    return client.post(
        f"{API}/sucursales",
        json={"ciudad_id": ciudad_id, "codigo": codigo, "nombre": f"Sucursal {codigo}", "direccion": "Calle 1"},
        headers=headers,
    )


def test_la_lista_trae_los_dos_planes_con_sus_valores(client_por_peticion, superadmin_headers):
    respuesta = client_por_peticion.get(f"{PLATAFORMA}/planes", headers=superadmin_headers)

    assert respuesta.status_code == 200
    planes = {p["codigo"]: p for p in respuesta.json()}
    assert set(planes) == {"basico", "profesional"}
    basico, profesional = planes["basico"], planes["profesional"]
    assert (basico["max_sucursales"], profesional["max_sucursales"]) == (2, 10)
    assert basico["reportes_ia"] is False and profesional["reportes_ia"] is True
    assert basico["analitica_ml"] is False and profesional["analitica_ml"] is True
    assert basico["copias_seguridad"] is False and profesional["copias_seguridad"] is True
    assert basico["reportes_convencionales"] and basico["gestion_productos"] and basico["reservas"]
    uno = client_por_peticion.get(f"{PLATAFORMA}/planes/{basico['id']}", headers=superadmin_headers)
    assert uno.json() == basico
    assert client_por_peticion.get(f"{PLATAFORMA}/planes/999999", headers=superadmin_headers).status_code == 404


def test_crear_un_plan(client_por_peticion, superadmin_headers):
    cuerpo = {"codigo": "empresarial", "nombre": "Empresarial", "max_sucursales": 25, "reportes_ia": True}

    creado = client_por_peticion.post(f"{PLATAFORMA}/planes", json=cuerpo, headers=superadmin_headers)

    assert creado.status_code == 201
    assert creado.json()["max_sucursales"] == 25
    assert creado.json()["reportes_ia"] is True
    assert creado.json()["reservas"] is True  # valor por defecto del esquema
    assert creado.json()["activo"] is True
    assert client_por_peticion.post(f"{PLATAFORMA}/planes", json=cuerpo, headers=superadmin_headers).status_code == 409
    for invalido in (
        {**cuerpo, "codigo": "Con Espacios"},
        {**cuerpo, "codigo": "otro", "max_sucursales": 0},
    ):
        assert client_por_peticion.post(f"{PLATAFORMA}/planes", json=invalido, headers=superadmin_headers).status_code == 422


def test_editar_max_sucursales_rige_de_inmediato(client_por_peticion, dos_empresas, superadmin_headers):
    admin_b = dos_empresas.b.headers  # Básico: 2 sucursales
    ciudad = _ciudad(client_por_peticion, admin_b)
    assert _sucursal(client_por_peticion, admin_b, ciudad, "S1").status_code == 201
    assert _sucursal(client_por_peticion, admin_b, ciudad, "S2").status_code == 201
    bloqueada = _sucursal(client_por_peticion, admin_b, ciudad, "S3")
    assert bloqueada.status_code == 409
    assert bloqueada.json()["detail"] == "limite_plan_excedido"

    editado = client_por_peticion.put(
        f"{PLATAFORMA}/planes/{_id_del_plan(client_por_peticion, superadmin_headers, 'basico')}",
        json={"max_sucursales": 3},
        headers=superadmin_headers,
    )

    assert editado.status_code == 200 and editado.json()["max_sucursales"] == 3
    assert editado.json()["codigo"] == "basico"
    assert _sucursal(client_por_peticion, admin_b, ciudad, "S3").status_code == 201
    assert _sucursal(client_por_peticion, admin_b, ciudad, "S4").status_code == 409


def test_bajar_el_limite_no_desactiva_sucursales_pero_bloquea_crear(client_por_peticion, dos_empresas, superadmin_headers):
    admin_a = dos_empresas.a.headers  # Profesional: 10 sucursales
    ciudad = _ciudad(client_por_peticion, admin_a)
    for codigo in ("S1", "S2"):
        assert _sucursal(client_por_peticion, admin_a, ciudad, codigo).status_code == 201

    client_por_peticion.put(
        f"{PLATAFORMA}/planes/{_id_del_plan(client_por_peticion, superadmin_headers, 'profesional')}",
        json={"max_sucursales": 1},
        headers=superadmin_headers,
    )

    activas = client_por_peticion.get(f"{API}/sucursales", headers=admin_a).json()
    assert [s["activo"] for s in activas] == [True, True]  # nada se desactivó
    rechazada = _sucursal(client_por_peticion, admin_a, ciudad, "S3")
    assert rechazada.status_code == 409
    assert (rechazada.json()["limite"], rechazada.json()["actual"]) == (1, 2)


def test_desactivar_un_plan_en_uso_es_409_y_uno_libre_se_da_de_baja(client_por_peticion, dos_empresas, superadmin_headers):
    en_uso = _id_del_plan(client_por_peticion, superadmin_headers, "basico")  # lo usa tienda-b

    rechazado = client_por_peticion.delete(f"{PLATAFORMA}/planes/{en_uso}", headers=superadmin_headers)

    assert rechazado.status_code == 409
    assert client_por_peticion.put(
        f"{PLATAFORMA}/planes/{en_uso}", json={"activo": False}, headers=superadmin_headers
    ).status_code == 409
    libre = client_por_peticion.post(
        f"{PLATAFORMA}/planes", json={"codigo": "libre", "nombre": "Libre", "max_sucursales": 1}, headers=superadmin_headers
    ).json()["id"]
    assert client_por_peticion.delete(f"{PLATAFORMA}/planes/{libre}", headers=superadmin_headers).status_code == 204
    # Baja lógica: el plan sigue en la lista del superadministrador, inactivo, y se puede reactivar.
    en_lista = client_por_peticion.get(f"{PLATAFORMA}/planes/{libre}", headers=superadmin_headers).json()
    assert en_lista["activo"] is False
    reactivado = client_por_peticion.put(f"{PLATAFORMA}/planes/{libre}", json={"activo": True}, headers=superadmin_headers)
    assert reactivado.json()["activo"] is True


def test_apagar_una_funcionalidad_y_ignorar_nulos(client_por_peticion, superadmin_headers):
    plan_id = _id_del_plan(client_por_peticion, superadmin_headers, "profesional")

    editado = client_por_peticion.put(
        f"{PLATAFORMA}/planes/{plan_id}",
        json={"reservas": False, "nombre": None, "max_sucursales": None, "codigo": "otro"},
        headers=superadmin_headers,
    )

    assert editado.status_code == 200
    assert editado.json()["reservas"] is False
    assert editado.json()["nombre"] == "Profesional"  # un null no vacía una columna obligatoria
    assert editado.json()["max_sucursales"] == 10
    assert editado.json()["codigo"] == "profesional"  # el código no cambia


def test_solo_el_superadministrador_gestiona_planes(client_por_peticion, dos_empresas):
    for metodo, ruta, cuerpo in (
        ("get", f"{PLATAFORMA}/planes", None),
        ("get", f"{PLATAFORMA}/planes/1", None),
        ("post", f"{PLATAFORMA}/planes", {"codigo": "x1", "nombre": "X", "max_sucursales": 1}),
        ("put", f"{PLATAFORMA}/planes/1", {"max_sucursales": 99}),
        ("delete", f"{PLATAFORMA}/planes/1", None),
    ):
        assert client_por_peticion.request(metodo, ruta, json=cuerpo, headers=dos_empresas.a.headers).status_code == 403, ruta
        assert client_por_peticion.request(metodo, ruta, json=cuerpo).status_code == 401, ruta


@pytest.mark.parametrize("limite", [0, -1, 1001])
def test_el_limite_de_sucursales_se_valida(client_por_peticion, superadmin_headers, limite):
    plan_id = _id_del_plan(client_por_peticion, superadmin_headers, "basico")

    respuesta = client_por_peticion.put(
        f"{PLATAFORMA}/planes/{plan_id}", json={"max_sucursales": limite}, headers=superadmin_headers
    )

    assert respuesta.status_code == 422
