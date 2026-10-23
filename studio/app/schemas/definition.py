"""Contrato da definicao visual de um endpoint.

Este modelo e a peca central: ele e (a) o que o construtor visual grava em
``endpoint_versions.definition``, (b) o que a validacao consome, e (c) a entrada do
compilador que materializa a rota FastAPI.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ParameterLocation = Literal["path", "query", "header", "body"]
SourceMode = Literal["sql", "procedure", "advanced"]
EnvelopeMode = Literal["object", "list", "paginated"]
AuthMode = Literal["none", "api_key", "jwt"]

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


class ParameterSpec(BaseModel):
    """Parametro exposto pelo endpoint."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    location: ParameterLocation = "query"
    type: str = "string"
    item_type: str | None = None
    required: bool = False
    description: str = ""
    default: Any = None
    enum: list[Any] | None = None
    alias: str | None = None
    example: Any = None

    # Validacoes numericas e de texto (viram ge/le/min_length/max_length/pattern).
    ge: float | None = None
    le: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None

    @field_validator("name")
    @classmethod
    def _valid_identifier(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate.replace("_", "").isalnum() or candidate[0].isdigit():
            raise ValueError(
                "o nome do parametro deve ser um identificador valido (letras, digitos e _)"
            )
        return candidate

    @field_validator("location")
    @classmethod
    def _path_is_required(cls, value: ParameterLocation) -> ParameterLocation:
        return value


class ResponseFieldSpec(BaseModel):
    """Campo do schema de resposta."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    type: str = "string"
    item_type: str | None = None
    nullable: bool = True
    required: bool = False
    description: str = ""
    alias: str | None = None
    example: Any = None
    enum: list[Any] | None = None
    default: Any = None


class PaginationSpec(BaseModel):
    """Configuracao de paginacao do envelope."""

    model_config = ConfigDict(extra="forbid")

    page_param: str = "page"
    page_size_param: str = "page_size"
    default_page_size: int = Field(default=50, ge=1, le=1000)
    max_page_size: int = Field(default=500, ge=1, le=10000)


class SourceSpec(BaseModel):
    """De onde os dados vem."""

    model_config = ConfigDict(extra="forbid")

    mode: SourceMode = "sql"
    # SQL parametrizado com bind params nomeados (:param).
    sql: str = ""
    # Stored procedure (modo procedure). Nome qualificado: dbo.MinhaProc.
    procedure_schema: str = "dbo"
    procedure_name: str = ""
    # Mapeia nome do parametro da procedure -> nome do parametro do endpoint.
    procedure_bindings: dict[str, str] = Field(default_factory=dict)
    # Modo avancado: codigo Python que implementa handle(ctx) -> dict.
    advanced_code: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> SourceSpec:
        if self.mode == "sql" and not self.sql.strip():
            raise ValueError("modo 'sql' exige o campo 'sql'")
        if self.mode == "procedure" and not self.procedure_name.strip():
            raise ValueError("modo 'procedure' exige 'procedure_name'")
        if self.mode == "advanced" and not self.advanced_code.strip():
            raise ValueError("modo 'advanced' exige 'advanced_code'")
        return self

    @property
    def qualified_procedure(self) -> str:
        return f"{self.procedure_schema}.{self.procedure_name}"


class ResponseSpec(BaseModel):
    """Como a resposta e montada."""

    model_config = ConfigDict(extra="forbid")

    envelope: EnvelopeMode = "list"
    fields: list[ResponseFieldSpec] = Field(default_factory=list)
    pagination: PaginationSpec = Field(default_factory=PaginationSpec)
    max_rows: int | None = Field(default=None, ge=1, le=100000)


class AuthSpec(BaseModel):
    """Autenticacao exigida no consumo do endpoint."""

    model_config = ConfigDict(extra="forbid")

    mode: AuthMode = "api_key"
    scopes: list[str] = Field(default_factory=list)
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100000)


class EndpointDefinition(BaseModel):
    """Definicao completa de um endpoint versionado."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str | None = None
    summary: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    deprecated: bool = False
    response_model_exclude_unset: bool = False
    parameters: list[ParameterSpec] = Field(default_factory=list)
    source: SourceSpec
    response: ResponseSpec = Field(default_factory=ResponseSpec)
    auth: AuthSpec = Field(default_factory=AuthSpec)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_path_params(self) -> EndpointDefinition:
        path_names = {param.name for param in self.parameters if param.location == "path"}
        # Parametros de path declarados como obrigatorios por definicao.
        for param in self.parameters:
            if param.location == "path" and not param.required:
                param.required = True
        duplicate = len(path_names) != len(
            [param for param in self.parameters if param.location == "path"]
        )
        if duplicate:
            raise ValueError("ha parametros de path duplicados")
        return self


def definition_from_json(payload: dict[str, Any] | None) -> EndpointDefinition:
    """Desserializa uma definicao, falhando com mensagem clara."""
    if not payload:
        raise ValueError("definicao vazia")
    return EndpointDefinition.model_validate(payload)
