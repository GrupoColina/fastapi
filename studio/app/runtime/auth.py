"""Autenticacao e limite de taxa das APIs publicadas (runtime).

Estas dependencias **nao aparecem como parametros** nas rotas geradas: elas recebem a
requisicao por injecao, resolvem o principal autenticado (API key ou JWT), conferem
escopos e projeto e aplicam o limite de taxa. O principal resolvido e publicado no
``RequestContext`` para que o executor e a telemetria o consumam.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy import select

from app.core.context import RuntimePrincipal, get_request_context
from app.core.errors import ForbiddenError, RateLimitedError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import TokenError, decode_token
from app.db.base import utcnow
from app.db.models import ROLE_ADMIN, ProjectAccess, User
from app.runtime.state import StudioRuntime, get_runtime
from app.schemas.definition import AuthSpec
from app.services.audit import find_api_key
from app.services.compiler import CompiledEndpoint

logger = get_logger("studio.runtime.auth")


# ---------------------------------------------------------------------------
# Dependencia ligada ao endpoint
# ---------------------------------------------------------------------------
def runtime_auth_dependency(compiled: CompiledEndpoint):
    """Cria a dependencia de autenticacao especifica deste endpoint.

    Devolve uma funcao **sincrona** para que o FastAPI a execute em thread pool, sem
    bloquear o event loop durante as consultas ao banco de metadados.
    """
    spec = compiled.definition.auth
    project_id = compiled.project_id
    endpoint_id = compiled.endpoint_id

    def _dependency(request: Request) -> None:
        runtime = get_runtime()
        principal = resolve_principal(request, spec, runtime, project_id=project_id)
        get_request_context().principal = principal
        enforce_rate_limit(runtime, spec, principal, request, endpoint_id=endpoint_id)

    _dependency.__name__ = f"auth_{compiled.operation_id}"
    return _dependency


# ---------------------------------------------------------------------------
# Resolucao do principal
# ---------------------------------------------------------------------------
def resolve_principal(
    request: Request,
    spec: AuthSpec,
    runtime: StudioRuntime,
    *,
    project_id: int,
) -> RuntimePrincipal:
    """Resolve a identidade do consumidor conforme o modo declarado no endpoint."""
    if spec.mode == "none":
        return RuntimePrincipal(kind="none", subject="anonymous")

    if spec.mode == "api_key":
        raw = request.headers.get("x-api-key") or _bearer(request)
        if not raw:
            raise UnauthorizedError(
                "credencial ausente: informe a API key no cabecalho X-API-Key"
            )
        return _principal_from_api_key(runtime, raw, spec, project_id=project_id)

    token = _bearer(request)
    if not token:
        raise UnauthorizedError("credencial ausente: informe o token Bearer")
    return _principal_from_jwt(runtime, token, spec, project_id=project_id)


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def _principal_from_api_key(
    runtime: StudioRuntime, raw: str, spec: AuthSpec, *, project_id: int
) -> RuntimePrincipal:
    with runtime.database.session() as session:
        key = find_api_key(session, raw)
        if key is None:
            # Mensagem uniforme: nao distingue "inexistente" de "revogada".
            raise UnauthorizedError("API key invalida, expirada ou revogada")
        if key.expires_at is not None and key.expires_at < utcnow():
            raise UnauthorizedError("API key expirada")

        if key.project_id is not None and key.project_id != project_id:
            raise ForbiddenError("esta API key nao pertence ao projeto do endpoint")

        principal = RuntimePrincipal(
            kind="api_key",
            subject=f"api-key:{key.id}",
            scopes=frozenset(key.scopes or []),
            api_key_id=key.id,
            project_id=key.project_id,
        )

    _check_scopes(principal, spec)
    return principal


def _principal_from_jwt(
    runtime: StudioRuntime, token: str, spec: AuthSpec, *, project_id: int
) -> RuntimePrincipal:
    try:
        payload = decode_token(
            token,
            secret=runtime.settings.secret_key,
            algorithm=runtime.settings.jwt_algorithm,
            expected_type="access",
        )
    except TokenError as exc:
        raise UnauthorizedError(str(exc)) from exc

    subject = str(payload.get("sub") or "")
    if not subject.isdigit():
        raise UnauthorizedError("token sem identificacao de usuario valida")

    with runtime.database.session() as session:
        user = session.get(User, int(subject))
        if user is None or not user.is_active:
            raise UnauthorizedError("usuario inexistente ou inativo")

        scopes = frozenset({"*"} if user.role == ROLE_ADMIN else {user.role})
        principal = RuntimePrincipal(
            kind="jwt",
            subject=user.email,
            scopes=scopes,
            user_id=user.id,
            project_id=project_id,
        )

        if user.role != ROLE_ADMIN:
            grant = session.scalar(
                select(ProjectAccess).where(
                    ProjectAccess.project_id == project_id,
                    ProjectAccess.user_id == user.id,
                )
            )
            if grant is None:
                raise ForbiddenError("o usuario autenticado nao tem acesso a este projeto")

    _check_scopes(principal, spec)
    return principal


def _check_scopes(principal: RuntimePrincipal, spec: AuthSpec) -> None:
    for scope in spec.scopes:
        if not principal.has_scope(scope):
            raise ForbiddenError(f"escopo necessario ausente: '{scope}'")


# ---------------------------------------------------------------------------
# Limite de taxa
# ---------------------------------------------------------------------------
def enforce_rate_limit(
    runtime: StudioRuntime,
    spec: AuthSpec,
    principal: RuntimePrincipal,
    request: Request,
    *,
    endpoint_id: int,
) -> None:
    """Aplica a janela deslizante por identidade (chave > usuario > IP)."""
    limit = spec.rate_limit_per_minute or runtime.settings.rate_limit_per_minute
    if limit <= 0:
        return

    if principal.api_key_id is not None:
        identity = f"key:{principal.api_key_id}"
    elif principal.user_id is not None:
        identity = f"user:{principal.user_id}"
    else:
        identity = f"ip:{_client_ip(request)}"

    state = runtime.rate_limiter.check(f"runtime:{endpoint_id}:{identity}", limit)
    if not state.allowed:
        raise RateLimitedError(
            "limite de requisicoes excedido para este endpoint",
            details={
                "limit_per_minute": limit,
                "retry_after_seconds": state.retry_after_seconds,
            },
        )


def _client_ip(request: Request) -> str:
    context = get_request_context()
    if context.client_ip:
        return context.client_ip
    return request.client.host if request.client else "unknown"
