"""Funciones que plataforma expone a sus propias secciones (Seguridad y
Organización), a los demás paquetes y a core.security, sin ser casos de uso
del catálogo: consultas y validaciones sobre las tablas de este paquete, para
que nadie más tenga que tocarlas directamente."""

import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError, NoEncontradoError, PermisoDenegadoError
from app.core.permisos import PERMISO_ALCANCE_GLOBAL, ROL_SUPERADMINISTRADOR
from app.core.tenant import sin_filtro
from app.plataforma.models import (
    Ciudad,
    Cliente,
    Empleado,
    Empresa,
    HorarioSucursal,
    Notificacion,
    Permiso,
    Rol,
    Sucursal,
    Usuario,
    rol_permiso,
    usuario_rol,
)
from app.plataforma.repository import (
    CiudadRepository,
    ClienteRepository,
    EmpleadoRepository,
    HorarioRepository,
    NotificacionRepository,
    SucursalRepository,
    UsuarioRepository,
)


# ---- Seguridad ----


usuario_repo = UsuarioRepository()
cliente_repo = ClienteRepository()


def permisos_de_usuario(db: Session, usuario_id: int) -> list[str]:
    """Códigos de permiso reales del usuario, vía sus roles activos. Vive
    acá (no en core.security) porque es una consulta de negocio sobre las
    tablas propias de este paquete; core.security la reexpone con el mismo
    nombre para el resto de los paquetes, que siguen sin tener que
    consultar rol_permiso/usuario_rol/permiso directamente."""
    filas = db.execute(
        select(Permiso.codigo)
        .join(rol_permiso, rol_permiso.c.permiso_id == Permiso.id)
        .join(Rol, Rol.id == rol_permiso.c.rol_id)
        .join(usuario_rol, usuario_rol.c.rol_id == Rol.id)
        .where(usuario_rol.c.usuario_id == usuario_id, Rol.activo.is_(True))
        .distinct()
    ).scalars()
    return list(filas)


def identidad_del_token_valida(db: Session, payload: dict, usuario: Usuario) -> bool:
    """El tenant sale del claim `empresa_id` del token y se cruza con la fila
    del usuario: ni el claim basta solo, ni la base sin claim. Con empresa,
    ademas tiene que seguir activa (desactivarla deja sin acceso a todos sus
    tokens ya emitidos). Para get_current_user y el refresco del token."""
    if payload.get("empresa_id") != usuario.empresa_id:
        return False
    return usuario.empresa_id is None or empresa_esta_activa(db, usuario.empresa_id)


def obtener_usuario_para_auth(db: Session, usuario_id: int) -> Usuario | None:
    """Para core.security (get_current_user/get_current_user_opcional):
    resuelve el usuario del JWT sin que core tenga que hacer `db.get(Usuario,
    ...)` directamente. Devuelve None (no una excepción) si no existe o está
    inactivo -- decidir si eso es un 401 le corresponde a quien llama."""
    # Todavía no se sabe la empresa (de aquí sale): único caso, junto con el
    # login, en que se consulta un usuario sin filtro de empresa.
    usuario = db.scalar(sin_filtro(select(Usuario).where(Usuario.id == usuario_id)))
    if usuario is None or not usuario.activo:
        return None
    return usuario


def validar_roles_asignables(empresa_id: int | None, nombres_rol: list[str] | set[str]) -> None:
    """El rol superadministrador solo se asigna a usuarios sin empresa
    (`empresa_id` NULL), y un usuario sin empresa solo puede tener ese rol.
    Quien lo intente (p. ej. un administrador de empresa) recibe 403."""
    nombres = set(nombres_rol)
    if empresa_id is not None and ROL_SUPERADMINISTRADOR in nombres:
        raise PermisoDenegadoError("Rol no asignable")
    if empresa_id is None and nombres - {ROL_SUPERADMINISTRADOR}:
        raise PermisoDenegadoError("Rol no asignable")


# ---- Empresa ----

_LONGITUD_CODIGO_EMPRESA = 60


def normalizar_nombre_empresa(nombre: str) -> str:
    """El nombre de una empresa tal como se compara con `empresa.codigo`: sin
    tildes ni la tilde de la n (NFKD), en minusculas, con toda secuencia de
    caracteres que no sean a-z0-9 convertida en un solo guion y sin guiones en
    los extremos. 'Boutique Andina' -> 'boutique-andina'. Vacio si no queda
    nada (se trata como credenciales invalidas). Maximo 60 caracteres, la
    longitud de `empresa.codigo`; E04 la reutiliza para generar el codigo."""
    sin_marcas = "".join(c for c in unicodedata.normalize("NFKD", nombre) if not unicodedata.combining(c))
    guionado = re.sub(r"[^a-z0-9]+", "-", sin_marcas.lower()).strip("-")
    return guionado[:_LONGITUD_CODIGO_EMPRESA].strip("-")


def empresa_esta_activa(db: Session, empresa_id: int) -> bool:
    """Si la empresa existe y esta activa. `empresa` no es una tabla de empresa
    (es la raiz), asi que se consulta por clave primaria sin filtro."""
    return bool(db.scalar(select(Empresa.activo).where(Empresa.id == empresa_id)))


def obtener_empresa_por_codigo(db: Session, codigo: str) -> Empresa | None:
    """La empresa cuyo `codigo` (inmutable, ver D04) coincide, o None. Para la
    dependencia `core.tenant.empresa_publica` (rutas /public/{codigo}); decidir
    si una empresa inactiva cuenta como inexistente le toca a quien llama."""
    return db.scalar(select(Empresa).where(Empresa.codigo == codigo.strip().lower()))


def obtener_empresa(db: Session, empresa_id: int) -> Empresa | None:
    """La empresa con esa clave primaria, o None. `empresa` es la raiz y no una
    tabla de empresa: no lleva filtro. Para /auth/yo (codigo y nombre de la
    empresa del usuario)."""
    return db.get(Empresa, empresa_id)


def listar_empresas_activas(db: Session) -> list[int]:
    """Ids de las empresas activas, para las tareas que corren por empresa
    (expirar reservas y ventas pendientes)."""
    return list(db.scalars(select(Empresa.id).where(Empresa.activo.is_(True)).order_by(Empresa.id)))


def obtener_usuario(db: Session, usuario_id: int) -> Usuario:
    """Punto de entrada para que la sección Organización (p. ej. al crear un
    empleado) valide un usuario sin consultar la tabla directamente."""
    return usuario_repo.obtener(db, usuario_id)


def obtener_usuarios_por_ids(db: Session, ids: list[int]) -> dict[int, Usuario]:
    """Para que la sección Organización (p. ej. al listar empleados)
    resuelva nombres de usuario en lote sin consultar la tabla
    directamente."""
    return {u.id: u for u in usuario_repo.listar_por_ids(db, ids)}


def obtener_perfil_cliente(db: Session, usuario_id: int) -> Cliente:
    """Para que los demás paquetes (catalogo, comercial, inteligencia) resuelvan
    el Cliente de un usuario logueado sin
    consultar la tabla `cliente` directamente."""
    return cliente_repo.obtener_por_usuario(db, usuario_id)


def obtener_cliente(db: Session, cliente_id: int) -> Cliente:
    """Para que `comercial` (p. ej. reservas, para notificar al dueño
    de una reserva) resuelva el usuario_id de un cliente sin consultar
    la tabla `cliente` directamente."""
    return cliente_repo.obtener(db, cliente_id)


# ---- Notificaciones ----


notificacion_repo = NotificacionRepository()


def crear_notificacion(
    db: Session,
    usuario_id: int,
    titulo: str,
    mensaje: str | None = None,
    tipo: str | None = None,
    referencia_id: int | None = None,
    commit: bool = True,
) -> Notificacion:
    """`commit=False`: ver el comentario en catalogo.politicas.actualizar_stock_operacion
    (lo usa ReservarPrendas, que notifica a varios empleados
    como parte de la misma transacción)."""
    notificacion = notificacion_repo.crear(db, usuario_id, titulo, mensaje, tipo, referencia_id)
    if commit:
        db.commit()
        db.refresh(notificacion)
    return notificacion


def listar_notificaciones(db: Session, usuario_id: int) -> list[Notificacion]:
    return notificacion_repo.listar_por_usuario(db, usuario_id)


def marcar_leida(db: Session, usuario_id: int, notificacion_id: int) -> Notificacion:
    return notificacion_repo.marcar_leida(db, usuario_id, notificacion_id)


# ---- Organización ----


ciudad_repo = CiudadRepository()
sucursal_repo = SucursalRepository()
horario_repo = HorarioRepository()
empleado_repo = EmpleadoRepository()

# Quien administra sucursales y empleados (hoy solo el administrador) opera
# y consulta todas las sucursales; el resto del personal (encargado, cajero)
# solo la de su ficha de empleado. Es el mismo permiso que ya tiene el
# administrador, así el alcance global no depende de volver a correr seeds.
# (La constante vive en core.permisos y se sigue importando desde acá.)


def sucursal_asignada(db: Session, usuario_id: int) -> int | None:
    """Sucursal a la que está limitado el usuario, o None si tiene alcance
    global. Sin alcance global y sin ficha de empleado activa con sucursal,
    no puede operar ninguna (PermisoDenegadoError)."""
    if PERMISO_ALCANCE_GLOBAL in permisos_de_usuario(db, usuario_id):
        return None
    empleado = empleado_repo.obtener_por_usuario(db, usuario_id)
    if empleado is None or not empleado.activo or empleado.sucursal_id is None:
        raise PermisoDenegadoError("No tenés una sucursal asignada")
    return empleado.sucursal_id


def validar_acceso_sucursal(db: Session, usuario_id: int, sucursal_id: int) -> None:
    """Para las operaciones de personal sobre una sucursal concreta (vender,
    cobrar, devolver, atender reservas, mover inventario): lanza
    PermisoDenegadoError si el usuario está limitado a otra sucursal."""
    propia = sucursal_asignada(db, usuario_id)
    if propia is not None and propia != sucursal_id:
        raise PermisoDenegadoError("No tenés acceso a esa sucursal")


def acotar_sucursal(db: Session, usuario_id: int, sucursal_id: int | None) -> int | None:
    """Para consultas de personal con filtro de sucursal opcional
    (inventario, reportes): con alcance global devuelve el filtro pedido
    (None = todas); si no, siempre la sucursal propia (403 si pidió otra)."""
    propia = sucursal_asignada(db, usuario_id)
    if propia is None:
        if sucursal_id is not None and sucursal_repo.buscar(db, sucursal_id) is None:
            # Un id de otra empresa responde igual que uno inexistente (404).
            # `buscar` no filtra por `activo`: se pueden consultar los datos
            # históricos de una sucursal dada de baja.
            raise NoEncontradoError("Sucursal no encontrada")
        return sucursal_id
    if sucursal_id is not None and sucursal_id != propia:
        raise PermisoDenegadoError("No tenés acceso a esa sucursal")
    return propia


def obtener_sucursal(db: Session, sucursal_id: int) -> Sucursal:
    """Para que los demás paquetes (p. ej. la sección Inventario de `catalogo`) validen una sucursal
    sin consultar la tabla `sucursal` directamente."""
    return sucursal_repo.obtener(db, sucursal_id)


def obtener_ciudad(db: Session, ciudad_id: int) -> Ciudad:
    """Para que `comercial` (zonas de envío) valide la ciudad que llega del
    cliente antes de guardarla como FK, sin consultar la tabla `ciudad`
    directamente. 404 si no existe, está inactiva o es de otra empresa."""
    return ciudad_repo.obtener(db, ciudad_id)


def resolver_sucursal_por_nombre(db: Session, nombre: str | None) -> int | None:
    """Para `inteligencia` (búsqueda por voz): matchea el nombre de sucursal
    que devolvió Groq (case-insensitive, exacto) sin consultar `sucursal`
    directamente. Sin match, devuelve None -- no rompe la búsqueda."""
    if not nombre:
        return None
    return db.scalar(
        select(Sucursal.id).where(func.lower(Sucursal.nombre) == nombre.strip().lower(), Sucursal.activo.is_(True))
    )


def atiende_al_publico(db: Session, sucursal_id: int) -> bool:
    """Un depósito (`es_deposito`) es solo almacén: puede despachar envíos
    pero no recibir clientes para retiro ni reservas."""
    return not sucursal_repo.obtener(db, sucursal_id).es_deposito


def obtener_horario_dia(db: Session, sucursal_id: int, dia_semana: int) -> HorarioSucursal | None:
    """Para que `comercial` (reservas) valide que una franja horaria cae dentro del
    horario de atención de la sucursal, sin consultar horario_sucursal
    directamente."""
    return horario_repo.obtener_por_dia(db, sucursal_id, dia_semana)


def validar_horario_en_atencion(db: Session, sucursal_id: int, fecha, hora_desde, hora_hasta) -> None:
    """Valida que [hora_desde, hora_hasta) caiga dentro del horario de
    atención de la sucursal para el día de `fecha`. Lanza DomainError si la
    sucursal es un depósito, no atiende ese día, o la franja se sale del
    horario. La usan reservas (CU-12) y cualquier otro caso de uso que
    necesite la misma validación, para no duplicarla."""
    if not atiende_al_publico(db, sucursal_id):
        raise DomainError("Esa sucursal es un depósito y no recibe clientes: elegí otra para tu reserva")

    if hora_desde >= hora_hasta:
        raise DomainError("La hora de inicio debe ser anterior a la hora de fin")

    # dia_semana: 1=lunes ... 7=domingo (date.isoweekday()), igual que se
    # pide al crear un horario_sucursal.
    dia_semana = fecha.isoweekday()
    horario = obtener_horario_dia(db, sucursal_id, dia_semana)
    if horario is None:
        raise DomainError("La sucursal no atiende ese día")
    if hora_desde < horario.hora_apertura or hora_hasta > horario.hora_cierre:
        raise DomainError("La franja horaria elegida está fuera del horario de atención de la sucursal")


def listar_empleados_sucursal(db: Session, sucursal_id: int) -> list[Empleado]:
    """Para que `comercial` (reservas) notifique a los empleados de una sucursal sin
    consultar la tabla `empleado` directamente."""
    return empleado_repo.listar_por_sucursal(db, sucursal_id)


def obtener_empleado_por_usuario(db: Session, usuario_id: int) -> Empleado | None:
    """Para que `comercial` (ventas y pagos) resuelva el cajero (empleado) a partir
    del usuario logueado, sin consultar `empleado` directamente."""
    return empleado_repo.obtener_por_usuario(db, usuario_id)
