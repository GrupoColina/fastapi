"""Fabrica da aplicacao FastAPI Studio.

Responsabilidades do ``lifespan``:

1. garantir o schema do banco de metadados (Alembic, com fallback para ``create_all``);
2. construir o :class:`StudioRuntime` (banco, cifra, cache, limitadores);
3. criar o administrador inicial quando a tabela de usuarios esta vazia;
4. instanciar o :class:`EndpointRegistry` e instalar as rotas publicadas.

O painel (SPA) e servido pela rota "cauda" ``/{full_path:path}``; as rotas publicadas
sao inseridas **antes** dela pelo registry, garantindo a precedencia correta.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

from app.api.admin import admin_router
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.security import SecretCipher, hash_password
from app.db.models import ROLE_ADMIN, User
from app.db.session import Database
from app.runtime.registry import EndpointRegistry
from app.runtime.state import StudioRuntime, set_runtime
from app.schemas.api import HealthResponse

logger = get_logger("studio.main")


# ---------------------------------------------------------------------------
# Preparacao do schema
# ---------------------------------------------------------------------------
def run_migrations(settings: Settings) -> None:
    """Aplica as migracoes Alembic ate ``head``."""
    from alembic import command  # noqa: PLC0415
    from alembic.config import Config as AlembicConfig  # noqa: PLC0415

    ini = settings.base_dir / "alembic.ini"
    if not ini.exists():
        raise RuntimeError(f"alembic.ini nao encontrado em {ini}")
    config = AlembicConfig(str(ini))
    config.set_main_option("script_location", str(settings.base_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


def bootstrap_admin(database: Database, settings: Settings) -> User | None:
    """Cria o administrador inicial quando nao existe nenhum usuario."""
    with database.session() as session:
        existing = session.scalar(select(func.count()).select_from(User)) or 0
        if existing:
            return None
        admin = User(
            email=settings.bootstrap_admin_email.strip().lower(),
            name=settings.bootstrap_admin_name,
            password_hash=hash_password(settings.bootstrap_admin_password),
            role=ROLE_ADMIN,
            is_active=True,
            must_change_password=True,
        )
        session.add(admin)
        session.flush()
        logger.warning(
            "administrador inicial criado; troque a senha no primeiro acesso",
            extra={"extra_data": {"email": admin.email}},
        )
        return admin


# ---------------------------------------------------------------------------
# Aplicacao
# ---------------------------------------------------------------------------
def create_app(settings: Settings | None = None) -> FastAPI:
    """Constroi a aplicacao completa (painel + runtime dinamico)."""
    config = settings or get_settings()
    configure_logging(
        level=config.log_level,
        json_output=config.env != "development",
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        database = Database(config.database_url, echo=False)
        try:
            if config.run_migrations_on_startup:
                try:
                    run_migrations(config)
                except Exception:  # noqa: BLE001 - ambiente sem Alembic pronto
                    logger.exception("migracoes falharam; criando schema a partir dos modelos")
                    database.create_all()
            else:
                database.create_all()

            runtime = StudioRuntime(
                settings=config,
                database=database,
                cipher=SecretCipher(config.encryption_key, config.secret_key),
            )
            app.state.runtime = runtime
            set_runtime(runtime)

            bootstrap_admin(database, config)

            registry = EndpointRegistry(app, tail_route=app.state.tail_route)
            runtime.registry = registry
            stats = registry.rebuild(runtime)
            logger.info(
                "studio pronto",
                extra={"extra_data": {"rotas_publicadas": stats.endpoints, "erros": len(stats.errors)}},
            )
            yield
        finally:
            registry = getattr(app.state, "registry", None)
            if registry is not None:
                try:
                    registry._uninstall()  # noqa: SLF001 - limpeza de rotas dinamicas
                except Exception:  # noqa: BLE001
                    logger.exception("falha ao remover rotas dinamicas no shutdown")
            set_runtime(None)
            database.dispose()

    app = FastAPI(
        title=config.app_name,
        version="1.0.0",
        description=(
            "Painel administrativo e runtime de APIs construidas visualmente sobre o "
            "FastAPI nativo."
        ),
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origin_list,
        allow_credentials=config.cors_origin_list != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(app)
    app.include_router(admin_router)

    _register_health(app)
    _register_runtime_docs(app, config)

    # Rota "cauda": a SPA. As rotas publicadas sao inseridas antes dela.
    app.state.tail_route = _register_spa(app, config)

    return app


# ---------------------------------------------------------------------------
# Rotas fixas
# ---------------------------------------------------------------------------
def _register_health(app: FastAPI) -> None:
    @app.get("/health", response_model=HealthResponse, tags=["Sistema"], summary="Healthcheck")
    def health() -> HealthResponse:
        from app.runtime.state import runtime_or_none  # noqa: PLC0415

        runtime = runtime_or_none()
        if runtime is None:
            return HealthResponse(
                status="starting",
                database=False,
                metadata_engine="desconhecido",
                runtime_endpoints=0,
            )
        registry = getattr(runtime, "registry", None)
        return HealthResponse(
            status="ok",
            database=runtime.database.ping(),
            metadata_engine=runtime.database.engine.dialect.name,
            runtime_endpoints=len(registry.installed_routes) if registry else 0,
        )


def _register_runtime_docs(app: FastAPI, config: Settings) -> None:
    """Espelha OpenAPI/Swagger/ReDoc sob o prefixo do runtime.

    Assim o consumidor encontra a documentacao no mesmo prefixo das APIs publicadas.
    """
    prefix = config.runtime_prefix.rstrip("/")

    @app.get(f"{prefix}/openapi.json", include_in_schema=False)
    def runtime_openapi() -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get(f"{prefix}/docs", include_in_schema=False)
    def runtime_docs():  # noqa: ANN202
        return get_swagger_ui_html(
            openapi_url=f"{prefix}/openapi.json",
            title=f"{config.app_name} - APIs publicadas",
        )

    @app.get(f"{prefix}/redoc", include_in_schema=False)
    def runtime_redoc():  # noqa: ANN202
        return get_redoc_html(
            openapi_url=f"{prefix}/openapi.json",
            title=f"{config.app_name} - APIs publicadas",
        )


def _register_spa(app: FastAPI, config: Settings) -> Route | None:
    """Serve o painel (build estatico) e devolve a rota cauda para o registry."""
    index_file = config.web_dir / "index.html"
    if not index_file.exists():
        logger.warning(
            "build do painel nao encontrado; apenas a API ficara disponivel",
            extra={"extra_data": {"web_dir": str(config.web_dir)}},
        )
        return None

    # Prefixos que nunca podem ser servidos pela SPA: um caminho de API inexistente
    # precisa virar 404 JSON, e nao um index.html com status 200.
    reserved = ["api"]
    runtime_prefix = config.runtime_prefix.strip("/")
    if runtime_prefix and not runtime_prefix.startswith("api"):
        reserved.append(runtime_prefix)

    def spa(full_path: str) -> FileResponse:
        if any(full_path == prefix or full_path.startswith(f"{prefix}/") for prefix in reserved):
            raise NotFoundError("rota de API inexistente")
        if full_path:
            candidate = (config.web_dir / full_path).resolve()
            try:
                candidate.relative_to(config.web_dir)
            except ValueError:
                raise NotFoundError("caminho invalido") from None
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index_file)

    app.get("/{full_path:path}", include_in_schema=False)(spa)
    return app.router.routes[-1]


app = create_app()
