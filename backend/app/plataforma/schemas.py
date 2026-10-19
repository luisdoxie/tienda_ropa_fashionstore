from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


# ---- Seguridad ----


# ---- Roles ----------------------------------------------------------------


class RolCrear(BaseModel):
    nombre: str = Field(max_length=40)
    descripcion: str | None = Field(default=None, max_length=200)


class RolActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=40)
    descripcion: str | None = Field(default=None, max_length=200)


class PermisoRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    modulo: str
    descripcion: str | None = None


class RolRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    descripcion: str | None = None
    activo: bool
    permisos: list[PermisoRespuesta] = []


class AsignarPermisosRequest(BaseModel):
    codigos_permiso: list[str]


# ---- Usuarios ---------------------------------------------------------------


class UsuarioCrear(BaseModel):
    nombre: str = Field(max_length=60)
    apellido: str = Field(max_length=60)
    email: EmailStr
    telefono: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=72)


class UsuarioActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=60)
    apellido: str | None = Field(default=None, max_length=60)
    telefono: str | None = Field(default=None, max_length=20)
    activo: bool | None = None


class AsignarRolesRequest(BaseModel):
    nombres_rol: list[str]


class UsuarioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    apellido: str
    email: str
    telefono: str | None = None
    activo: bool
    roles: list[str] = []

    @classmethod
    def from_modelo(cls, usuario) -> "UsuarioRespuesta":
        return cls(
            id=usuario.id,
            nombre=usuario.nombre,
            apellido=usuario.apellido,
            email=usuario.email,
            telefono=usuario.telefono,
            activo=usuario.activo,
            roles=[r.nombre for r in usuario.roles],
        )


class UsuarioYoRespuesta(UsuarioRespuesta):
    permisos: list[str] = []


# ---- Autenticación ----------------------------------------------------------


class RegistroRequest(BaseModel):
    nombre: str = Field(max_length=60)
    apellido: str = Field(max_length=60)
    email: EmailStr
    telefono: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=72)
    ci_nit: str | None = Field(default=None, max_length=20)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RecuperarRequest(BaseModel):
    email: EmailStr


class RecuperarConfirmarRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=72)


class RecuperarRespuesta(BaseModel):
    detail: str
    token_dev: str | None = None


class TokenRespuesta(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ---- Perfil de cliente --------------------------------------------------------


class ClientePerfilRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nombre: str
    apellido: str
    email: str
    telefono: str | None = None
    ci_nit: str | None = None
    razon_social: str | None = None
    fecha_nacimiento: dt.date | None = None
    estatura_cm: int | None = None
    preferencia_ajuste: str | None = None
    acepta_datos_foto: bool

    @classmethod
    def from_modelo(cls, cliente) -> "ClientePerfilRespuesta":
        return cls(
            nombre=cliente.usuario.nombre,
            apellido=cliente.usuario.apellido,
            email=cliente.usuario.email,
            telefono=cliente.usuario.telefono,
            ci_nit=cliente.ci_nit,
            razon_social=cliente.razon_social,
            fecha_nacimiento=cliente.fecha_nacimiento,
            estatura_cm=cliente.estatura_cm,
            preferencia_ajuste=cliente.preferencia_ajuste,
            acepta_datos_foto=cliente.acepta_datos_foto,
        )


class ClientePerfilActualizar(BaseModel):
    telefono: str | None = Field(default=None, max_length=20)
    ci_nit: str | None = Field(default=None, max_length=20)
    razon_social: str | None = Field(default=None, max_length=120)
    fecha_nacimiento: dt.date | None = None
    estatura_cm: int | None = Field(default=None, ge=100, le=250)
    # Mismos valores que el CHECK de la tabla `cliente`: un valor distinto
    # tiene que ser un 422 claro, no un error de la base.
    preferencia_ajuste: Literal["ajustado", "regular", "holgado"] | None = None
    acepta_datos_foto: bool | None = None


# ---- Notificaciones ----


class NotificacionRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    titulo: str
    mensaje: str | None
    tipo: str | None
    referencia_id: int | None
    leida: bool
    creado_en: dt.datetime


# ---- Organización ----


# ---- Ciudades -----------------------------------------------------------


class CiudadCrear(BaseModel):
    nombre: str = Field(max_length=60)
    departamento: str | None = Field(default=None, max_length=60)


class CiudadActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=60)
    departamento: str | None = Field(default=None, max_length=60)


class CiudadRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    departamento: str | None = None
    activo: bool


# ---- Sucursales -----------------------------------------------------------
# SucursalRespuesta es la que se expone públicamente (GET /sucursales):
# no incluye datos de empleados, ni los va a incluir nunca. No se agrega
# una relación con Empleado al modelo por esa misma razón.


class SucursalCrear(BaseModel):
    ciudad_id: int
    codigo: str = Field(max_length=15)
    nombre: str = Field(max_length=80)
    direccion: str = Field(max_length=200)
    telefono: str | None = Field(default=None, max_length=20)
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_deposito: bool = False


class SucursalActualizar(BaseModel):
    ciudad_id: int | None = None
    codigo: str | None = Field(default=None, max_length=15)
    nombre: str | None = Field(default=None, max_length=80)
    direccion: str | None = Field(default=None, max_length=200)
    telefono: str | None = Field(default=None, max_length=20)
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_deposito: bool | None = None
    activo: bool | None = None


class SucursalRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ciudad_id: int
    codigo: str
    nombre: str
    direccion: str
    telefono: str | None = None
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_deposito: bool
    activo: bool
    creado_en: dt.datetime


# ---- Horarios de sucursal --------------------------------------------------


class HorarioCrear(BaseModel):
    dia_semana: int = Field(ge=1, le=7)
    hora_apertura: dt.time
    hora_cierre: dt.time

    @model_validator(mode="after")
    def _validar_rango(self) -> "HorarioCrear":
        if self.hora_cierre <= self.hora_apertura:
            raise ValueError("hora_cierre debe ser posterior a hora_apertura")
        return self


class HorarioActualizar(BaseModel):
    hora_apertura: dt.time | None = None
    hora_cierre: dt.time | None = None

    @model_validator(mode="after")
    def _validar_rango(self) -> "HorarioActualizar":
        if (
            self.hora_apertura is not None
            and self.hora_cierre is not None
            and self.hora_cierre <= self.hora_apertura
        ):
            raise ValueError("hora_cierre debe ser posterior a hora_apertura")
        return self


class HorarioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sucursal_id: int
    dia_semana: int
    hora_apertura: dt.time
    hora_cierre: dt.time


# ---- Empleados ----------------------------------------------------------


class EmpleadoCrear(BaseModel):
    usuario_id: int
    sucursal_id: int | None = None
    ci: str | None = Field(default=None, max_length=20)
    cargo: str | None = Field(default=None, max_length=60)
    fecha_ingreso: dt.date | None = None


class EmpleadoActualizar(BaseModel):
    sucursal_id: int | None = None
    ci: str | None = Field(default=None, max_length=20)
    cargo: str | None = Field(default=None, max_length=60)
    fecha_ingreso: dt.date | None = None
    activo: bool | None = None


class EmpleadoRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int
    usuario_nombre: str | None = None
    usuario_apellido: str | None = None
    sucursal_id: int | None = None
    sucursal_nombre: str | None = None
    ci: str | None = None
    cargo: str | None = None
    fecha_ingreso: dt.date | None = None
    activo: bool
