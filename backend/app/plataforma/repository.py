from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crud_base import CRUDBase
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError
from app.core.repository import confirmar, obtener_por_clave
from app.core.security import hash_password
from app.core.tenant import sin_filtro
from app.plataforma.models import (
    Ciudad,
    Cliente,
    Empleado,
    HorarioSucursal,
    Notificacion,
    Permiso,
    Rol,
    Sucursal,
    Usuario,
)
from app.plataforma.schemas import (
    CiudadActualizar,
    CiudadCrear,
    ClientePerfilActualizar,
    EmpleadoActualizar,
    EmpleadoCrear,
    RolActualizar,
    RolCrear,
    SucursalActualizar,
    SucursalCrear,
    UsuarioActualizar,
    UsuarioCrear,
)


# ---- Seguridad ----


class RolRepository(CRUDBase[Rol, RolCrear, RolActualizar]):
    def __init__(self) -> None:
        super().__init__(Rol)

    def asignar_permisos(self, db: Session, rol: Rol, codigos: list[str], commit: bool = True) -> Rol:
        codigos_unicos = set(codigos)
        permisos = list(db.scalars(select(Permiso).where(Permiso.codigo.in_(codigos_unicos))))
        if len(permisos) != len(codigos_unicos):
            raise DomainError("Uno o más códigos de permiso no existen")
        rol.permisos = permisos
        confirmar(db, commit)
        db.refresh(rol)
        return rol

    def listar_permisos(self, db: Session) -> list[Permiso]:
        """El catálogo completo de permisos, para que la pantalla de roles
        pueda ofrecerlos como casillas. Ordenado por módulo y código para que
        salga agrupado sin que el cliente tenga que ordenarlo. No se pagina:
        son pocos y fijos, y una página parcial dejaría permisos fuera de la
        vista sin que se note."""
        return list(db.scalars(select(Permiso).order_by(Permiso.modulo, Permiso.codigo)))


class UsuarioRepository(CRUDBase[Usuario, UsuarioCrear, UsuarioActualizar]):
    def __init__(self) -> None:
        super().__init__(Usuario)

    def obtener_por_email(self, db: Session, email: str) -> Usuario | None:
        """El usuario con ese correo DENTRO de la empresa de la sesión."""
        return db.scalar(select(Usuario).where(Usuario.email == email))

    def obtener_por_email_sin_empresa(self, db: Session, email: str) -> Usuario | None:
        """Para el inicio de sesión y la recuperación de contraseña, donde la
        empresa todavía no se conoce: la primera coincidencia por id. Es
        transitorio: la E03 hace el login con empresa y lo reemplaza."""
        return db.scalar(sin_filtro(select(Usuario).where(Usuario.email == email).order_by(Usuario.id)))

    def listar_por_ids(self, db: Session, ids: list[int]) -> list[Usuario]:
        if not ids:
            return []
        return list(db.scalars(select(Usuario).where(Usuario.id.in_(ids))))

    def crear(self, db: Session, datos: UsuarioCrear, commit: bool = True) -> Usuario:
        existente = self.obtener_por_email(db, datos.email)
        if existente is not None:
            if existente.activo:
                raise ConflictoError("Ya existe un usuario con ese email")
            existente.nombre = datos.nombre
            existente.apellido = datos.apellido
            existente.telefono = datos.telefono
            existente.password_hash = hash_password(datos.password)
            existente.activo = True
            confirmar(db, commit)
            db.refresh(existente)
            return existente
        usuario = Usuario(
            nombre=datos.nombre,
            apellido=datos.apellido,
            email=datos.email,
            telefono=datos.telefono,
            password_hash=hash_password(datos.password),
        )
        db.add(usuario)
        confirmar(db, commit)
        db.refresh(usuario)
        return usuario

    def actualizar_password(self, db: Session, usuario: Usuario, password: str, commit: bool = True) -> None:
        usuario.password_hash = hash_password(password)
        confirmar(db, commit)

    def asignar_roles(
        self, db: Session, usuario: Usuario, nombres_rol: list[str], commit: bool = True
    ) -> Usuario:
        nombres_unicos = set(nombres_rol)
        roles = list(
            db.scalars(select(Rol).where(Rol.nombre.in_(nombres_unicos), Rol.activo.is_(True)))
        )
        if len(roles) != len(nombres_unicos):
            raise DomainError("Uno o más roles no existen o están inactivos")
        usuario.roles = roles
        confirmar(db, commit)
        db.refresh(usuario)
        return usuario


class ClienteRepository:
    def obtener(self, db: Session, cliente_id: int) -> Cliente:
        cliente = obtener_por_clave(db, Cliente, cliente_id)
        if cliente is None:
            raise NoEncontradoError("Cliente no encontrado")
        return cliente

    def obtener_por_usuario(self, db: Session, usuario_id: int) -> Cliente:
        cliente = db.scalar(select(Cliente).where(Cliente.usuario_id == usuario_id))
        if cliente is None:
            raise NoEncontradoError("Perfil de cliente no encontrado")
        return cliente

    def buscar_por_usuario(self, db: Session, usuario_id: int) -> Cliente | None:
        """Variante de obtener_por_usuario que no lanza si no existe, para
        que el caller decida si crea el perfil o lo reusa (ver
        plataforma.casos_uso.cu01_autenticar_registrar_usuarios.RegistrarCliente.registrar)."""
        return db.scalar(select(Cliente).where(Cliente.usuario_id == usuario_id))

    def crear_o_actualizar_perfil(
        self, db: Session, usuario_id: int, ci_nit: str | None, commit: bool = True
    ) -> Cliente:
        """Alta del perfil de cliente de un usuario. Si el usuario venía
        reactivado (estaba dado de baja con este mismo email) puede ya tener un
        perfil de antes -- cliente.usuario_id es único, así que insertar uno
        nuevo rompería con IntegrityError: en ese caso se reutiliza y se le
        actualiza el ci_nit."""
        cliente = self.buscar_por_usuario(db, usuario_id)
        if cliente is not None:
            cliente.ci_nit = ci_nit
        else:
            cliente = Cliente(usuario_id=usuario_id, ci_nit=ci_nit)
            db.add(cliente)
        confirmar(db, commit)
        db.refresh(cliente)
        return cliente

    def actualizar_perfil(
        self, db: Session, usuario_id: int, datos: ClientePerfilActualizar, commit: bool = True
    ) -> Cliente:
        cliente = self.obtener_por_usuario(db, usuario_id)
        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(cliente, campo, valor)
        confirmar(db, commit)
        db.refresh(cliente)
        return cliente


# ---- Notificaciones ----


class NotificacionRepository:
    """Sin `activo`: una notificación no se desactiva, se marca leída o
    simplemente se acumula."""

    def crear(
        self,
        db: Session,
        usuario_id: int,
        titulo: str,
        mensaje: str | None,
        tipo: str | None,
        referencia_id: int | None,
    ) -> Notificacion:
        notificacion = Notificacion(
            usuario_id=usuario_id, titulo=titulo, mensaje=mensaje, tipo=tipo, referencia_id=referencia_id
        )
        db.add(notificacion)
        db.flush()
        return notificacion

    def listar_por_usuario(self, db: Session, usuario_id: int) -> list[Notificacion]:
        return list(
            db.scalars(
                select(Notificacion)
                .where(Notificacion.usuario_id == usuario_id)
                # `id` desempata: dos avisos creados en el mismo instante (la misma transacción)
                # comparten `creado_en` y sin esto su orden sería indeterminado.
                .order_by(Notificacion.creado_en.desc(), Notificacion.id.desc())
            )
        )

    def marcar_leida(self, db: Session, usuario_id: int, notificacion_id: int) -> Notificacion:
        notificacion = obtener_por_clave(db, Notificacion, notificacion_id)
        if notificacion is None or notificacion.usuario_id != usuario_id:
            raise NoEncontradoError("Notificación no encontrada")
        notificacion.leida = True
        db.commit()
        db.refresh(notificacion)
        return notificacion


# ---- Organización ----


class CiudadRepository(CRUDBase[Ciudad, CiudadCrear, CiudadActualizar]):
    def __init__(self) -> None:
        super().__init__(Ciudad)

    def crear(self, db: Session, datos: CiudadCrear, commit: bool = True) -> Ciudad:
        existe = db.scalar(
            select(Ciudad).where(
                Ciudad.nombre == datos.nombre, Ciudad.departamento == datos.departamento
            )
        )
        if existe is not None:
            raise ConflictoError("Ya existe una ciudad con ese nombre y departamento")
        return super().crear(db, datos, commit)


class SucursalRepository(CRUDBase[Sucursal, SucursalCrear, SucursalActualizar]):
    def __init__(self) -> None:
        super().__init__(Sucursal)

    def obtener_por_codigo(self, db: Session, codigo: str) -> Sucursal | None:
        return db.scalar(select(Sucursal).where(Sucursal.codigo == codigo))

    def listar_por_ids(self, db: Session, ids: list[int]) -> list[Sucursal]:
        if not ids:
            return []
        return list(db.scalars(select(Sucursal).where(Sucursal.id.in_(ids))))

    def crear(self, db: Session, datos: SucursalCrear, commit: bool = True) -> Sucursal:
        if self.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe una sucursal con ese código")
        ciudad = obtener_por_clave(db, Ciudad, datos.ciudad_id)
        if ciudad is None or not ciudad.activo:
            raise NoEncontradoError("Ciudad no encontrada")
        return super().crear(db, datos, commit)

    def actualizar(self, db: Session, id_: int, datos: SucursalActualizar, commit: bool = True) -> Sucursal:
        # La ciudad llega del cliente y se escribe como FK: se resuelve con una
        # búsqueda filtrada por empresa (404 si no existe, está inactiva o es
        # de otra empresa), igual que en `crear`.
        if datos.ciudad_id is not None:
            CiudadRepository().obtener(db, datos.ciudad_id)
        return super().actualizar(db, id_, datos, commit)


class HorarioRepository:
    """No hereda de CRUDBase: horario_sucursal no tiene columna `activo`,
    las filas se eliminan físicamente."""

    def listar_por_sucursal(self, db: Session, sucursal_id: int) -> list[HorarioSucursal]:
        return list(
            db.scalars(
                select(HorarioSucursal)
                .where(HorarioSucursal.sucursal_id == sucursal_id)
                .order_by(HorarioSucursal.dia_semana)
            )
        )

    def obtener(self, db: Session, sucursal_id: int, horario_id: int) -> HorarioSucursal:
        horario = db.scalar(
            select(HorarioSucursal).where(
                HorarioSucursal.id == horario_id, HorarioSucursal.sucursal_id == sucursal_id
            )
        )
        if horario is None:
            raise NoEncontradoError("Horario no encontrado")
        return horario

    def obtener_por_dia(self, db: Session, sucursal_id: int, dia_semana: int) -> HorarioSucursal | None:
        return db.scalar(
            select(HorarioSucursal).where(
                HorarioSucursal.sucursal_id == sucursal_id,
                HorarioSucursal.dia_semana == dia_semana,
            )
        )

    def crear(self, db: Session, sucursal_id: int, horario: HorarioSucursal) -> HorarioSucursal:
        db.add(horario)
        db.commit()
        db.refresh(horario)
        return horario

    def actualizar(self, db: Session, horario: HorarioSucursal, hora_apertura, hora_cierre) -> HorarioSucursal:
        if hora_apertura is not None:
            horario.hora_apertura = hora_apertura
        if hora_cierre is not None:
            horario.hora_cierre = hora_cierre
        db.commit()
        db.refresh(horario)
        return horario

    def eliminar(self, db: Session, horario: HorarioSucursal) -> None:
        db.delete(horario)
        db.commit()


class EmpleadoRepository(CRUDBase[Empleado, EmpleadoCrear, EmpleadoActualizar]):
    def __init__(self) -> None:
        super().__init__(Empleado)

    def obtener_por_usuario(self, db: Session, usuario_id: int) -> Empleado | None:
        return db.scalar(select(Empleado).where(Empleado.usuario_id == usuario_id))

    def reactivar(self, db: Session, empleado: Empleado, datos: EmpleadoCrear) -> Empleado:
        """Reusa la fila de un empleado dado de baja en vez de dejar un
        duplicado: `obtener_por_usuario` no filtra por `activo`, así que un
        usuario solo puede tener una fila de empleado en toda su historia."""
        empleado.activo = True
        empleado.sucursal_id = datos.sucursal_id
        empleado.cargo = datos.cargo
        empleado.ci = datos.ci
        empleado.fecha_ingreso = datos.fecha_ingreso
        db.commit()
        db.refresh(empleado)
        return empleado

    def listar_por_sucursal(self, db: Session, sucursal_id: int) -> list[Empleado]:
        return list(
            db.scalars(
                select(Empleado).where(
                    Empleado.sucursal_id == sucursal_id, Empleado.activo.is_(True)
                )
            )
        )
