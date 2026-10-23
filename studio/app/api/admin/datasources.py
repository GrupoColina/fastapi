"""Fontes de dados: CRUD, teste de conexao, introspeccao e allow-list de objetos."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin.auth import audit_request_context
from app.api.deps import current_user, get_session, require_role
from app.core.errors import NotFoundError
from app.db.models import Datasource, Project, User
from app.runtime.state import get_runtime
from app.schemas.api import (
    ConnectionTestResult,
    DatasourceCreate,
    DatasourceOut,
    DatasourceUpdate,
    DiscoveredObjectOut,
    DiscoverRequest,
    DiscoverResult,
    ObjectAuthorizationRequest,
)
from app.services import audit, datasource_service

router = APIRouter(prefix="/datasources", tags=["Admin · Fontes de dados"])


def _to_out(source: Datasource) -> DatasourceOut:
    """Serializa sem expor a senha (``serialize`` devolve apenas ``has_password``)."""
    return DatasourceOut.model_validate(datasource_service.serialize(source))


@router.get("", response_model=list[DatasourceOut], summary="Lista fontes de dados")
def list_datasources(
    project_id: int | None = Query(default=None),
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[DatasourceOut]:
    statement = select(Datasource).order_by(Datasource.id)
    if project_id is not None:
        statement = statement.where(Datasource.project_id == project_id)
    return [_to_out(item) for item in session.scalars(statement)]


@router.post("", response_model=DatasourceOut, status_code=201, summary="Cria fonte de dados")
def create_datasource(
    payload: DatasourceCreate,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> DatasourceOut:
    runtime = get_runtime()
    if session.get(Project, payload.project_id) is None:
        raise NotFoundError(f"projeto {payload.project_id} nao encontrado")

    source = datasource_service.create_datasource(
        session, cipher=runtime.cipher, payload=payload
    )
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_DATASOURCE_CREATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="datasource",
        resource_id=source.id,
        context={"kind": source.kind, "host": source.host, "database": source.database},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return _to_out(source)


@router.get("/{datasource_id}", response_model=DatasourceOut, summary="Detalha uma fonte")
def get_datasource(
    datasource_id: int,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> DatasourceOut:
    return _to_out(datasource_service.get_datasource_or_404(session, datasource_id))


@router.patch("/{datasource_id}", response_model=DatasourceOut, summary="Atualiza uma fonte")
def update_datasource(
    datasource_id: int,
    payload: DatasourceUpdate,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> DatasourceOut:
    runtime = get_runtime()
    source = datasource_service.get_datasource_or_404(session, datasource_id)
    source = datasource_service.update_datasource(
        session, cipher=runtime.cipher, source=source, payload=payload
    )
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_DATASOURCE_UPDATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="datasource",
        resource_id=source.id,
        context={"campos": sorted(payload.model_dump(exclude_unset=True))},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return _to_out(source)


@router.delete("/{datasource_id}", status_code=204, summary="Remove uma fonte de dados")
def delete_datasource(
    datasource_id: int,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> None:
    source = datasource_service.get_datasource_or_404(session, datasource_id)
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_DATASOURCE_DELETE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="datasource",
        resource_id=source.id,
        ip=client["ip"],
        request_id=client["request_id"],
    )
    datasource_service.delete_datasource(session, source)


@router.post(
    "/{datasource_id}/test",
    response_model=ConnectionTestResult,
    summary="Testa a conexao com o banco alvo",
)
def test_connection(
    datasource_id: int,
    request: Request,
    actor: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> ConnectionTestResult:
    runtime = get_runtime()
    source = datasource_service.get_datasource_or_404(session, datasource_id)
    probe = datasource_service.test_connection(
        session, source, cipher=runtime.cipher, settings=runtime.settings
    )
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_DATASOURCE_TEST,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="datasource",
        resource_id=source.id,
        context={"ok": probe.ok, "latency_ms": probe.latency_ms, "driver": probe.driver},
        ip=client["ip"],
        request_id=client["request_id"],
        success=probe.ok,
    )
    return ConnectionTestResult(
        ok=probe.ok,
        message=probe.message,
        latency_ms=probe.latency_ms,
        server_version=probe.server_version,
        driver=probe.driver,
    )


@router.post(
    "/{datasource_id}/discover",
    response_model=DiscoverResult,
    summary="Descobre os objetos do banco alvo",
)
def discover(
    datasource_id: int,
    payload: DiscoverRequest,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> DiscoverResult:
    runtime = get_runtime()
    source = datasource_service.get_datasource_or_404(session, datasource_id)
    result = datasource_service.introspect(
        session, runtime, source, schemas=payload.schemas or None
    )
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_DATASOURCE_INTROSPECT,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="datasource",
        resource_id=source.id,
        context=result,
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return DiscoverResult(**result)


@router.get(
    "/{datasource_id}/objects",
    response_model=list[DiscoveredObjectOut],
    summary="Lista os objetos descobertos",
)
def list_objects(
    datasource_id: int,
    object_type: str | None = Query(default=None, pattern="^(table|view|procedure)$"),
    only_allowed: bool = Query(default=False),
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[DiscoveredObjectOut]:
    datasource_service.get_datasource_or_404(session, datasource_id)
    records = datasource_service.list_objects(
        session, datasource_id, object_type=object_type, only_allowed=only_allowed
    )
    return [DiscoveredObjectOut.model_validate(item) for item in records]


@router.post(
    "/{datasource_id}/objects/authorize",
    summary="Autoriza ou desautoriza objetos (allow-list)",
)
def authorize_objects(
    datasource_id: int,
    payload: ObjectAuthorizationRequest,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> dict[str, int]:
    runtime = get_runtime()
    source = datasource_service.get_datasource_or_404(session, datasource_id)
    changed = datasource_service.set_objects_allowed(
        session, runtime, source, payload.object_ids, allowed=payload.allowed
    )
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_DATASOURCE_OBJECT_AUTHORIZE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="datasource",
        resource_id=source.id,
        context={"allowed": payload.allowed, "objetos": changed},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return {"updated": changed}
