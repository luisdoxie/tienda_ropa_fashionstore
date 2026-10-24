"""E06: la bitácora también se aísla por empresa. Un administrador ve solo su
empresa, el superadministrador ve todo, y lo que hace la plataforma sobre una
empresa le llega a su administrador con el actor enmascarado."""

from sqlalchemy import select

from app.plataforma.models import Bitacora
from tests.ayudas_bitacora import filas_de

API = "/api/v1"
RANGO = "desde=2000-01-01&hasta=2100-01-01"


def _marcar(db, empresa_id: int | None, marca: str, cantidad: int = 3) -> list[int]:
    ids = []
    for i in range(cantidad):
        fila = Bitacora(empresa_id=empresa_id, entidad=marca, entidad_id=i, accion="crear", ip="9.9.9.9")
        db.add(fila)
        db.flush()
        ids.append(fila.id)
    db.commit()
    return ids


def test_cada_administrador_ve_solo_las_filas_de_su_empresa(client_por_peticion, dos_empresas, db_session):
    a, b = dos_empresas.a, dos_empresas.b
    _marcar(db_session, a.id, "marca-a", 3)
    _marcar(db_session, b.id, "marca-b", 5)

    de_a = client_por_peticion.get(f"{API}/bitacora?{RANGO}&entidad=marca-a", headers=a.headers).json()
    de_b = client_por_peticion.get(f"{API}/bitacora?{RANGO}&entidad=marca-b", headers=b.headers).json()
    assert (de_a["total"], de_b["total"]) == (3, 5)

    todo_a = client_por_peticion.get(f"{API}/bitacora?{RANGO}", headers=a.headers).json()
    assert {item["entidad"] for item in todo_a["items"]} == {"marca-a"}
    assert "marca-b" not in client_por_peticion.get(f"{API}/bitacora?{RANGO}", headers=a.headers).text
    assert "marca-a" not in client_por_peticion.get(f"{API}/bitacora?{RANGO}", headers=b.headers).text


def test_el_administrador_de_b_no_ve_nada_de_a_ni_cuenta_sus_filas(client_por_peticion, dos_empresas, db_session):
    _marcar(db_session, dos_empresas.a.id, "marca-a", 4)
    cuerpo = client_por_peticion.get(f"{API}/bitacora?{RANGO}&entidad=marca-a", headers=dos_empresas.b.headers).json()
    assert cuerpo["total"] == 0 and cuerpo["items"] == []


def test_el_detalle_de_una_fila_ajena_es_404_igual_que_uno_inexistente(client_por_peticion, dos_empresas, db_session):
    [fila_a] = _marcar(db_session, dos_empresas.a.id, "marca-a", 1)
    ajena = client_por_peticion.get(f"{API}/bitacora/{fila_a}", headers=dos_empresas.b.headers)
    inexistente = client_por_peticion.get(f"{API}/bitacora/999999", headers=dos_empresas.b.headers)
    assert ajena.status_code == inexistente.status_code == 404
    assert ajena.json() == inexistente.json()
    assert client_por_peticion.get(f"{API}/bitacora/{fila_a}", headers=dos_empresas.a.headers).status_code == 200


def test_el_parametro_empresa_id_del_cliente_se_ignora(client_por_peticion, dos_empresas, db_session):
    _marcar(db_session, dos_empresas.a.id, "marca-a", 2)
    _marcar(db_session, dos_empresas.b.id, "marca-b", 2)
    for extra in (f"empresa_id={dos_empresas.b.id}", "sin_empresa=true"):
        cuerpo = client_por_peticion.get(f"{API}/bitacora?{RANGO}&{extra}", headers=dos_empresas.a.headers).json()
        assert {item["entidad"] for item in cuerpo["items"]} == {"marca-a"}
        assert all(item["empresa_id"] is None for item in cuerpo["items"])  # el administrador no ve ids de empresa


def test_el_superadministrador_ve_las_dos_empresas_y_filtra(
    client_por_peticion, dos_empresas, db_session, superadmin_headers
):
    _marcar(db_session, dos_empresas.a.id, "marca-a", 2)
    _marcar(db_session, dos_empresas.b.id, "marca-b", 3)
    _marcar(db_session, None, "marca-global", 1)
    super_headers = superadmin_headers

    def pedir(extra: str = "") -> dict:
        respuesta = client_por_peticion.get(f"{API}/plataforma/bitacora?{RANGO}&{extra}", headers=super_headers)
        assert respuesta.status_code == 200
        return respuesta.json()

    todo = pedir()
    assert {item["entidad"] for item in todo["items"]} >= {"marca-a", "marca-b", "marca-global"}
    assert pedir("entidad=marca-a")["items"][0]["empresa_id"] == dos_empresas.a.id
    assert pedir(f"empresa_id={dos_empresas.b.id}&entidad=marca-b")["total"] == 3
    assert pedir(f"empresa_id={dos_empresas.b.id}&entidad=marca-a")["total"] == 0
    solo_sin_empresa = pedir("sin_empresa=true&entidad=marca-global")
    assert solo_sin_empresa["total"] == 1 and solo_sin_empresa["items"][0]["empresa_id"] is None


def test_el_administrador_de_empresa_no_entra_a_la_bitacora_de_plataforma(client_por_peticion, dos_empresas):
    respuesta = client_por_peticion.get(f"{API}/plataforma/bitacora", headers=dos_empresas.a.headers)
    assert respuesta.status_code == 403


def test_el_superadministrador_no_usa_la_ruta_de_una_empresa(client_por_peticion, superadmin_headers):
    respuesta = client_por_peticion.get(f"{API}/bitacora", headers=superadmin_headers)
    assert respuesta.status_code == 403


def test_el_cambio_de_plan_del_superadministrador_lo_ve_solo_esa_empresa_con_el_actor_enmascarado(
    client_por_peticion, dos_empresas, superadmin_headers
):
    super_headers = superadmin_headers
    cambio = client_por_peticion.post(
        f"{API}/plataforma/suscripciones",
        json={"empresa_id": dos_empresas.b.id, "plan_codigo": "profesional"},
        headers=super_headers,
    )
    assert cambio.status_code == 201

    de_b = client_por_peticion.get(f"{API}/bitacora?{RANGO}&entidad=suscripcion", headers=dos_empresas.b.headers).json()
    assert de_b["total"] >= 1
    fila = de_b["items"][0]
    assert fila["usuario_nombre"] == "Administrador de la plataforma" and fila["ip"] is None
    assert "Super" not in str(fila) and "plataforma.example.com" not in str(fila)

    de_a = client_por_peticion.get(f"{API}/bitacora?{RANGO}&entidad=suscripcion", headers=dos_empresas.a.headers).json()
    assert de_a["total"] == 0  # a la otra empresa no le llega nada de esto

    para_la_plataforma = client_por_peticion.get(
        f"{API}/plataforma/bitacora?{RANGO}&entidad=suscripcion", headers=super_headers
    ).json()["items"][0]
    assert para_la_plataforma["empresa_id"] == dos_empresas.b.id and para_la_plataforma["ip"] is not None


def test_un_login_fallido_con_empresa_inexistente_queda_sin_empresa_y_nadie_de_una_empresa_lo_ve(
    client_por_peticion, dos_empresas, db_session, superadmin_headers
):
    respuesta = client_por_peticion.post(
        f"{API}/auth/login", json={"empresa": "no-existe", "email": "x@example.com", "password": "claveSegura123"}
    )
    assert respuesta.status_code == 401

    fallidos = [f for f in filas_de(db_session, "sesion", "login_fallido") if f.empresa_id is None]
    assert len(fallidos) == 1 and fallidos[0].datos["motivo"] == "empresa_inexistente"
    for empresa in (dos_empresas.a, dos_empresas.b):
        cuerpo = client_por_peticion.get(f"{API}/bitacora?{RANGO}&accion=login_fallido", headers=empresa.headers).json()
        assert cuerpo["total"] == 0
    # El superadministrador sí lo encuentra, con sin_empresa=true.
    sin_empresa = client_por_peticion.get(
        f"{API}/plataforma/bitacora?{RANGO}&accion=login_fallido&sin_empresa=true", headers=superadmin_headers
    ).json()
    assert sin_empresa["total"] == 1


def test_los_filtros_de_la_consulta_no_dejan_ver_otra_empresa_por_usuario_id(client_por_peticion, dos_empresas, db_session):
    fila = Bitacora(empresa_id=dos_empresas.b.id, usuario_id=dos_empresas.b.admin_id, entidad="usuario", accion="crear")
    db_session.add(fila)
    db_session.commit()
    cuerpo = client_por_peticion.get(
        f"{API}/bitacora?{RANGO}&usuario_id={dos_empresas.b.admin_id}", headers=dos_empresas.a.headers
    ).json()
    assert cuerpo["total"] == 0
    assert db_session.scalar(select(Bitacora).where(Bitacora.usuario_id == dos_empresas.b.admin_id)) is not None
