"""Lectura de las rutas de la app por introspección: qué permiso y qué
funcionalidad de plan exige cada una. Lo usan el generador del registro de rutas
y las pruebas guardianas (E05, 4.1)."""

from fastapi.routing import APIRoute

from app.main import app

METODOS_IGNORADOS = {"HEAD", "OPTIONS"}


def rutas_api() -> list[APIRoute]:
    return [ruta for ruta in app.routes if isinstance(ruta, APIRoute)]


def metodo_y_ruta() -> set[tuple[str, str]]:
    """Conjunto (método, ruta) de todas las rutas API, sin HEAD ni OPTIONS."""
    return {(metodo, ruta.path) for ruta in rutas_api() for metodo in ruta.methods - METODOS_IGNORADOS}


def _llamadas(dependant):
    """Todas las funciones de dependencia de una ruta, recorriendo el árbol."""
    for sub in dependant.dependencies:
        if sub.call is not None:
            yield sub.call
        yield from _llamadas(sub)


def permisos_de(ruta: APIRoute) -> list[str]:
    return sorted({c.permiso for c in _llamadas(ruta.dependant) if hasattr(c, "permiso")})


def funcionalidades_de(ruta: APIRoute) -> list[str]:
    return sorted({c.funcionalidad for c in _llamadas(ruta.dependant) if hasattr(c, "funcionalidad")})


def parametros_de_consulta(ruta: APIRoute) -> set[str]:
    """Nombres de los parámetros de query de la ruta, incluidos los de sus dependencias."""

    def recorrer(dependant):
        yield from (p.alias for p in dependant.query_params)
        for sub in dependant.dependencies:
            yield from recorrer(sub)

    return set(recorrer(ruta.dependant))


def ruta_por_clave(metodo: str, path: str) -> APIRoute:
    return next(r for r in rutas_api() if r.path == path and metodo in r.methods)


def nombres_de_dependencias(ruta: APIRoute) -> set[str]:
    """Nombres de las funciones de dependencia (get_current_user, etc.)."""
    return {getattr(c, "__name__", "") for c in _llamadas(ruta.dependant)}
