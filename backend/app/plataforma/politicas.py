"""Funciones que plataforma expone a sus propias secciones (Seguridad y
Organización), a los demás paquetes y a core.security, sin ser casos de uso
del catálogo: consultas y validaciones sobre las tablas de este paquete, para
que nadie más tenga que tocarlas directamente."""

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictoError,
    DomainError,
    ErrorFuncional,
    NoEncontradoError,
    PermisoDenegadoError,
)
from app.core.permisos import PERMISO_ALCANCE_GLOBAL, ROL_ADMINISTRADOR, ROL_SUPERADMINISTRADOR
from app.core.planes import FUNCIONALIDADES
from app.core.tenant import exigir_empresa, registrar_inicializador, sin_filtro
from app.core.tiempo import hoy_utc
from app.plataforma.models import (
    Ciudad,
    Cliente,
    Empleado,
    Empresa,
    HorarioSucursal,
    Notificacion,
    Permiso,
    Plan,
    Rol,
    Sucursal,
    Suscripcion,
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


# ---- Plan y suscripción ----

# Estados y transiciones de la suscripción (D08). `cancelada` es final. Cambiar
# de plan no es una transición: cierra la suscripción (cancelada) y crea otra.
ESTADOS_SUSCRIPCION = ("activa", "suspendida", "vencida", "cancelada")
_TRANSICIONES = {
    "activa": frozenset({"suspendida", "vencida", "cancelada"}),
    "suspendida": frozenset({"activa", "cancelada"}),
    "vencida": frozenset({"activa", "cancelada"}),
    "cancelada": frozenset(),
}


def validar_transicion(origen: str, destino: str) -> None:
    """409 si `origen` → `destino` no está permitida. `vencida → activa` solo
    ocurre renovando con una fecha futura (lo valida quien renueva)."""
    if destino not in _TRANSICIONES.get(origen, frozenset()):
        raise ConflictoError("Transición de estado no permitida")


def estado_efectivo(suscripcion: Suscripcion, hoy=None) -> str:
    """El estado que cuenta: una `activa` cuya fecha de vencimiento ya pasó es
    `vencida` aunque la tarea periódica todavía no la haya persistido. El
    bloqueo no puede depender de que haya corrido una tarea."""
    hoy = hoy or hoy_utc()
    if suscripcion.estado == "activa" and suscripcion.fecha_vencimiento < hoy:
        return "vencida"
    return suscripcion.estado


def obtener_suscripcion_vigente(db: Session, bloquear: bool = False) -> Suscripcion | None:
    """La suscripción NO cancelada de la empresa de la sesión (a lo sumo una).
    `bloquear=True` toma la fila con SELECT ... FOR UPDATE (solo PostgreSQL; en
    SQLite se omite) para serializar altas o cambios simultáneos."""
    consulta = select(Suscripcion).where(Suscripcion.estado != "cancelada")
    if bloquear:
        consulta = consulta.with_for_update()
    return db.scalar(consulta)


def plan_de_la_empresa(db: Session) -> Plan | None:
    """El plan de la suscripción vigente de la empresa de la sesión."""
    return db.scalar(
        select(Plan).join(Suscripcion, Suscripcion.plan_id == Plan.id).where(Suscripcion.estado != "cancelada")
    )


@dataclass(frozen=True)
class SituacionEmpresa:
    """Lo que hace falta para decidir si una empresa opera: `estado` es el
    efectivo de su suscripción, o `sin_suscripcion` / `empresa_inactiva`."""

    estado: str
    suscripcion: Suscripcion | None
    plan: Plan | None


def situacion_de_la_empresa(db: Session) -> SituacionEmpresa:
    """Empresa activa + suscripción vigente + plan de la empresa de la sesión."""
    empresa_id = exigir_empresa(db)
    if not empresa_esta_activa(db, empresa_id):
        return SituacionEmpresa("empresa_inactiva", None, None)
    fila = db.execute(
        select(Suscripcion, Plan).join(Plan, Plan.id == Suscripcion.plan_id).where(Suscripcion.estado != "cancelada")
    ).first()
    if fila is None:
        return SituacionEmpresa("sin_suscripcion", None, None)
    suscripcion, plan = fila
    return SituacionEmpresa(estado_efectivo(suscripcion), suscripcion, plan)


def funcionalidades_habilitadas(db: Session) -> list[str]:
    """Las funcionalidades que incluye el plan de la empresa, en el orden de
    `core.planes.FUNCIONALIDADES`. Sin suscripción vigente, ninguna."""
    plan = plan_de_la_empresa(db)
    if plan is None:
        return []
    return [nombre for nombre in FUNCIONALIDADES if getattr(plan, nombre)]


def contar_sucursales_activas(db: Session) -> int:
    """Sucursales con `activo` de la empresa de la sesión. El depósito cuenta."""
    return db.scalar(select(func.count(Sucursal.id)).where(Sucursal.activo.is_(True))) or 0


def error_limite_sucursales(plan: Plan, actual: int) -> ErrorFuncional:
    return ErrorFuncional(
        "limite_plan_excedido",
        f"El plan {plan.nombre} permite hasta {plan.max_sucursales} sucursales activas",
        409,
        recurso="sucursales",
        limite=plan.max_sucursales,
        actual=actual,
        plan=plan.codigo,
    )


def verificar_limite_sucursales(db: Session) -> None:
    """Antes de crear o reactivar una sucursal: 409 `limite_plan_excedido` si la
    empresa ya tiene tantas activas como permite su plan. Bloquea la fila de la
    suscripción (FOR UPDATE, solo PostgreSQL) para que dos altas simultáneas no
    superen el límite. Sin suscripción vigente → 403 `suscripcion_no_activa`."""
    suscripcion = obtener_suscripcion_vigente(db, bloquear=True)
    if suscripcion is None:
        raise ErrorFuncional(
            "suscripcion_no_activa", "La empresa no tiene una suscripción", 403, estado="sin_suscripcion"
        )
    plan = db.get(Plan, suscripcion.plan_id)
    actual = contar_sucursales_activas(db)
    if actual >= plan.max_sucursales:
        raise error_limite_sucursales(plan, actual)


def obtener_suscripcion_de_la_empresa(db: Session, suscripcion_id: int, bloquear: bool = False) -> Suscripcion:
    """La suscripción con ese id DENTRO de la empresa de la sesión (la del
    superadministrador entra antes con `en_empresa`). 404 si no existe o es de
    otra empresa. `bloquear=True` toma la fila con SELECT ... FOR UPDATE (solo
    PostgreSQL)."""
    consulta = select(Suscripcion).where(Suscripcion.id == suscripcion_id)
    if bloquear:
        consulta = consulta.with_for_update()
    suscripcion = db.scalar(consulta)
    if suscripcion is None:
        raise NoEncontradoError("Suscripción no encontrada")
    return suscripcion


def cerrar_suscripcion(suscripcion: Suscripcion, hoy=None) -> None:
    """Cancela la suscripción por un cambio de plan. Su `fecha_vencimiento` se
    recorta a `min(actual, hoy)` (nunca antes de `fecha_inicio`, que exige
    `ck_suscripcion_fechas`): así queda constancia de cuándo terminó sin una
    columna nueva."""
    hoy = hoy or hoy_utc()
    suscripcion.estado = "cancelada"
    suscripcion.fecha_vencimiento = max(suscripcion.fecha_inicio, min(suscripcion.fecha_vencimiento, hoy))


def contar_usuarios_activos(db: Session) -> int:
    """Usuarios activos de la empresa de la sesión (staff y clientes)."""
    return db.scalar(select(func.count(Usuario.id)).where(Usuario.activo.is_(True))) or 0


def administrador_principal(db: Session) -> Usuario | None:
    """El administrador "principal" de la empresa de la sesión: el usuario
    activo con el rol administrador de menor id."""
    return db.scalar(
        select(Usuario)
        .join(usuario_rol, usuario_rol.c.usuario_id == Usuario.id)
        .join(Rol, Rol.id == usuario_rol.c.rol_id)
        .where(Rol.nombre == ROL_ADMINISTRADOR, Usuario.activo.is_(True))
        .order_by(Usuario.id)
        .limit(1)
    )


def vencer_suscripciones(db: Session) -> int:
    """Persiste `vencida` en las suscripciones activas cuya fecha de
    vencimiento ya pasó, en TODAS las empresas (una sola pasada: no toca datos
    de negocio). Idempotente. Devuelve cuántas cambió."""
    consulta = (
        update(Suscripcion)
        .where(Suscripcion.estado == "activa", Suscripcion.fecha_vencimiento < hoy_utc())
        .values(estado="vencida")
        .execution_options(synchronize_session=False)
    )
    cambiadas = db.execute(sin_filtro(consulta)).rowcount
    db.commit()
    return cambiadas


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

# Las 9 capitales de departamento de Bolivia: lo único que una empresa nueva
# trae sembrado de la organización (sin ciudad no se puede crear una sucursal).
# (nombre de la ciudad, departamento)
CIUDADES_BASE: list[tuple[str, str]] = [
    ("La Paz", "La Paz"),
    ("Santa Cruz de la Sierra", "Santa Cruz"),
    ("Cochabamba", "Cochabamba"),
    ("Oruro", "Oruro"),
    ("Potosí", "Potosí"),
    ("Sucre", "Chuquisaca"),
    ("Tarija", "Tarija"),
    ("Trinidad", "Beni"),
    ("Cobija", "Pando"),
]


@registrar_inicializador
def sembrar_ciudades_base(db: Session) -> None:
    """Inicializador de empresa nueva (ver `core.tenant.registrar_inicializador`):
    crea las ciudades base que falten en la empresa de la sesión. Idempotente y
    sin confirmar: la transacción es de quien registra la empresa."""
    existentes = {(nombre, departamento) for nombre, departamento in db.execute(select(Ciudad.nombre, Ciudad.departamento))}
    for nombre, departamento in CIUDADES_BASE:
        if (nombre, departamento) not in existentes:
            db.add(Ciudad(nombre=nombre, departamento=departamento))
    db.flush()


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
