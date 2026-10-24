"""E06: los eventos de PLATAFORMA que dejan su fila en la bitácora (usuarios, roles,
sucursales, empleados, login, recuperación de contraseña y CU-04). Cada caso usa el
cliente HTTP, como la pantalla: comprueba el usuario, la empresa, el id de la
entidad, la IP y que `datos` no traiga nada sensible. Aparte, una operación que
falla (409, 404, 400) NO deja fila, y el caso de uso llamado sin contexto no
registra nada.

Usan `client_por_peticion` (sesión nueva por petición, como en producción),
`dos_empresas` (A 'tienda-a' Profesional, B 'tienda-b' Básico, cada una con su
administrador) y `superadmin_headers`. Los eventos de comercial y catálogo están
en su propio archivo."""

import datetime as dt
import json

import pytest
from sqlalchemy import select

from app.core.auditoria import ContextoAuditoria
from app.core.tenant import sin_filtro
from app.plataforma.casos_uso.cu02_gestionar_usuarios_roles_permisos import GestionarUsuarios
from app.plataforma.models import Empresa, Usuario
from app.plataforma.schemas import UsuarioCrear
from tests.ayudas_bitacora import exigir_datos_sin_sensibles, filas_de
from tests.plataforma.ayudas_empresas import CLAVE, CORREO_SUPERADMIN, PLATAFORMA, registrar, suscripciones_de

API = "/api/v1"
USUARIOS = f"{API}/usuarios"
ROLES = f"{API}/roles"
SUCURSALES = f"{API}/sucursales"
EMPLEADOS = f"{API}/empleados"
LOGIN = f"{API}/auth/login"
IP = "testclient"  # la IP que ve el cliente de pruebas de Starlette


# ---- Ayudas ----------------------------------------------------------------------------------


def _fila(db, entidad: str, accion: str, entidad_id: int | None = None, cantidad: int = 1):
    """La fila (única, o la última de `cantidad`) de esa entidad/acción."""
    filas = filas_de(db, entidad, accion)
    if entidad_id is not None:
        filas = [f for f in filas if f.entidad_id == entidad_id]
    assert len(filas) == cantidad, f"{entidad}/{accion}: {len(filas)} filas, se esperaban {cantidad}"
    return filas[-1]


def _revisar(fila, *, usuario_id, empresa_id, entidad_id, ip=IP) -> None:
    """Lo común a todos los eventos: quién, en qué empresa, sobre qué, desde dónde."""
    assert fila.usuario_id == usuario_id
    assert fila.empresa_id == empresa_id
    assert fila.entidad_id == entidad_id
    assert fila.ip == ip
    exigir_datos_sin_sensibles(fila)


def _todo_el_texto(fila) -> str:
    """Todas las columnas de la fila juntas, para comprobar que un texto NO aparece."""
    return json.dumps(
        [fila.empresa_id, fila.usuario_id, fila.entidad, fila.entidad_id, fila.accion, fila.datos, fila.ip],
        default=str,
    )


def _id_superadmin(db) -> int:
    return db.scalar(sin_filtro(select(Usuario.id).where(Usuario.email == CORREO_SUPERADMIN)))


def _usuario(client, headers, email="nuevo@example.com", **extra) -> dict:
    cuerpo = {"nombre": "Nu", "apellido": "Evo", "email": email, "password": CLAVE, "telefono": "70011223", **extra}
    respuesta = client.post(USUARIOS, json=cuerpo, headers=headers)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _ciudad(client, headers, nombre: str = "Ciudad de prueba") -> int:
    respuesta = client.post(f"{API}/ciudades", json={"nombre": nombre}, headers=headers)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _sucursal(client, headers, ciudad_id: int, codigo: str = "S-1"):
    return client.post(
        SUCURSALES,
        json={"ciudad_id": ciudad_id, "codigo": codigo, "nombre": f"Sucursal {codigo}", "direccion": "Av. Secreta 99"},
        headers=headers,
    )


def _rol(client, headers, nombre="auditor") -> dict:
    respuesta = client.post(ROLES, json={"nombre": nombre, "descripcion": "Solo lectura"}, headers=headers)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# ---- Usuarios ----------------------------------------------------------------------------------


def test_crear_usuario_deja_su_fila_sin_correo_ni_telefono(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    creado = _usuario(client_por_peticion, a.headers, "privado@example.com")

    fila = _fila(db_session, "usuario", "crear", creado["id"])

    _revisar(fila, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=creado["id"])
    assert fila.datos == {"reactivado": False}
    assert "privado@example.com" not in _todo_el_texto(fila) and "70011223" not in _todo_el_texto(fila)


def test_volver_a_crear_un_usuario_dado_de_baja_marca_reactivado(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    creado = _usuario(client_por_peticion, a.headers)
    assert client_por_peticion.delete(f"{USUARIOS}/{creado['id']}", headers=a.headers).status_code == 204

    nuevo = _usuario(client_por_peticion, a.headers)  # mismo correo: reactiva la fila

    assert nuevo["id"] == creado["id"]
    filas = filas_de(db_session, "usuario", "crear")
    assert [f.datos for f in filas] == [{"reactivado": False}, {"reactivado": True}]


def test_actualizar_usuario_guarda_solo_los_nombres_de_los_campos(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    creado = _usuario(client_por_peticion, a.headers)

    respuesta = client_por_peticion.put(
        f"{USUARIOS}/{creado['id']}", json={"telefono": "79998888", "nombre": "Otro"}, headers=a.headers
    )

    assert respuesta.status_code == 200
    fila = _fila(db_session, "usuario", "actualizar", creado["id"])
    _revisar(fila, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=creado["id"])
    assert sorted(fila.datos["campos"]) == ["nombre", "telefono"]
    assert "79998888" not in _todo_el_texto(fila) and "Otro" not in _todo_el_texto(fila)
    assert "antes" not in fila.datos  # ninguno de los dos campos es visible


def test_actualizar_activo_si_muestra_el_valor_antes_y_despues(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    creado = _usuario(client_por_peticion, a.headers)

    assert client_por_peticion.put(f"{USUARIOS}/{creado['id']}", json={"activo": False}, headers=a.headers).status_code == 200

    fila = _fila(db_session, "usuario", "actualizar", creado["id"])
    assert fila.datos == {"campos": ["activo"], "antes": {"activo": True}, "despues": {"activo": False}}


def test_desactivar_usuario(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    creado = _usuario(client_por_peticion, a.headers)

    assert client_por_peticion.delete(f"{USUARIOS}/{creado['id']}", headers=a.headers).status_code == 204

    fila = _fila(db_session, "usuario", "desactivar", creado["id"])
    _revisar(fila, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=creado["id"])
    assert fila.datos == {}


def test_asignar_roles_guarda_los_roles_de_antes_y_de_despues(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    creado = _usuario(client_por_peticion, a.headers)
    ruta = f"{USUARIOS}/{creado['id']}/roles"

    assert client_por_peticion.put(ruta, json={"nombres_rol": ["cliente", "cajero"]}, headers=a.headers).status_code == 200
    assert client_por_peticion.put(ruta, json={"nombres_rol": ["cajero"]}, headers=a.headers).status_code == 200

    primera, segunda = filas_de(db_session, "usuario", "asignar_roles")
    _revisar(primera, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=creado["id"])
    _revisar(segunda, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=creado["id"])
    assert primera.datos == {"antes": [], "despues": ["cajero", "cliente"]}
    assert segunda.datos == {"antes": ["cajero", "cliente"], "despues": ["cajero"]}


# ---- Roles y permisos (los escribe el superadministrador: la fila no tiene empresa) --------------


def test_crear_rol(client_por_peticion, db_session, superadmin_headers):
    rol = _rol(client_por_peticion, superadmin_headers)

    fila = _fila(db_session, "rol", "crear", rol["id"])

    _revisar(fila, usuario_id=_id_superadmin(db_session), empresa_id=None, entidad_id=rol["id"])
    assert fila.datos == {"nombre": "auditor"}


def test_actualizar_rol(client_por_peticion, db_session, superadmin_headers):
    rol = _rol(client_por_peticion, superadmin_headers)

    respuesta = client_por_peticion.put(f"{ROLES}/{rol['id']}", json={"descripcion": "Otra"}, headers=superadmin_headers)

    assert respuesta.status_code == 200
    fila = _fila(db_session, "rol", "actualizar", rol["id"])
    _revisar(fila, usuario_id=_id_superadmin(db_session), empresa_id=None, entidad_id=rol["id"])
    assert fila.datos == {"nombre": "auditor", "campos": ["descripcion"]}


def test_desactivar_rol(client_por_peticion, db_session, superadmin_headers):
    rol = _rol(client_por_peticion, superadmin_headers)

    assert client_por_peticion.delete(f"{ROLES}/{rol['id']}", headers=superadmin_headers).status_code == 204

    fila = _fila(db_session, "rol", "desactivar", rol["id"])
    _revisar(fila, usuario_id=_id_superadmin(db_session), empresa_id=None, entidad_id=rol["id"])
    assert fila.datos == {"nombre": "auditor"}


def test_asignar_permisos_guarda_agregados_y_quitados(client_por_peticion, db_session, superadmin_headers):
    rol = _rol(client_por_peticion, superadmin_headers)
    ruta = f"{ROLES}/{rol['id']}/permisos"

    cuerpo = {"codigos_permiso": ["reportes.ver", "usuarios.gestionar"]}
    assert client_por_peticion.put(ruta, json=cuerpo, headers=superadmin_headers).status_code == 200
    cuerpo = {"codigos_permiso": ["reportes.ver", "roles.gestionar"]}
    assert client_por_peticion.put(ruta, json=cuerpo, headers=superadmin_headers).status_code == 200

    primera, segunda = filas_de(db_session, "rol", "asignar_permisos")
    for fila in (primera, segunda):
        _revisar(fila, usuario_id=_id_superadmin(db_session), empresa_id=None, entidad_id=rol["id"])
    assert primera.datos == {"agregados": ["reportes.ver", "usuarios.gestionar"], "quitados": []}
    assert segunda.datos == {"agregados": ["roles.gestionar"], "quitados": ["usuarios.gestionar"]}


# ---- Sucursales y empleados -----------------------------------------------------------------------


def test_crear_sucursal_guarda_el_codigo_y_no_la_direccion(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    ciudad = _ciudad(client_por_peticion, a.headers)

    creada = _sucursal(client_por_peticion, a.headers, ciudad)

    assert creada.status_code == 201
    fila = _fila(db_session, "sucursal", "crear", creada.json()["id"])
    _revisar(fila, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=creada.json()["id"])
    assert fila.datos == {"codigo": "S-1"}
    assert "Av. Secreta" not in _todo_el_texto(fila)
    assert filas_de(db_session, "ciudad") == []  # las ciudades no se auditan


def test_actualizar_sucursal(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    sucursal = _sucursal(client_por_peticion, a.headers, _ciudad(client_por_peticion, a.headers)).json()

    respuesta = client_por_peticion.put(
        f"{SUCURSALES}/{sucursal['id']}", json={"nombre": "Renombrada", "direccion": "Calle Nueva 1"}, headers=a.headers
    )

    assert respuesta.status_code == 200
    fila = _fila(db_session, "sucursal", "actualizar", sucursal["id"])
    _revisar(fila, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=sucursal["id"])
    assert fila.datos["codigo"] == "S-1" and sorted(fila.datos["campos"]) == ["direccion", "nombre"]
    assert "Calle Nueva" not in _todo_el_texto(fila)


def test_desactivar_sucursal(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    sucursal = _sucursal(client_por_peticion, a.headers, _ciudad(client_por_peticion, a.headers)).json()

    assert client_por_peticion.delete(f"{SUCURSALES}/{sucursal['id']}", headers=a.headers).status_code == 204

    fila = _fila(db_session, "sucursal", "desactivar", sucursal["id"])
    _revisar(fila, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=sucursal["id"])
    assert fila.datos == {"codigo": "S-1"}


def _empleado(client, headers, db_session, *, codigo="S-1", email="empleado@example.com") -> tuple[dict, dict]:
    """(empleado, sucursal) recién creados por HTTP."""
    sucursal = _sucursal(client, headers, _ciudad(client, headers), codigo).json()
    usuario = _usuario(client, headers, email)
    respuesta = client.post(
        EMPLEADOS,
        json={"usuario_id": usuario["id"], "sucursal_id": sucursal["id"], "cargo": "Cajero", "ci": "1234567"},
        headers=headers,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json(), sucursal


def test_crear_empleado_guarda_ids_y_cargo_pero_no_el_ci(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a

    empleado, sucursal = _empleado(client_por_peticion, a.headers, db_session)

    fila = _fila(db_session, "empleado", "crear", empleado["id"])
    _revisar(fila, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=empleado["id"])
    assert fila.datos == {
        "usuario_id": empleado["usuario_id"], "sucursal_id_antes": None,
        "sucursal_id_despues": sucursal["id"], "cargo": "Cajero",
    }  # fmt: skip
    assert "1234567" not in _todo_el_texto(fila)


def test_actualizar_empleado_cambia_de_sucursal(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    empleado, primera = _empleado(client_por_peticion, a.headers, db_session)
    segunda = _sucursal(client_por_peticion, a.headers, _ciudad(client_por_peticion, a.headers, "Otra"), "S-2").json()

    respuesta = client_por_peticion.put(
        f"{EMPLEADOS}/{empleado['id']}", json={"sucursal_id": segunda["id"], "cargo": "Encargado"}, headers=a.headers
    )

    assert respuesta.status_code == 200
    fila = _fila(db_session, "empleado", "actualizar", empleado["id"])
    _revisar(fila, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=empleado["id"])
    assert fila.datos["usuario_id"] == empleado["usuario_id"]
    assert (fila.datos["sucursal_id_antes"], fila.datos["sucursal_id_despues"]) == (primera["id"], segunda["id"])
    assert fila.datos["cargo"] == "Encargado"
    assert sorted(fila.datos["campos"]) == ["cargo", "sucursal_id"]


def test_desactivar_empleado(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    empleado, sucursal = _empleado(client_por_peticion, a.headers, db_session)

    assert client_por_peticion.delete(f"{EMPLEADOS}/{empleado['id']}", headers=a.headers).status_code == 204

    fila = _fila(db_session, "empleado", "desactivar", empleado["id"])
    _revisar(fila, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=empleado["id"])
    assert fila.datos["sucursal_id_antes"] == fila.datos["sucursal_id_despues"] == sucursal["id"]


def test_volver_a_dar_de_alta_a_un_empleado_dado_de_baja_conserva_la_sucursal_anterior(
    client_por_peticion, db_session, dos_empresas
):
    a = dos_empresas.a
    empleado, primera = _empleado(client_por_peticion, a.headers, db_session)
    client_por_peticion.delete(f"{EMPLEADOS}/{empleado['id']}", headers=a.headers)
    segunda = _sucursal(client_por_peticion, a.headers, _ciudad(client_por_peticion, a.headers, "Otra"), "S-2").json()

    respuesta = client_por_peticion.post(
        EMPLEADOS, json={"usuario_id": empleado["usuario_id"], "sucursal_id": segunda["id"]}, headers=a.headers
    )

    assert respuesta.status_code == 201 and respuesta.json()["id"] == empleado["id"]  # reutiliza la fila
    ultima = filas_de(db_session, "empleado", "crear")[-1]
    assert (ultima.datos["sucursal_id_antes"], ultima.datos["sucursal_id_despues"]) == (primera["id"], segunda["id"])


# ---- Login y recuperación de contraseña -------------------------------------------------------------


def _entrar(client, empresa, correo, clave=CLAVE):
    cuerpo = {"email": correo, "password": clave}
    if empresa is not None:
        cuerpo["empresa"] = empresa
    return client.post(LOGIN, json=cuerpo)


CORREO_A = "admin@tienda-a.example.com"


def test_login_exitoso(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a

    assert _entrar(client_por_peticion, "tienda-a", CORREO_A).status_code == 200

    fila = _fila(db_session, "sesion", "login_exitoso")
    _revisar(fila, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=a.admin_id)
    assert fila.datos == {}
    assert CORREO_A not in _todo_el_texto(fila)


def test_login_exitoso_del_superadministrador_queda_sin_empresa(client_por_peticion, db_session):
    from tests.conftest import crear_superadmin_de_prueba

    superadmin = crear_superadmin_de_prueba(db_session, CORREO_SUPERADMIN, CLAVE)

    assert _entrar(client_por_peticion, None, CORREO_SUPERADMIN).status_code == 200

    fila = _fila(db_session, "sesion", "login_exitoso")
    _revisar(fila, usuario_id=superadmin, empresa_id=None, entidad_id=superadmin)


def test_refrescar_el_token_no_se_audita(client_por_peticion, db_session, dos_empresas):
    tokens = _entrar(client_por_peticion, "tienda-a", CORREO_A).json()

    respuesta = client_por_peticion.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert respuesta.status_code == 200
    assert len(filas_de(db_session, "sesion")) == 1  # solo el login


def test_login_fallido_con_contrasena_mala_deja_fila_y_la_respuesta_no_cambia(
    client_por_peticion, db_session, dos_empresas
):
    a = dos_empresas.a
    mala = _entrar(client_por_peticion, "tienda-a", CORREO_A, "claveEquivocada1")
    inexistente = _entrar(client_por_peticion, "tienda-a", "nadie@example.com", "claveEquivocada1")

    assert mala.status_code == inexistente.status_code == 401
    assert mala.json() == inexistente.json() == {"detail": "Credenciales inválidas"}
    de_la_cuenta, de_nadie = filas_de(db_session, "sesion", "login_fallido")
    # Contraseña mala: el usuario existe.
    _revisar(de_la_cuenta, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=a.admin_id)
    assert de_la_cuenta.datos == {"motivo": "credenciales"}
    # Usuario inexistente: sin usuario, pero con la empresa de la tienda.
    _revisar(de_nadie, usuario_id=None, empresa_id=a.id, entidad_id=None)
    assert de_nadie.datos == {"motivo": "credenciales"}
    for fila in (de_la_cuenta, de_nadie):
        assert CORREO_A not in _todo_el_texto(fila) and "nadie@example.com" not in _todo_el_texto(fila)
        assert "claveEquivocada1" not in _todo_el_texto(fila)


def test_login_fallido_con_empresa_inexistente_queda_sin_empresa(client_por_peticion, db_session, dos_empresas):
    respuesta = _entrar(client_por_peticion, "no-existe", CORREO_A)

    assert respuesta.status_code == 401 and respuesta.json() == {"detail": "Credenciales inválidas"}
    fila = _fila(db_session, "sesion", "login_fallido")
    _revisar(fila, usuario_id=None, empresa_id=None, entidad_id=None)
    assert fila.datos == {"motivo": "empresa_inexistente"}
    assert CORREO_A not in _todo_el_texto(fila)


def test_login_fallido_de_un_usuario_inactivo(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    creado = _usuario(client_por_peticion, a.headers, "baja@example.com")
    client_por_peticion.delete(f"{USUARIOS}/{creado['id']}", headers=a.headers)

    respuesta = _entrar(client_por_peticion, "tienda-a", "baja@example.com")

    assert respuesta.status_code == 401 and respuesta.json() == {"detail": "Credenciales inválidas"}
    fila = _fila(db_session, "sesion", "login_fallido")
    _revisar(fila, usuario_id=creado["id"], empresa_id=a.id, entidad_id=creado["id"])
    assert fila.datos == {"motivo": "usuario_inactivo"}
    assert "baja@example.com" not in _todo_el_texto(fila)


def test_un_intento_de_plataforma_con_credenciales_malas_queda_sin_empresa(client_por_peticion, db_session, superadmin_headers):
    superadmin = _id_superadmin(db_session)

    respuesta = _entrar(client_por_peticion, None, CORREO_SUPERADMIN, "claveEquivocada1")

    assert respuesta.status_code == 401
    fila = _fila(db_session, "sesion", "login_fallido")
    _revisar(fila, usuario_id=superadmin, empresa_id=None, entidad_id=superadmin)
    assert fila.datos == {"motivo": "credenciales"}


def test_el_bloqueo_por_demasiados_intentos_no_deja_fila(client_por_peticion, db_session, dos_empresas):
    respuestas = [_entrar(client_por_peticion, "tienda-a", CORREO_A, "claveEquivocada1") for _ in range(8)]

    codigos = [r.status_code for r in respuestas]
    assert 401 in codigos and 429 in codigos  # llegó el bloqueo
    assert codigos == sorted(codigos, key=lambda c: c == 429)  # primero 401, después solo 429
    assert len(filas_de(db_session, "sesion", "login_fallido")) == codigos.count(401)


def test_confirmar_la_recuperacion_de_contrasena(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    registro = client_por_peticion.post(
        f"{API}/public/tienda-a/registro",
        json={"nombre": "Cli", "apellido": "Ente", "email": "cliente@example.com", "password": CLAVE},
    )
    assert registro.status_code == 201
    cliente = registro.json()["id"]
    token = client_por_peticion.post(
        f"{API}/auth/recuperar", json={"empresa": "tienda-a", "email": "cliente@example.com"}
    ).json()["token_dev"]

    respuesta = client_por_peticion.post(
        f"{API}/auth/recuperar/confirmar", json={"token": token, "password": "nuevaClave456"}
    )

    assert respuesta.status_code == 200
    fila = _fila(db_session, "usuario", "contrasena_restablecida")
    _revisar(fila, usuario_id=cliente, empresa_id=a.id, entidad_id=cliente)
    assert fila.datos == {}
    assert token not in _todo_el_texto(fila) and "nuevaClave456" not in _todo_el_texto(fila)
    # Pedir el token no se audita; un token inválido tampoco deja fila.
    assert client_por_peticion.post(f"{API}/auth/recuperar/confirmar", json={"token": token, "password": "otraClave789"}).status_code == 401
    assert len(filas_de(db_session, "usuario", "contrasena_restablecida")) == 1


# ---- CU-04: empresas, planes y suscripciones (actor: el superadministrador) ---------------------------


def test_registrar_empresa_guarda_codigo_y_plan_sin_el_correo_del_administrador(
    client_por_peticion, db_session, superadmin_headers
):
    respuesta = registrar(client_por_peticion, superadmin_headers, "Boutique Nueva", "dueno@boutique.example.com")

    assert respuesta.status_code == 201, respuesta.text
    empresa_id = respuesta.json()["id"]
    fila = _fila(db_session, "empresa", "crear", empresa_id)
    _revisar(fila, usuario_id=_id_superadmin(db_session), empresa_id=empresa_id, entidad_id=empresa_id)
    assert fila.datos == {"codigo": "boutique-nueva", "plan": "basico"}
    assert "dueno@boutique.example.com" not in _todo_el_texto(fila)


def test_actualizar_y_desactivar_una_empresa(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    b = dos_empresas.b
    super_id = _id_superadmin(db_session)

    actualizada = client_por_peticion.put(f"{PLATAFORMA}/empresas/{b.id}", json={"nombre": "B Renombrada"}, headers=superadmin_headers)
    desactivada = client_por_peticion.delete(f"{PLATAFORMA}/empresas/{b.id}", headers=superadmin_headers)

    assert actualizada.status_code == 200 and desactivada.status_code == 204
    cambio = _fila(db_session, "empresa", "actualizar", b.id)
    _revisar(cambio, usuario_id=super_id, empresa_id=b.id, entidad_id=b.id)
    assert cambio.datos == {"campos": ["nombre"]}
    baja = _fila(db_session, "empresa", "desactivar", b.id)
    _revisar(baja, usuario_id=super_id, empresa_id=b.id, entidad_id=b.id)


def test_asignar_el_primer_plan_a_una_empresa(client_por_peticion, db_session, superadmin_headers):
    empresa = Empresa(nombre="Sin Plan", codigo="sin-plan")
    db_session.add(empresa)
    db_session.commit()

    respuesta = client_por_peticion.post(
        f"{PLATAFORMA}/suscripciones", json={"empresa_id": empresa.id, "plan_codigo": "profesional"}, headers=superadmin_headers
    )

    assert respuesta.status_code == 201
    suscripcion = respuesta.json()["id"]
    fila = _fila(db_session, "suscripcion", "asignar_plan", suscripcion)
    _revisar(fila, usuario_id=_id_superadmin(db_session), empresa_id=empresa.id, entidad_id=suscripcion)
    assert fila.datos == {"plan_despues": "profesional", "suscripcion_nueva_id": suscripcion}
    assert filas_de(db_session, "suscripcion", "cambiar_plan") == []


def test_cambiar_de_plan(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    b = dos_empresas.b

    respuesta = client_por_peticion.post(
        f"{PLATAFORMA}/suscripciones", json={"empresa_id": b.id, "plan_codigo": "profesional"}, headers=superadmin_headers
    )

    assert respuesta.status_code == 201
    nueva = respuesta.json()["id"]
    fila = _fila(db_session, "suscripcion", "cambiar_plan", nueva)
    _revisar(fila, usuario_id=_id_superadmin(db_session), empresa_id=b.id, entidad_id=nueva)
    assert fila.datos == {"plan_antes": "basico", "plan_despues": "profesional", "suscripcion_nueva_id": nueva}


def test_cambiar_el_estado_de_la_suscripcion(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    b = dos_empresas.b
    vigente = suscripciones_de(db_session, b.id)[0].id

    respuesta = client_por_peticion.put(
        f"{PLATAFORMA}/suscripciones/{vigente}/estado", json={"estado": "suspendida"}, headers=superadmin_headers
    )

    assert respuesta.status_code == 200
    fila = _fila(db_session, "suscripcion", "cambiar_estado", vigente)
    _revisar(fila, usuario_id=_id_superadmin(db_session), empresa_id=b.id, entidad_id=vigente)
    assert fila.datos == {"estado_antes": "activa", "estado_despues": "suspendida"}


def test_renovar_la_suscripcion(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    b = dos_empresas.b
    vigente = suscripciones_de(db_session, b.id)[0]
    antes = vigente.fecha_vencimiento
    nueva_fecha = dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=45)

    respuesta = client_por_peticion.put(
        f"{PLATAFORMA}/suscripciones/{vigente.id}/renovar", json={"fecha_vencimiento": nueva_fecha.isoformat()}, headers=superadmin_headers
    )

    assert respuesta.status_code == 200
    fila = _fila(db_session, "suscripcion", "renovar", vigente.id)
    _revisar(fila, usuario_id=_id_superadmin(db_session), empresa_id=b.id, entidad_id=vigente.id)
    assert fila.datos == {"vencimiento_antes": antes.isoformat(), "vencimiento_despues": nueva_fecha.isoformat()}


def _plan_de(client, headers, codigo: str) -> int:
    planes = client.get(f"{PLATAFORMA}/planes", headers=headers).json()
    return next(p["id"] for p in planes if p["codigo"] == codigo)


def test_actualizar_un_plan_no_tiene_empresa(client_por_peticion, db_session, superadmin_headers):
    plan_id = _plan_de(client_por_peticion, superadmin_headers, "basico")

    respuesta = client_por_peticion.put(
        f"{PLATAFORMA}/planes/{plan_id}", json={"max_sucursales": 5, "nombre": "Básico Plus"}, headers=superadmin_headers
    )

    assert respuesta.status_code == 200
    fila = _fila(db_session, "plan", "actualizar", plan_id)
    _revisar(fila, usuario_id=_id_superadmin(db_session), empresa_id=None, entidad_id=plan_id)
    assert fila.datos["codigo"] == "basico" and fila.datos["max_sucursales"] == 5
    assert sorted(fila.datos["campos"]) == ["max_sucursales", "nombre"]


def test_crear_y_desactivar_un_plan(client_por_peticion, db_session, superadmin_headers):
    creado = client_por_peticion.post(
        f"{PLATAFORMA}/planes", json={"codigo": "temporal", "nombre": "Temporal", "max_sucursales": 3}, headers=superadmin_headers
    )
    assert creado.status_code == 201
    plan_id = creado.json()["id"]
    assert client_por_peticion.delete(f"{PLATAFORMA}/planes/{plan_id}", headers=superadmin_headers).status_code == 204

    alta = _fila(db_session, "plan", "crear", plan_id)
    _revisar(alta, usuario_id=_id_superadmin(db_session), empresa_id=None, entidad_id=plan_id)
    assert alta.datos == {"codigo": "temporal", "max_sucursales": 3}
    baja = _fila(db_session, "plan", "desactivar", plan_id)
    assert baja.datos == {"codigo": "temporal"}


def test_el_administrador_edita_la_identidad_visual_de_su_empresa(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a

    respuesta = client_por_peticion.put(f"{API}/mi-empresa", json={"color_acento": "#336699"}, headers=a.headers)

    assert respuesta.status_code == 200
    fila = _fila(db_session, "empresa", "actualizar")
    _revisar(fila, usuario_id=a.admin_id, empresa_id=a.id, entidad_id=a.id)
    assert fila.datos == {"campos": ["color_acento"]}


def test_el_superadministrador_agrega_un_administrador_y_una_sucursal_a_una_empresa(
    client_por_peticion, db_session, dos_empresas, superadmin_headers
):
    b = dos_empresas.b
    ciudad = _ciudad(client_por_peticion, b.headers)

    usuario = client_por_peticion.post(
        f"{PLATAFORMA}/empresas/{b.id}/usuarios",
        json={"nombre": "Otro", "apellido": "Admin", "email": "otro@tienda-b.example.com", "password": CLAVE},
        headers=superadmin_headers,
    )
    sucursal = client_por_peticion.post(
        f"{PLATAFORMA}/empresas/{b.id}/sucursales",
        json={"ciudad_id": ciudad, "codigo": "B-1", "nombre": "B uno", "direccion": "Calle 1"},
        headers=superadmin_headers,
    )

    assert usuario.status_code == 201 and sucursal.status_code == 201
    super_id = _id_superadmin(db_session)
    fila_usuario = _fila(db_session, "usuario", "crear", usuario.json()["id"])
    _revisar(fila_usuario, usuario_id=super_id, empresa_id=b.id, entidad_id=usuario.json()["id"])
    assert fila_usuario.datos == {"reactivado": False, "rol": "administrador"}
    assert "otro@tienda-b.example.com" not in _todo_el_texto(fila_usuario)
    fila_sucursal = _fila(db_session, "sucursal", "crear", sucursal.json()["id"])
    _revisar(fila_sucursal, usuario_id=super_id, empresa_id=b.id, entidad_id=sucursal.json()["id"])
    assert fila_sucursal.datos == {"codigo": "B-1"}


# ---- Atomicidad: lo que falla no deja fila ---------------------------------------------------------------


def test_crear_una_sucursal_por_encima_del_limite_del_plan_no_deja_fila(client_por_peticion, db_session, dos_empresas):
    b = dos_empresas.b  # Básico: 2 sucursales activas
    ciudad = _ciudad(client_por_peticion, b.headers)
    for codigo in ("B-1", "B-2"):
        assert _sucursal(client_por_peticion, b.headers, ciudad, codigo).status_code == 201

    tercera = _sucursal(client_por_peticion, b.headers, ciudad, "B-3")

    assert tercera.status_code == 409 and tercera.json()["detail"] == "limite_plan_excedido"
    assert [f.datos["codigo"] for f in filas_de(db_session, "sucursal", "crear")] == ["B-1", "B-2"]


def test_asignar_un_rol_inexistente_no_deja_fila(client_por_peticion, db_session, dos_empresas):
    a = dos_empresas.a
    creado = _usuario(client_por_peticion, a.headers)

    respuesta = client_por_peticion.put(
        f"{USUARIOS}/{creado['id']}/roles", json={"nombres_rol": ["cajero", "no_existe"]}, headers=a.headers
    )

    assert respuesta.status_code == 400
    assert filas_de(db_session, "usuario", "asignar_roles") == []


def test_bajar_a_un_plan_con_menos_sucursales_de_las_usadas_no_deja_fila(
    client_por_peticion, db_session, dos_empresas, superadmin_headers
):
    a = dos_empresas.a  # Profesional con 3 sucursales activas; Básico permite 2
    ciudad = _ciudad(client_por_peticion, a.headers)
    for codigo in ("A-1", "A-2", "A-3"):
        assert _sucursal(client_por_peticion, a.headers, ciudad, codigo).status_code == 201

    respuesta = client_por_peticion.post(
        f"{PLATAFORMA}/suscripciones", json={"empresa_id": a.id, "plan_codigo": "basico"}, headers=superadmin_headers
    )

    assert respuesta.status_code == 409 and respuesta.json()["detail"] == "limite_plan_excedido"
    assert filas_de(db_session, "suscripcion") == []


def test_otras_operaciones_rechazadas_no_dejan_fila(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    a, b = dos_empresas.a, dos_empresas.b
    _usuario(client_por_peticion, a.headers, "repetido@example.com")
    vigente = suscripciones_de(db_session, b.id)[0].id
    manana = (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=1)).isoformat()
    antes = len(filas_de(db_session))

    duplicado = client_por_peticion.post(
        USUARIOS,
        json={"nombre": "X", "apellido": "Y", "email": "repetido@example.com", "password": CLAVE},
        headers=a.headers,
    )
    inexistente = client_por_peticion.delete(f"{USUARIOS}/999999", headers=a.headers)
    mismo_plan = client_por_peticion.post(
        f"{PLATAFORMA}/suscripciones", json={"empresa_id": b.id, "plan_codigo": "basico"}, headers=superadmin_headers
    )
    transicion_invalida = client_por_peticion.put(
        f"{PLATAFORMA}/suscripciones/{vigente}/estado", json={"estado": "activa"}, headers=superadmin_headers
    )  # activa -> activa no es una transición
    renovar_inexistente = client_por_peticion.put(
        f"{PLATAFORMA}/suscripciones/999999/renovar", json={"fecha_vencimiento": manana}, headers=superadmin_headers
    )
    empleado_sin_usuario = client_por_peticion.post(EMPLEADOS, json={"usuario_id": 999999}, headers=a.headers)

    assert duplicado.status_code == 409
    assert inexistente.status_code == 404
    assert mismo_plan.status_code == 409
    assert transicion_invalida.status_code == 409
    assert renovar_inexistente.status_code == 404
    assert empleado_sin_usuario.status_code == 404
    assert len(filas_de(db_session)) == antes  # ninguna de las seis dejó fila


# ---- Sin contexto no se registra nada ----------------------------------------------------------------------


def test_un_caso_de_uso_llamado_sin_contexto_no_registra_y_con_contexto_si(db_session):
    datos = UsuarioCrear(nombre="Di", apellido="Recto", email="directo@example.com", password=CLAVE)

    GestionarUsuarios().crear(db_session, datos)
    assert filas_de(db_session) == []

    otros = UsuarioCrear(nombre="Con", apellido="Texto", email="contexto@example.com", password=CLAVE)
    contexto = ContextoAuditoria(usuario_id=None, empresa_id=None, ip="9.9.9.9")
    creado = GestionarUsuarios().crear(db_session, otros, contexto)

    fila = _fila(db_session, "usuario", "crear", creado.id)
    assert fila.ip == "9.9.9.9" and fila.datos == {"reactivado": False}


@pytest.mark.parametrize("entidad", ["ciudad", "horario"])
def test_ciudades_y_horarios_no_se_auditan(client_por_peticion, db_session, dos_empresas, entidad):
    a = dos_empresas.a
    ciudad = _ciudad(client_por_peticion, a.headers)
    sucursal = _sucursal(client_por_peticion, a.headers, ciudad).json()
    horario = client_por_peticion.post(
        f"{SUCURSALES}/{sucursal['id']}/horarios",
        json={"dia_semana": 1, "hora_apertura": "09:00:00", "hora_cierre": "18:00:00"},
        headers=a.headers,
    )
    assert horario.status_code == 201, horario.text

    assert filas_de(db_session, entidad) == []
