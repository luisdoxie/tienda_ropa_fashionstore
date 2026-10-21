"""CU-01 — Autenticar y registrar usuarios

Absorbe los antiguos CU-01 (Registrar cliente), CU-02 (Iniciar sesión) y
CU-35 (Recuperar contraseña).

Actor: Cliente, Administrador, Encargado de sucursal, Cajero, Proveedor.
Precondición: ninguna (accesible sin sesión) para el alta, el inicio de
sesión y la recuperación de contraseña; sesión propia para consultar o editar
el perfil. Para iniciar sesión, el usuario existe y está activo.
Postcondición: existe un usuario con rol cliente y su perfil (Cliente); se
emiten access_token y refresh_token con los roles y permisos vigentes; si el
email está registrado se emite un token de recuperación y, al confirmarlo con
una contraseña nueva, el hash se actualiza.

Caso de uso COMPUESTO: agrupa el alta del cliente (y la gestión de su propio
perfil), el inicio de sesión (con el refresco del token) y la recuperación de
contraseña. Cada clase es un controlador del caso de uso."""

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NoAutenticadoError
from app.core.tenant import fijar_empresa_de_usuario
from app.core.security import (
    crear_access_token,
    crear_refresh_token,
    crear_reset_token,
    decodificar_token,
    usuario_id_de_payload,
    verificar_password,
)
from app.plataforma.models import Cliente, Usuario
from app.plataforma.politicas import obtener_perfil_cliente, obtener_usuario_para_auth, permisos_de_usuario
from app.plataforma.repository import ClienteRepository, UsuarioRepository
from app.plataforma.schemas import (
    ClientePerfilActualizar,
    LoginRequest,
    RegistroRequest,
    TokenRespuesta,
    UsuarioCrear,
)

logger = logging.getLogger(__name__)

ROL_CLIENTE = "cliente"

# Hash bcrypt fijo (de un password que no le pertenece a nadie) para que
# ejecutar() siempre corra verificar_password() con costo real, exista o no
# el email: sin esto, el cortocircuito de `or` se salta bcrypt.checkpw()
# cuando el usuario no existe, y ese ida-y-vuelta más rápido deja adivinar
# por tiempo de respuesta qué emails están registrados.
_HASH_DUMMY = "$2b$12$d1ru1mgPSWsBsc/AHIyMHeWrDeAVeESRlnXjY52JXjnR/XOLoWB22"


# ---- Registrar cliente (antiguo CU-01: Registrar cliente) ----


class RegistrarCliente:
    def __init__(self) -> None:
        self._usuarios = UsuarioRepository()
        self._clientes = ClienteRepository()

    def registrar(self, db: Session, datos: RegistroRequest) -> Usuario:
        # Usuario + rol + perfil de cliente son UNA unidad de trabajo: un solo
        # commit al final. Si falta el rol "cliente" (o cualquier paso falla)
        # se revierte todo, sin dejar un usuario huérfano sin perfil ni rol.
        try:
            usuario = self._usuarios.crear(
                db,
                UsuarioCrear(
                    nombre=datos.nombre,
                    apellido=datos.apellido,
                    email=datos.email,
                    telefono=datos.telefono,
                    password=datos.password,
                ),
                commit=False,
            )
            self._usuarios.asignar_roles(db, usuario, [ROL_CLIENTE], commit=False)
            self._clientes.crear_o_actualizar_perfil(db, usuario.id, datos.ci_nit, commit=False)
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(usuario)
        return usuario

    def obtener_perfil(self, db: Session, usuario_id: int) -> Cliente:
        return obtener_perfil_cliente(db, usuario_id)

    def actualizar_perfil(
        self, db: Session, usuario_id: int, datos: ClientePerfilActualizar
    ) -> Cliente:
        return self._clientes.actualizar_perfil(db, usuario_id, datos)


# ---- Iniciar sesión (antiguo CU-02: Iniciar sesión) ----


class IniciarSesion:
    """Incluye también refrescar el token (mismo flujo de autenticación, no un
    CU aparte del catálogo)."""

    def __init__(self) -> None:
        self._usuarios = UsuarioRepository()

    def _emitir_tokens(self, db: Session, usuario: Usuario) -> TokenRespuesta:
        roles = [r.nombre for r in usuario.roles]
        permisos = permisos_de_usuario(db, usuario.id)
        return TokenRespuesta(
            access_token=crear_access_token(usuario.id, roles, permisos),
            refresh_token=crear_refresh_token(usuario.id),
        )

    def ejecutar(self, db: Session, datos: LoginRequest) -> TokenRespuesta:
        usuario = self._usuarios.obtener_por_email_sin_empresa(db, datos.email)
        hash_a_verificar = usuario.password_hash if usuario is not None else _HASH_DUMMY
        password_valida = verificar_password(datos.password, hash_a_verificar)
        credenciales_invalidas = usuario is None or not usuario.activo or not password_valida
        if credenciales_invalidas:
            raise NoAutenticadoError("Credenciales inválidas")

        # Desde acá la sesión trabaja en la empresa del usuario.
        fijar_empresa_de_usuario(db, usuario)
        usuario.ultimo_acceso = dt.datetime.now(dt.timezone.utc)
        db.commit()

        return self._emitir_tokens(db, usuario)

    def refrescar(self, db: Session, refresh_token: str) -> TokenRespuesta:
        payload = decodificar_token(refresh_token, tipo="refresh")
        usuario_id = usuario_id_de_payload(payload)
        if usuario_id is None:
            raise NoAutenticadoError("Token inválido")

        usuario = obtener_usuario_para_auth(db, usuario_id)
        if usuario is None:
            raise NoAutenticadoError("Usuario inválido")

        fijar_empresa_de_usuario(db, usuario)
        return self._emitir_tokens(db, usuario)


# ---- Recuperar contraseña (antiguo CU-35: Recuperar contraseña) ----


class RecuperarContrasena:
    def __init__(self) -> None:
        self._usuarios = UsuarioRepository()

    def solicitar(self, db: Session, email: str) -> str | None:
        """Genera un token de recuperación si el email existe.

        Todavía no hay un servicio de correo en el proyecto, así que el token
        se deja en el log para pruebas manuales, y se devuelve acá para que
        el router lo incluya en la respuesta solo en entorno local (ver
        `RecuperarRespuesta.token_dev`). La respuesta al cliente es siempre
        genérica en cuanto al mensaje (ver router) para no revelar si el
        email está registrado.
        """
        usuario = self._usuarios.obtener_por_email_sin_empresa(db, email)
        if usuario is None or not usuario.activo:
            return None

        token = crear_reset_token(usuario.id)
        if get_settings().environment == "local":  # mismo criterio que token_dev en el router
            logger.info("Token de recuperación para %s: %s", email, token)
        return token

    def confirmar(self, db: Session, token: str, password: str) -> None:
        payload = decodificar_token(token, tipo="reset")
        usuario_id = usuario_id_de_payload(payload)
        usuario = obtener_usuario_para_auth(db, usuario_id) if usuario_id is not None else None
        if usuario is None:
            raise NoAutenticadoError("Token inválido")

        fijar_empresa_de_usuario(db, usuario)
        self._usuarios.actualizar_password(db, usuario, password)
