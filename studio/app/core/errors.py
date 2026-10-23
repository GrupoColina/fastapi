"""Erros de dominio e handlers de excecao com formato de resposta uniforme."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class StudioError(Exception):
    """Erro de dominio do Studio, com codigo estavel e status HTTP associado."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "studio_error"

    def __init__(self, message: str, *, details: Any = None, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(StudioError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(StudioError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class UnauthorizedError(StudioError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class ForbiddenError(StudioError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class ValidationFailure(StudioError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_failed"


class RateLimitedError(StudioError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class UpstreamError(StudioError):
    """Falha ao falar com o banco alvo (ERP)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "upstream_error"


class ExecutionTimeoutError(StudioError):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    code = "execution_timeout"


def _error_body(code: str, message: str, *, details: Any = None, request_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    if request_id:
        body["error"]["request_id"] = request_id
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """Registra handlers globais na aplicacao."""

    @app.exception_handler(StudioError)
    async def _studio_error_handler(request: Request, exc: StudioError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.warning(
            "erro de dominio",
            extra={"path": request.url.path, "extra_data": {"code": exc.code, "message": exc.message}},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, details=exc.details, request_id=request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_error_body(
                "request_validation_error",
                "a requisicao nao passou na validacao",
                details=exc.errors(),
                request_id=request_id,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code, str(exc.detail), request_id=request_id),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        # O stack trace fica no log interno; o cliente recebe apenas o identificador.
        logger.exception("excecao nao tratada", extra={"path": request.url.path})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(
                "internal_error",
                "erro interno; consulte os logs com o request_id informado",
                request_id=request_id,
            ),
        )
