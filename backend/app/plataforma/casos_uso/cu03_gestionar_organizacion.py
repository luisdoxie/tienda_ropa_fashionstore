"""CU-03 — Gestionar organización: ciudades, sucursales y empleados

Absorbe los antiguos CU-04 (Gestionar ciudades), CU-05 (Gestionar
sucursales) y CU-06 (Gestionar empleados y asignarlos a sucursal).

Actor: Administrador.
Precondición: sesión de administrador con el permiso organizacion.gestionar;
para asignar un empleado existen su usuario (CU-02) y la sucursal.
Postcondición: la ciudad queda disponible para asociarle sucursales; la
sucursal y sus horarios de atención quedan registrados; el empleado queda
asignado a su sucursal y las reservas, ventas y recepciones que registre se
asocian a esa sucursal.

Caso de uso COMPUESTO: agrupa tres entidades del mismo dominio (Ciudad,
Sucursal con sus horarios, Empleado), cada una con su propia clase."""

from sqlalchemy.orm import Session

from app.core.auditoria import (
    ACCION_ACTUALIZAR,
    ACCION_CREAR,
    ACCION_DESACTIVAR,
    ENTIDAD_EMPLEADO,
    ENTIDAD_SUCURSAL,
    ContextoAuditoria,
    diff_campos,
)
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, NoEncontradoError
from app.plataforma import politicas as plataforma_politicas
from app.plataforma.models import Ciudad, Empleado, HorarioSucursal, Sucursal
from app.plataforma.repository import (
    CiudadRepository,
    EmpleadoRepository,
    HorarioRepository,
    SucursalRepository,
)
from app.plataforma.schemas import (
    CiudadActualizar,
    CiudadCrear,
    EmpleadoActualizar,
    EmpleadoCrear,
    EmpleadoRespuesta,
    HorarioActualizar,
    HorarioCrear,
    SucursalActualizar,
    SucursalCrear,
)


# ---- Ciudades (antiguo CU-04: Gestionar ciudades) ----


class GestionarCiudades:
    def __init__(self) -> None:
        self._repo = CiudadRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Ciudad]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, ciudad_id: int) -> Ciudad:
        return self._repo.obtener(db, ciudad_id)

    def crear(self, db: Session, datos: CiudadCrear) -> Ciudad:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, ciudad_id: int, datos: CiudadActualizar) -> Ciudad:
        return self._repo.actualizar(db, ciudad_id, datos)

    def desactivar(self, db: Session, ciudad_id: int) -> Ciudad:
        return self._repo.desactivar(db, ciudad_id)


# ---- Sucursales y horarios (antiguo CU-05: Gestionar sucursales) ----


class GestionarSucursales:
    """Agrupa la sucursal física y sus horarios de atención (antes eran dos CU
    separados en el plan de 79)."""

    def __init__(self) -> None:
        self._sucursales = SucursalRepository()
        self._horarios = HorarioRepository()

    # -- Sucursal ---------------------------------------------------------

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Sucursal]:
        return list(self._sucursales.listar(db, paginacion))

    def obtener(self, db: Session, sucursal_id: int) -> Sucursal:
        return self._sucursales.obtener(db, sucursal_id)

    def crear(self, db: Session, datos: SucursalCrear, contexto: ContextoAuditoria | None = None) -> Sucursal:
        # commit=False: la sucursal y su fila de bitácora se confirman juntas (y
        # el bloqueo del límite del plan dura hasta ese commit).
        sucursal = self._sucursales.crear(db, datos, commit=False)
        plataforma_politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_SUCURSAL, sucursal.id, ACCION_CREAR, {"codigo": sucursal.codigo}
        )
        db.commit()
        db.refresh(sucursal)
        return sucursal

    def actualizar(
        self, db: Session, sucursal_id: int, datos: SucursalActualizar, contexto: ContextoAuditoria | None = None
    ) -> Sucursal:
        actual = self._sucursales.buscar(db, sucursal_id)
        cambios = diff_campos(actual, datos.model_dump(exclude_unset=True), ("activo",)) if actual else {}
        sucursal = self._sucursales.actualizar(db, sucursal_id, datos, commit=False)
        plataforma_politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_SUCURSAL, sucursal.id, ACCION_ACTUALIZAR, {"codigo": sucursal.codigo, **cambios}
        )
        db.commit()
        db.refresh(sucursal)
        return sucursal

    def desactivar(self, db: Session, sucursal_id: int, contexto: ContextoAuditoria | None = None) -> Sucursal:
        sucursal = self._sucursales.desactivar(db, sucursal_id, commit=False)
        plataforma_politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_SUCURSAL, sucursal.id, ACCION_DESACTIVAR, {"codigo": sucursal.codigo}
        )
        db.commit()
        db.refresh(sucursal)
        return sucursal

    # -- Horarios de atención ----------------------------------------------

    def listar_horarios(self, db: Session, sucursal_id: int) -> list[HorarioSucursal]:
        self._sucursales.obtener(db, sucursal_id)  # 404 si no existe / está inactiva
        return list(self._horarios.listar_por_sucursal(db, sucursal_id))

    def crear_horario(self, db: Session, sucursal_id: int, datos: HorarioCrear) -> HorarioSucursal:
        self._sucursales.obtener(db, sucursal_id)  # 404 si no existe / está inactiva

        if self._horarios.obtener_por_dia(db, sucursal_id, datos.dia_semana) is not None:
            raise ConflictoError("Ya existe un horario para ese día en esta sucursal")

        horario = HorarioSucursal(
            sucursal_id=sucursal_id,
            dia_semana=datos.dia_semana,
            hora_apertura=datos.hora_apertura,
            hora_cierre=datos.hora_cierre,
        )
        return self._horarios.crear(db, sucursal_id, horario)

    def actualizar_horario(
        self, db: Session, sucursal_id: int, horario_id: int, datos: HorarioActualizar
    ) -> HorarioSucursal:
        horario = self._horarios.obtener(db, sucursal_id, horario_id)
        return self._horarios.actualizar(db, horario, datos.hora_apertura, datos.hora_cierre)

    def eliminar_horario(self, db: Session, sucursal_id: int, horario_id: int) -> None:
        horario = self._horarios.obtener(db, sucursal_id, horario_id)
        self._horarios.eliminar(db, horario)


# ---- Empleados y asignación a sucursal (antiguo CU-06: Gestionar empleados y asignarlos a sucursal) ----


class GestionarEmpleados:
    def __init__(self) -> None:
        self._empleados = EmpleadoRepository()
        self._sucursales = SucursalRepository()

    def _enriquecer(self, db: Session, empleados: list[Empleado]) -> list[EmpleadoRespuesta]:
        """Resuelve usuario_nombre/usuario_apellido/sucursal_nombre para que la
        tabla de empleados en Angular no muestre ids crudos. La sección Organización
        no consulta la tabla `usuario` directamente (es de la sección Seguridad;
        regla 2 de CLAUDE.md), así que el nombre de usuario se resuelve vía
        plataforma.politicas."""
        usuarios = plataforma_politicas.obtener_usuarios_por_ids(db, [e.usuario_id for e in empleados])
        sucursal_ids = [e.sucursal_id for e in empleados if e.sucursal_id is not None]
        sucursales = {s.id: s for s in self._sucursales.listar_por_ids(db, sucursal_ids)}
        resultado = []
        for e in empleados:
            usuario = usuarios.get(e.usuario_id)
            sucursal = sucursales.get(e.sucursal_id) if e.sucursal_id is not None else None
            resultado.append(
                EmpleadoRespuesta.model_validate(e).model_copy(
                    update={
                        "usuario_nombre": usuario.nombre if usuario else None,
                        "usuario_apellido": usuario.apellido if usuario else None,
                        "sucursal_nombre": sucursal.nombre if sucursal else None,
                    }
                )
            )
        return resultado

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[EmpleadoRespuesta]:
        return self._enriquecer(db, list(self._empleados.listar(db, paginacion)))

    def obtener(self, db: Session, empleado_id: int) -> EmpleadoRespuesta:
        return self._enriquecer(db, [self._empleados.obtener(db, empleado_id)])[0]

    def obtener_mi_empleado(self, db: Session, usuario_id: int) -> EmpleadoRespuesta:
        """GET /empleados/yo: para que la caja (Angular) sepa en qué sucursal
        trabaja el cajero logueado, sin necesitar el permiso de administración
        de organizacion.gestionar (ver router)."""
        empleado = self._empleados.obtener_por_usuario(db, usuario_id)
        if empleado is None:
            raise NoEncontradoError("Este usuario no tiene un registro de empleado")
        return self._enriquecer(db, [empleado])[0]

    def crear(self, db: Session, datos: EmpleadoCrear, contexto: ContextoAuditoria | None = None) -> Empleado:
        plataforma_politicas.obtener_usuario(db, datos.usuario_id)  # valida que el usuario exista

        if datos.sucursal_id is not None:
            self._sucursales.obtener(db, datos.sucursal_id)  # 404 si no existe / está inactiva

        existente = self._empleados.obtener_por_usuario(db, datos.usuario_id)
        sucursal_antes = None
        if existente is not None:
            if existente.activo:
                raise ConflictoError("Ese usuario ya es empleado")
            sucursal_antes = existente.sucursal_id
            empleado = self._empleados.reactivar(db, existente, datos, commit=False)
        else:
            empleado = self._empleados.crear(db, datos, commit=False)
        plataforma_politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_EMPLEADO, empleado.id, ACCION_CREAR,
            self._datos_bitacora(empleado, sucursal_antes),
        )  # fmt: skip
        db.commit()
        db.refresh(empleado)
        return empleado

    def actualizar(
        self, db: Session, empleado_id: int, datos: EmpleadoActualizar, contexto: ContextoAuditoria | None = None
    ) -> Empleado:
        if datos.sucursal_id is not None:
            self._sucursales.obtener(db, datos.sucursal_id)  # 404 si no existe / está inactiva
        actual = self._empleados.buscar(db, empleado_id)
        sucursal_antes = actual.sucursal_id if actual else None
        cambios = diff_campos(actual, datos.model_dump(exclude_unset=True), ("activo",)) if actual else {}
        empleado = self._empleados.actualizar(db, empleado_id, datos, commit=False)
        plataforma_politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_EMPLEADO, empleado.id, ACCION_ACTUALIZAR,
            {**self._datos_bitacora(empleado, sucursal_antes), **cambios},
        )  # fmt: skip
        db.commit()
        db.refresh(empleado)
        return empleado

    def desactivar(self, db: Session, empleado_id: int, contexto: ContextoAuditoria | None = None) -> Empleado:
        empleado = self._empleados.desactivar(db, empleado_id, commit=False)
        plataforma_politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_EMPLEADO, empleado.id, ACCION_DESACTIVAR,
            self._datos_bitacora(empleado, empleado.sucursal_id),
        )  # fmt: skip
        db.commit()
        db.refresh(empleado)
        return empleado

    @staticmethod
    def _datos_bitacora(empleado: Empleado, sucursal_antes: int | None) -> dict:
        """Ids y cargo; nunca el CI ni el nombre de la persona."""
        return {
            "usuario_id": empleado.usuario_id,
            "sucursal_id_antes": sucursal_antes,
            "sucursal_id_despues": empleado.sucursal_id,
            "cargo": empleado.cargo,
        }
