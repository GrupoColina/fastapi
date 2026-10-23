"""API keys de consumo das APIs publicadas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin.auth import audit_request_context
from app.api.deps import current_user, get_session, require_role
from app.core.errors import NotFoundError, ValidationFailure
from app.core.security import generate_api_key
from app.db.base import utcnow
from app.db.models import ApiKey, Project, User
from app.schemas.api import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.services import audit

router = APIRouter(prefix="/api-keys", tags=["Admin · API keys"])


@router.get("", response_model=list[ApiKeyOut], summary="Lista API keys")
def list_api_keys(
    project_id: int | None = Query(default=None),
    _: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> list[ApiKey]:
    statement = select(ApiKey).order_by(ApiKey.id)
    if project_id is not None:
        statement = statement.where(ApiKey.project_id == project_id)
    return list(session.scalars(statement))


@router.post("", response_model=ApiKeyCreated, status_code=201, summary="Cria uma API key")
def create_api_key(
    payload: ApiKeyCreate,
    request: Request,
    actor: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> ApiKeyCreated:
    if payload.project_id is not None and session.get(Project, payload.project_id) is None:
        raise NotFoundError(f"projeto {payload.project_id} nao encontrado")

    generated = generate_api_key(payload.environment)
    record = ApiKey(
        project_id=payload.project_id,
        name=payload.name,
        key_prefix=generated.prefix,
        key_hash=generated.hashed,
        environment=generated.environment,
        scopes=list(payload.scopes),
        expires_at=payload.expires_at,
        created_by=actor.id,
    )
    session.add(record)
    session.flush()

    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_APIKEY_CREATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="api_key",
        resource_id=record.id,
        context={
            "prefixo": record.key_prefix,
            "ambiente": record.environment,
            "escopos": list(record.scopes),
            "projeto": record.project_id,
        },
        ip=client["ip"],
        request_id=client["request_id"],
    )
    # O segredo em claro e devolvido **somente** nesta resposta.
    return ApiKeyCreated(**ApiKeyOut.model_validate(record).model_dump(), plaintext=generated.plaintext)


@router.post("/{key_id}/revoke", response_model=ApiKeyOut, summary="Revoga uma API key")
def revoke_api_key(
    key_id: int,
    request: Request,
    actor: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> ApiKey:
    record = session.get(ApiKey, key_id)
    if record is None:
        raise NotFoundError(f"API key {key_id} nao encontrada")
    if record.revoked_at is not None:
        raise ValidationFailure("esta API key ja esta revogada")

    record.is_active = False
    record.revoked_at = utcnow()
    session.flush()

    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_APIKEY_REVOKE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="api_key",
        resource_id=record.id,
        context={"prefixo": record.key_prefix},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return record


@router.delete("/{key_id}", status_code=204, summary="Remove uma API key")
def delete_api_key(
    key_id: int,
    request: Request,
    actor: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> None:
    record = session.get(ApiKey, key_id)
    if record is None:
        raise NotFoundError(f"API key {key_id} nao encontrada")

    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_APIKEY_DELETE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="api_key",
        resource_id=record.id,
        context={"prefixo": record.key_prefix},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    session.delete(record)
