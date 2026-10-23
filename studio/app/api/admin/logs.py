"""Observabilidade do painel: telemetria de requisicoes, auditoria e estado do runtime."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.admin.auth import audit_request_context
from app.api.deps import current_user, get_session, require_role
from app.db.models import (
    ApiKey,
    AuditLog,
    Datasource,
    Endpoint,
    Project,
    RequestLog,
    User,
)
from app.runtime.state import get_runtime
from app.schemas.api import AuditLogOut, DashboardStats, RequestLogOut, RuntimeStatus
from app.services import audit

router = APIRouter(prefix="/logs", tags=["Admin · Logs e métricas"])


def _count(session: Session, model, *conditions) -> int:  # noqa: ANN001
    statement = select(func.count()).select_from(model)
    if conditions:
        statement = statement.where(*conditions)
    return int(session.scalar(statement) or 0)


@router.get("/requests", response_model=list[RequestLogOut], summary="Telemetria de requisicoes")
def list_request_logs(
    endpoint_id: int | None = Query(default=None),
    project_id: int | None = Query(default=None),
    status_min: int | None = Query(default=None, ge=100, le=599),
    limit: int = Query(default=100, ge=1, le=1000),
    _: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> list[RequestLog]:
    statement = select(RequestLog).order_by(RequestLog.ts.desc(), RequestLog.id.desc())
    if endpoint_id is not None:
        statement = statement.where(RequestLog.endpoint_id == endpoint_id)
    if project_id is not None:
        statement = statement.where(RequestLog.project_id == project_id)
    if status_min is not None:
        statement = statement.where(RequestLog.status_code >= status_min)
    return list(session.scalars(statement.limit(limit)))


@router.get("/audit", response_model=list[AuditLogOut], summary="Trilha de auditoria")
def list_audit_logs(
    action: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=1000),
    _: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> list[AuditLog]:
    statement = select(AuditLog).order_by(AuditLog.ts.desc(), AuditLog.id.desc())
    if action:
        statement = statement.where(AuditLog.action == action)
    return list(session.scalars(statement.limit(limit)))


@router.get("/stats", response_model=DashboardStats, summary="Indicadores do painel")
def dashboard_stats(
    _: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> DashboardStats:
    runtime = get_runtime()
    statistics = audit.log_statistics(session)
    registry = getattr(runtime, "registry", None)
    status = RuntimeStatus(**(registry.stats.as_dict() if registry else {
        "endpoints": 0, "projects": 0, "errors": [], "duration_ms": 0, "rebuilt_at": None
    }))
    return DashboardStats(
        users=_count(session, User),
        projects=_count(session, Project),
        datasources=_count(session, Datasource),
        endpoints=_count(session, Endpoint),
        published_endpoints=_count(session, Endpoint, Endpoint.published_version_id.is_not(None)),
        api_keys=_count(session, ApiKey, ApiKey.is_active.is_(True)),
        requests=statistics["requests"],
        errors=statistics["errors"],
        audit_entries=statistics["audit_entries"],
        runtime=status,
    )


@router.get("/runtime", response_model=RuntimeStatus, summary="Estado do runtime dinamico")
def runtime_status(
    _: User = Depends(require_role("operator")),
) -> RuntimeStatus:
    runtime = get_runtime()
    registry = getattr(runtime, "registry", None)
    if registry is None:
        return RuntimeStatus(endpoints=0, projects=0, errors=["runtime nao inicializado"])
    return RuntimeStatus(**registry.stats.as_dict())


@router.post("/runtime/rebuild", response_model=RuntimeStatus, summary="Reconstroi o runtime")
def rebuild_runtime(
    request: Request,
    actor: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> RuntimeStatus:
    runtime = get_runtime()
    result = audit_request_context(request)
    audit.record(
        session,
        action="runtime.rebuild",
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="runtime",
        ip=result["ip"],
        request_id=result["request_id"],
    )
    from app.services.endpoints import rebuild_runtime as do_rebuild  # noqa: PLC0415

    return RuntimeStatus(**do_rebuild(runtime))


@router.post("/purge", summary="Remove telemetria antiga")
def purge_logs(
    request: Request,
    older_than_days: int = Query(default=30, ge=1, le=3650),
    actor: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> dict[str, int]:
    deleted = audit.purge_request_logs(session, older_than_days=older_than_days)
    client = audit_request_context(request)
    audit.record(
        session,
        action="logs.purge",
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="request_log",
        context={"dias": older_than_days, "removidos": deleted},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return {"deleted": deleted}
