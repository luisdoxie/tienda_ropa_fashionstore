import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Error de regla de negocio. No expone detalles de implementación."""

    def __init__(self, mensaje: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        self.mensaje = mensaje
        self.status_code = status_code
        super().__init__(mensaje)


class NoEncontradoError(DomainError):
    def __init__(self, mensaje: str = "Recurso no encontrado") -> None:
        super().__init__(mensaje, status_code=status.HTTP_404_NOT_FOUND)


class ConflictoError(DomainError):
    def __init__(self, mensaje: str = "Conflicto con el estado actual del recurso") -> None:
        super().__init__(mensaje, status_code=status.HTTP_409_CONFLICT)


class PermisoDenegadoError(DomainError):
    def __init__(self, mensaje: str = "No tiene permiso para realizar esta acción") -> None:
        super().__init__(mensaje, status_code=status.HTTP_403_FORBIDDEN)


class NoAutenticadoError(DomainError):
    def __init__(self, mensaje: str = "No autenticado") -> None:
        super().__init__(mensaje, status_code=status.HTTP_401_UNAUTHORIZED)


class DemasiadosIntentosError(DomainError):
    """429 con la cabecera `Retry-After` (segundos) que el handler agrega."""

    def __init__(self, reintentar_en: int, mensaje: str = "Demasiados intentos. Intente nuevamente mas tarde.") -> None:
        super().__init__(mensaje, status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        self.reintentar_en = reintentar_en


def registrar_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        cabeceras = None
        if isinstance(exc, DemasiadosIntentosError):
            cabeceras = {"Retry-After": str(exc.reintentar_en)}
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.mensaje}, headers=cabeceras)

    @app.exception_handler(Exception)
    async def excepcion_no_controlada_handler(request: Request, exc: Exception) -> JSONResponse:
        """Red de seguridad para lo que ningún DomainError esperaba
        (IntegrityError de SQLAlchemy, KeyError, etc.): sin esto, FastAPI
        deja pasar el 500 genérico de Starlette sin loguear nada y (en
        debug) exponiendo el traceback real al cliente. Nunca se expone
        `str(exc)` en la respuesta -- puede contener detalles internos
        (nombres de tabla, columnas, rutas)."""
        logger.exception("Excepción no controlada en %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"})
