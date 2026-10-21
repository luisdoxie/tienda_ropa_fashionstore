"""Multitenant: la empresa de la sesión y el relleno de `empresa_id` al insertar.

Infraestructura transversal (no es un paquete de negocio). Aquí vive lo único
que sabe en qué empresa se está trabajando:

- La empresa se guarda en `Session.info` (explícita por sesión; no depende de
  hilos, de async ni de variables de contexto, y se fija igual en una tarea en
  segundo plano o en una prueba).
- `EmpresaMixin` da la columna `empresa_id` (NOT NULL, FK, índice) a las tablas
  propias de cada empresa; `EmpresaOpcionalMixin` la da con NULL permitido
  (solo `usuario`: NULL = superadministrador de la plataforma).
- Un evento `before_flush` rellena `empresa_id` en los objetos nuevos con la
  empresa de la sesión, y se niega a crear un registro en otra empresa.

Las FK se escriben como cadena ("empresa.id"): este módulo no importa ningún
paquete de negocio. El FILTRADO de lecturas por empresa y el cableado con el
token no están aquí: son del punto único de `core/crud_base.py` y de
`core/deps.py`. Fuera de este módulo, ningún paquete fija ni cambia la empresa
de la sesión.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, event
from sqlalchemy.orm import Mapped, Session, mapped_column

CLAVE_EMPRESA = "empresa_id"


class EmpresaNoDefinidaError(RuntimeError):
    """Error de programación: se operó sin empresa o contra otra empresa.

    Nunca debe llegar al usuario: una petición real fija la empresa desde el
    token antes de tocar datos.
    """


class EmpresaMixin:
    """Tabla propia de una empresa: `empresa_id` NOT NULL."""

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), nullable=False, index=True)


class EmpresaOpcionalMixin:
    """Como `EmpresaMixin` pero con NULL permitido (superadministrador)."""

    empresa_id: Mapped[int | None] = mapped_column(ForeignKey("empresa.id"), nullable=True, index=True)


def fijar_empresa(db: Session, empresa_id: int | None) -> None:
    """Fija la empresa de la sesión. `None` la deja sin empresa.

    Si la sesión ya trabajaba con OTRA empresa se vacía el mapa de identidad
    (`expunge_all`) para no reutilizar objetos de la empresa anterior.
    """
    actual = db.info.get(CLAVE_EMPRESA)
    if actual is not None and actual != empresa_id:
        db.expunge_all()
    if empresa_id is None:
        db.info.pop(CLAVE_EMPRESA, None)
    else:
        db.info[CLAVE_EMPRESA] = empresa_id


def empresa_de(db: Session) -> int | None:
    """Empresa fijada en la sesión, o `None` si no tiene."""
    return db.info.get(CLAVE_EMPRESA)


def exigir_empresa(db: Session) -> int:
    """Empresa de la sesión; lanza `EmpresaNoDefinidaError` si no hay."""
    empresa_id = empresa_de(db)
    if empresa_id is None:
        raise EmpresaNoDefinidaError("La sesión no tiene empresa definida")
    return empresa_id


@event.listens_for(Session, "before_flush")
def _rellenar_empresa(session: Session, flush_context, instances) -> None:
    de_la_sesion = empresa_de(session)
    for obj in session.new:
        if isinstance(obj, EmpresaMixin):
            if obj.empresa_id is None:
                obj.empresa_id = exigir_empresa(session)
            elif de_la_sesion is not None and obj.empresa_id != de_la_sesion:
                raise EmpresaNoDefinidaError(
                    f"{type(obj).__name__} con empresa_id={obj.empresa_id} en una sesión de la empresa {de_la_sesion}"
                )
            # Sesión sin empresa y empresa_id explícito: lo hace el
            # superadministrador al dar de alta una empresa (suscripción,
            # administrador). Se respeta el valor dado.
        elif isinstance(obj, EmpresaOpcionalMixin):
            if obj.empresa_id is None:
                # Sin empresa en la sesión queda en NULL (superadministrador).
                obj.empresa_id = de_la_sesion
            elif de_la_sesion is not None and obj.empresa_id != de_la_sesion:
                raise EmpresaNoDefinidaError(
                    f"{type(obj).__name__} con empresa_id={obj.empresa_id} en una sesión de la empresa {de_la_sesion}"
                )
