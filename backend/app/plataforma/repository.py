from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crud_base import CRUDBase, CRUDBaseSinActivo
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError
from app.core.repository import confirmar, obtener_por_clave
from app.core.permisos import ROL_ADMINISTRADOR, ROL_SUPERADMINISTRADOR
from app.core.security import hash_password
from app.core.tenant import empresa_de, sin_filtro
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
    usuario_rol,
)
from app.plataforma.schemas import (
    CiudadActualizar,
    CiudadCrear,
    ClientePerfilActualizar,
    EmpleadoActualizar,
    EmpleadoCrear,
    EmpresaActualizar,
    EmpresaRegistrar,
    PlanActualizar,
    PlanCrear,
    RolActualizar,
    RolCrear,
    SucursalActualizar,
    SucursalCrear,
    SuscripcionAsignar,
    SuscripcionEstadoActualizar,
    UsuarioActualizar,
    UsuarioCrear,
)


# ---- Seguridad ----


class RolRepository(CRUDBase[Rol, RolCrear, RolActualizar]):
    def __init__(self) -> None:
        super().__init__(Rol)

    # Los roles son globales, pero el superadministrador es de la plataforma:
    # una sesion de empresa no lo ve (ni en listados ni por id).
    def buscar(self, db: Session, id_) -> Rol | None:
        rol = super().buscar(db, id_)
        if rol is not None and rol.nombre == ROL_SUPERADMINISTRADOR and empresa_de(db) is not None:
            return None
        return rol

    def listar(self, db: Session, paginacion, filtros=None) -> list[Rol]:
        roles = super().listar(db, paginacion, filtros)
        if empresa_de(db) is None:
            return roles
        return [r for r in roles if r.nombre != ROL_SUPERADMINISTRADOR]

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
        """El usuario con ese correo DENTRO de la empresa de la sesión. El
        correo no distingue mayúsculas (los datos anteriores a que se
        guardara en minúsculas siguen encontrándose)."""
        return db.scalar(select(Usuario).where(func.lower(Usuario.email) == email.lower()))

    def obtener_de_plataforma_por_email(self, db: Session, email: str) -> Usuario | None:
        """El usuario SIN empresa (superadministrador) con ese correo, si de
        verdad tiene el rol superadministrador. Único uso, junto con
        get_current_user, de una consulta de usuarios sin filtro de empresa."""
        usuario = db.scalar(
            sin_filtro(
                select(Usuario).where(Usuario.empresa_id.is_(None), func.lower(Usuario.email) == email.lower())
            )
        )
        if usuario is None or ROL_SUPERADMINISTRADOR not in {r.nombre for r in usuario.roles}:
            return None
        return usuario

    def obtener_sin_empresa_por_correo(self, db: Session, email: str) -> Usuario | None:
        """El usuario sin empresa con ese correo, tenga el rol que tenga: para
        que scripts/crear_superadmin.py no duplique ni pise a un usuario ajeno."""
        return db.scalar(
            sin_filtro(
                select(Usuario).where(Usuario.empresa_id.is_(None), func.lower(Usuario.email) == email.lower())
            )
        )

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

    # -- Siempre al menos un administrador activo por empresa (D36) ------------

    def contar_otros_administradores_activos(self, db: Session, usuario_id: int) -> int:
        """Usuarios activos con el rol administrador, de la empresa de la
        sesión, sin contar a `usuario_id`."""
        consulta = (
            select(func.count(func.distinct(Usuario.id)))
            .select_from(Usuario)
            .join(usuario_rol, usuario_rol.c.usuario_id == Usuario.id)
            .join(Rol, Rol.id == usuario_rol.c.rol_id)
            .where(Rol.nombre == ROL_ADMINISTRADOR, Usuario.activo.is_(True), Usuario.id != usuario_id)
        )
        return db.scalar(consulta) or 0

    def _exigir_otro_administrador(self, db: Session, usuario: Usuario, accion: str) -> None:
        """409 si `usuario` es el último administrador activo de su empresa y se
        le va a desactivar o quitar el rol (`accion` completa el mensaje)."""
        if usuario.empresa_id is None or not usuario.activo:
            return
        if ROL_ADMINISTRADOR not in {r.nombre for r in usuario.roles}:
            return
        if self.contar_otros_administradores_activos(db, usuario.id) == 0:
            raise ConflictoError(
                f"No se puede {accion}: es el último administrador activo de la empresa. "
                "Asigne primero el rol de administrador a otro usuario"
            )

    def actualizar(self, db: Session, id_, datos, commit: bool = True) -> Usuario:
        if datos.activo is False:
            usuario = self.buscar(db, id_)
            if usuario is not None:
                self._exigir_otro_administrador(db, usuario, "desactivar al usuario")
        return super().actualizar(db, id_, datos, commit)

    def desactivar(self, db: Session, id_, commit: bool = True) -> Usuario:
        self._exigir_otro_administrador(db, self.obtener(db, id_), "desactivar al usuario")
        return super().desactivar(db, id_, commit)

    def asignar_roles(
        self, db: Session, usuario: Usuario, nombres_rol: list[str], commit: bool = True
    ) -> Usuario:
        from app.plataforma.politicas import validar_roles_asignables  # import diferido: politicas importa este módulo

        nombres_unicos = set(nombres_rol)
        validar_roles_asignables(usuario.empresa_id, nombres_unicos)
        if ROL_ADMINISTRADOR not in nombres_unicos:
            self._exigir_otro_administrador(db, usuario, "quitar el rol de administrador")
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
        self._verificar_limite_del_plan(db)
        return super().crear(db, datos, commit)

    def actualizar(self, db: Session, id_: int, datos: SucursalActualizar, commit: bool = True) -> Sucursal:
        # La ciudad llega del cliente y se escribe como FK: se resuelve con una
        # búsqueda filtrada por empresa (404 si no existe, está inactiva o es
        # de otra empresa), igual que en `crear`.
        if datos.ciudad_id is not None:
            CiudadRepository().obtener(db, datos.ciudad_id)
        # Reactivar una sucursal inactiva ocupa un cupo del plan, igual que
        # crearla. Editar una sucursal ya activa (o desactivar) no cuenta.
        if datos.activo is True:
            existente = self.buscar(db, id_)
            if existente is not None and not existente.activo:
                self._verificar_limite_del_plan(db)
        return super().actualizar(db, id_, datos, commit)

    @staticmethod
    def _verificar_limite_del_plan(db: Session) -> None:
        # Import diferido: politicas importa este módulo. Toma el bloqueo de la
        # suscripción (PostgreSQL) hasta el commit, así dos altas simultáneas
        # no pasan las dos con un solo cupo.
        from app.plataforma.politicas import verificar_limite_sucursales

        verificar_limite_sucursales(db)


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


# ---- Empresas, planes y suscripciones ----


class EmpresaRepository(CRUDBase[Empresa, EmpresaRegistrar, EmpresaActualizar]):
    """`empresa` es la raíz del aislamiento: no lleva filtro de empresa, así que
    estas consultas valen en cualquier sesión (superadministrador o empresa).
    Quien las expone decide quién las puede pedir."""

    def __init__(self) -> None:
        super().__init__(Empresa)

    def obtener_por_codigo(self, db: Session, codigo: str) -> Empresa | None:
        return db.scalar(select(Empresa).where(Empresa.codigo == codigo))

    def insertar(self, db: Session, nombre: str, codigo: str, logo_url: str | None, color_acento: str | None) -> Empresa:
        """Inserta la empresa sin confirmar (la transacción es de quien registra).
        El código ya viene normalizado; si choca, 409."""
        if self.obtener_por_codigo(db, codigo) is not None:
            raise ConflictoError("Ya existe una empresa con ese nombre")
        empresa = Empresa(nombre=nombre, codigo=codigo, logo_url=logo_url, color_acento=color_acento)
        db.add(empresa)
        db.flush()
        return empresa

    def listar_filtrado(
        self, db: Session, paginacion, q: str | None = None, activo: bool | None = None
    ) -> list[Empresa]:
        """Para el superadministrador: incluye las inactivas (`activo` filtra)."""
        consulta = select(Empresa)
        if q:
            patron = f"%{q.strip().lower()}%"
            consulta = consulta.where(
                func.lower(Empresa.nombre).like(patron) | func.lower(Empresa.codigo).like(patron)
            )
        if activo is not None:
            consulta = consulta.where(Empresa.activo.is_(activo))
        consulta = consulta.order_by(Empresa.id).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta))

    def listar_publicas(self, db: Session, paginacion, q: str | None = None) -> list[Empresa]:
        """Las tiendas que se muestran al público: empresas activas con una
        suscripción activa y vigente por fecha. Ordenadas por nombre."""
        from app.core.tiempo import hoy_utc

        hoy = hoy_utc()
        con_suscripcion_activa = (
            select(Suscripcion.empresa_id)
            .where(Suscripcion.estado == "activa", Suscripcion.fecha_vencimiento >= hoy)
        )
        consulta = select(Empresa).where(Empresa.activo.is_(True), Empresa.id.in_(con_suscripcion_activa))
        if q:
            patron = f"%{q.strip().lower()}%"
            consulta = consulta.where(
                func.lower(Empresa.nombre).like(patron) | func.lower(Empresa.codigo).like(patron)
            )
        consulta = consulta.order_by(func.lower(Empresa.nombre), Empresa.id).offset(paginacion.offset).limit(paginacion.tamanio)
        # La suscripción se mira de TODAS las empresas (la lista es pública):
        # `sin_filtro` va en la consulta externa, que es la que el filtro revisa.
        return list(db.scalars(sin_filtro(consulta)))


class PlanRepository(CRUDBase[Plan, PlanCrear, PlanActualizar]):
    """`plan` es global. `listar` (heredado) solo trae los activos."""

    def __init__(self) -> None:
        super().__init__(Plan)

    def obtener_por_codigo(self, db: Session, codigo: str) -> Plan | None:
        """El plan con ese código, activo o no."""
        return db.scalar(select(Plan).where(Plan.codigo == codigo))

    def en_uso(self, db: Session, plan_id: int) -> bool:
        """Si alguna suscripción NO cancelada (de cualquier empresa) usa el plan."""
        consulta = select(func.count(Suscripcion.id)).where(
            Suscripcion.plan_id == plan_id, Suscripcion.estado != "cancelada"
        )
        return (db.scalar(sin_filtro(consulta)) or 0) > 0

    def listar_todos(self, db: Session, paginacion) -> list[Plan]:
        """Para el superadministrador: incluye los planes inactivos."""
        consulta = select(Plan).order_by(Plan.id).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta))

    def por_ids(self, db: Session, ids) -> dict[int, Plan]:
        ids = set(ids)
        if not ids:
            return {}
        return {plan.id: plan for plan in db.scalars(select(Plan).where(Plan.id.in_(ids)))}


class SuscripcionRepository(CRUDBaseSinActivo[Suscripcion, SuscripcionAsignar, SuscripcionEstadoActualizar]):
    """Consultas del SUPERADMINISTRADOR sobre las suscripciones de todas las
    empresas (`sin_filtro`, permitido para esta tabla). Solo se usa desde una
    sesión sin empresa. Para operar sobre UNA empresa se entra con
    `core.tenant.en_empresa` y se usan las políticas, que sí filtran."""

    def __init__(self) -> None:
        super().__init__(Suscripcion)

    def _aplicar_alcance(self, consulta):
        return sin_filtro(consulta)

    def listar_filtrado(
        self, db: Session, paginacion, empresa_id: int | None = None, estado: str | None = None
    ) -> list[Suscripcion]:
        """`estado` es el EFECTIVO: `vencida` incluye a las activas cuya fecha ya
        pasó (aunque la tarea no las haya persistido) y `activa` solo a las
        vigentes por fecha."""
        from app.core.tiempo import hoy_utc

        hoy = hoy_utc()
        consulta = self._aplicar_alcance(select(Suscripcion))
        if empresa_id is not None:
            consulta = consulta.where(Suscripcion.empresa_id == empresa_id)
        if estado == "activa":
            consulta = consulta.where(Suscripcion.estado == "activa", Suscripcion.fecha_vencimiento >= hoy)
        elif estado == "vencida":
            consulta = consulta.where(
                (Suscripcion.estado == "vencida")
                | ((Suscripcion.estado == "activa") & (Suscripcion.fecha_vencimiento < hoy))
            )
        elif estado is not None:
            consulta = consulta.where(Suscripcion.estado == estado)
        consulta = consulta.order_by(Suscripcion.id).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta))

    def vigentes_de(self, db: Session, empresa_ids) -> dict[int, tuple[Suscripcion, Plan]]:
        """La suscripción NO cancelada (con su plan) de cada empresa, en un solo
        SELECT, para los listados del superadministrador."""
        ids = set(empresa_ids)
        if not ids:
            return {}
        consulta = self._aplicar_alcance(
            select(Suscripcion, Plan)
            .join(Plan, Plan.id == Suscripcion.plan_id)
            .where(Suscripcion.empresa_id.in_(ids), Suscripcion.estado != "cancelada")
        )
        return {s.empresa_id: (s, p) for s, p in db.execute(consulta)}

    def insertar(
        self,
        db: Session,
        empresa_id: int,
        plan_id: int,
        fecha_inicio,
        fecha_vencimiento,
        estado: str = "activa",
    ) -> Suscripcion:
        """Inserta una suscripción sin confirmar. El `empresa_id` va explícito:
        la sesión del superadministrador no tiene empresa (o ya está en la
        misma). Un segundo vigente lo rechaza el índice parcial (IntegrityError
        al volcar)."""
        suscripcion = Suscripcion(
            empresa_id=empresa_id,
            plan_id=plan_id,
            estado=estado,
            fecha_inicio=fecha_inicio,
            fecha_vencimiento=fecha_vencimiento,
        )
        db.add(suscripcion)
        db.flush()
        return suscripcion

    def empresa_de_suscripcion(self, db: Session, suscripcion_id: int) -> int:
        """El `empresa_id` de la suscripción, o 404."""
        empresa_id = db.scalar(sin_filtro(select(Suscripcion.empresa_id).where(Suscripcion.id == suscripcion_id)))
        if empresa_id is None:
            raise NoEncontradoError("Suscripción no encontrada")
        return empresa_id
