"""Trilha de auditoria e telemetria de requisicoes.

Regra: campos sensiveis sao registrados **apenas como chave e comprimento**, nunca em
claro. Toda acao administrativa relevante passa por :func:`record`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.logging import PIIRedactor, get_logger
from app.core.security import constant_time_equals, hash_api_key
from app.db.models import ApiKey, AuditLog, RequestLog
from app.db.base import utcnow

logger = get_logger("studio.audit")

# Acoes auditadas. Lista fechada para evitar strings soltas pelo codigo.
ACTION_LOGIN_SUCCESS = "auth.login.success"
ACTION_LOGIN_FAILURE = "auth.login.failure"
ACTION_LOGOUT = "auth.logout"
ACTION_TOKEN_REFRESH = "auth.token.refresh"
ACTION_USER_CREATE = "user.create"
ACTION_USER_UPDATE = "user.update"
ACTION_USER_DELETE = "user.delete"
ACTION_USER_PASSWORD_CHANGE = "user.password.change"
ACTION_PROJECT_CREATE = "project.create"
ACTION_PROJECT_UPDATE = "project.update"
ACTION_PROJECT_DELETE = "project.delete"
ACTION_DATASOURCE_CREATE = "datasource.create"
ACTION_DATASOURCE_UPDATE = "datasource.update"
ACTION_DATASOURCE_DELETE = "datasource.delete"
ACTION_DATASOURCE_TEST = "datasource.test"
ACTION_DATASOURCE_INTROSPECT = "datasource.introspect"
ACTION_DATASOURCE_OBJECT_AUTHORIZE = "datasource.object.authorize"
ACTION_ENDPOINT_CREATE = "endpoint.create"
ACTION_ENDPOINT_UPDATE = "endpoint.update"
ACTION_ENDPOINT_DELETE = "endpoint.delete"
ACTION_VERSION_CREATE = "endpoint.version.create"
ACTION_VERSION_VALIDATE = "endpoint.version.validate"
ACTION_VERSION_PUBLISH = "endpoint.version.publish"
ACTION_VERSION_ROLLBACK = "endpoint.version.rollback"
ACTION_VERSION_ARCHIVE = "endpoint.version.archive"
ACTION_APIKEY_CREATE = "apikey.create"
ACTION_APIKEY_REVOKE = "apikey.revoke"
ACTION_APIKEY_DELETE = "apikey.delete"
ACTION_PLAYGROUND_RUN = "playground.run"


def record(
    session: Session,
    *,
    action: str,
    actor_user_id: int | None = None,
    actor_email: str = "",
    resource_type: str = "",
    resource_id: str | int = "",
    context: dict[str, Any] | None = None,
    ip: str = "",
    request_id: str = "",
    success: bool = True,
    commit: bool = True,
) -> AuditLog:
    """Registra um evento de auditoria com PII redigida."""
    entry = AuditLog(
        ts=utcnow(),
        actor_user_id=actor_user_id,
        actor_email=actor_email or "",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        context=PIIRedactor.redact_mapping(context or {}),
        ip=ip or "",
        request_id=request_id or "",
        success=success,
    )
    session.add(entry)
    if commit:
        session.commit()
    return entry


def record_request(
    session: Session,
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    project_id: int | None = None,
    endpoint_id: int | None = None,
    version_id: int | None = None,
    api_key_id: int | None = None,
    user_id: int | None = None,
    rows_returned: int = 0,
    client_ip: str = "",
    mode: str = "visual",
    error_code: str = "",
    error_message: str = "",
    commit: bool = True,
) -> RequestLog:
    """Grava a telemetria de uma requisicao ao runtime."""
    entry = RequestLog(
        ts=utcnow(),
        request_id=request_id,
        project_id=project_id,
        endpoint_id=endpoint_id,
        version_id=version_id,
        api_key_id=api_key_id,
        user_id=user_id,
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
        rows_returned=rows_returned,
        client_ip=client_ip,
        mode=mode,
        error_code=error_code,
        error_message=PIIRedactor.redact_text(error_message)[:1000],
    )
    session.add(entry)
    if commit:
        session.commit()
    return entry


def register_api_key_usage(session: Session, api_key_id: int) -> None:
    """Atualiza os contadores de uso da API key."""
    session.execute(
        ApiKey.__table__.update()
        .where(ApiKey.id == api_key_id)
        .values(usage_count=ApiKey.usage_count + 1, last_used_at=utcnow())
    )


def find_api_key(session: Session, plaintext: str) -> ApiKey | None:
    """Localiza a API key pelo prefixo publico e confere o hash em tempo constante."""
    prefix = plaintext[:12]
    candidates = session.scalars(
        select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.is_active.is_(True))
    ).all()
    digest = hash_api_key(plaintext)
    for candidate in candidates:
        if constant_time_equals(candidate.key_hash, digest):
            return candidate
    return None


def purge_request_logs(session: Session, *, older_than_days: int = 30) -> int:
    """Remove telemetria antiga e devolve quantas linhas foram apagadas."""
    from datetime import timedelta  # noqa: PLC0415

    cutoff = utcnow() - timedelta(days=older_than_days)
    result = session.execute(delete(RequestLog).where(RequestLog.ts < cutoff))
    session.commit()
    return int(result.rowcount or 0)


def log_statistics(session: Session) -> dict[str, int]:
    """Contagens usadas pelo painel."""
    total = session.scalar(select(func.count()).select_from(RequestLog)) or 0
    errors = (
        session.scalar(
            select(func.count()).select_from(RequestLog).where(RequestLog.status_code >= 400)
        )
        or 0
    )
    audit = session.scalar(select(func.count()).select_from(AuditLog)) or 0
    return {"requests": int(total), "errors": int(errors), "audit_entries": int(audit)}
