import datetime as dt
from dataclasses import dataclass

from fastapi import Query

from app.core.exceptions import DomainError
from app.core.tiempo import ahora_utc_naive, hoy_utc  # noqa: F401  (se reexportan: tantos módulos las importan de acá)


@dataclass
class ParametrosPaginacion:
    pagina: int
    tamanio: int

    @property
    def offset(self) -> int:
        return (self.pagina - 1) * self.tamanio


def parametros_paginacion(
    pagina: int = Query(default=1, ge=1),
    tamanio: int = Query(default=20, ge=1, le=100),
) -> ParametrosPaginacion:
    return ParametrosPaginacion(pagina=pagina, tamanio=tamanio)


DIAS_PERIODO_POR_DEFECTO = 30


@dataclass
class ParametrosPeriodo:
    desde: dt.date
    hasta: dt.date


def periodo_reportes(
    desde: dt.date | None = Query(default=None),
    hasta: dt.date | None = Query(default=None),
) -> ParametrosPeriodo:
    """Para los endpoints de reportes de `inteligencia` (P6.3): sin `desde`/`hasta` toma los últimos 30
    días. `desde` > `hasta` es un rango inválido, no un caso a tolerar."""
    hasta_final = hasta if hasta is not None else hoy_utc()
    desde_final = desde if desde is not None else hasta_final - dt.timedelta(days=DIAS_PERIODO_POR_DEFECTO)
    if desde_final > hasta_final:
        raise DomainError("El rango de fechas es inválido: 'desde' no puede ser posterior a 'hasta'")
    return ParametrosPeriodo(desde=desde_final, hasta=hasta_final)
