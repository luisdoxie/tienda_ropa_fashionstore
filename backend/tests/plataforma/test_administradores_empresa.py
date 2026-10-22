"""E04 / CU-04 (D36): una empresa puede tener varios administradores, pero
SIEMPRE al menos uno activo. No se puede desactivar ni quitar el rol
administrador al último administrador activo (409 con mensaje claro). Usan
`client_por_peticion` y `dos_empresas` (A = 'tienda-a': su único administrador es
`dos_empresas.a.admin_id`)."""

from tests.plataforma.ayudas_empresas import CLAVE, PLATAFORMA

API = "/api/v1"


def _segundo_administrador(client, superadmin_headers, empresa_id: int, correo: str = "segundo@tienda-a.example.com") -> int:
    creado = client.post(
        f"{PLATAFORMA}/empresas/{empresa_id}/usuarios",
        json={"nombre": "Segundo", "apellido": "Admin", "email": correo, "password": CLAVE},
        headers=superadmin_headers,
    )
    assert creado.status_code == 201, creado.text
    return creado.json()["id"]


def test_no_se_desactiva_al_ultimo_administrador(client_por_peticion, dos_empresas):
    admin = dos_empresas.a.headers
    id_admin = dos_empresas.a.admin_id

    por_delete = client_por_peticion.delete(f"{API}/usuarios/{id_admin}", headers=admin)
    por_put = client_por_peticion.put(f"{API}/usuarios/{id_admin}", json={"activo": False}, headers=admin)

    assert por_delete.status_code == 409
    assert por_put.status_code == 409
    assert "último administrador" in por_delete.json()["detail"]
    assert client_por_peticion.get(f"{API}/usuarios/{id_admin}", headers=admin).json()["activo"] is True


def test_no_se_quita_el_rol_al_ultimo_administrador(client_por_peticion, dos_empresas):
    respuesta = client_por_peticion.put(
        f"{API}/usuarios/{dos_empresas.a.admin_id}/roles", json={"nombres_rol": ["cajero"]}, headers=dos_empresas.a.headers
    )

    assert respuesta.status_code == 409
    assert "último administrador" in respuesta.json()["detail"]
    roles = client_por_peticion.get(f"{API}/usuarios/{dos_empresas.a.admin_id}", headers=dos_empresas.a.headers).json()["roles"]
    assert roles == ["administrador"]


def test_con_dos_administradores_se_puede_desactivar_uno_pero_no_el_ultimo(
    client_por_peticion, dos_empresas, superadmin_headers
):
    admin = dos_empresas.a.headers
    segundo = _segundo_administrador(client_por_peticion, superadmin_headers, dos_empresas.a.id)

    uno = client_por_peticion.delete(f"{API}/usuarios/{segundo}", headers=admin)
    otra_vez = client_por_peticion.delete(f"{API}/usuarios/{dos_empresas.a.admin_id}", headers=admin)

    assert uno.status_code == 204
    assert otra_vez.status_code == 409  # el desactivado ya no cuenta


def test_con_dos_administradores_se_puede_quitar_el_rol_a_uno(client_por_peticion, dos_empresas, superadmin_headers):
    admin = dos_empresas.a.headers
    segundo = _segundo_administrador(client_por_peticion, superadmin_headers, dos_empresas.a.id)

    quitado = client_por_peticion.put(f"{API}/usuarios/{segundo}/roles", json={"nombres_rol": ["cajero"]}, headers=admin)
    ultimo = client_por_peticion.put(
        f"{API}/usuarios/{dos_empresas.a.admin_id}/roles", json={"nombres_rol": ["cajero"]}, headers=admin
    )

    assert quitado.status_code == 200 and quitado.json()["roles"] == ["cajero"]
    assert ultimo.status_code == 409


def test_conservar_el_rol_administrador_al_reasignar_roles_es_valido(client_por_peticion, dos_empresas):
    respuesta = client_por_peticion.put(
        f"{API}/usuarios/{dos_empresas.a.admin_id}/roles",
        json={"nombres_rol": ["administrador", "cajero"]},
        headers=dos_empresas.a.headers,
    )

    assert respuesta.status_code == 200
    assert sorted(respuesta.json()["roles"]) == ["administrador", "cajero"]


def test_desactivar_a_un_usuario_que_no_es_administrador_no_se_afecta(client_por_peticion, dos_empresas):
    admin = dos_empresas.a.headers
    cajero = client_por_peticion.post(
        f"{API}/usuarios",
        json={"nombre": "Caja", "apellido": "Uno", "email": "cajero@tienda-a.example.com", "password": CLAVE},
        headers=admin,
    ).json()["id"]
    client_por_peticion.put(f"{API}/usuarios/{cajero}/roles", json={"nombres_rol": ["cajero"]}, headers=admin)

    assert client_por_peticion.delete(f"{API}/usuarios/{cajero}", headers=admin).status_code == 204


def test_los_administradores_de_otra_empresa_no_cuentan(client_por_peticion, dos_empresas):
    # B tiene su propio administrador, pero eso no habilita a desactivar al de A.
    assert client_por_peticion.delete(f"{API}/usuarios/{dos_empresas.a.admin_id}", headers=dos_empresas.a.headers).status_code == 409
    assert client_por_peticion.get(f"{API}/usuarios/{dos_empresas.b.admin_id}", headers=dos_empresas.a.headers).status_code == 404
