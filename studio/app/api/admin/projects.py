"""Gestao de projetos e do acesso de usuarios por projeto."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin.auth import audit_request_context
from app.api.deps import current_user, get_session, require_role
from app.core.errors import ConflictError, NotFoundError
from app.db.models import Project, ProjectAccess, User
from app.schemas.api import (
    ProjectAccessOut,
    ProjectAccessRequest,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from app.services import audit

router = APIRouter(prefix="/projects", tags=["Admin · Projetos"])


@router.get("", response_model=list[ProjectOut], summary="Lista projetos")
def list_projects(
    _: User = Depends(current_user), session: Session = Depends(get_session)
) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.id)))


@router.post("", response_model=ProjectOut, status_code=201, summary="Cria projeto")
def create_project(
    payload: ProjectCreate,
    request: Request,
    actor: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> Project:
    if session.scalar(select(Project).where(Project.slug == payload.slug)) is not None:
        raise ConflictError(f"ja existe um projeto com o slug '{payload.slug}'")

    project = Project(
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        openapi_title=payload.openapi_title or payload.name,
        openapi_version=payload.openapi_version,
        is_active=payload.is_active,
    )
    session.add(project)
    session.flush()

    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_PROJECT_CREATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="project",
        resource_id=project.id,
        context={"slug": project.slug},
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return project


@router.get("/{project_id}", response_model=ProjectOut, summary="Detalha um projeto")
def get_project(
    project_id: int,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"projeto {project_id} nao encontrado")
    return project


@router.patch("/{project_id}", response_model=ProjectOut, summary="Atualiza um projeto")
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    request: Request,
    actor: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"projeto {project_id} nao encontrado")

    for field in ("name", "description", "openapi_title", "openapi_version", "is_active"):
        value = getattr(payload, field)
        if value is not None:
            setattr(project, field, value)
    session.flush()

    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_PROJECT_UPDATE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="project",
        resource_id=project.id,
        ip=client["ip"],
        request_id=client["request_id"],
    )
    return project


@router.delete("/{project_id}", status_code=204, summary="Remove um projeto")
def delete_project(
    project_id: int,
    request: Request,
    actor: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> None:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"projeto {project_id} nao encontrado")
    session.delete(project)
    client = audit_request_context(request)
    audit.record(
        session,
        action=audit.ACTION_PROJECT_DELETE,
        actor_user_id=actor.id,
        actor_email=actor.email,
        resource_type="project",
        resource_id=project_id,
        ip=client["ip"],
        request_id=client["request_id"],
    )
    session.flush()


# ---------------------------------------------------------------------------
# Acesso por projeto
# ---------------------------------------------------------------------------
@router.get(
    "/{project_id}/access",
    response_model=list[ProjectAccessOut],
    summary="Lista o acesso ao projeto",
)
def list_access(
    project_id: int,
    _: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> list[ProjectAccess]:
    return list(
        session.scalars(select(ProjectAccess).where(ProjectAccess.project_id == project_id))
    )


@router.post(
    "/{project_id}/access",
    response_model=ProjectAccessOut,
    status_code=201,
    summary="Concede acesso a um usuario",
)
def grant_access(
    project_id: int,
    payload: ProjectAccessRequest,
    _: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> ProjectAccess:
    if session.get(Project, project_id) is None:
        raise NotFoundError(f"projeto {project_id} nao encontrado")
    if session.get(User, payload.user_id) is None:
        raise NotFoundError(f"usuario {payload.user_id} nao encontrado")

    existing = session.scalar(
        select(ProjectAccess).where(
            ProjectAccess.project_id == project_id, ProjectAccess.user_id == payload.user_id
        )
    )
    if existing is not None:
        existing.role = payload.role
        session.flush()
        return existing

    grant = ProjectAccess(project_id=project_id, user_id=payload.user_id, role=payload.role)
    session.add(grant)
    session.flush()
    return grant


@router.delete(
    "/{project_id}/access/{user_id}", status_code=204, summary="Revoga o acesso de um usuario"
)
def revoke_access(
    project_id: int,
    user_id: int,
    _: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> None:
    grant = session.scalar(
        select(ProjectAccess).where(
            ProjectAccess.project_id == project_id, ProjectAccess.user_id == user_id
        )
    )
    if grant is None:
        raise NotFoundError("vinculo de acesso nao encontrado")
    session.delete(grant)
    session.flush()
