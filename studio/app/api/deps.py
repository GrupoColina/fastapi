"""Dependencias compartilhadas da API administrativa."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.context import get_request_context
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import TokenError, decode_token
from app.db.models import ROLE_RANK, User
from app.runtime.state import StudioRuntime, get_runtime

bearer_scheme = HTTPBearer(auto_error=False, description="Token de acesso (JWT) do painel")


def get_runtime_dep() -> StudioRuntime:
    """Runtime ativo da aplicacao."""
    return get_runtime()


def get_session() -> Iterator[Session]:
    """Sessao transacional por requisicao (commit no sucesso, rollback no erro)."""
    runtime = get_runtime()
    session = runtime.database.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    """Resolve o usuario autenticado a partir do access token."""
    runtime = get_runtime()
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("credencial ausente: informe o token Bearer")

    try:
        payload = decode_token(
            credentials.credentials,
            secret=runtime.settings.secret_key,
            algorithm=runtime.settings.jwt_algorithm,
            expected_type="access",
        )
    except TokenError as exc:
        raise UnauthorizedError(str(exc)) from exc

    subject = str(payload.get("sub") or "")
    user = session.get(User, int(subject)) if subject.isdigit() else None
    if user is None or not user.is_active:
        raise UnauthorizedError("usuario inexistente ou inativo")

    get_request_context().extra["user_id"] = user.id
    return user


def require_role(minimum: str):
    """Dependencia que exige um papel minimo (hierarquia em ``ROLE_RANK``)."""
    needed = ROLE_RANK[minimum]

    def _dependency(user: User = Depends(current_user)) -> User:
        if user.role_rank < needed:
            raise ForbiddenError(
                f"acao restrita: requer papel '{minimum}' ou superior (papel atual: '{user.role}')"
            )
        return user

    return _dependency


def client_ip() -> str:
    """IP do cliente, conforme registrado pelo middleware de contexto."""
    return get_request_context().client_ip
