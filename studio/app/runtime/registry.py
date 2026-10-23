"""Registro em memoria dos endpoints publicados.

Responsabilidades:

* carregar do banco de metadados as **versoes publicadas** ativas;
* compilar cada uma e materializar a rota nativa (``app.runtime.builder``);
* instalar/desinstalar essas rotas na aplicacao **sem reiniciar o processo**;
* invalidar o cache do schema OpenAPI a cada reconstrucao.

A instalacao e feita inserindo as ``APIRoute`` diretamente na lista de rotas do
``APIRouter`` da aplicacao, imediatamente antes da rota "cauda" (a SPA montada em ``/``),
para que as rotas dinamicas tenham precedencia sobre o *catch-all* do painel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import VERSION_PUBLISHED, Endpoint, EndpointVersion, Project
from app.runtime.builder import build_route
from app.runtime.state import StudioRuntime
from app.schemas.definition import definition_from_json
from app.services.compiler import CompiledEndpoint, compile_endpoint

logger = get_logger("studio.registry")


@dataclass
class RegistryStats:
    """Resultado de uma reconstrucao do runtime."""

    endpoints: int = 0
    projects: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    rebuilt_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "endpoints": self.endpoints,
            "projects": self.projects,
            "errors": list(self.errors),
            "duration_ms": self.duration_ms,
            "rebuilt_at": self.rebuilt_at.isoformat() if self.rebuilt_at else None,
        }


class EndpointRegistry:
    """Mantem as rotas publicadas sincronizadas com o banco de metadados."""

    def __init__(self, app: FastAPI, *, tail_route: Any = None) -> None:
        self._app = app
        self._tail = tail_route
        self._installed: list[Any] = []
        self._compiled: dict[int, CompiledEndpoint] = {}
        self.stats = RegistryStats()

    # -- Consultas ---------------------------------------------------------
    def compiled_for(self, endpoint_id: int) -> CompiledEndpoint | None:
        return self._compiled.get(endpoint_id)

    def list_compiled(self) -> list[CompiledEndpoint]:
        return list(self._compiled.values())

    @property
    def installed_routes(self) -> list[Any]:
        return list(self._installed)

    # -- Reconstrucao ------------------------------------------------------
    def rebuild(self, runtime: StudioRuntime) -> RegistryStats:
        """Recarrega, compila e reinstala todas as rotas publicadas."""
        started = time.perf_counter()
        settings = runtime.settings
        compiled: list[CompiledEndpoint] = []
        errors: list[str] = []
        seen: set[tuple[str, str]] = set()

        with runtime.database.session() as session:
            rows = session.execute(
                select(Endpoint, EndpointVersion, Project)
                .join(EndpointVersion, EndpointVersion.id == Endpoint.published_version_id)
                .join(Project, Project.id == Endpoint.project_id)
                .where(
                    Endpoint.is_active.is_(True),
                    EndpointVersion.status == VERSION_PUBLISHED,
                    Project.is_active.is_(True),
                )
                .order_by(Endpoint.id)
            ).all()

        for endpoint, version, project in rows:
            try:
                definition = definition_from_json(version.definition)
                candidate = compile_endpoint(
                    endpoint_id=endpoint.id,
                    version_id=version.id,
                    version_number=version.version_number,
                    project_id=project.id,
                    project_slug=project.slug,
                    datasource_id=endpoint.datasource_id,
                    method=endpoint.http_method,
                    path=endpoint.path,
                    definition=definition,
                )
            except Exception as exc:  # noqa: BLE001 - uma versao ruim nao derruba o runtime
                errors.append(f"endpoint {endpoint.id}: {exc}")
                logger.warning("falha ao compilar endpoint publicado", extra={"extra_data": {"endpoint_id": endpoint.id, "erro": str(exc)}})
                continue

            route_key = (candidate.method, self.full_path(settings, project.slug, candidate.path))
            if route_key in seen:
                errors.append(
                    f"endpoint {endpoint.id}: rota duplicada {route_key[0]} {route_key[1]}"
                )
                continue
            seen.add(route_key)
            compiled.append(candidate)

        routes: list[Any] = []
        ready: list[CompiledEndpoint] = []
        for candidate in compiled:
            try:
                routes.append(
                    build_route(
                        candidate,
                        full_path=self.full_path(settings, candidate.project_slug, candidate.path),
                    )
                )
                ready.append(candidate)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"endpoint {candidate.endpoint_id}: rota nao instalada ({exc})")

        self._uninstall()
        self._install(routes)
        self._compiled = {item.endpoint_id: item for item in ready}
        self.stats = RegistryStats(
            endpoints=len(ready),
            projects=len({item.project_id for item in ready}),
            errors=errors,
            duration_ms=int((time.perf_counter() - started) * 1000),
            rebuilt_at=utcnow(),
        )
        logger.info(
            "runtime reconstruido",
            extra={"extra_data": {"endpoints": self.stats.endpoints, "erros": len(errors)}},
        )
        return self.stats

    # -- Instalacao --------------------------------------------------------
    def full_path(self, settings, project_slug: str, path: str) -> str:  # noqa: ANN001
        """Caminho HTTP completo de um endpoint publicado."""
        base = settings.runtime_prefix.rstrip("/")
        suffix = (path or "").strip("/")
        return f"{base}/{project_slug}" + (f"/{suffix}" if suffix else "")

    def _uninstall(self) -> None:
        target = self._app.router.routes
        for route in self._installed:
            try:
                target.remove(route)
            except ValueError:
                continue
        if self._installed:
            self._app.openapi_schema = None
        self._installed = []

    def _install(self, routes: list[Any]) -> None:
        if not routes:
            return
        target = self._app.router.routes
        if self._tail is not None and self._tail in target:
            index = target.index(self._tail)
            for offset, route in enumerate(routes):
                target.insert(index + offset, route)
        else:
            target.extend(routes)
        self._installed = list(routes)
        self._app.openapi_schema = None

    def invalidate(self) -> None:
        """Forca a regeracao do schema OpenAPI na proxima leitura."""
        self._app.openapi_schema = None
