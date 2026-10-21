"""E03: el inicio de sesión con empresa.

Se prueba por HTTP como en producción (`client_por_peticion`: una sesión nueva y
sin empresa por petición). Las empresas son 'fashionstore' (la semilla),
'tienda-a' y 'tienda-b' (fixture `dos_empresas`); la clave de todas las cuentas
de prueba es `claveSegura123`."""

import pytest

from app.core.rate_limit import limitador_intentos
from app.core.security import decodificar_token
from app.core.tenant import empresa_de, fijar_empresa
from app.plataforma import politicas
from app.plataforma.casos_uso import cu01_autenticar_registrar_usuarios as cu01
from app.plataforma.models import Empresa, Usuario
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.conftest import crear_empresa, crear_superadmin_de_prueba

CLAVE = "claveSegura123"
LOGIN = "/api/v1/auth/login"
INVALIDAS = {"detail": "Credenciales inválidas"}


def _crear_usuario(db, empresa_id, email, *, password=CLAVE, roles=("cliente",), activo=True):
    """Un usuario dentro de `empresa_id`; deja la sesión en la empresa que tenía."""
    original = empresa_de(db)
    fijar_empresa(db, empresa_id)
    try:
        repo = UsuarioRepository()
        usuario = repo.crear(db, UsuarioCrear(nombre="Per", apellido="Sona", email=email, password=password))
        repo.asignar_roles(db, usuario, list(roles))
        if not activo:
            usuario.activo = False
            db.commit()
        return usuario.id
    finally:
        fijar_empresa(db, original)


def _login(client, email, password=CLAVE, empresa="fashionstore"):
    cuerpo = {"email": email, "password": password}
    if empresa is not None:
        cuerpo["empresa"] = empresa
    return client.post(LOGIN, json=cuerpo)


def _con_token(respuesta):
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


@pytest.fixture()
def cuentas(db_session):
    """Un administrador en 'fashionstore' (id 1), el mismo correo con claves
    distintas en tienda-a y tienda-b, y nadie más."""
    _crear_usuario(db_session, 1, "ana@example.com", roles=("administrador",))
    return None


# ---- el nombre de la empresa -------------------------------------------------


@pytest.mark.parametrize("nombre", ["FashionStore", "  fashionstore ", "FASHIONSTORE", "fashionstore"])
def test_el_nombre_de_la_empresa_se_normaliza_al_entrar(client_por_peticion, cuentas, nombre):
    respuesta = _login(client_por_peticion, "ana@example.com", empresa=nombre)
    assert respuesta.status_code == 200
    assert decodificar_token(respuesta.json()["access_token"], tipo="access")["empresa_id"] == 1


@pytest.mark.parametrize(
    "entrada, salida",
    [
        ("Boutique Andina", "boutique-andina"),
        ("  FashionStore  ", "fashionstore"),
        ("Ñandú Moda  S.R.L.", "nandu-moda-s-r-l"),
        ("Nandu Moda  S.R.L.", "nandu-moda-s-r-l"),
        ("boutique-andina", "boutique-andina"),
        ("Café--Núñez!!", "cafe-nunez"),
        ("", ""),
        ("!!!", ""),
        ("A" * 100, "a" * 60),
    ],
)
def test_normalizar_nombre_empresa(entrada, salida):
    assert politicas.normalizar_nombre_empresa(entrada) == salida


# ---- los tokens ---------------------------------------------------------------


def test_los_tokens_traen_la_empresa_y_conservan_roles_y_permisos(client_por_peticion, cuentas):
    respuesta = _login(client_por_peticion, "ana@example.com")
    cuerpo = respuesta.json()
    assert cuerpo["token_type"] == "bearer"
    acceso = decodificar_token(cuerpo["access_token"], tipo="access")
    refresco = decodificar_token(cuerpo["refresh_token"], tipo="refresh")
    assert acceso["empresa_id"] == refresco["empresa_id"] == 1
    assert acceso["roles"] == ["administrador"]
    assert "usuarios.gestionar" in acceso["permisos"]
    assert "plataforma.gestionar" not in acceso["permisos"]


def test_refrescar_emite_tokens_con_la_empresa_de_la_fila(client_por_peticion, cuentas):
    refresco = _login(client_por_peticion, "ana@example.com").json()["refresh_token"]
    nuevo = client_por_peticion.post("/api/v1/auth/refresh", json={"refresh_token": refresco})
    assert nuevo.status_code == 200
    assert decodificar_token(nuevo.json()["access_token"], tipo="access")["empresa_id"] == 1


# ---- el mismo correo en dos empresas ------------------------------------------


def test_el_mismo_correo_en_dos_empresas_entra_a_la_suya(client_por_peticion, db_session, dos_empresas):
    a, b = dos_empresas.a, dos_empresas.b
    _crear_usuario(db_session, a.id, "comun@example.com", password="claveDeLaTiendaA1")
    _crear_usuario(db_session, b.id, "comun@example.com", password="claveDeLaTiendaB2")

    en_a = _login(client_por_peticion, "comun@example.com", "claveDeLaTiendaA1", empresa=a.codigo)
    en_b = _login(client_por_peticion, "comun@example.com", "claveDeLaTiendaB2", empresa=b.codigo)
    assert en_a.status_code == en_b.status_code == 200
    assert decodificar_token(en_a.json()["access_token"])["empresa_id"] == a.id
    assert decodificar_token(en_b.json()["access_token"])["empresa_id"] == b.id
    # La clave de una no sirve en la otra.
    assert _login(client_por_peticion, "comun@example.com", "claveDeLaTiendaA1", empresa=b.codigo).status_code == 401
    assert _login(client_por_peticion, "comun@example.com", "claveDeLaTiendaB2", empresa=a.codigo).status_code == 401


def test_el_token_de_una_empresa_solo_ve_sus_datos(client_por_peticion, dos_empresas):
    a, b = dos_empresas.a, dos_empresas.b
    entrada = _login(client_por_peticion, f"admin@{a.codigo}.example.com", empresa=a.codigo)
    correos = {u["email"] for u in client_por_peticion.get("/api/v1/usuarios", headers=_con_token(entrada)).json()}
    assert correos == {f"admin@{a.codigo}.example.com"}
    assert f"admin@{b.codigo}.example.com" not in correos


# ---- los 9 casos que no deben distinguirse (4.7) --------------------------------


def _preparar_casos(db):
    """Las cuentas que los 9 casos necesitan; devuelve los datos de la petición."""
    a_id = crear_empresa(db, "tienda-a").id
    b_id = crear_empresa(db, "tienda-b").id
    baja_id = crear_empresa(db, "tienda-baja").id
    _crear_usuario(db, a_id, "ana@example.com")
    _crear_usuario(db, a_id, "baja@example.com", activo=False)
    _crear_usuario(db, b_id, "belen@example.com")
    _crear_usuario(db, baja_id, "olga@example.com")
    db.get(Empresa, baja_id).activo = False
    db.commit()
    crear_superadmin_de_prueba(db, "super@plataforma.example.com")


CASOS = {
    "empresa inexistente": ("no-existe", "ana@example.com", CLAVE),
    "empresa inactiva": ("tienda-baja", "olga@example.com", CLAVE),
    "correo inexistente en esa empresa": ("tienda-a", "nadie@example.com", CLAVE),
    "correo de otra empresa": ("tienda-a", "belen@example.com", CLAVE),
    "contraseña incorrecta": ("tienda-a", "ana@example.com", "claveIncorrecta99"),
    "usuario inactivo": ("tienda-a", "baja@example.com", CLAVE),
    "empresa omitida con correo de empresa": (None, "ana@example.com", CLAVE),
    "empresa con correo de superadministrador": ("tienda-a", "super@plataforma.example.com", CLAVE),
    "nombre que normaliza a vacío": ("!!!", "ana@example.com", CLAVE),
}


def test_los_nueve_casos_responden_igual_y_corren_bcrypt(client_por_peticion, db_session, monkeypatch):
    _preparar_casos(db_session)
    llamadas = []
    original = cu01.verificar_password
    monkeypatch.setattr(cu01, "verificar_password", lambda *a, **k: (llamadas.append(1), original(*a, **k))[1])

    respuestas = {}
    for caso, (empresa, correo, clave) in CASOS.items():
        antes = len(llamadas)
        r = _login(client_por_peticion, correo, clave, empresa=empresa)
        respuestas[caso] = (r.status_code, r.json())
        assert len(llamadas) - antes == 1, f"bcrypt no corrió exactamente una vez en: {caso}"

    assert all(r == (401, INVALIDAS) for r in respuestas.values()), respuestas


def test_los_controles_del_caso_ok_si_entran(client_por_peticion, db_session):
    """Contra falsos negativos: con los datos correctos las mismas cuentas SÍ entran."""
    _preparar_casos(db_session)
    assert _login(client_por_peticion, "ana@example.com", empresa="tienda-a").status_code == 200
    assert _login(client_por_peticion, "belen@example.com", empresa="Tienda B").status_code == 200
    assert _login(client_por_peticion, "super@plataforma.example.com", empresa=None).status_code == 200


# ---- empresa inactiva -----------------------------------------------------------


def test_desactivar_la_empresa_corta_los_tokens_ya_emitidos(client_por_peticion, db_session, cuentas):
    entrada = _login(client_por_peticion, "ana@example.com")
    cabeceras = _con_token(entrada)
    assert client_por_peticion.get("/api/v1/auth/yo", headers=cabeceras).status_code == 200

    empresa = db_session.get(Empresa, 1)
    empresa.activo = False
    db_session.commit()

    assert client_por_peticion.get("/api/v1/auth/yo", headers=cabeceras).status_code == 401
    refresco = entrada.json()["refresh_token"]
    assert client_por_peticion.post("/api/v1/auth/refresh", json={"refresh_token": refresco}).status_code == 401
    assert _login(client_por_peticion, "ana@example.com").status_code == 401


# ---- superadministrador -----------------------------------------------------------


def test_login_de_superadministrador_sin_empresa(client_por_peticion, db_session):
    crear_superadmin_de_prueba(db_session)
    bien = _login(client_por_peticion, "super@plataforma.example.com", empresa=None)
    assert bien.status_code == 200
    assert decodificar_token(bien.json()["access_token"], tipo="access")["empresa_id"] is None
    assert _login(client_por_peticion, "super@plataforma.example.com", "otraClave12345", empresa=None).status_code == 401


def test_un_usuario_de_empresa_no_entra_por_la_via_sin_empresa(client_por_peticion, cuentas):
    r = _login(client_por_peticion, "ana@example.com", empresa=None)
    assert (r.status_code, r.json()) == (401, INVALIDAS)


# ---- bloqueo por cuenta -------------------------------------------------------------


def test_cinco_fallos_bloquean_la_cuenta_con_retry_after(client_por_peticion, cuentas):
    for _ in range(5):
        assert _login(client_por_peticion, "ana@example.com", "claveIncorrecta99").status_code == 401
    bloqueada = _login(client_por_peticion, "ana@example.com")  # ya con la clave buena
    assert bloqueada.status_code == 429
    assert bloqueada.json() == {"detail": "Demasiados intentos. Intente nuevamente mas tarde."}
    assert 1 <= int(bloqueada.headers["Retry-After"]) <= 900


def test_una_cuenta_que_no_existe_tambien_se_bloquea(client_por_peticion, cuentas):
    for _ in range(5):
        assert _login(client_por_peticion, "fantasma@example.com", "claveIncorrecta99").status_code == 401
    r = _login(client_por_peticion, "fantasma@example.com", "claveIncorrecta99")
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_el_bloqueo_no_pasa_a_otra_empresa_con_el_mismo_correo(client_por_peticion, db_session, dos_empresas):
    a, b = dos_empresas.a, dos_empresas.b
    _crear_usuario(db_session, b.id, "comun@example.com")
    for _ in range(5):
        _login(client_por_peticion, "comun@example.com", "claveIncorrecta99", empresa=a.codigo)
    assert _login(client_por_peticion, "comun@example.com", "claveIncorrecta99", empresa=a.codigo).status_code == 429
    assert _login(client_por_peticion, "comun@example.com", empresa=b.codigo).status_code == 200


def test_pasada_la_ventana_vuelve_a_permitir(client_por_peticion, cuentas, monkeypatch):
    reloj = {"ahora": 1000.0}
    monkeypatch.setattr(limitador_intentos, "_reloj", lambda: reloj["ahora"])
    for _ in range(5):
        _login(client_por_peticion, "ana@example.com", "claveIncorrecta99")
    assert _login(client_por_peticion, "ana@example.com").status_code == 429
    reloj["ahora"] += 899
    assert _login(client_por_peticion, "ana@example.com").status_code == 429
    reloj["ahora"] += 2  # ya salió el fallo más viejo de la ventana de 900 s
    assert _login(client_por_peticion, "ana@example.com").status_code == 200


def test_un_acierto_limpia_el_contador(client_por_peticion, cuentas):
    for _ in range(4):
        _login(client_por_peticion, "ana@example.com", "claveIncorrecta99")
    assert _login(client_por_peticion, "ana@example.com").status_code == 200
    # Con el contador en cero, otros 4 fallos todavía no bloquean.
    for _ in range(4):
        assert _login(client_por_peticion, "ana@example.com", "claveIncorrecta99").status_code == 401
    assert _login(client_por_peticion, "ana@example.com").status_code == 200


def test_el_limitador_acota_su_memoria():
    limitador = type(limitador_intentos)(max_claves=3)
    for i in range(10):
        limitador.registrar_fallo(f"clave-{i}")
    assert len(limitador._fallos) == 3
    assert list(limitador._fallos) == ["clave-7", "clave-8", "clave-9"]


# ---- límite por IP -----------------------------------------------------------------


def test_el_login_once_en_un_minuto_responde_429_por_ip(client_por_peticion, cuentas):
    estados = [_login(client_por_peticion, f"intento{i}@example.com", "claveIncorrecta99").status_code for i in range(11)]
    assert estados[:10] == [401] * 10
    assert estados[10] == 429


# ---- correo en minúsculas ------------------------------------------------------------


def test_el_correo_no_distingue_mayusculas(client_por_peticion, cuentas):
    assert _login(client_por_peticion, "ANA@Example.COM").status_code == 200


def test_el_alta_guarda_el_correo_en_minusculas(db_session):
    datos = UsuarioCrear(nombre="Per", apellido="Sona", email="Mayus.Culas@Example.COM", password=CLAVE)
    assert datos.email == "mayus.culas@example.com"
    usuario = UsuarioRepository().crear(db_session, datos)
    assert db_session.get(Usuario, usuario.id).email == "mayus.culas@example.com"


def test_un_correo_antiguo_con_mayusculas_sigue_entrando(client_por_peticion, db_session):
    """Datos anteriores a que se guardara en minúsculas (sin migración)."""
    from app.core.security import hash_password

    db_session.add(Usuario(nombre="Vie", apellido="Jo", email="Viejo@Example.com", password_hash=hash_password(CLAVE)))
    db_session.commit()
    assert _login(client_por_peticion, "viejo@example.com").status_code == 200
