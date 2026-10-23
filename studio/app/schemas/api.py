"""Contratos HTTP da API administrativa.

Modelos de entrada e saida do painel. Os modelos de saida sao construidos a partir dos
objetos ORM (``from_attributes``) para evitar conversoes manuais espalhadas pelo codigo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import ROLES
from app.schemas.definition import HTTP_METHODS

Environment = Literal["live", "test"]


# ---------------------------------------------------------------------------
# Autenticacao
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=10)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    role: str
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    name: str = Field(default="", max_length=160)
    password: str = Field(min_length=1, max_length=256)
    role: str = "viewer"
    is_active: bool = True

    @field_validator("role")
    @classmethod
    def _known_role(cls, value: str) -> str:
        if value not in ROLES:
            raise ValueError(f"papel invalido: {value}")
        return value


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=160)
    password: str | None = Field(default=None, min_length=1, max_length=256)
    role: str | None = None
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def _known_role(cls, value: str | None) -> str | None:
        if value is not None and value not in ROLES:
            raise ValueError(f"papel invalido: {value}")
        return value


# ---------------------------------------------------------------------------
# Projetos
# ---------------------------------------------------------------------------
class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    openapi_title: str = Field(default="", max_length=200)
    openapi_version: str = Field(default="1.0.0", max_length=40)
    is_active: bool = True


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=160)
    description: str | None = None
    openapi_title: str | None = Field(default=None, max_length=200)
    openapi_version: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: str
    openapi_title: str
    openapi_version: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProjectAccessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    user_id: int
    role: str


class ProjectAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def _known_role(cls, value: str) -> str:
        if value not in ROLES:
            raise ValueError(f"papel invalido: {value}")
        return value


# ---------------------------------------------------------------------------
# Fontes de dados
# ---------------------------------------------------------------------------
class DatasourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=160)
    kind: str = "sqlserver"
    host: str = ""
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str = ""
    username: str = ""
    password: str = ""
    options: dict[str, Any] = Field(default_factory=dict)
    file_path: str = ""
    is_active: bool = True
    allow_write: bool = False
    discover_schemas: list[str] = Field(default_factory=list)


class DatasourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=160)
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = None
    username: str | None = None
    # Ausente = mantem a senha atual; string vazia = limpa a senha.
    password: str | None = None
    options: dict[str, Any] | None = None
    file_path: str | None = None
    is_active: bool | None = None
    allow_write: bool | None = None
    discover_schemas: list[str] | None = None


class DatasourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    slug: str
    name: str
    kind: str
    host: str
    port: int | None
    database: str
    username: str
    file_path: str
    options: dict[str, Any]
    is_active: bool
    allow_write: bool
    has_password: bool = False
    last_test_at: datetime | None = None
    last_test_ok: bool | None = None
    last_test_message: str = ""
    last_test_latency_ms: int | None = None
    created_at: datetime
    updated_at: datetime


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: int
    server_version: str = ""
    driver: str = ""


class DiscoveredObjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    datasource_id: int
    schema_name: str
    object_name: str
    object_type: str
    columns: list[dict[str, Any]]
    parameters: list[dict[str, Any]]
    allowed: bool
    row_count_estimate: int | None = None
    updated_at: datetime


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemas: list[str] = Field(default_factory=list)


class DiscoverResult(BaseModel):
    objects: int
    tables: int
    views: int
    procedures: int
    duration_ms: int


class ObjectAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_ids: list[int] = Field(min_length=1)
    allowed: bool = True


# ---------------------------------------------------------------------------
# Endpoints e versoes
# ---------------------------------------------------------------------------
class EndpointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int
    datasource_id: int | None = None
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    http_method: str = "GET"
    path: str = Field(min_length=1, max_length=255)
    tags: list[str] = Field(default_factory=list)
    is_active: bool = True
    definition: dict[str, Any] | None = None

    @field_validator("http_method")
    @classmethod
    def _known_method(cls, value: str) -> str:
        method = value.strip().upper()
        if method not in HTTP_METHODS:
            raise ValueError(f"metodo HTTP invalido: {value}")
        return method


class EndpointUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datasource_id: int | None = None
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    http_method: str | None = None
    path: str | None = Field(default=None, max_length=255)
    tags: list[str] | None = None
    is_active: bool | None = None

    @field_validator("http_method")
    @classmethod
    def _known_method(cls, value: str | None) -> str | None:
        if value is None:
            return None
        method = value.strip().upper()
        if method not in HTTP_METHODS:
            raise ValueError(f"metodo HTTP invalido: {value}")
        return method


class VersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    endpoint_id: int
    version_number: int
    semver: str
    status: str
    change_note: str
    validation_errors: list[str]
    created_at: datetime
    published_at: datetime | None = None


class EndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    datasource_id: int | None
    slug: str
    name: str
    description: str
    http_method: str
    path: str
    tags: list[str]
    is_active: bool
    published_version_id: int | None
    runtime_path: str = ""
    created_at: datetime
    updated_at: datetime
    latest_version: VersionSummary | None = None


class VersionOut(VersionSummary):
    definition: dict[str, Any]


class VersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: dict[str, Any]
    change_note: str = ""
    semver: str | None = Field(default=None, max_length=40)


class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)


class PublishResult(BaseModel):
    endpoint_id: int
    version: VersionSummary
    runtime: dict[str, Any]


class DiffResult(BaseModel):
    from_version: int
    to_version: int
    changed: bool
    changes: list[dict[str, Any]] = Field(default_factory=list)


class PlaygroundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any] = Field(default_factory=dict)
    version_id: int | None = None


class PlaygroundResponse(BaseModel):
    ok: bool
    status_code: int
    payload: Any = None
    rows: int = 0
    truncated: bool = False
    duration_ms: int = 0
    mode: str = "visual"
    error_code: str = ""
    error_message: str = ""
    columns: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    project_id: int | None = None
    environment: Environment = "live"
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    name: str
    key_prefix: str
    environment: str
    scopes: list[str]
    is_active: bool
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    usage_count: int
    created_at: datetime
    revoked_at: datetime | None = None


class ApiKeyCreated(ApiKeyOut):
    # O segredo em claro aparece **uma unica vez**, na resposta de criacao.
    plaintext: str


# ---------------------------------------------------------------------------
# Logs e painel
# ---------------------------------------------------------------------------
class RequestLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    request_id: str
    project_id: int | None
    endpoint_id: int | None
    version_id: int | None
    api_key_id: int | None
    method: str
    path: str
    status_code: int
    duration_ms: int
    rows_returned: int
    client_ip: str
    mode: str
    error_code: str
    error_message: str


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    actor_user_id: int | None
    actor_email: str
    action: str
    resource_type: str
    resource_id: str
    context: dict[str, Any]
    ip: str
    request_id: str
    success: bool


class RuntimeStatus(BaseModel):
    endpoints: int
    projects: int
    errors: list[str]
    duration_ms: int
    rebuilt_at: datetime | None = None


class DashboardStats(BaseModel):
    users: int
    projects: int
    datasources: int
    endpoints: int
    published_endpoints: int
    api_keys: int
    requests: int
    errors: int
    audit_entries: int
    runtime: RuntimeStatus


class HealthResponse(BaseModel):
    status: str
    database: bool
    metadata_engine: str
    runtime_endpoints: int
