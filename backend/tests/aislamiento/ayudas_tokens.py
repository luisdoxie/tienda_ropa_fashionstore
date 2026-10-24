"""E05, 4.5 y 4.6: ayudas compartidas por `test_tokens_y_superadmin.py`, `test_publico.py` y
`test_reportes_y_vistas.py`. No son pruebas.

- tokens a medida (sin `empresa_id`, de otra empresa, firmados con otra clave, adulterados);
- empresas descartables (propias de estas pruebas): se crean con `tests.conftest.crear_empresa`,
  se usan y se dan de baja, para no tocar a A ni a B (el universo es compartido por el paquete);
- el superadministrador (un solo login por corrida);
- armado de rutas con ids (reales de A o inexistentes).
"""

from __future__ import annotations

import base64
import datetime as dt
import itertools
import json
from contextlib import contextmanager

import jwt
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.security import crear_access_token, permisos_de_usuario
from app.core.tenant import fijar_empresa, sin_filtro
from app.plataforma.models import Empresa, Suscripcion, Usuario
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.conftest import EmpresaDePrueba, crear_empresa, crear_superadmin_de_prueba, token_de

from .oraculo import ID_INEXISTENTE, parametros_de
from .plantillas import PARAMETROS
from .rutas_esperadas import RUTAS

API = "/api/v1"
CLAVE = "claveSegura123"
CLAVE_AJENA = "una-clave-que-no-es-la-del-servidor-0123456789"
CORREO_SUPER = "super-e05@plataforma.example.com"

CLASES_NO_AUTENTICADAS = {"PUBLICA", "AUTH", "PASARELA", "SERVICIO"}
CLASES_DE_NEGOCIO = {"POR_ID", "LISTADO", "CREA_O_ACCION", "PROPIA", "MI_EMPRESA"}

_settings = get_settings()
_contador = itertools.count(1)


# --- las rutas ------------------------------------------------------------------------------


def rutas_de(clases: set[str]) -> list[tuple[str, str]]:
    return sorted(clave for clave, ruta in RUTAS.items() if ruta.clase in clases)


def nombre_corto(clave: tuple[str, str]) -> str:
    return f"{clave[0]} {clave[1].removeprefix(API)}"


def armar_ruta(ruta: str, universo=None, *, inexistente: bool = False, codigo: str | None = None) -> str:
    """Rellena los parámetros de la ruta: con ids reales de `universo` o, si `inexistente`
    (o la ruta no tiene recurso en el universo), con un id que no existe en ninguna empresa."""
    for nombre in parametros_de(ruta):
        if nombre == "codigo":
            valor = codigo or (universo.codigo if universo else "tienda-a")
        elif nombre == "pasarela":
            valor = "libelula"
        elif nombre == "id_transaccion":
            valor = universo.ids["id_transaccion"] if universo and not inexistente else "TXN-INEXISTENTE"
        elif not inexistente and universo is not None and nombre in PARAMETROS:
            valor = universo.ids[PARAMETROS[nombre]]
        else:
            valor = ID_INEXISTENTE
        ruta = ruta.replace("{" + nombre + "}", str(valor))
    return ruta


# --- tokens a medida --------------------------------------------------------------------------


def _payload(usuario_id: int, *, empresa_id, con_empresa: bool = True, roles=(), permisos=(), tipo: str = "access") -> dict:
    ahora = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(usuario_id),
        "tipo": tipo,
        "iat": ahora,
        "exp": ahora + dt.timedelta(minutes=30),
        "roles": list(roles),
        "permisos": list(permisos),
    }
    if con_empresa:
        payload["empresa_id"] = empresa_id
    return payload


def _cabecera(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def datos_del_usuario(mundo, universo) -> tuple[list[str], list[str]]:
    """Roles y permisos reales del administrador de `universo` (para armar tokens creíbles)."""
    with mundo.sesiones() as db:
        fijar_empresa(db, universo.id)
        usuario = db.scalar(select(Usuario).where(Usuario.id == universo.empresa.admin_id))
        return [r.nombre for r in usuario.roles], permisos_de_usuario(db, usuario.id)


def token_sin_empresa_id(usuario_id: int, roles, permisos) -> dict:
    """Firmado con la clave buena pero SIN la clave `empresa_id` (un token anterior a E03)."""
    payload = _payload(usuario_id, empresa_id=None, con_empresa=False, roles=roles, permisos=permisos)
    return _cabecera(jwt.encode(payload, _settings.jwt_secret_key, algorithm=_settings.jwt_algorithm))


def token_con_empresa_ajena(usuario_id: int, empresa_ajena_id: int, roles, permisos) -> dict:
    """Usuario de una empresa con el `empresa_id` de OTRA en el token (firmado bien)."""
    return _cabecera(crear_access_token(usuario_id, list(roles), list(permisos), empresa_id=empresa_ajena_id))


def token_con_otra_clave(usuario_id: int, empresa_id: int, roles, permisos) -> dict:
    """Todo correcto, pero firmado con una clave que no es la del servidor."""
    payload = _payload(usuario_id, empresa_id=empresa_id, roles=roles, permisos=permisos)
    return _cabecera(jwt.encode(payload, CLAVE_AJENA, algorithm=_settings.jwt_algorithm))


def token_adulterado(token_valido: dict, empresa_ajena_id: int) -> dict:
    """Toma un token válido y le cambia el `empresa_id` del cuerpo SIN volver a firmar."""
    cabecera, cuerpo, firma = token_valido["Authorization"].removeprefix("Bearer ").split(".")
    relleno = "=" * (-len(cuerpo) % 4)
    datos = json.loads(base64.urlsafe_b64decode(cuerpo + relleno))
    datos["empresa_id"] = empresa_ajena_id
    nuevo = base64.urlsafe_b64encode(json.dumps(datos).encode()).decode().rstrip("=")
    return _cabecera(f"{cabecera}.{nuevo}.{firma}")


# --- empresas descartables --------------------------------------------------------------------


def crear_descartable(mundo, *, plan: str = "profesional", con_admin: bool = False) -> EmpresaDePrueba:
    """Una empresa propia de estas pruebas ('desc-e05-N'), con su suscripción activa y, si se
    pide, un administrador (con token). Hay que darla de baja con `retirar_descartable`."""
    codigo = f"desc-e05-{next(_contador)}"
    with mundo.sesiones() as db:
        empresa = crear_empresa(db, codigo, plan=plan)
        admin_id, headers = 0, {}
        if con_admin:
            fijar_empresa(db, empresa.id)
            repo = UsuarioRepository()
            admin = repo.crear(
                db, UsuarioCrear(nombre="Admin", apellido="Descartable", email="admin@descartable.bo", password=CLAVE)
            )
            repo.asignar_roles(db, admin, ["administrador"])
            admin_id, headers = admin.id, token_de(db, admin)
        return EmpresaDePrueba(id=empresa.id, codigo=codigo, admin_id=admin_id, headers=headers)


def retirar_descartable(mundo, empresa: EmpresaDePrueba) -> None:
    """La da de baja (activo = falso): deja de aparecer en /public/tiendas y no estorba a otras pruebas."""
    with mundo.sesiones() as db:
        db.execute(update(Empresa).where(Empresa.id == empresa.id).values(activo=False))
        db.commit()


@contextmanager
def empresa_descartable(mundo, *, plan: str = "profesional", con_admin: bool = False):
    empresa = crear_descartable(mundo, plan=plan, con_admin=con_admin)
    try:
        yield empresa
    finally:
        retirar_descartable(mundo, empresa)


def poner_estado_suscripcion(mundo, empresa_id: int, estado: str) -> None:
    """Cambia el estado de la suscripción vigente de una empresa DESCARTABLE (nunca de A ni de B)."""
    with mundo.sesiones() as db:
        db.execute(
            sin_filtro(
                update(Suscripcion).where(Suscripcion.empresa_id == empresa_id, Suscripcion.estado != "cancelada").values(estado=estado)
            ),
            execution_options={"synchronize_session": False},
        )
        db.commit()


def poner_activa_empresa(mundo, empresa_id: int, activo: bool) -> None:
    with mundo.sesiones() as db:
        db.execute(update(Empresa).where(Empresa.id == empresa_id).values(activo=activo))
        db.commit()


# --- el superadministrador ----------------------------------------------------------------------

_SUPER: dict = {}


def cabecera_superadmin(mundo) -> dict:
    """El token del superadministrador de estas pruebas, obtenido con UN login real (sin `empresa`)
    por corrida: más intentos chocarían con el límite de tráfico de /auth/login."""
    if "headers" not in _SUPER:
        with mundo.sesiones() as db:
            _SUPER["id"] = crear_superadmin_de_prueba(db, CORREO_SUPER, CLAVE)
        respuesta = mundo.client.post(f"{API}/auth/login", json={"email": CORREO_SUPER, "password": CLAVE})
        assert respuesta.status_code == 200, f"login del superadministrador: {respuesta.status_code} {respuesta.text}"
        _SUPER["headers"] = _cabecera(respuesta.json()["access_token"])
    return _SUPER["headers"]


# --- varios ----------------------------------------------------------------------------------------


def hay_marca(texto: str) -> bool:
    """Si el texto trae alguna marca de las empresas del universo (MARCA-A- o MARCA-B-)."""
    return "MARCA-" in texto
