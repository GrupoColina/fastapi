"""Casos de uso de endpoints versionados: criacao, validacao, publicacao e rollback.

Regras centrais:

* a **versao publicada e imutavel**: publicar nunca altera uma versao existente;
* rollback **nao** republica a versao antiga: ele cria uma nova versao com o mesmo
  conteudo e publica essa nova versao, preservando o historico;
* publicar exige validacao sem aprovacao — qualquer erro bloqueia a publicacao (422);
* toda publicacao reconstroi o runtime, tornando a rota imediatamente disponivel.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import (
    VERSION_ARCHIVED,
    VERSION_DRAFT,
    VERSION_PUBLISHED,
    Datasource,
    Endpoint,
    EndpointVersion,
    Project,
)
from app.schemas.api import EndpointCreate, EndpointUpdate
from app.schemas.definition import EndpointDefinition, definition_from_json
from app.services.compiler import validate_definition

logger = get_logger("studio.endpoints")

_MISSING = object()


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def get_endpoint_or_404(session: Session, endpoint_id: int) -> Endpoint:
    endpoint = session.get(Endpoint, endpoint_id)
    if endpoint is None:
        raise NotFoundError(f"endpoint {endpoint_id} nao encontrado")
    return endpoint


def get_version_or_404(session: Session, endpoint_id: int, version_id: int) -> EndpointVersion:
    version = session.get(EndpointVersion, version_id)
    if version is None or version.endpoint_id != endpoint_id:
        raise NotFoundError(f"versao {version_id} nao encontrada para o endpoint {endpoint_id}")
    return version


def latest_version(session: Session, endpoint_id: int) -> EndpointVersion | None:
    return session.scalar(
        select(EndpointVersion)
        .where(EndpointVersion.endpoint_id == endpoint_id)
        .order_by(EndpointVersion.version_number.desc())
        .limit(1)
    )


def next_version_number(session: Session, endpoint_id: int) -> int:
    current = session.scalar(
        select(func.max(EndpointVersion.version_number)).where(
            EndpointVersion.endpoint_id == endpoint_id
        )
    )
    return int(current or 0) + 1


def runtime_path(settings, project_slug: str, endpoint: Endpoint) -> str:  # noqa: ANN001
    base = settings.runtime_prefix.rstrip("/")
    suffix = (endpoint.path or "").strip("/")
    return f"{base}/{project_slug}" + (f"/{suffix}" if suffix else "")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def create_endpoint(
    session: Session,
    settings,  # noqa: ANN001 - Settings
    payload: EndpointCreate,
    *,
    created_by: int | None,
) -> Endpoint:
    project = session.get(Project, payload.project_id)
    if project is None:
        raise NotFoundError(f"projeto {payload.project_id} nao encontrado")

    duplicated = session.scalar(
        select(Endpoint).where(
            Endpoint.project_id == payload.project_id, Endpoint.slug == payload.slug
        )
    )
    if duplicated is not None:
        raise ConflictError(f"ja existe um endpoint com o slug '{payload.slug}' neste projeto")

    endpoint = Endpoint(
        project_id=payload.project_id,
        datasource_id=payload.datasource_id,
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        http_method=payload.http_method.upper(),
        path=payload.path,
        tags=list(payload.tags),
        is_active=payload.is_active,
        created_by=created_by,
    )
    session.add(endpoint)
    session.flush()

    if payload.definition:
        definition = definition_from_json(payload.definition)
        session.add(
            EndpointVersion(
                endpoint_id=endpoint.id,
                version_number=1,
                semver="0.1.0",
                status=VERSION_DRAFT,
                definition=definition.model_dump(mode="json"),
                change_note="versao inicial",
                created_by=created_by,
            )
        )

    session.commit()
    session.refresh(endpoint)
    return endpoint


def update_endpoint(
    session: Session, endpoint: Endpoint, payload: EndpointUpdate
) -> Endpoint:
    if payload.datasource_id is not None:
        endpoint.datasource_id = payload.datasource_id
    if payload.name is not None:
        endpoint.name = payload.name
    if payload.description is not None:
        endpoint.description = payload.description
    if payload.http_method is not None:
        endpoint.http_method = payload.http_method.upper()
    if payload.path is not None:
        endpoint.path = payload.path
    if payload.tags is not None:
        endpoint.tags = list(payload.tags)
    if payload.is_active is not None:
        endpoint.is_active = payload.is_active
    session.commit()
    session.refresh(endpoint)
    return endpoint


def delete_endpoint(session: Session, endpoint: Endpoint) -> None:
    session.delete(endpoint)
    session.commit()


# ---------------------------------------------------------------------------
# Versoes
# ---------------------------------------------------------------------------
def create_version(
    session: Session,
    endpoint: Endpoint,
    *,
    definition: EndpointDefinition | dict[str, Any],
    change_note: str = "",
    semver: str | None = None,
    created_by: int | None,
) -> EndpointVersion:
    parsed = (
        definition if isinstance(definition, EndpointDefinition) else definition_from_json(definition)
    )
    number = next_version_number(session, endpoint.id)
    version = EndpointVersion(
        endpoint_id=endpoint.id,
        version_number=number,
        semver=semver or f"0.{number}.0",
        status=VERSION_DRAFT,
        definition=parsed.model_dump(mode="json"),
        change_note=change_note,
        created_by=created_by,
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def _allow_write(runtime, endpoint: Endpoint) -> bool:  # noqa: ANN001
    """Escrita so e permitida com consentimento global **e** da fonte de dados."""
    if not runtime.settings.allow_write_operations or endpoint.datasource_id is None:
        return False
    with runtime.database.session() as session:
        source = session.get(Datasource, endpoint.datasource_id)
        return bool(source and source.allow_write)


def validate_version(runtime, endpoint: Endpoint, version: EndpointVersion) -> list[str]:  # noqa: ANN001
    """Valida a versao no contexto do endpoint (allow-list, SQL, sandbox)."""
    try:
        definition = definition_from_json(version.definition)
    except Exception as exc:  # noqa: BLE001 - definicao corrompida vira erro de validacao
        return [f"definicao invalida: {exc}"]

    allowed = (
        runtime.allowed_objects(endpoint.datasource_id) if endpoint.datasource_id else set()
    )
    return validate_definition(
        definition,
        method=endpoint.http_method,
        path=endpoint.path,
        allow_write=_allow_write(runtime, endpoint),
        allowed_objects=allowed,
    )


def publish_version(
    session: Session,
    runtime,  # noqa: ANN001 - StudioRuntime
    endpoint: Endpoint,
    version: EndpointVersion,
    *,
    published_by: int | None,
) -> EndpointVersion:
    errors = validate_version(runtime, endpoint, version)
    version.validation_errors = errors
    session.commit()

    if errors:
        raise ValidationFailure(
            "a versao nao passou na validacao e nao foi publicada",
            details={"errors": errors},
        )

    if endpoint.published_version_id and endpoint.published_version_id != version.id:
        previous = session.get(EndpointVersion, endpoint.published_version_id)
        if previous is not None and previous.status == VERSION_PUBLISHED:
            previous.status = VERSION_ARCHIVED

    version.status = VERSION_PUBLISHED
    version.published_at = utcnow()
    version.published_by = published_by
    endpoint.published_version_id = version.id
    session.commit()
    session.refresh(version)

    rebuild_runtime(runtime)
    return version


def rollback(
    session: Session,
    runtime,  # noqa: ANN001
    endpoint: Endpoint,
    target: EndpointVersion,
    *,
    actor: int | None,
) -> EndpointVersion:
    """Republica o conteudo de uma versao anterior como uma **nova** versao."""
    new_version = create_version(
        session,
        endpoint,
        definition=target.definition,
        change_note=f"rollback para a versao {target.version_number}",
        created_by=actor,
    )
    return publish_version(session, runtime, endpoint, new_version, published_by=actor)


def archive_version(
    session: Session, runtime, endpoint: Endpoint, version: EndpointVersion  # noqa: ANN001
) -> EndpointVersion:
    if version.status == VERSION_PUBLISHED:
        raise ValidationFailure(
            "arquive uma versao diferente da publicada: publique outra versao primeiro"
        )
    version.status = VERSION_ARCHIVED
    session.commit()
    session.refresh(version)
    return version


def deactivate_endpoint(session: Session, runtime, endpoint: Endpoint) -> Endpoint:  # noqa: ANN001
    """Desativa um endpoint publicado, removendo a rota do runtime."""
    endpoint.is_active = False
    session.commit()
    rebuild_runtime(runtime)
    return endpoint


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------
def diff_definitions(left: dict[str, Any] | None, right: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Diff estrutural entre duas definicoes (usado pela UI e pela auditoria)."""
    changes: list[dict[str, Any]] = []
    _walk("", left or {}, right or {}, changes)
    return changes


def _walk(prefix: str, left: Any, right: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            path = f"{prefix}.{key}" if prefix else key
            _walk(path, left.get(key, _MISSING), right.get(key, _MISSING), out)
        return
    if left != right:
        out.append(
            {
                "path": prefix,
                "before": None if left is _MISSING else left,
                "after": None if right is _MISSING else right,
            }
        )


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
def rebuild_runtime(runtime) -> dict[str, Any]:  # noqa: ANN001
    """Reconstroi o runtime, se ele estiver ligado a aplicacao."""
    registry = getattr(runtime, "registry", None)
    if registry is None:
        return {"endpoints": 0, "projects": 0, "errors": ["runtime nao inicializado"], "duration_ms": 0, "rebuilt_at": None}
    return registry.rebuild(runtime).as_dict()
