"""Hash de contraseñas, JWT y dependencias de autenticación/autorización.

Vive en `core` (así lo pide el plan de desarrollo), pero para resolver el
usuario/los permisos detrás de un JWT necesita al paquete `plataforma`
(dueño de esas tablas). En vez de consultar `usuario`/`rol_permiso`/
`usuario_rol` directamente, llama a `plataforma.politicas` -- mismo patrón
que CLAUDE.md pide entre los 4 paquetes de negocio ("llama a la política
del otro paquete, no consulta sus tablas"). El import es diferido (dentro
de cada función) porque `plataforma.repository` importa `core.security` a
nivel de módulo (para hash_password): con el import acá arriba, cargar
cualquiera de los dos módulos primero rompería con un ImportError
circular.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import PermisoDenegadoError
from app.core.tenant import empresa_de, fijar_empresa_de_usuario

settings = get_settings()

_bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _crear_token(
    usuario_id: int, tipo: str, expira: dt.timedelta, empresa_id: int | None, extra: dict | None = None
) -> str:
    # `empresa_id` va SIEMPRE en el token (None solo para el
    # superadministrador): por eso los tres crear_* lo piden como argumento
    # obligatorio y sin valor por defecto, para que un None accidental no cree
    # un token de plataforma.
    ahora = dt.datetime.now(dt.timezone.utc)
    payload: dict = {
        "sub": str(usuario_id),
        "tipo": tipo,
        "empresa_id": empresa_id,
        "iat": ahora,
        "exp": ahora + expira,
    }
    payload.update(extra or {})
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def crear_access_token(usuario_id: int, roles: list[str], permisos: list[str], *, empresa_id: int | None) -> str:
    """El payload lleva usuario_id, empresa_id, roles y permisos, nunca la contraseña."""
    return _crear_token(
        usuario_id,
        tipo="access",
        expira=dt.timedelta(minutes=settings.jwt_access_token_expire_minutes),
        empresa_id=empresa_id,
        extra={"roles": roles, "permisos": permisos},
    )


def crear_refresh_token(usuario_id: int, *, empresa_id: int | None) -> str:
    return _crear_token(
        usuario_id,
        tipo="refresh",
        expira=dt.timedelta(days=settings.jwt_refresh_token_expire_days),
        empresa_id=empresa_id,
    )


def huella_de_password(password_hash: str) -> str:
    """Primeros 16 hex del SHA-256 del hash vigente. Va en el token de
    recuperacion (claim `ph`): al cambiar la contrasena el hash cambia y el
    mismo token deja de servir (un solo uso, sin tabla nueva)."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def crear_reset_token(usuario_id: int, *, empresa_id: int | None, password_hash: str) -> str:
    return _crear_token(
        usuario_id,
        tipo="reset",
        expira=dt.timedelta(minutes=30),
        empresa_id=empresa_id,
        extra={"ph": huella_de_password(password_hash)},
    )


def decodificar_token(token: str, tipo: str | None = None) -> dict:
    """Decodifica y valida el JWT: firma, vencimiento (la claim `exp` es
    obligatoria: un token firmado sin vencimiento no se acepta) y, si se
    indica `tipo`, que sea de ese tipo (access/refresh/reset)."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado"
        ) from exc
    if tipo is not None and payload.get("tipo") != tipo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    # El claim tiene que EXISTIR (puede ser null: superadministrador). Asi los
    # tokens anteriores a esta exigencia dejan de valer de golpe.
    if "empresa_id" not in payload or not _empresa_id_valido(payload["empresa_id"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    return payload


def _empresa_id_valido(valor: object) -> bool:
    return valor is None or (isinstance(valor, int) and not isinstance(valor, bool))


def usuario_id_de_payload(payload: dict) -> int | None:
    """El id de usuario de la claim `sub`, o `None` si falta o no es numérico
    (el llamador lo traduce a 401 en vez de dejar escapar un ValueError)."""
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None


def permisos_de_usuario(db: Session, usuario_id: int) -> list[str]:
    """Códigos de permiso reales del usuario, vía sus roles activos. La
    consulta real vive en plataforma.politicas (dueño de esas tablas); acá
    solo se reexpone con el mismo nombre para no obligar a los demás
    paquetes a cambiar su import."""
    from app.plataforma import politicas as plataforma_politicas

    return plataforma_politicas.permisos_de_usuario(db, usuario_id)


def get_current_user(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    from app.plataforma import politicas as plataforma_politicas

    if credenciales is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    payload = decodificar_token(credenciales.credentials, tipo="access")
    usuario_id = usuario_id_de_payload(payload)
    if usuario_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    usuario = plataforma_politicas.obtener_usuario_para_auth(db, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inválido")

    # El tenant sale del claim del token y se cruza con la fila del usuario, y
    # la empresa tiene que seguir activa.
    if not plataforma_politicas.identidad_del_token_valida(db, payload, usuario):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    # Si la sesión ya trae empresa (la tienda de una ruta /public/{codigo}), el
    # usuario tiene que ser de esa misma empresa: el token de otra empresa no
    # vale ahí.
    actual = empresa_de(db)
    if actual is not None:
        if usuario.empresa_id != actual:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inválido")
    else:
        fijar_empresa_de_usuario(db, usuario)
    return usuario


def fijar_empresa_del_token(request: Request, db: Session) -> None:
    """Fija la empresa de la sesión a partir del token de la petición, si lo
    trae y es válido, aunque la ruta no exija autenticación. Sin esto, las
    rutas de catálogo que no piden usuario (las que el back office también
    llama, con su token) nunca sabrían la empresa. Un token ausente o inválido
    se ignora: lo que cada ruta exija lo decide su propia dependencia."""
    esquema, _, token = request.headers.get("authorization", "").partition(" ")
    if esquema.lower() != "bearer" or not token:
        return
    try:
        get_current_user(HTTPAuthorizationCredentials(scheme=esquema, credentials=token), db)
    except HTTPException:
        return


def get_current_user_opcional(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    """Igual que `get_current_user`, pero devuelve `None` en vez de 401 si no
    hay token o es inválido/expirado. Para endpoints públicos que igual
    quieren asociar la acción a un usuario logueado cuando lo hay (p. ej.
    POST /ia/voz, que admite búsqueda anónima)."""
    if credenciales is None:
        return None
    try:
        return get_current_user(credenciales, db)
    except HTTPException:
        return None


def require_permission(codigo: str):
    """Dependencia que exige el permiso `codigo`.

    Consulta rol_permiso/usuario_rol en cada request: el permiso vivo en la
    base es la fuente de verdad, no una lista fija ni lo que venga en el JWT.
    """

    def verificador(usuario=Depends(get_current_user), db: Session = Depends(get_db)):
        if codigo not in permisos_de_usuario(db, usuario.id):
            raise PermisoDenegadoError(f"Falta el permiso '{codigo}'")
        return usuario

    return verificador


def require_service_token(x_service_token: str | None = Header(default=None)) -> None:
    """Protege endpoints de tareas de sistema (cron/scheduler), que no
    tienen un usuario logueado detrás. No es un JWT: es un secreto fijo
    compartido, configurado por variable de entorno (TAREAS_TOKEN). Si no
    está configurado, la tarea queda inhabilitada (nunca compara contra
    una cadena vacía)."""
    if not settings.tareas_token or not x_service_token or not hmac.compare_digest(x_service_token, settings.tareas_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de servicio inválido")
