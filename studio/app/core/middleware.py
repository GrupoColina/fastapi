"""Middleware transversal: correlacao, logs de acesso e cabecalhos de seguranca."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import RequestContext, clear_request_context, set_request_context
from app.core.logging import get_logger

logger = get_logger("studio.access")

REQUEST_ID_HEADER = "X-Request-ID"
_NO_LOG_PREFIXES = ("/static",)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Atribui um ``request_id`` a cada requisicao e loga o acesso."""

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming and len(incoming) <= 64 else uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        client_ip = request.client.host if request.client else ""
        set_request_context(
            RequestContext(
                request_id=request_id,
                client_ip=client_ip,
                method=request.method,
                path=request.url.path,
            )
        )

        started = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "requisicao falhou",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            raise
        finally:
            clear_request_context()

        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")

        if not request.url.path.startswith(_NO_LOG_PREFIXES):
            logger.info(
                "acesso",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        return response
