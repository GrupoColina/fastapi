"""Autenticacao do painel: login, refresh, logout, perfil e troca de senha."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_session
from app.core.errors import RateLimitedError, UnauthorizedError, ValidationFailure
from app.core.logging import get_logger
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    password_policy_errors,
    verify_password,
)
from app.db.base import utcnow
from app.db.models import RefreshTokenRecord, User
from app.runtime.state import get_runtime
from app.schemas.api import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserOut,
)
from app.services import audit

router = APIRouter(prefix="/auth", tags=["Admin · Autenticação"])
logger = get_logger("studio.api.auth")


def issue_tokens(session: Session, user: User, runtime) -> TokenResponse:  # noqa: ANN001
    """Emite o par access/refresh e registra o refresh para permitir revogacao."""
    settings = runtime.settings
    access, _ = create_access_token(
        subject=str(user.id),
        secret=settings.secret_key,
        algorithm=settings.jwt_algorithm,
        minutes=settings.access_token_minutes,
        extra_claims={"role": user.role, "email": user.email},
    )
    refresh, expires_at = create_refresh_token(
        subject=str(user.id),
        secret=settings.secret_key,
        algorithm=settings.jwt_algorithm,
        days=settings.refresh_token_days,
    )
    claims = decode_token(
        refresh,
        secret=settings.secret_key,
        algorithm=settings.jwt_algorithm,
        expected_type="refresh",
    )
    session.add(
        RefreshTokenRecord(
            jti=str(claims["jti"]),
            user_id=user.id,
            expires_at=expires_at,
        )
    )
    session.flush()
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse, summary="Autentica o administrador")
def login(
    payload: LoginRequest, request: Request, session: Session = Depends(get_session)
) -> TokenResponse:
    runtime = get_runtime()
    email = payload.email.strip().lower()
    tracker = runtime.login_tracker
    client = audit_request_context(request)

    if tracker.is_locked(email):
        raise RateLimitedError(
            "muitas tentativas de login para este identificador; aguarde alguns minutos"
        )

    user = session.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        tracker.register_failure(email)
        audit.record(
            session,
            action=audit.ACTION_LOGIN_FAILURE,
            actor_email=email,
            resource_type="user",
            context={"motivo": "credenciais invalidas"},
            ip=client["ip"],
            request_id=client["request_id"],
            success=False,
        )
        raise UnauthorizedError("credenciais invalidas")

    if not user.is_active:
        raise UnauthorizedError("usuario inativo")
    if user.locked_until is not None and user.locked_until > utcnow():
        raise UnauthorizedError("usuario temporariamente bloqueado")

    tracker.register_success(email)
    user.last_login_at = utcnow()
    user.failed_login_count = 0
    user.locked_until = None
    tokens = issue_tokens(session, user, runtime)
    audit.record(
        session,
        action=audit.ACTION_LOGIN_SUCCESS,
        actor_user_id=user.id,
        actor_email=user.email,
        resource_type="user",
        resource_id=user.id,
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return tokens


@router.post("/refresh", response_model=TokenResponse, summary="Renova o access token")
def refresh_tokens(
    payload: RefreshRequest, request: Request, session: Session = Depends(get_session)
) -> TokenResponse:
    runtime = get_runtime()
    settings = runtime.settings
    try:
        claims = decode_token(
            payload.refresh_token,
            secret=settings.secret_key,
            algorithm=settings.jwt_algorithm,
            expected_type="refresh",
        )
    except TokenError as exc:
        raise UnauthorizedError(str(exc)) from exc

    record = session.scalar(
        select(RefreshTokenRecord).where(RefreshTokenRecord.jti == str(claims.get("jti")))
    )
    if record is None or record.revoked_at is not None:
        raise UnauthorizedError("refresh token revogado ou desconhecido")
    if record.expires_at < utcnow():
        raise UnauthorizedError("refresh token expirado")

    user = session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("usuario inexistente ou inativo")

    # Rotacao de refresh: o token anterior deixa de valer.
    record.revoked_at = utcnow()
    tokens = issue_tokens(session, user, runtime)
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_TOKEN_REFRESH,
        actor_user_id=user.id,
        actor_email=user.email,
        resource_type="user",
        resource_id=user.id,
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return tokens


@router.post("/logout", summary="Revoga o refresh token informado")
def logout(
    payload: RefreshRequest, request: Request, session: Session = Depends(get_session)
) -> dict[str, bool]:
    runtime = get_runtime()
    settings = runtime.settings
    try:
        claims = decode_token(
            payload.refresh_token,
            secret=settings.secret_key,
            algorithm=settings.jwt_algorithm,
            expected_type="refresh",
        )
    except TokenError:
        # Logout idempotente: token invalido nao e erro para o cliente.
        return {"revoked": False}

    record = session.scalar(
        select(RefreshTokenRecord).where(RefreshTokenRecord.jti == str(claims.get("jti")))
    )
    if record is not None and record.revoked_at is None:
        record.revoked_at = utcnow()
        client = audit_request_context(request)
        audit.record(
            session,
            action=audit.ACTION_LOGOUT,
            actor_user_id=record.user_id,
            resource_type="user",
            resource_id=record.user_id,
            ip=client["ip"],
            request_id=client["request_id"],
        )
    return {"revoked": True}


@router.get("/me", response_model=UserOut, summary="Perfil do usuario autenticado")
def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/change-password", response_model=UserOut, summary="Troca a propria senha")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> User:
    runtime = get_runtime()
    if not verify_password(payload.current_password, user.password_hash):
        raise UnauthorizedError("senha atual incorreta")

    errors = password_policy_errors(payload.new_password, runtime.settings.password_min_length)
    if errors:
        raise ValidationFailure("a nova senha nao atende a politica minima", details={"errors": errors})

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    session.flush()

    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_USER_PASSWORD_CHANGE,
        actor_user_id=user.id,
        actor_email=user.email,
        resource_type="user",
        resource_id=user.id,
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return user


def audit_request_context(request: Request) -> dict[str, str]:
    """IP e request_id para a trilha de auditoria."""
    from app.core.context import get_request_context  # noqa: PLC0415

    context = get_request_context()
    return {
        "ip": context.client_ip or (request.client.host if request.client else ""),
        "request_id": context.request_id or getattr(request.state, "request_id", "") or "",
    }
