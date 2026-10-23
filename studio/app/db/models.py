"""Modelos ORM do banco de metadados do Studio.

Este schema e a *Single Source of Truth* da plataforma: descricoes de endpoints,
conexoes, permissoes, chaves e trilhas de auditoria vivem aqui.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow

# ---------------------------------------------------------------------------
# Constantes de dominio (evitam strings soltas pelo codigo)
# ---------------------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_EDITOR, ROLE_OPERATOR, ROLE_VIEWER)

ROLE_RANK = {ROLE_VIEWER: 10, ROLE_OPERATOR: 20, ROLE_EDITOR: 30, ROLE_ADMIN: 40}

VERSION_DRAFT = "draft"
VERSION_PUBLISHED = "published"
VERSION_ARCHIVED = "archived"

DS_KIND_SQLSERVER = "sqlserver"
DS_KIND_SQLITE = "sqlite"
DS_KINDS = (DS_KIND_SQLSERVER, DS_KIND_SQLITE)

OBJECT_TYPE_TABLE = "table"
OBJECT_TYPE_VIEW = "view"
OBJECT_TYPE_PROCEDURE = "procedure"

AUTH_NONE = "none"
AUTH_API_KEY = "api_key"
AUTH_JWT = "jwt"
AUTH_MODES = (AUTH_NONE, AUTH_API_KEY, AUTH_JWT)


class User(Base):
    """Usuario administrativo da plataforma."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=ROLE_VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow, onupdate=utcnow)

    @property
    def role_rank(self) -> int:
        return ROLE_RANK.get(self.role, 0)


class Project(Base):
    """Agrupador logico de endpoints e escopo de acesso."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    openapi_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    openapi_version: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0.0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow, onupdate=utcnow)

    datasources: Mapped[list[Datasource]] = relationship(back_populates="project", cascade="all, delete-orphan")
    endpoints: Mapped[list[Endpoint]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectAccess(Base):
    """Vinculo usuario <-> projeto, com papel especifico no projeto."""

    __tablename__ = "project_access"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_access"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=ROLE_VIEWER)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)


class Datasource(Base):
    """Conexao com um banco alvo (SQL Server ou SQLite para desenvolvimento)."""

    __tablename__ = "datasources"
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_datasource_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default=DS_KIND_SQLSERVER)

    host: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    database: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    password_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_write: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # SQLite (dev/teste): caminho do arquivo. Ignorado no SQL Server.
    file_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    last_test_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="datasources")
    objects: Mapped[list[DatasourceObject]] = relationship(
        back_populates="datasource", cascade="all, delete-orphan"
    )


class DatasourceObject(Base):
    """Objeto descoberto no banco alvo e seu estado de autorizacao (allow-list)."""

    __tablename__ = "datasource_objects"
    __table_args__ = (
        UniqueConstraint("datasource_id", "schema_name", "object_name", name="uq_datasource_object"),
        Index("ix_datasource_objects_allowed", "datasource_id", "allowed"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasources.id", ondelete="CASCADE"), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False, default="dbo")
    object_name: Mapped[str] = mapped_column(String(255), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    parameters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    row_count_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow, onupdate=utcnow)

    datasource: Mapped[Datasource] = relationship(back_populates="objects")


class Endpoint(Base):
    """Identidade de um endpoint (o conteudo versionado fica em ``EndpointVersion``)."""

    __tablename__ = "endpoints"
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_endpoint_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    datasource_id: Mapped[int | None] = mapped_column(
        ForeignKey("datasources.id", ondelete="SET NULL"), nullable=True
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    http_method: Mapped[str] = mapped_column(String(10), nullable=False, default="GET")
    path: Mapped[str] = mapped_column(String(255), nullable=False, default="/")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Referencia logica (sem FK fisica) para evitar ciclo entre `endpoints` e
    # `endpoint_versions`, que impediria a criacao do schema no SQLite.
    published_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="endpoints")
    versions: Mapped[list[EndpointVersion]] = relationship(
        back_populates="endpoint",
        cascade="all, delete-orphan",
        foreign_keys="EndpointVersion.endpoint_id",
    )


class EndpointVersion(Base):
    """Snapshot imutavel da definicao de um endpoint."""

    __tablename__ = "endpoint_versions"
    __table_args__ = (
        UniqueConstraint("endpoint_id", "version_number", name="uq_endpoint_version_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    semver: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0.0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=VERSION_DRAFT)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    change_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)

    endpoint: Mapped[Endpoint] = relationship(back_populates="versions", foreign_keys=[endpoint_id])


class ApiKey(Base):
    """Chave de consumo das APIs publicadas. O segredo nunca e armazenado em claro."""

    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_prefix_active", "key_prefix", "is_active"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="live")
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class RequestLog(Base):
    """Telemetria de execucao de uma requisicao em endpoint publicado."""

    __tablename__ = "request_logs"
    __table_args__ = (Index("ix_request_logs_ts", "ts"), Index("ix_request_logs_endpoint", "endpoint_id", "ts"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    endpoint_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    api_key_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_returned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    client_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="visual")
    error_code: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AuditLog(Base):
    """Trilha de auditoria de acoes administrativas (com PII redigida)."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_ts", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RefreshTokenRecord(Base):
    """Registro de refresh token emitido, para permitir revogacao."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)


class StudioSetting(Base):
    """Configuracao editavel em runtime, sobrepondo o ambiente."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow, onupdate=utcnow)
