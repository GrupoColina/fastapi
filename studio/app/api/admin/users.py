"""Gestao de usuarios e papeis (RBAC)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.admin.auth import audit_request_context
from app.api.deps import current_user, get_session, require_role
from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.core.security import hash_password, password_policy_errors
from app.db.base import utcnow
from app.db.models import ROLE_ADMIN, User
from app.runtime.state import get_runtime
from app.schemas.api import UserCreate, UserOut, UserUpdate
from app.services import audit

router = APIRouter(prefix="/users", tags=["Admin · Usuários"])


def validate_password(password: str) -> None:
    errors = password_policy_errors(password, get_runtime().settings.password_min_length)
    if errors:
        raise ValidationFailure("a senha nao atende a politica minima", details={"errors": errors})


@router.get("", response_model=list[UserOut], summary="Lista usuarios")
def list_users(
    _: User = Depends(require_role("admin")), session: Session = Depends(get_session)
) -> list[User]:
    return list(session.scalars(select(User).order_by(User.id)))


@router.post("", response_model=UserOut, status_code=201, summary="Cria usuario")
def create_user(
    payload: UserCreate,
    request: Request,
    actor: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> User:
    email = payload.email.strip().lower()
    if session.scalar(select(User).where(func.lower(User.email) == email)) is not None:
        raise ConflictError(f"ja existe um usuario com o e-mail '{email}'")
    validate_password(payload.password)

    user = User(
        email=email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=payload.is_active,
    )
    session.add(user)
    session.flush()

    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_USER_CREATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="user",
        resource_id=user.id,
        context={"papel": user.role},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return user


@router.get("/{user_id}", response_model=UserOut, summary="Detalha um usuario")
def get_user(
    user_id: int,
    _: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError(f"usuario {user_id} nao encontrado")
    return user


@router.patch("/{user_id}", response_model=UserOut, summary="Atualiza um usuario")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    actor: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError(f"usuario {user_id} nao encontrado")

    if payload.name is not None:
        user.name = payload.name
    if payload.role is not None:
        if user.id == actor.id and payload.role != ROLE_ADMIN:
            raise ValidationFailure("nao e possivel remover o proprio papel de administrador")
        user.role = payload.role
    if payload.is_active is not None:
        if user.id == actor.id and not payload.is_active:
            raise ValidationFailure("nao e possivel desativar o proprio usuario")
        user.is_active = payload.is_active
    if payload.password is not None:
        validate_password(payload.password)
        user.password_hash = hash_password(payload.password)
        user.must_change_password = False
        user.updated_at = utcnow()

    session.flush()
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_USER_UPDATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="user",
        resource_id=user.id,
        context={"campos": sorted(payload.model_dump(exclude_unset=True))},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return user


@router.delete("/{user_id}", status_code=204, summary="Remove um usuario")
def delete_user(
    user_id: int,
    request: Request,
    actor: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError(f"usuario {user_id} nao encontrado")
    if user.id == actor.id:
        raise ValidationFailure("nao e possivel remover o proprio usuario")

    session.delete(user)
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_USER_DELETE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="user",
        resource_id=user_id,
        ip=client["ip"],
        request_id=client["request_id"],
    )
    session.flush()
