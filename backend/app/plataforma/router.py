from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import ParametrosPaginacion, parametros_paginacion
from app.core.permisos import PERMISO_ORGANIZACION, PERMISO_ROLES, PERMISO_USUARIOS
from app.core.rate_limit import limiter
from app.core.security import get_current_user, permisos_de_usuario, require_permission
from app.plataforma.casos_uso.cu01_autenticar_registrar_usuarios import (
    IniciarSesion,
    RecuperarContrasena,
    RegistrarCliente,
)
from app.plataforma.casos_uso.cu02_gestionar_usuarios_roles_permisos import (
    GestionarRolesPermisos,
    GestionarUsuarios,
)
from app.plataforma.casos_uso.cu03_gestionar_organizacion import (
    GestionarCiudades,
    GestionarEmpleados,
    GestionarSucursales,
)
from app.plataforma import politicas
from app.plataforma.politicas import obtener_usuario
from app.plataforma.schemas import (
    AsignarPermisosRequest,
    AsignarRolesRequest,
    CiudadActualizar,
    CiudadCrear,
    CiudadRespuesta,
    ClientePerfilActualizar,
    ClientePerfilRespuesta,
    EmpleadoActualizar,
    EmpleadoCrear,
    EmpleadoRespuesta,
    HorarioActualizar,
    HorarioCrear,
    HorarioRespuesta,
    LoginRequest,
    NotificacionRespuesta,
    PermisoRespuesta,
    RecuperarConfirmarRequest,
    RecuperarRequest,
    RecuperarRespuesta,
    RefreshRequest,
    RegistroRequest,
    RolActualizar,
    RolCrear,
    RolRespuesta,
    SucursalActualizar,
    SucursalCrear,
    SucursalRespuesta,
    TokenRespuesta,
    UsuarioActualizar,
    UsuarioCrear,
    UsuarioRespuesta,
    UsuarioYoRespuesta,
)


# ---- Seguridad ----


cu_registrar_cliente = RegistrarCliente()
cu_iniciar_sesion = IniciarSesion()
cu_gestionar_usuarios = GestionarUsuarios()
cu_gestionar_roles = GestionarRolesPermisos()
cu_recuperar_contrasena = RecuperarContrasena()

# ---- /api/v1/auth -----------------------------------------------------------

auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# `registro` y `login` son los dos endpoints públicos más atacables del
# sistema (creación masiva de cuentas y fuerza bruta de contraseñas), y el
# RNF02 pide límite de tráfico en los endpoints públicos. Agravante propio
# de `login`: bcrypt hace cada intento caro en CPU, así que sin límite es
# también un vector de agotamiento de recursos.
# `request: Request` no se usa en el cuerpo pero es obligatorio: slowapi lo
# necesita en la firma para resolver la IP del cliente (mismo motivo que en
# `recuperar`, más abajo).
@auth_router.post("/registro", response_model=UsuarioRespuesta, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def registro(request: Request, datos: RegistroRequest, db: Session = Depends(get_db)) -> UsuarioRespuesta:
    usuario = cu_registrar_cliente.registrar(db, datos)
    return UsuarioRespuesta.from_modelo(usuario)


@auth_router.post("/login", response_model=TokenRespuesta)
@limiter.limit("10/minute")
def login(request: Request, datos: LoginRequest, db: Session = Depends(get_db)) -> TokenRespuesta:
    return cu_iniciar_sesion.ejecutar(db, datos)


@auth_router.post("/refresh", response_model=TokenRespuesta)
def refresh(datos: RefreshRequest, db: Session = Depends(get_db)) -> TokenRespuesta:
    return cu_iniciar_sesion.refrescar(db, datos.refresh_token)


@auth_router.get("/yo", response_model=UsuarioYoRespuesta)
def yo(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> UsuarioYoRespuesta:
    base = UsuarioRespuesta.from_modelo(usuario)
    return UsuarioYoRespuesta(**base.model_dump(), permisos=permisos_de_usuario(db, usuario.id))


@auth_router.post("/recuperar", response_model=RecuperarRespuesta, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
def recuperar(request: Request, datos: RecuperarRequest, db: Session = Depends(get_db)) -> RecuperarRespuesta:
    token = cu_recuperar_contrasena.solicitar(db, datos.email)
    token_dev = token if get_settings().environment == "local" else None
    return RecuperarRespuesta(
        detail="Si el correo está registrado, se enviarán instrucciones de recuperación.",
        token_dev=token_dev,
    )


@auth_router.post("/recuperar/confirmar", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
def recuperar_confirmar(
    request: Request, datos: RecuperarConfirmarRequest, db: Session = Depends(get_db)
) -> dict[str, str]:
    cu_recuperar_contrasena.confirmar(db, datos.token, datos.password)
    return {"detail": "Contraseña actualizada."}


# ---- /api/v1/roles -----------------------------------------------------------

roles_router = APIRouter(prefix="/api/v1/roles", tags=["roles"])


@roles_router.get("", response_model=list[RolRespuesta], dependencies=[Depends(require_permission(PERMISO_ROLES))])
def listar_roles(
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion),
) -> list[RolRespuesta]:
    return cu_gestionar_roles.listar(db, paginacion)


@roles_router.get("/{rol_id}", response_model=RolRespuesta, dependencies=[Depends(require_permission(PERMISO_ROLES))])
def obtener_rol(rol_id: int, db: Session = Depends(get_db)) -> RolRespuesta:
    return cu_gestionar_roles.obtener(db, rol_id)


@roles_router.post(
    "", response_model=RolRespuesta, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(PERMISO_ROLES))],
)
def crear_rol(datos: RolCrear, db: Session = Depends(get_db)) -> RolRespuesta:
    return cu_gestionar_roles.crear(db, datos)


@roles_router.put("/{rol_id}", response_model=RolRespuesta, dependencies=[Depends(require_permission(PERMISO_ROLES))])
def actualizar_rol(rol_id: int, datos: RolActualizar, db: Session = Depends(get_db)) -> RolRespuesta:
    return cu_gestionar_roles.actualizar(db, rol_id, datos)


@roles_router.delete(
    "/{rol_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(PERMISO_ROLES))],
)
def desactivar_rol(rol_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_roles.desactivar(db, rol_id)


@roles_router.put(
    "/{rol_id}/permisos", response_model=RolRespuesta,
    dependencies=[Depends(require_permission(PERMISO_ROLES))],
)
def asignar_permisos(
    rol_id: int, datos: AsignarPermisosRequest, db: Session = Depends(get_db)
) -> RolRespuesta:
    return cu_gestionar_roles.asignar_permisos(db, rol_id, datos.codigos_permiso)


# ---- /api/v1/permisos --------------------------------------------------------
# Router propio y no GET /roles/permisos: ese path chocaría con
# /roles/{rol_id}, que ya existe, y quedaría dependiendo del orden en que se
# declaran las rutas.

permisos_router = APIRouter(prefix="/api/v1/permisos", tags=["permisos"])


@permisos_router.get(
    "", response_model=list[PermisoRespuesta],
    dependencies=[Depends(require_permission(PERMISO_ROLES))],
)
def listar_permisos(db: Session = Depends(get_db)) -> list[PermisoRespuesta]:
    """El catálogo de permisos que se pueden asignar a un rol. Lo consume la
    pantalla de roles para pintar las casillas (RF03). Mismo permiso que
    exige asignar_permisos: quien no puede asignarlos tampoco necesita verlos."""
    return [PermisoRespuesta.model_validate(p) for p in cu_gestionar_roles.listar_permisos(db)]


# ---- /api/v1/usuarios --------------------------------------------------------

usuarios_router = APIRouter(prefix="/api/v1/usuarios", tags=["usuarios"])


@usuarios_router.get(
    "", response_model=list[UsuarioRespuesta],
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def listar_usuarios(
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion),
) -> list[UsuarioRespuesta]:
    usuarios = cu_gestionar_usuarios.listar(db, paginacion)
    return [UsuarioRespuesta.from_modelo(u) for u in usuarios]


@usuarios_router.get(
    "/{usuario_id}", response_model=UsuarioRespuesta,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def obtener_usuario_endpoint(usuario_id: int, db: Session = Depends(get_db)) -> UsuarioRespuesta:
    return UsuarioRespuesta.from_modelo(obtener_usuario(db, usuario_id))


@usuarios_router.post(
    "", response_model=UsuarioRespuesta, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def crear_usuario(datos: UsuarioCrear, db: Session = Depends(get_db)) -> UsuarioRespuesta:
    return UsuarioRespuesta.from_modelo(cu_gestionar_usuarios.crear(db, datos))


@usuarios_router.put(
    "/{usuario_id}", response_model=UsuarioRespuesta,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def actualizar_usuario(
    usuario_id: int, datos: UsuarioActualizar, db: Session = Depends(get_db)
) -> UsuarioRespuesta:
    return UsuarioRespuesta.from_modelo(cu_gestionar_usuarios.actualizar(db, usuario_id, datos))


@usuarios_router.delete(
    "/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def desactivar_usuario(usuario_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_usuarios.desactivar(db, usuario_id)


@usuarios_router.put(
    "/{usuario_id}/roles", response_model=UsuarioRespuesta,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def asignar_roles(
    usuario_id: int, datos: AsignarRolesRequest, db: Session = Depends(get_db)
) -> UsuarioRespuesta:
    return UsuarioRespuesta.from_modelo(cu_gestionar_usuarios.asignar_roles(db, usuario_id, datos.nombres_rol))


# ---- /api/v1/clientes/perfil --------------------------------------------------

clientes_router = APIRouter(prefix="/api/v1/clientes", tags=["clientes"])


@clientes_router.get("/perfil", response_model=ClientePerfilRespuesta)
def obtener_perfil(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> ClientePerfilRespuesta:
    cliente = cu_registrar_cliente.obtener_perfil(db, usuario.id)
    return ClientePerfilRespuesta.from_modelo(cliente)


@clientes_router.put("/perfil", response_model=ClientePerfilRespuesta)
def actualizar_perfil(
    datos: ClientePerfilActualizar, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ClientePerfilRespuesta:
    cliente = cu_registrar_cliente.actualizar_perfil(db, usuario.id, datos)
    return ClientePerfilRespuesta.from_modelo(cliente)


# ---- /api/v1/notificaciones ---------------------------------------------------

notificaciones_router = APIRouter(prefix="/api/v1/notificaciones", tags=["notificaciones"])


@notificaciones_router.get("", response_model=list[NotificacionRespuesta])
def listar_notificaciones(
    usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[NotificacionRespuesta]:
    return list(politicas.listar_notificaciones(db, usuario.id))


@notificaciones_router.put("/{notificacion_id}/leida", response_model=NotificacionRespuesta)
def marcar_leida(
    notificacion_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> NotificacionRespuesta:
    return politicas.marcar_leida(db, usuario.id, notificacion_id)


# ---- Organización ----


admin_requerido = Depends(require_permission(PERMISO_ORGANIZACION))

cu_gestionar_ciudades = GestionarCiudades()
cu_gestionar_sucursales = GestionarSucursales()
cu_gestionar_empleados = GestionarEmpleados()

# ---- /api/v1/ciudades ---------------------------------------------------

ciudades_router = APIRouter(prefix="/api/v1/ciudades", tags=["ciudades"], dependencies=[admin_requerido])


@ciudades_router.get("", response_model=list[CiudadRespuesta])
def listar_ciudades(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[CiudadRespuesta]:
    return cu_gestionar_ciudades.listar(db, paginacion)


@ciudades_router.get("/{ciudad_id}", response_model=CiudadRespuesta)
def obtener_ciudad(ciudad_id: int, db: Session = Depends(get_db)) -> CiudadRespuesta:
    return cu_gestionar_ciudades.obtener(db, ciudad_id)


@ciudades_router.post("", response_model=CiudadRespuesta, status_code=status.HTTP_201_CREATED)
def crear_ciudad(datos: CiudadCrear, db: Session = Depends(get_db)) -> CiudadRespuesta:
    return cu_gestionar_ciudades.crear(db, datos)


@ciudades_router.put("/{ciudad_id}", response_model=CiudadRespuesta)
def actualizar_ciudad(ciudad_id: int, datos: CiudadActualizar, db: Session = Depends(get_db)) -> CiudadRespuesta:
    return cu_gestionar_ciudades.actualizar(db, ciudad_id, datos)


@ciudades_router.delete("/{ciudad_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_ciudad(ciudad_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_ciudades.desactivar(db, ciudad_id)


# ---- /api/v1/sucursales ---------------------------------------------------
# GET es público (lo consume el catálogo). SucursalRespuesta nunca incluye
# datos de empleados: no existe ese campo en el schema ni una relación en
# el modelo que lo permita.

sucursales_router = APIRouter(prefix="/api/v1/sucursales", tags=["sucursales"])


@sucursales_router.get("", response_model=list[SucursalRespuesta])
def listar_sucursales(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[SucursalRespuesta]:
    return cu_gestionar_sucursales.listar(db, paginacion)


@sucursales_router.get("/{sucursal_id}", response_model=SucursalRespuesta)
def obtener_sucursal(sucursal_id: int, db: Session = Depends(get_db)) -> SucursalRespuesta:
    return cu_gestionar_sucursales.obtener(db, sucursal_id)


@sucursales_router.post(
    "", response_model=SucursalRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido]
)
def crear_sucursal(datos: SucursalCrear, db: Session = Depends(get_db)) -> SucursalRespuesta:
    return cu_gestionar_sucursales.crear(db, datos)


@sucursales_router.put(
    "/{sucursal_id}", response_model=SucursalRespuesta, dependencies=[admin_requerido]
)
def actualizar_sucursal(
    sucursal_id: int, datos: SucursalActualizar, db: Session = Depends(get_db)
) -> SucursalRespuesta:
    return cu_gestionar_sucursales.actualizar(db, sucursal_id, datos)


@sucursales_router.delete(
    "/{sucursal_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido]
)
def desactivar_sucursal(sucursal_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_sucursales.desactivar(db, sucursal_id)


# ---- /api/v1/sucursales/{id}/horarios --------------------------------------
# GET es público: el horario de atención lo necesita el cliente (Flutter,
# al elegir franja para una reserva) tanto como el back office. Escribir
# horarios sigue siendo solo de administración.

horarios_router = APIRouter(prefix="/api/v1/sucursales/{sucursal_id}/horarios", tags=["horarios"])


@horarios_router.get("", response_model=list[HorarioRespuesta])
def listar_horarios(sucursal_id: int, db: Session = Depends(get_db)) -> list[HorarioRespuesta]:
    return cu_gestionar_sucursales.listar_horarios(db, sucursal_id)


@horarios_router.post(
    "", response_model=HorarioRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido]
)
def crear_horario(sucursal_id: int, datos: HorarioCrear, db: Session = Depends(get_db)) -> HorarioRespuesta:
    return cu_gestionar_sucursales.crear_horario(db, sucursal_id, datos)


@horarios_router.put("/{horario_id}", response_model=HorarioRespuesta, dependencies=[admin_requerido])
def actualizar_horario(
    sucursal_id: int, horario_id: int, datos: HorarioActualizar, db: Session = Depends(get_db)
) -> HorarioRespuesta:
    return cu_gestionar_sucursales.actualizar_horario(db, sucursal_id, horario_id, datos)


@horarios_router.delete("/{horario_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido])
def eliminar_horario(sucursal_id: int, horario_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_sucursales.eliminar_horario(db, sucursal_id, horario_id)


# ---- /api/v1/empleados ---------------------------------------------------
# Sin dependencies=[admin_requerido] a nivel de router (a diferencia de los
# otros): /empleados/yo lo llama cualquier empleado logueado (p. ej. la caja
# en Angular, para saber su propia sucursal), el resto sigue siendo de
# administración.

empleados_router = APIRouter(prefix="/api/v1/empleados", tags=["empleados"])


@empleados_router.get("/yo", response_model=EmpleadoRespuesta)
def obtener_mi_empleado(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> EmpleadoRespuesta:
    return cu_gestionar_empleados.obtener_mi_empleado(db, usuario.id)


@empleados_router.get("", response_model=list[EmpleadoRespuesta], dependencies=[admin_requerido])
def listar_empleados(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[EmpleadoRespuesta]:
    return cu_gestionar_empleados.listar(db, paginacion)


@empleados_router.get("/{empleado_id}", response_model=EmpleadoRespuesta, dependencies=[admin_requerido])
def obtener_empleado(empleado_id: int, db: Session = Depends(get_db)) -> EmpleadoRespuesta:
    return cu_gestionar_empleados.obtener(db, empleado_id)


@empleados_router.post("", response_model=EmpleadoRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido])
def crear_empleado(datos: EmpleadoCrear, db: Session = Depends(get_db)) -> EmpleadoRespuesta:
    return cu_gestionar_empleados.crear(db, datos)


@empleados_router.put("/{empleado_id}", response_model=EmpleadoRespuesta, dependencies=[admin_requerido])
def actualizar_empleado(
    empleado_id: int, datos: EmpleadoActualizar, db: Session = Depends(get_db)
) -> EmpleadoRespuesta:
    return cu_gestionar_empleados.actualizar(db, empleado_id, datos)


@empleados_router.delete("/{empleado_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido])
def desactivar_empleado(empleado_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_empleados.desactivar(db, empleado_id)


# ---- /api/v1/public/{codigo} (tienda pública por empresa) --------------------------
# Los MISMOS handlers públicos de sucursales y horarios, bajo el código de la
# tienda (D02, D10). La empresa la fija `contexto_empresa` (core/tenant.py) desde
# el código de la ruta; `_codigo_tienda` solo documenta el parámetro en OpenAPI.
# No se copian handlers. (El registro público por empresa lo agrega la E03.)


def _codigo_tienda(codigo: str) -> str:
    return codigo


publico_tienda_router = APIRouter(
    prefix="/api/v1/public/{codigo}", tags=["tienda-publica"], dependencies=[Depends(_codigo_tienda)]
)

for _ruta, _handler, _modelo in (
    ("/sucursales", listar_sucursales, list[SucursalRespuesta]),
    ("/sucursales/{sucursal_id}", obtener_sucursal, SucursalRespuesta),
    ("/sucursales/{sucursal_id}/horarios", listar_horarios, list[HorarioRespuesta]),
):
    publico_tienda_router.add_api_route(_ruta, _handler, methods=["GET"], response_model=_modelo)


routers = [
    auth_router,
    roles_router,
    permisos_router,
    usuarios_router,
    clientes_router,
    notificaciones_router,
    ciudades_router,
    sucursales_router,
    horarios_router,
    empleados_router,
    publico_tienda_router,
]
