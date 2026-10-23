"""Endpoints versionados: CRUD, versoes, validacao, publicacao, rollback e playground."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin.auth import audit_request_context
from app.api.deps import current_user, get_session, require_role
from app.core.errors import NotFoundError, StudioError, ValidationFailure
from app.db.models import Endpoint, EndpointVersion, Project, User
from app.runtime.executor import run_endpoint
from app.runtime.state import get_runtime
from app.schemas.api import (
    DiffResult,
    EndpointCreate,
    EndpointOut,
    EndpointUpdate,
    PlaygroundRequest,
    PlaygroundResponse,
    PublishResult,
    ValidationResult,
    VersionCreate,
    VersionOut,
    VersionSummary,
)
from app.schemas.definition import definition_from_json
from app.services import audit, endpoints as endpoint_service
from app.services.compiler import compile_endpoint

router = APIRouter(prefix="/endpoints", tags=["Admin · Endpoints"])


# ---------------------------------------------------------------------------
# Serializacao
# ---------------------------------------------------------------------------
def _project_slug(session: Session, project_id: int) -> str:
    project = session.get(Project, project_id)
    return project.slug if project is not None else ""


def _to_out(session: Session, endpoint: Endpoint) -> EndpointOut:
    runtime = get_runtime()
    latest = endpoint_service.latest_version(session, endpoint.id)
    data = EndpointOut.model_validate(endpoint)
    data.runtime_path = endpoint_service.runtime_path(
        runtime.settings, _project_slug(session, endpoint.project_id), endpoint
    )
    data.latest_version = VersionSummary.model_validate(latest) if latest is not None else None
    return data


def _runtime_dict(runtime: Any) -> dict[str, Any]:  # noqa: ANN401
    registry = getattr(runtime, "registry", None)
    if registry is None:
        return {"endpoints": 0, "projects": 0, "errors": [], "duration_ms": 0, "rebuilt_at": None}
    return registry.stats.as_dict()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("", response_model=list[EndpointOut], summary="Lista endpoints")
def list_endpoints(
    project_id: int | None = Query(default=None),
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[EndpointOut]:
    statement = select(Endpoint).order_by(Endpoint.id)
    if project_id is not None:
        statement = statement.where(Endpoint.project_id == project_id)
    return [_to_out(session, item) for item in session.scalars(statement)]


@router.post("", response_model=EndpointOut, status_code=201, summary="Cria um endpoint")
def create_endpoint(
    payload: EndpointCreate,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> EndpointOut:
    endpoint = endpoint_service.create_endpoint(
        session, get_runtime().settings, payload, created_by=actor.id
    )
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_ENDPOINT_CREATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="endpoint",
        resource_id=endpoint.id,
        context={"metodo": endpoint.http_method, "path": endpoint.path},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return _to_out(session, endpoint)


@router.get("/{endpoint_id}", response_model=EndpointOut, summary="Detalha um endpoint")
def get_endpoint(
    endpoint_id: int,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> EndpointOut:
    return _to_out(session, endpoint_service.get_endpoint_or_404(session, endpoint_id))


@router.patch("/{endpoint_id}", response_model=EndpointOut, summary="Atualiza um endpoint")
def update_endpoint(
    endpoint_id: int,
    payload: EndpointUpdate,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> EndpointOut:
    endpoint = endpoint_service.get_endpoint_or_404(session, endpoint_id)
    endpoint = endpoint_service.update_endpoint(session, endpoint, payload)
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_ENDPOINT_UPDATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="endpoint",
        resource_id=endpoint.id,
        context={"campos": sorted(payload.model_dump(exclude_unset=True))},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return _to_out(session, endpoint)


@router.delete("/{endpoint_id}", status_code=204, summary="Remove um endpoint")
def delete_endpoint(
    endpoint_id: int,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> None:
    runtime = get_runtime()
    endpoint = endpoint_service.get_endpoint_or_404(session, endpoint_id)
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_ENDPOINT_DELETE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="endpoint",
        resource_id=endpoint.id,
        ip=client["ip"],
        request_id=client["request_id"],
    )
    was_published = endpoint.published_version_id is not None
    endpoint_service.delete_endpoint(session, endpoint)
    if was_published:
        endpoint_service.rebuild_runtime(runtime)


# ---------------------------------------------------------------------------
# Versoes
# ---------------------------------------------------------------------------
@router.get(
    "/{endpoint_id}/versions",
    response_model=list[VersionSummary],
    summary="Lista as versoes do endpoint",
)
def list_versions(
    endpoint_id: int,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[EndpointVersion]:
    endpoint_service.get_endpoint_or_404(session, endpoint_id)
    return list(
        session.scalars(
            select(EndpointVersion)
            .where(EndpointVersion.endpoint_id == endpoint_id)
            .order_by(EndpointVersion.version_number.desc())
        )
    )


@router.post(
    "/{endpoint_id}/versions",
    response_model=VersionOut,
    status_code=201,
    summary="Cria uma nova versao (rascunho)",
)
def create_version(
    endpoint_id: int,
    payload: VersionCreate,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> EndpointVersion:
    endpoint = endpoint_service.get_endpoint_or_404(session, endpoint_id)
    version = endpoint_service.create_version(
        session,
        endpoint,
        definition=payload.definition,
        change_note=payload.change_note,
        semver=payload.semver,
        created_by=actor.id,
    )
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_VERSION_CREATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="endpoint_version",
        resource_id=version.id,
        context={"endpoint_id": endpoint_id, "numero": version.version_number},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return version


@router.get(
    "/{endpoint_id}/versions/{version_id}",
    response_model=VersionOut,
    summary="Detalha uma versao",
)
def get_version(
    endpoint_id: int,
    version_id: int,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> EndpointVersion:
    return endpoint_service.get_version_or_404(session, endpoint_id, version_id)


@router.post(
    "/{endpoint_id}/versions/{version_id}/validate",
    response_model=ValidationResult,
    summary="Valida a versao sem publicar",
)
def validate_version(
    endpoint_id: int,
    version_id: int,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> ValidationResult:
    runtime = get_runtime()
    endpoint = endpoint_service.get_endpoint_or_404(session, endpoint_id)
    version = endpoint_service.get_version_or_404(session, endpoint_id, version_id)
    errors = endpoint_service.validate_version(runtime, endpoint, version)
    version.validation_errors = errors
    session.flush()

    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_VERSION_VALIDATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="endpoint_version",
        resource_id=version.id,
        context={"ok": not errors, "erros": len(errors)},
        ip=client["ip"],
        request_id=client["request_id"],
        success=not errors,
    )
    return ValidationResult(ok=not errors, errors=errors)


@router.post(
    "/{endpoint_id}/versions/{version_id}/publish",
    response_model=PublishResult,
    summary="Publica a versao (bloqueia se houver erro de validacao)",
)
def publish_version(
    endpoint_id: int,
    version_id: int,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> PublishResult:
    runtime = get_runtime()
    endpoint = endpoint_service.get_endpoint_or_404(session, endpoint_id)
    version = endpoint_service.get_version_or_404(session, endpoint_id, version_id)

    published = endpoint_service.publish_version(
        session, runtime, endpoint, version, published_by=actor.id
    )
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_VERSION_PUBLISH,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="endpoint_version",
        resource_id=published.id,
        context={"endpoint_id": endpoint_id, "numero": published.version_number},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return PublishResult(
        endpoint_id=endpoint_id,
        version=VersionSummary.model_validate(published),
        runtime=_runtime_dict(runtime),
    )


@router.post(
    "/{endpoint_id}/versions/{version_id}/rollback",
    response_model=PublishResult,
    summary="Restaura uma versao anterior como uma nova versao publicada",
)
def rollback_version(
    endpoint_id: int,
    version_id: int,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> PublishResult:
    runtime = get_runtime()
    endpoint = endpoint_service.get_endpoint_or_404(session, endpoint_id)
    target = endpoint_service.get_version_or_404(session, endpoint_id, version_id)

    published = endpoint_service.rollback(session, runtime, endpoint, target, actor=actor.id)
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_VERSION_ROLLBACK,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="endpoint_version",
        resource_id=published.id,
        context={"endpoint_id": endpoint_id, "restaurada_de": target.version_number},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return PublishResult(
        endpoint_id=endpoint_id,
        version=VersionSummary.model_validate(published),
        runtime=_runtime_dict(runtime),
    )


@router.post(
    "/{endpoint_id}/versions/{version_id}/archive",
    response_model=VersionSummary,
    summary="Arquiva uma versao nao publicada",
)
def archive_version(
    endpoint_id: int,
    version_id: int,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> EndpointVersion:
    runtime = get_runtime()
    endpoint = endpoint_service.get_endpoint_or_404(session, endpoint_id)
    version = endpoint_service.get_version_or_404(session, endpoint_id, version_id)
    version = endpoint_service.archive_version(session, runtime, endpoint, version)

    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_VERSION_ARCHIVE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="endpoint_version",
        resource_id=version.id,
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return version


@router.get(
    "/{endpoint_id}/versions/{version_id}/diff",
    response_model=DiffResult,
    summary="Compara duas versoes",
)
def diff_versions(
    endpoint_id: int,
    version_id: int,
    against: int = Query(..., description="ID da versao usada como base da comparacao"),
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> DiffResult:
    base = endpoint_service.get_version_or_404(session, endpoint_id, version_id)
    target = endpoint_service.get_version_or_404(session, endpoint_id, against)
    changes = endpoint_service.diff_definitions(base.definition, target.definition)
    return DiffResult(
        from_version=against,
        to_version=version_id,
        changed=bool(changes),
        changes=changes,
    )


@router.post(
    "/{endpoint_id}/deactivate",
    response_model=EndpointOut,
    summary="Desativa o endpoint e remove a rota do runtime",
)
def deactivate_endpoint(
    endpoint_id: int,
    request: Request,
    actor: User = Depends(require_role("editor")),
    session: Session = Depends(get_session),
) -> EndpointOut:
    runtime = get_runtime()
    endpoint = endpoint_service.get_endpoint_or_404(session, endpoint_id)
    endpoint = endpoint_service.deactivate_endpoint(session, runtime, endpoint)
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_ENDPOINT_UPDATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="endpoint",
        resource_id=endpoint.id,
        context={"is_active": False},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return _to_out(session, endpoint)


# ---------------------------------------------------------------------------
# Playground (execucao sem publicar)
# ---------------------------------------------------------------------------
@router.post(
    "/{endpoint_id}/playground",
    response_model=PlaygroundResponse,
    summary="Executa a versao em rascunho sem publicar",
)
def playground(
    endpoint_id: int,
    payload: PlaygroundRequest,
    request: Request,
    actor: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> PlaygroundResponse:
    runtime = get_runtime()
    endpoint = endpoint_service.get_endpoint_or_404(session, endpoint_id)

    if payload.version_id is not None:
        version = endpoint_service.get_version_or_404(session, endpoint_id, payload.version_id)
    else:
        version = endpoint_service.latest_version(session, endpoint_id)
    if version is None:
        raise NotFoundError(f"o endpoint {endpoint_id} nao possui versoes")

    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_PLAYGROUND_RUN,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="endpoint",
        resource_id=endpoint.id,
        context={"version_id": version.id},
        ip=client["ip"],
        request_id=client["request_id"],
    )

    # A validacao acontece antes de executar: o playground nao contorna a allow-list.
    errors = endpoint_service.validate_version(runtime, endpoint, version)
    if errors:
        return PlaygroundResponse(
            ok=False,
            status_code=422,
            error_code="validation_failed",
            error_message="; ".join(errors),
        )

    try:
        definition = definition_from_json(version.definition)
    except Exception as exc:  # noqa: BLE001 - definicao corrompida vira resposta de erro
        raise ValidationFailure(f"definicao invalida: {exc}") from exc

    compiled = compile_endpoint(
        endpoint_id=endpoint.id,
        version_id=version.id,
        version_number=version.version_number,
        project_id=endpoint.project_id,
        project_slug=_project_slug(session, endpoint.project_id),
        datasource_id=endpoint.datasource_id,
        method=endpoint.http_method,
        path=endpoint.path,
        definition=definition,
    )

    try:
        outcome = run_endpoint(compiled, payload.arguments, runtime)
    except StudioError as exc:
        return PlaygroundResponse(
            ok=False,
            status_code=exc.status_code,
            error_code=exc.code,
            error_message=str(exc),
            mode=getattr(exc, "mode", "visual"),
            duration_ms=getattr(exc, "duration_ms", 0),
        )

    return PlaygroundResponse(
        ok=True,
        status_code=200,
        payload=outcome.payload,
        rows=outcome.rows,
        truncated=outcome.truncated,
        duration_ms=outcome.duration_ms,
        mode=outcome.mode,
        columns=outcome.columns,
    )
