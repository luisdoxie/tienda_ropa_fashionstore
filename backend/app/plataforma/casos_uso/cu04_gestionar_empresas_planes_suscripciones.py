"""CU-04 - Gestionar empresas, planes y suscripciones

Actor: Superadministrador de la plataforma (y Administrador de empresa para
consultar su propia empresa, plan y suscripción).
Precondición: sesión de superadministrador con plataforma.gestionar (o de
administrador con empresa.gestionar).
Postcondición: empresa registrada con su suscripción, administrador y catálogos
base; plan y estado de suscripción actualizados y reflejados en el backend
(límites de sucursales, funcionalidades y bloqueo por suscripción).

Caso de uso COMPUESTO: cuatro clases de control en este archivo.

- GestionarEmpresas: registrar (una sola transacción), actualizar, desactivar,
  resumen, alta de administrador y de sucursal sobre una empresa ajena y la
  lista pública de tiendas.
- GestionarPlanes: planes con límites y funcionalidades configurables.
- GestionarSuscripciones: asignar o cambiar de plan, renovar, suspender,
  reactivar, cancelar y vencer.
- ConsultarMiEmpresa: la empresa, el plan y la suscripción de quien administra.

El superadministrador no tiene empresa en su sesión: para tocar los datos de
una empresa entra con `core.tenant.en_empresa`, que restaura el modo
plataforma al salir y vacía el mapa de identidad de la sesión. Por eso cada
operación guarda los valores que necesita (ids, códigos) y arma su respuesta
DENTRO del bloque. La lógica reutilizable (estados, transiciones, límites) vive
en plataforma/politicas.py."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auditoria import (
    ACCION_ACTUALIZAR,
    ACCION_ASIGNAR_PLAN,
    ACCION_CAMBIAR_ESTADO,
    ACCION_CAMBIAR_PLAN,
    ACCION_CAMBIAR_PLAZO_CAMBIO,
    ACCION_CREAR,
    ACCION_DESACTIVAR,
    ACCION_RENOVAR,
    ENTIDAD_EMPRESA,
    ENTIDAD_PLAN,
    ENTIDAD_SUCURSAL,
    ENTIDAD_SUSCRIPCION,
    ENTIDAD_USUARIO,
    ContextoAuditoria,
    diff_campos,
)
from app.core.config import get_settings
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError
from app.core.permisos import ROL_ADMINISTRADOR
from app.core.tenant import en_empresa, exigir_empresa, inicializar_empresa
from app.core.tiempo import hoy_utc
from app.plataforma import politicas
from app.plataforma.models import Empresa, Plan, Suscripcion, Usuario
from app.plataforma.repository import (
    EmpresaRepository,
    PlanRepository,
    SucursalRepository,
    SuscripcionRepository,
    UsuarioRepository,
)
from app.plataforma.schemas import (
    AdministradorRegistrar,
    EmpresaActualizar,
    EmpresaRegistrar,
    EmpresaRespuesta,
    EmpresaResumenRespuesta,
    MiEmpresaActualizar,
    MiEmpresaRespuesta,
    MiSuscripcionRespuesta,
    PlanActualizar,
    PlanCrear,
    SucursalCrear,
    SucursalRespuesta,
    SuscripcionAsignar,
    SuscripcionEstadoActualizar,
    SuscripcionRenovar,
    SuscripcionRespuesta,
    TiendaPublicaDetalle,
    TiendaPublicaRespuesta,
    UsuarioCrear,
    UsuarioRespuesta,
)

PLAN_POR_DEFECTO = "basico"
CAMPOS_ANULABLES_EMPRESA = ("logo_url", "color_acento")


# ---- Apoyo común de las cuatro clases -------------------------------------------


@contextmanager
def _transaccion(db: Session, conflicto: str = "La operación choca con un registro existente"):
    """Una sola unidad de trabajo: confirma al terminar y revierte TODO si algo
    falla. Una violación de unicidad de la base (carrera entre dos peticiones)
    se responde 409."""
    try:
        yield
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictoError(conflicto) from exc
    except Exception:
        db.rollback()
        raise


def _sin_nulos(datos: BaseModel, destino: type[BaseModel] | None = None, anulables: tuple[str, ...] = ()):
    """Los campos enviados que traen valor. Un `null` explícito en una columna
    NOT NULL (nombre, límites, estado) no la vacía: se ignora. Las columnas de
    `anulables` sí aceptan `null` (borrar el logo)."""
    campos = {
        campo: valor
        for campo, valor in datos.model_dump(exclude_unset=True).items()
        if valor is not None or campo in anulables
    }
    return (destino or type(datos))(**campos)


def _fecha_vencimiento_valida(inicio: dt.date, vencimiento: dt.date, hoy: dt.date) -> None:
    if vencimiento <= hoy:
        raise DomainError("La fecha de vencimiento debe ser posterior a hoy", 422)
    if vencimiento < inicio:
        raise DomainError("La fecha de vencimiento no puede ser anterior a la de inicio", 422)


def _plan_asignable(planes: PlanRepository, db: Session, codigo: str) -> Plan:
    """El plan por su código: 404 si no existe, 409 si está inactivo."""
    plan = planes.obtener_por_codigo(db, codigo.strip().lower())
    if plan is None:
        raise NoEncontradoError("Plan no encontrado")
    if not plan.activo:
        raise ConflictoError("El plan está inactivo")
    return plan


def _respuesta_suscripcion(suscripcion: Suscripcion, plan: Plan) -> SuscripcionRespuesta:
    return SuscripcionRespuesta(
        id=suscripcion.id,
        empresa_id=suscripcion.empresa_id,
        plan_codigo=plan.codigo,
        plan_nombre=plan.nombre,
        estado=suscripcion.estado,
        estado_efectivo=politicas.estado_efectivo(suscripcion),
        fecha_inicio=suscripcion.fecha_inicio,
        fecha_vencimiento=suscripcion.fecha_vencimiento,
        creado_en=suscripcion.creado_en,
    )


def _respuesta_empresa(
    empresa: Empresa, ficha: tuple[Suscripcion, Plan] | None = None, administrador_email: str | None = None
) -> EmpresaRespuesta:
    """`ficha` = (suscripción vigente, su plan). Es el estado EFECTIVO el que se
    informa."""
    suscripcion, plan = ficha if ficha is not None else (None, None)
    return EmpresaRespuesta(
        id=empresa.id,
        codigo=empresa.codigo,
        nombre=empresa.nombre,
        logo_url=empresa.logo_url,
        color_acento=empresa.color_acento,
        activo=empresa.activo,
        plan_codigo=plan.codigo if plan is not None else None,
        suscripcion_estado=politicas.estado_efectivo(suscripcion) if suscripcion is not None else None,
        fecha_inicio=suscripcion.fecha_inicio if suscripcion is not None else None,
        fecha_vencimiento=suscripcion.fecha_vencimiento if suscripcion is not None else None,
        administrador_email=administrador_email,
    )


# ---- Empresas ---------------------------------------------------------------------


class GestionarEmpresas:
    """Las empresas contratantes de la plataforma. Solo las usa el
    superadministrador, salvo la lista pública de tiendas."""

    def __init__(self) -> None:
        self._repo = EmpresaRepository()
        self._planes = PlanRepository()
        self._suscripciones = SuscripcionRepository()
        self._usuarios = UsuarioRepository()
        self._sucursales = SucursalRepository()

    # -- Consulta ----------------------------------------------------------------

    def _buscar(self, db: Session, empresa_id: int) -> Empresa:
        empresa = self._repo.buscar(db, empresa_id)
        if empresa is None:
            raise NoEncontradoError("Empresa no encontrada")
        return empresa

    def _correo_administrador(self, db: Session, empresa_id: int) -> str | None:
        """Correo del administrador principal (el activo de menor id)."""
        with en_empresa(db, empresa_id):
            administrador = politicas.administrador_principal(db)
            return administrador.email if administrador is not None else None

    def listar(
        self, db: Session, paginacion: ParametrosPaginacion, q: str | None = None, activo: bool | None = None
    ) -> list[EmpresaRespuesta]:
        empresas = self._repo.listar_filtrado(db, paginacion, q, activo)
        fichas = self._suscripciones.vigentes_de(db, [e.id for e in empresas])
        return [_respuesta_empresa(e, fichas.get(e.id)) for e in empresas]

    def obtener(self, db: Session, empresa_id: int) -> EmpresaRespuesta:
        empresa = self._buscar(db, empresa_id)
        ficha = self._suscripciones.vigentes_de(db, [empresa_id]).get(empresa_id)
        respuesta = _respuesta_empresa(empresa, ficha)  # antes de entrar en la empresa: vacía la sesión
        respuesta.administrador_email = self._correo_administrador(db, empresa_id)
        return respuesta

    def resumen(self, db: Session, empresa_id: int) -> EmpresaResumenRespuesta:
        """Usuarios activos, sucursales activas (el depósito cuenta), plan, estado
        efectivo y administrador principal de la empresa."""
        base = self.obtener(db, empresa_id)
        with en_empresa(db, empresa_id):
            usuarios = politicas.contar_usuarios_activos(db)
            sucursales = politicas.contar_sucursales_activas(db)
            plan = politicas.plan_de_la_empresa(db)
            limite = plan.max_sucursales if plan is not None else None
        return EmpresaResumenRespuesta(
            **base.model_dump(), usuarios_activos=usuarios, sucursales_activas=sucursales, max_sucursales=limite
        )

    # -- Registro ----------------------------------------------------------------

    def registrar(
        self, db: Session, datos: EmpresaRegistrar, contexto: ContextoAuditoria | None = None
    ) -> EmpresaRespuesta:
        """Alta de una empresa en UNA transacción: la empresa, su suscripción
        activa, su administrador y los catálogos base (tallas, materiales,
        ciudades). Cualquier error revierte todo y no queda nada a medias. La
        respuesta nunca trae la contraseña."""
        codigo = politicas.normalizar_nombre_empresa(datos.nombre)
        if not codigo:
            raise DomainError("El nombre de la empresa no es válido")
        if self._repo.obtener_por_codigo(db, codigo) is not None:
            raise ConflictoError("Ya existe una empresa con ese nombre")

        hoy = hoy_utc()
        vencimiento = datos.fecha_vencimiento or hoy + dt.timedelta(days=get_settings().suscripcion_dias_por_defecto)
        _fecha_vencimiento_valida(hoy, vencimiento, hoy)
        plan = _plan_asignable(self._planes, db, datos.plan_codigo or PLAN_POR_DEFECTO)
        plan_id, plan_codigo = plan.id, plan.codigo

        with _transaccion(db, "Ya existe una empresa con ese nombre"):
            empresa = self._repo.insertar(db, datos.nombre.strip(), codigo, datos.logo_url, datos.color_acento)
            empresa_id = empresa.id
            # La sesión del superadministrador no tiene empresa: va explícita.
            self._suscripciones.insertar(db, empresa_id, plan_id, hoy, vencimiento)
            with en_empresa(db, empresa_id):
                administrador = self._crear_administrador(db, datos.administrador)
                correo = administrador.email
            inicializar_empresa(db, empresa_id)
            # Actor: el superadministrador (sin empresa en la sesión), así que la
            # empresa afectada va explícita. Sin el correo del administrador.
            politicas.registrar_bitacora_de(
                db, contexto, ENTIDAD_EMPRESA, empresa_id, ACCION_CREAR,
                {"codigo": codigo, "plan": plan_codigo}, empresa_id=empresa_id,
            )  # fmt: skip
            respuesta = EmpresaRespuesta(
                id=empresa_id,
                codigo=codigo,
                nombre=datos.nombre.strip(),
                logo_url=datos.logo_url,
                color_acento=datos.color_acento,
                activo=True,
                plan_codigo=plan_codigo,
                suscripcion_estado="activa",
                fecha_inicio=hoy,
                fecha_vencimiento=vencimiento,
                administrador_email=correo,
            )
        return respuesta

    def _crear_administrador(self, db: Session, datos: AdministradorRegistrar) -> Usuario:
        """Dentro de `en_empresa`: el usuario (correo único en la empresa, clave
        con bcrypt) con el rol administrador. Sin confirmar."""
        usuario = self._usuarios.crear(db, UsuarioCrear(**datos.model_dump()), commit=False)
        return self._usuarios.asignar_roles(db, usuario, [ROL_ADMINISTRADOR], commit=False)

    # -- Cambios -----------------------------------------------------------------

    def actualizar(
        self, db: Session, empresa_id: int, datos: EmpresaActualizar, contexto: ContextoAuditoria | None = None
    ) -> EmpresaRespuesta:
        """Nombre comercial, logo, color de acento y estado. El código NO cambia."""
        cambios = _sin_nulos(datos, anulables=CAMPOS_ANULABLES_EMPRESA)
        actual = self._repo.buscar(db, empresa_id)
        detalle = diff_campos(actual, cambios.model_dump(exclude_unset=True), ("activo",)) if actual else {}
        self._repo.actualizar(db, empresa_id, cambios, commit=False)
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_EMPRESA, empresa_id, ACCION_ACTUALIZAR, detalle, empresa_id=empresa_id
        )
        db.commit()
        return self.obtener(db, empresa_id)

    def desactivar(
        self, db: Session, empresa_id: int, contexto: ContextoAuditoria | None = None
    ) -> EmpresaRespuesta:
        """Baja lógica: bloquea el login y los tokens ya emitidos de la empresa."""
        self._repo.desactivar(db, empresa_id, commit=False)
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_EMPRESA, empresa_id, ACCION_DESACTIVAR, {}, empresa_id=empresa_id
        )
        db.commit()
        return self.obtener(db, empresa_id)

    # -- Asociar usuarios y sucursales a una empresa ajena -----------------------------

    def _exigir_activa(self, db: Session, empresa_id: int) -> None:
        if not self._buscar(db, empresa_id).activo:
            raise ConflictoError("La empresa está inactiva")

    def agregar_administrador(
        self, db: Session, empresa_id: int, datos: AdministradorRegistrar, contexto: ContextoAuditoria | None = None
    ) -> UsuarioRespuesta:
        """Otro administrador para la empresa (solo con el rol administrador)."""
        self._exigir_activa(db, empresa_id)
        with _transaccion(db, "Ya existe un usuario con ese email"):
            with en_empresa(db, empresa_id):
                administrador = self._crear_administrador(db, datos)
                respuesta = UsuarioRespuesta.from_modelo(administrador)
                politicas.registrar_bitacora_de(
                    db, contexto, ENTIDAD_USUARIO, administrador.id, ACCION_CREAR,
                    {"reactivado": False, "rol": ROL_ADMINISTRADOR}, empresa_id=empresa_id,
                )  # fmt: skip
        return respuesta

    def agregar_sucursal(
        self, db: Session, empresa_id: int, datos: SucursalCrear, contexto: ContextoAuditoria | None = None
    ) -> SucursalRespuesta:
        """Una sucursal para la empresa. Pasa por el mismo repositorio que el
        alta de la propia empresa, así que respeta el límite de su plan."""
        self._exigir_activa(db, empresa_id)
        with _transaccion(db, "Ya existe una sucursal con ese código"):
            with en_empresa(db, empresa_id):
                sucursal = self._sucursales.crear(db, datos, commit=False)
                respuesta = SucursalRespuesta.model_validate(sucursal)
                politicas.registrar_bitacora_de(
                    db, contexto, ENTIDAD_SUCURSAL, sucursal.id, ACCION_CREAR,
                    {"codigo": sucursal.codigo}, empresa_id=empresa_id,
                )  # fmt: skip
        return respuesta

    # -- Tiendas públicas ----------------------------------------------------------------

    def listar_tiendas(
        self, db: Session, paginacion: ParametrosPaginacion, q: str | None = None
    ) -> list[TiendaPublicaRespuesta]:
        """Empresas activas con suscripción activa. Solo código, nombre, logo y
        color de acento."""
        return [TiendaPublicaRespuesta.model_validate(e) for e in self._repo.listar_publicas(db, paginacion, q)]

    def obtener_tienda(self, db: Session, codigo: str) -> TiendaPublicaDetalle:
        empresa = self._repo.obtener_por_codigo(db, codigo.strip().lower())
        if empresa is None or not empresa.activo:
            raise NoEncontradoError("Tienda no encontrada")
        tienda = TiendaPublicaDetalle.model_validate(empresa)
        tienda.disponible = self._repo.tiene_suscripcion_activa(db, empresa.id)
        return tienda


# ---- Planes -------------------------------------------------------------------------------


class GestionarPlanes:
    """Catálogo global de planes. Los límites y las funcionalidades viven en la
    tabla `plan`: editarlos cambia el comportamiento sin tocar el código."""

    def __init__(self) -> None:
        self._repo = PlanRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Plan]:
        return self._repo.listar_todos(db, paginacion)

    def listar_publicos(self, db: Session) -> list[Plan]:
        """Sin sesión: los planes activos para la portada pública (los lee de la
        tabla, así que un plan editado se refleja solo)."""
        return self._repo.listar_publicos(db)

    def obtener(self, db: Session, plan_id: int) -> Plan:
        plan = self._repo.buscar(db, plan_id)
        if plan is None:
            raise NoEncontradoError("Plan no encontrado")
        return plan

    # El plan es global (sin empresa): sus filas de bitácora quedan sin empresa y
    # solo las ve el superadministrador.

    def crear(self, db: Session, datos: PlanCrear, contexto: ContextoAuditoria | None = None) -> Plan:
        if self._repo.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe un plan con ese código")
        plan = self._repo.crear(db, datos, commit=False)
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_PLAN, plan.id, ACCION_CREAR,
            {"codigo": plan.codigo, "max_sucursales": plan.max_sucursales},
        )  # fmt: skip
        db.commit()
        db.refresh(plan)
        return plan

    def actualizar(
        self, db: Session, plan_id: int, datos: PlanActualizar, contexto: ContextoAuditoria | None = None
    ) -> Plan:
        """Límites y funcionalidades. Bajar `max_sucursales` por debajo del uso de
        una empresa NO desactiva nada: solo impide crear o reactivar sucursales
        hasta quedar dentro del límite."""
        actual = self.obtener(db, plan_id)
        cambios = _sin_nulos(datos)
        if cambios.activo is False:
            self._exigir_sin_uso(db, plan_id)
        campos = diff_campos(actual, cambios.model_dump(exclude_unset=True), ("activo",))
        plan = self._repo.actualizar(db, plan_id, cambios, commit=False)
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_PLAN, plan.id, ACCION_ACTUALIZAR,
            {"codigo": plan.codigo, **campos, "max_sucursales": plan.max_sucursales},
        )  # fmt: skip
        db.commit()
        db.refresh(plan)
        return plan

    def desactivar(self, db: Session, plan_id: int, contexto: ContextoAuditoria | None = None) -> Plan:
        self._exigir_sin_uso(db, plan_id)
        plan = self._repo.desactivar(db, plan_id, commit=False)
        politicas.registrar_bitacora_de(db, contexto, ENTIDAD_PLAN, plan.id, ACCION_DESACTIVAR, {"codigo": plan.codigo})
        db.commit()
        db.refresh(plan)
        return plan

    def _exigir_sin_uso(self, db: Session, plan_id: int) -> None:
        if self._repo.en_uso(db, plan_id):
            raise ConflictoError("El plan está en uso por una suscripción vigente")


# ---- Suscripciones ---------------------------------------------------------------------------


class GestionarSuscripciones:
    """Una empresa tiene a lo sumo una suscripción vigente (no cancelada). Cambiar
    de plan cierra la vigente y crea otra: queda el historial."""

    def __init__(self) -> None:
        self._repo = SuscripcionRepository()
        self._empresas = EmpresaRepository()
        self._planes = PlanRepository()

    # -- Consulta ----------------------------------------------------------------

    def listar(
        self,
        db: Session,
        paginacion: ParametrosPaginacion,
        empresa_id: int | None = None,
        estado: str | None = None,
    ) -> list[SuscripcionRespuesta]:
        """`estado` es el efectivo (una activa con la fecha pasada cuenta como vencida)."""
        suscripciones = self._repo.listar_filtrado(db, paginacion, empresa_id, estado)
        planes = self._planes.por_ids(db, [s.plan_id for s in suscripciones])
        return [_respuesta_suscripcion(s, planes[s.plan_id]) for s in suscripciones]

    def obtener(self, db: Session, suscripcion_id: int) -> SuscripcionRespuesta:
        suscripcion = self._repo.buscar(db, suscripcion_id)
        if suscripcion is None:
            raise NoEncontradoError("Suscripción no encontrada")
        return _respuesta_suscripcion(suscripcion, self._planes.buscar(db, suscripcion.plan_id))

    # -- Asignar o cambiar de plan ------------------------------------------------------

    def asignar_o_cambiar_plan(
        self, db: Session, datos: SuscripcionAsignar, contexto: ContextoAuditoria | None = None
    ) -> SuscripcionRespuesta:
        """Asigna un plan a una empresa sin suscripción o LO CAMBIA: la vigente
        pasa a `cancelada` (con su vencimiento recortado a hoy) y se crea otra
        activa. Mismo plan: 409. Un plan cuyo límite de sucursales es menor que el
        uso actual se rechaza (409 `limite_plan_excedido`); subir de plan siempre
        se puede."""
        if self._empresas.buscar(db, datos.empresa_id) is None:
            raise NoEncontradoError("Empresa no encontrada")
        plan = _plan_asignable(self._planes, db, datos.plan_codigo)
        hoy = hoy_utc()
        inicio = datos.fecha_inicio or hoy
        vencimiento = datos.fecha_vencimiento or inicio + dt.timedelta(days=get_settings().suscripcion_dias_por_defecto)
        _fecha_vencimiento_valida(inicio, vencimiento, hoy)

        with _transaccion(db, "La empresa ya tiene una suscripción vigente: reintente"):
            with en_empresa(db, datos.empresa_id):
                vigente = politicas.obtener_suscripcion_vigente(db, bloquear=True)
                if vigente is not None and vigente.plan_id == plan.id:
                    raise ConflictoError("La empresa ya tiene ese plan: para extender la vigencia use renovar")
                actual = politicas.contar_sucursales_activas(db)
                if actual > plan.max_sucursales:
                    raise politicas.error_limite_sucursales(plan, actual)
                plan_antes = None
                if vigente is not None:
                    plan_antes = self._planes.buscar(db, vigente.plan_id).codigo
                    politicas.cerrar_suscripcion(vigente, hoy)
                    db.flush()  # libera el índice de la vigente antes de insertar la nueva
                nueva = self._repo.insertar(db, datos.empresa_id, plan.id, inicio, vencimiento)
                db.refresh(nueva)
                respuesta = _respuesta_suscripcion(nueva, plan)
                # Actor: el superadministrador. La empresa afectada va explícita
                # (dentro de `en_empresa` coincide con la de la sesión).
                if vigente is None:
                    politicas.registrar_bitacora_de(
                        db, contexto, ENTIDAD_SUSCRIPCION, nueva.id, ACCION_ASIGNAR_PLAN,
                        {"plan_despues": plan.codigo, "suscripcion_nueva_id": nueva.id},
                        empresa_id=datos.empresa_id,
                    )  # fmt: skip
                else:
                    politicas.registrar_bitacora_de(
                        db, contexto, ENTIDAD_SUSCRIPCION, nueva.id, ACCION_CAMBIAR_PLAN,
                        {"plan_antes": plan_antes, "plan_despues": plan.codigo, "suscripcion_nueva_id": nueva.id},
                        empresa_id=datos.empresa_id,
                    )  # fmt: skip
        return respuesta

    # -- Renovar ------------------------------------------------------------------------------

    def renovar(
        self, db: Session, suscripcion_id: int, datos: SuscripcionRenovar, contexto: ContextoAuditoria | None = None
    ) -> SuscripcionRespuesta:
        """Fija un nuevo vencimiento (futuro). Si la suscripción estaba vencida
        vuelve a `activa`; si estaba suspendida solo cambia la fecha; una
        cancelada no se renueva."""
        hoy = hoy_utc()
        if datos.fecha_vencimiento <= hoy:
            raise DomainError("La nueva fecha de vencimiento debe ser posterior a hoy", 422)
        empresa_id = self._repo.empresa_de_suscripcion(db, suscripcion_id)
        with _transaccion(db):
            with en_empresa(db, empresa_id):
                suscripcion = politicas.obtener_suscripcion_de_la_empresa(db, suscripcion_id, bloquear=True)
                if suscripcion.estado == "cancelada":
                    raise ConflictoError("Una suscripción cancelada no se puede renovar")
                if datos.fecha_vencimiento < suscripcion.fecha_inicio:
                    raise DomainError("La fecha de vencimiento no puede ser anterior a la de inicio", 422)
                if politicas.estado_efectivo(suscripcion, hoy) == "vencida":
                    politicas.validar_transicion("vencida", "activa")
                    suscripcion.estado = "activa"
                vencimiento_antes = suscripcion.fecha_vencimiento
                suscripcion.fecha_vencimiento = datos.fecha_vencimiento
                db.flush()
                respuesta = _respuesta_suscripcion(suscripcion, self._planes.buscar(db, suscripcion.plan_id))
                politicas.registrar_bitacora_de(
                    db, contexto, ENTIDAD_SUSCRIPCION, suscripcion_id, ACCION_RENOVAR,
                    {"vencimiento_antes": vencimiento_antes, "vencimiento_despues": datos.fecha_vencimiento},
                    empresa_id=empresa_id,
                )  # fmt: skip
        return respuesta

    # -- Suspender, reactivar, cancelar --------------------------------------------------------

    def cambiar_estado(
        self,
        db: Session,
        suscripcion_id: int,
        datos: SuscripcionEstadoActualizar,
        contexto: ContextoAuditoria | None = None,
    ) -> SuscripcionRespuesta:
        """Suspender, reactivar o cancelar. La transición se valida contra el
        estado EFECTIVO. Reactivar solo vale si la fecha de vencimiento no pasó
        (si pasó, primero se renueva); `vencida` solo se sale renovando."""
        hoy = hoy_utc()
        empresa_id = self._repo.empresa_de_suscripcion(db, suscripcion_id)
        with _transaccion(db):
            with en_empresa(db, empresa_id):
                suscripcion = politicas.obtener_suscripcion_de_la_empresa(db, suscripcion_id, bloquear=True)
                origen = politicas.estado_efectivo(suscripcion, hoy)
                politicas.validar_transicion(origen, datos.estado)
                if datos.estado == "activa" and (origen == "vencida" or suscripcion.fecha_vencimiento < hoy):
                    raise ConflictoError("La suscripción está vencida: renuévela primero")
                suscripcion.estado = datos.estado
                db.flush()
                respuesta = _respuesta_suscripcion(suscripcion, self._planes.buscar(db, suscripcion.plan_id))
                politicas.registrar_bitacora_de(
                    db, contexto, ENTIDAD_SUSCRIPCION, suscripcion_id, ACCION_CAMBIAR_ESTADO,
                    {"estado_antes": origen, "estado_despues": datos.estado},
                    empresa_id=empresa_id,
                )  # fmt: skip
        return respuesta

    # -- Tarea periódica --------------------------------------------------------------------------

    def vencer_pendientes(self, db: Session) -> int:
        """Persiste `vencida` en las suscripciones activas con la fecha pasada, de
        todas las empresas. Idempotente. Devuelve cuántas cambió."""
        return politicas.vencer_suscripciones(db)


# ---- Mi empresa ---------------------------------------------------------------------------------


class ConsultarMiEmpresa:
    """La empresa de quien administra (la del token, con los filtros normales).
    Sus rutas están exentas de la suscripción: funcionan con ella vencida o
    suspendida, para poder ver el estado y pedir la renovación."""

    def __init__(self) -> None:
        self._repo = EmpresaRepository()

    def _empresa(self, db: Session) -> Empresa:
        empresa = self._repo.buscar(db, exigir_empresa(db))
        if empresa is None:
            raise NoEncontradoError("Empresa no encontrada")
        return empresa

    @staticmethod
    def _respuesta(db: Session, empresa: Empresa) -> MiEmpresaRespuesta:
        return MiEmpresaRespuesta(
            id=empresa.id,
            codigo=empresa.codigo,
            nombre=empresa.nombre,
            logo_url=empresa.logo_url,
            color_acento=empresa.color_acento,
            activo=empresa.activo,
            plazo_cambio_horas=empresa.plazo_cambio_horas,
            plazo_cambio_horas_efectivo=politicas.obtener_plazo_cambio_horas(db),
        )

    def obtener(self, db: Session) -> MiEmpresaRespuesta:
        return self._respuesta(db, self._empresa(db))

    def actualizar(
        self, db: Session, datos: MiEmpresaActualizar, contexto: ContextoAuditoria | None = None
    ) -> MiEmpresaRespuesta:
        """Nombre comercial, logo, color de acento y plazo de cambio de prendas
        (`null` = el del plan). Plan, estado y código no se tocan desde aquí."""
        empresa = self._empresa(db)
        empresa_id = empresa.id
        plazo_enviado = "plazo_cambio_horas" in datos.model_fields_set
        plazo_antes = empresa.plazo_cambio_horas
        cambios = _sin_nulos(datos, EmpresaActualizar, CAMPOS_ANULABLES_EMPRESA)
        detalle = diff_campos(empresa, cambios.model_dump(exclude_unset=True), ("activo",))
        actualizada = self._repo.actualizar(db, empresa_id, cambios, commit=False)
        # La empresa es la de la sesión (el administrador que la edita). Si solo se
        # tocó el plazo, el único evento es el del plazo.
        if detalle["campos"] or not plazo_enviado:
            politicas.registrar_bitacora_de(db, contexto, ENTIDAD_EMPRESA, empresa_id, ACCION_ACTUALIZAR, detalle)
        if plazo_enviado and datos.plazo_cambio_horas != plazo_antes:
            actualizada.plazo_cambio_horas = datos.plazo_cambio_horas
            politicas.registrar_bitacora_de(
                db,
                contexto,
                ENTIDAD_EMPRESA,
                empresa_id,
                ACCION_CAMBIAR_PLAZO_CAMBIO,
                {"antes": plazo_antes, "despues": datos.plazo_cambio_horas},
            )
        db.commit()
        db.refresh(actualizada)
        return self._respuesta(db, actualizada)

    def obtener_suscripcion(self, db: Session) -> MiSuscripcionRespuesta:
        """Plan, estado efectivo, fechas, límite y uso de sucursales, y las
        funcionalidades que incluye el plan."""
        situacion = politicas.situacion_de_la_empresa(db)
        suscripcion, plan = situacion.suscripcion, situacion.plan
        return MiSuscripcionRespuesta(
            plan_codigo=plan.codigo if plan is not None else None,
            plan_nombre=plan.nombre if plan is not None else None,
            estado=situacion.estado,
            fecha_inicio=suscripcion.fecha_inicio if suscripcion is not None else None,
            fecha_vencimiento=suscripcion.fecha_vencimiento if suscripcion is not None else None,
            max_sucursales=plan.max_sucursales if plan is not None else None,
            sucursales_activas=politicas.contar_sucursales_activas(db),
            funcionalidades=politicas.funcionalidades_habilitadas(db),
        )
