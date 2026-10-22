"""E04 / CU-04: el superadministrador registra y administra empresas.

El registro es una sola transacción (empresa + suscripción activa + administrador
+ tallas, materiales y ciudades base); el código sale del nombre y no cambia; solo
el superadministrador entra a /plataforma. Usan `client_por_peticion` (una sesión
por petición, sin empresa) y `dos_empresas` (A = 'tienda-a' Profesional, B =
'tienda-b' Básico)."""

import datetime as dt

import pytest
from sqlalchemy import select

from app.catalogo.models import Material, Talla
from app.core import tenant
from app.core.exceptions import ConflictoError
from app.core.tenant import en_empresa, sin_filtro
from app.plataforma.models import Ciudad, Empresa, Sucursal, Usuario
from tests.plataforma.ayudas_empresas import (
    CLAVE,
    PLATAFORMA,
    contar,
    contar_suscripciones,
    cuerpo_registro,
    login_de_empresa,
    registrar,
    suscripciones_de,
)

CORREO_ADMIN = "ana@boutiqueandina.example.com"


def _empresa_por_codigo(db, codigo: str):
    return db.scalar(select(Empresa).where(Empresa.codigo == codigo))


def test_registrar_crea_empresa_suscripcion_administrador_y_catalogos_base(
    client_por_peticion, db_session, superadmin_headers
):
    respuesta = registrar(client_por_peticion, superadmin_headers)

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "boutique-andina"
    assert cuerpo["nombre"] == "Boutique Andina"
    assert cuerpo["activo"] is True
    assert cuerpo["plan_codigo"] == "basico"  # el plan por defecto
    assert cuerpo["suscripcion_estado"] == "activa"
    hoy = dt.datetime.now(dt.timezone.utc).date()
    assert cuerpo["fecha_inicio"] == hoy.isoformat()
    assert cuerpo["fecha_vencimiento"] == (hoy + dt.timedelta(days=30)).isoformat()
    assert cuerpo["administrador_email"] == CORREO_ADMIN
    assert "password" not in respuesta.text and CLAVE not in respuesta.text

    empresa_id = cuerpo["id"]
    assert contar_suscripciones(db_session, empresa_id) == 1
    assert contar(db_session, Talla, empresa_id) == 6
    assert contar(db_session, Material, empresa_id) == 8
    assert contar(db_session, Ciudad, empresa_id) == 9
    with en_empresa(db_session, empresa_id):
        administrador = db_session.scalar(select(Usuario).where(Usuario.email == CORREO_ADMIN))
        assert administrador.empresa_id == empresa_id
        assert [r.nombre for r in administrador.roles] == ["administrador"]
        assert administrador.password_hash != CLAVE  # con bcrypt, nunca en claro


def test_el_codigo_sale_del_nombre_normalizado(client_por_peticion, superadmin_headers):
    respuesta = registrar(client_por_peticion, superadmin_headers, nombre="  Ñandú  Moda & Co.  ")

    assert respuesta.status_code == 201
    assert respuesta.json()["codigo"] == "nandu-moda-co"
    assert respuesta.json()["nombre"] == "Ñandú  Moda & Co."  # el nombre comercial solo se recorta


def test_dos_nombres_que_normalizan_igual_colisionan_con_409(client_por_peticion, superadmin_headers):
    assert registrar(client_por_peticion, superadmin_headers, nombre="Boutique Andina").status_code == 201

    repetida = registrar(client_por_peticion, superadmin_headers, nombre="boutique-andina", correo="otra@x.example.com")

    assert repetida.status_code == 409
    assert repetida.json() == {"detail": "Ya existe una empresa con ese nombre"}


def test_un_nombre_sin_letras_ni_numeros_es_400(client_por_peticion, db_session, superadmin_headers):
    antes = contar_suscripciones(db_session)

    respuesta = registrar(client_por_peticion, superadmin_headers, nombre="!!!")

    assert respuesta.status_code == 400
    assert contar_suscripciones(db_session) == antes
    assert _empresa_por_codigo(db_session, "") is None


@pytest.mark.parametrize(
    ("extra", "estado", "detalle"),
    [
        ({"plan_codigo": "no-existe"}, 404, "Plan no encontrado"),
        ({"fecha_vencimiento": "2020-01-01"}, 422, "La fecha de vencimiento debe ser posterior a hoy"),
    ],
)
def test_registro_con_plan_o_fecha_invalidos_no_deja_nada(
    client_por_peticion, db_session, superadmin_headers, extra, estado, detalle
):
    antes = contar_suscripciones(db_session)

    respuesta = registrar(client_por_peticion, superadmin_headers, **extra)

    assert respuesta.status_code == estado
    assert respuesta.json() == {"detail": detalle}
    assert _empresa_por_codigo(db_session, "boutique-andina") is None
    assert contar_suscripciones(db_session) == antes


def test_registro_con_un_plan_inactivo_es_409(client_por_peticion, superadmin_headers):
    # Un plan en uso no se desactiva: se crea uno aparte y se desactiva.
    nuevo = client_por_peticion.post(
        f"{PLATAFORMA}/planes", json={"codigo": "antiguo", "nombre": "Antiguo", "max_sucursales": 1}, headers=superadmin_headers
    )
    assert nuevo.status_code == 201
    assert client_por_peticion.delete(f"{PLATAFORMA}/planes/{nuevo.json()['id']}", headers=superadmin_headers).status_code == 204

    respuesta = registrar(client_por_peticion, superadmin_headers, plan_codigo="antiguo")

    assert respuesta.status_code == 409
    assert respuesta.json() == {"detail": "El plan está inactivo"}


def test_registrar_con_plan_y_vencimiento_pedidos(client_por_peticion, superadmin_headers):
    vencimiento = (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=200)).isoformat()

    respuesta = registrar(
        client_por_peticion, superadmin_headers, plan_codigo="profesional", fecha_vencimiento=vencimiento,
        color_acento="#9A3E1F",
    )

    assert respuesta.status_code == 201
    assert respuesta.json()["plan_codigo"] == "profesional"
    assert respuesta.json()["fecha_vencimiento"] == vencimiento
    assert respuesta.json()["color_acento"] == "#9A3E1F"


def test_el_administrador_creado_inicia_sesion_con_nombre_correo_y_clave(client_por_peticion, superadmin_headers):
    registrar(client_por_peticion, superadmin_headers)

    login = login_de_empresa(client_por_peticion, "Boutique Andina", CORREO_ADMIN)

    assert login.status_code == 200, login.text
    cabeceras = {"Authorization": f"Bearer {login.json()['access_token']}"}
    yo = client_por_peticion.get("/api/v1/auth/yo", headers=cabeceras).json()
    assert yo["roles"] == ["administrador"]
    assert yo["empresa_codigo"] == "boutique-andina"
    assert login_de_empresa(client_por_peticion, "Boutique Andina", CORREO_ADMIN, "otraClave12345").status_code == 401


def test_rollback_total_si_falla_un_inicializador(client_por_peticion, db_session, superadmin_headers, monkeypatch):
    def inicializador_roto(_db):
        raise ConflictoError("Falló un inicializador")

    monkeypatch.setattr(tenant, "_inicializadores", [*tenant._inicializadores, inicializador_roto])
    suscripciones = contar_suscripciones(db_session)

    respuesta = registrar(client_por_peticion, superadmin_headers)

    assert respuesta.status_code == 409
    assert _empresa_por_codigo(db_session, "boutique-andina") is None  # ni empresa...
    assert contar_suscripciones(db_session) == suscripciones  # ...ni suscripción...
    sin_empresa = db_session.scalar(sin_filtro(select(Usuario).where(Usuario.email == CORREO_ADMIN)))
    assert sin_empresa is None  # ...ni administrador


def test_el_correo_del_administrador_invalido_se_rechaza_antes_de_escribir(
    client_por_peticion, db_session, superadmin_headers
):
    cuerpo = cuerpo_registro()
    cuerpo["administrador"]["email"] = "esto-no-es-un-correo"

    respuesta = client_por_peticion.post(f"{PLATAFORMA}/empresas", json=cuerpo, headers=superadmin_headers)

    assert respuesta.status_code == 422
    assert _empresa_por_codigo(db_session, "boutique-andina") is None


def test_solo_el_superadministrador_entra_a_plataforma(client_por_peticion, dos_empresas):
    admin = dos_empresas.a.headers
    rutas = (
        ("get", f"{PLATAFORMA}/empresas", None),
        ("post", f"{PLATAFORMA}/empresas", cuerpo_registro()),
        ("get", f"{PLATAFORMA}/empresas/{dos_empresas.a.id}", None),
        ("put", f"{PLATAFORMA}/empresas/{dos_empresas.a.id}", {"nombre": "Otro"}),
        ("delete", f"{PLATAFORMA}/empresas/{dos_empresas.a.id}", None),
        ("get", f"{PLATAFORMA}/empresas/{dos_empresas.a.id}/resumen", None),
        ("post", f"{PLATAFORMA}/empresas/{dos_empresas.a.id}/usuarios", cuerpo_registro()["administrador"]),
    )

    for metodo, ruta, cuerpo in rutas:
        respuesta = client_por_peticion.request(metodo, ruta, json=cuerpo, headers=admin)
        assert respuesta.status_code == 403, (metodo, ruta)
        assert client_por_peticion.request(metodo, ruta, json=cuerpo).status_code == 401, (metodo, ruta)


def test_renombrar_no_cambia_el_codigo(client_por_peticion, superadmin_headers):
    creada = registrar(client_por_peticion, superadmin_headers).json()

    respuesta = client_por_peticion.put(
        f"{PLATAFORMA}/empresas/{creada['id']}",
        json={"nombre": "Andina Moda", "codigo": "otro-codigo", "logo_url": "https://x.example.com/logo.png"},
        headers=superadmin_headers,
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["nombre"] == "Andina Moda"
    assert respuesta.json()["codigo"] == "boutique-andina"
    assert respuesta.json()["logo_url"] == "https://x.example.com/logo.png"
    # El login por el código de siempre sigue funcionando.
    assert login_de_empresa(client_por_peticion, "boutique-andina", CORREO_ADMIN).status_code == 200


def test_desactivar_la_empresa_bloquea_login_y_tokens_y_reactivar_los_devuelve(
    client_por_peticion, superadmin_headers
):
    creada = registrar(client_por_peticion, superadmin_headers).json()
    token = login_de_empresa(client_por_peticion, "boutique-andina", CORREO_ADMIN).json()["access_token"]
    cabeceras = {"Authorization": f"Bearer {token}"}
    assert client_por_peticion.get("/api/v1/auth/yo", headers=cabeceras).status_code == 200

    baja = client_por_peticion.delete(f"{PLATAFORMA}/empresas/{creada['id']}", headers=superadmin_headers)

    assert baja.status_code == 204
    assert login_de_empresa(client_por_peticion, "boutique-andina", CORREO_ADMIN).status_code == 401
    assert client_por_peticion.get("/api/v1/auth/yo", headers=cabeceras).status_code == 401
    # Sigue en el listado del superadministrador, marcada como inactiva.
    inactivas = client_por_peticion.get(f"{PLATAFORMA}/empresas?activo=false", headers=superadmin_headers).json()
    assert [e["codigo"] for e in inactivas] == ["boutique-andina"]

    alta = client_por_peticion.put(
        f"{PLATAFORMA}/empresas/{creada['id']}", json={"activo": True}, headers=superadmin_headers
    )
    assert alta.status_code == 200 and alta.json()["activo"] is True
    assert client_por_peticion.get("/api/v1/auth/yo", headers=cabeceras).status_code == 200
    assert login_de_empresa(client_por_peticion, "boutique-andina", CORREO_ADMIN).status_code == 200


def test_resumen_con_conteos_plan_y_administrador_principal(client_por_peticion, dos_empresas, superadmin_headers):
    # B (tienda-b, Básico) tiene su administrador; se le agrega un segundo.
    segundo = client_por_peticion.post(
        f"{PLATAFORMA}/empresas/{dos_empresas.b.id}/usuarios",
        json={**cuerpo_registro()["administrador"], "email": "segundo@tienda-b.example.com"},
        headers=superadmin_headers,
    )
    assert segundo.status_code == 201

    resumen = client_por_peticion.get(f"{PLATAFORMA}/empresas/{dos_empresas.b.id}/resumen", headers=superadmin_headers)

    assert resumen.status_code == 200
    cuerpo = resumen.json()
    assert cuerpo["codigo"] == "tienda-b"
    assert cuerpo["usuarios_activos"] == 2
    assert cuerpo["sucursales_activas"] == 0
    assert cuerpo["max_sucursales"] == 2
    assert cuerpo["plan_codigo"] == "basico"
    assert cuerpo["suscripcion_estado"] == "activa"
    assert cuerpo["administrador_email"] == "admin@tienda-b.example.com"  # el de menor id
    assert client_por_peticion.get(f"{PLATAFORMA}/empresas/999999/resumen", headers=superadmin_headers).status_code == 404


def test_el_superadmin_agrega_administradores_a_una_empresa_ajena(client_por_peticion, dos_empresas, superadmin_headers):
    ruta = f"{PLATAFORMA}/empresas/{dos_empresas.a.id}/usuarios"
    nuevo = {**cuerpo_registro()["administrador"], "email": "otro@tienda-a.example.com"}

    creado = client_por_peticion.post(ruta, json=nuevo, headers=superadmin_headers)

    assert creado.status_code == 201
    assert creado.json()["roles"] == ["administrador"]
    assert "password" not in creado.text and CLAVE not in creado.text
    assert login_de_empresa(client_por_peticion, "tienda-a", "otro@tienda-a.example.com").status_code == 200
    # El mismo correo en la misma empresa: 409. En otra empresa: permitido.
    assert client_por_peticion.post(ruta, json=nuevo, headers=superadmin_headers).status_code == 409
    en_b = client_por_peticion.post(
        f"{PLATAFORMA}/empresas/{dos_empresas.b.id}/usuarios", json=nuevo, headers=superadmin_headers
    )
    assert en_b.status_code == 201
    assert client_por_peticion.post(
        f"{PLATAFORMA}/empresas/999999/usuarios", json=nuevo, headers=superadmin_headers
    ).status_code == 404


def test_el_alta_de_sucursales_por_el_superadmin_respeta_el_limite_del_plan(
    client_por_peticion, db_session, superadmin_headers
):
    creada = registrar(client_por_peticion, superadmin_headers).json()  # Básico: hasta 2 sucursales
    with en_empresa(db_session, creada["id"]):
        ciudad_id = db_session.scalar(select(Ciudad.id).where(Ciudad.nombre == "La Paz"))
    ruta = f"{PLATAFORMA}/empresas/{creada['id']}/sucursales"

    def sucursal(codigo: str, deposito: bool = False) -> dict:
        return {"ciudad_id": ciudad_id, "codigo": codigo, "nombre": f"Sucursal {codigo}", "direccion": "Calle 1", "es_deposito": deposito}

    primera = client_por_peticion.post(ruta, json=sucursal("S1"), headers=superadmin_headers)
    segunda = client_por_peticion.post(ruta, json=sucursal("DEP", deposito=True), headers=superadmin_headers)  # el depósito cuenta
    tercera = client_por_peticion.post(ruta, json=sucursal("S3"), headers=superadmin_headers)

    assert primera.status_code == 201 and segunda.status_code == 201, (primera.text, segunda.text)
    assert tercera.status_code == 409
    assert tercera.json()["detail"] == "limite_plan_excedido"
    assert tercera.json()["limite"] == 2 and tercera.json()["actual"] == 2
    assert contar(db_session, Sucursal, creada["id"]) == 2  # la tercera no quedó


def test_la_sucursal_de_otra_empresa_se_resuelve_con_404(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    # La ciudad de A no sirve para una sucursal de B: la FK sola lo permitiría.
    with en_empresa(db_session, dos_empresas.a.id):
        db_session.add(Ciudad(nombre="Ciudad de A"))
        db_session.flush()
        ciudad_a = db_session.scalar(select(Ciudad.id).where(Ciudad.nombre == "Ciudad de A"))
        db_session.commit()

    respuesta = client_por_peticion.post(
        f"{PLATAFORMA}/empresas/{dos_empresas.b.id}/sucursales",
        json={"ciudad_id": ciudad_a, "codigo": "X1", "nombre": "X", "direccion": "Calle"},
        headers=superadmin_headers,
    )

    assert respuesta.status_code == 404


def test_listar_y_filtrar_empresas(client_por_peticion, dos_empresas, superadmin_headers):
    todas = client_por_peticion.get(f"{PLATAFORMA}/empresas", headers=superadmin_headers)

    assert todas.status_code == 200
    por_codigo = {e["codigo"]: e for e in todas.json()}
    assert {"fashionstore", "tienda-a", "tienda-b"} <= set(por_codigo)
    assert por_codigo["tienda-a"]["plan_codigo"] == "profesional"
    assert por_codigo["tienda-b"]["plan_codigo"] == "basico"
    assert por_codigo["tienda-b"]["suscripcion_estado"] == "activa"
    filtradas = client_por_peticion.get(f"{PLATAFORMA}/empresas?q=TIENDA-", headers=superadmin_headers).json()
    assert sorted(e["codigo"] for e in filtradas) == ["tienda-a", "tienda-b"]
    assert client_por_peticion.get(f"{PLATAFORMA}/empresas?q=tienda-&tamanio=1", headers=superadmin_headers).json()[0]["codigo"] == "tienda-a"
    assert client_por_peticion.get(f"{PLATAFORMA}/empresas/999999", headers=superadmin_headers).status_code == 404
    uno = client_por_peticion.get(f"{PLATAFORMA}/empresas/{dos_empresas.a.id}", headers=superadmin_headers).json()
    assert uno["administrador_email"] == "admin@tienda-a.example.com"


def test_los_inicializadores_son_idempotentes_y_comparten_las_constantes_del_seed(db_session):
    from app.catalogo import politicas as catalogo_politicas
    from app.plataforma import politicas as plataforma_politicas
    from scripts import seed_catalogo
    from tests.conftest import crear_empresa

    empresa_id = crear_empresa(db_session, "inicializada").id

    for _ in range(2):  # la segunda vuelta no duplica nada
        tenant.inicializar_empresa(db_session, empresa_id)

    assert contar(db_session, Talla, empresa_id) == len(catalogo_politicas.TALLAS_BASE) == 6
    assert contar(db_session, Material, empresa_id) == len(catalogo_politicas.MATERIALES_BASE) == 8
    assert contar(db_session, Ciudad, empresa_id) == len(plataforma_politicas.CIUDADES_BASE) == 9
    assert seed_catalogo.TALLAS_BASE is catalogo_politicas.TALLAS_BASE  # una sola fuente
    assert {d for _, d in plataforma_politicas.CIUDADES_BASE} == {
        "La Paz", "Santa Cruz", "Cochabamba", "Oruro", "Potosí", "Chuquisaca", "Tarija", "Beni", "Pando",
    }


def test_las_rutas_de_negocio_con_token_de_superadmin_siguen_en_403(client_por_peticion, dos_empresas, superadmin_headers):
    for ruta in ("/api/v1/productos", "/api/v1/sucursales", "/api/v1/ciudades", "/api/v1/usuarios"):
        assert client_por_peticion.get(ruta, headers=superadmin_headers).status_code == 403, ruta
    # Operar sobre una empresa ajena por /plataforma no deja la sesión en esa empresa.
    assert client_por_peticion.get(f"{PLATAFORMA}/empresas/{dos_empresas.a.id}/resumen", headers=superadmin_headers).status_code == 200
    assert client_por_peticion.get("/api/v1/sucursales", headers=superadmin_headers).status_code == 403
