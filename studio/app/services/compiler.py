"""Compilador: definicao visual -> especificacao executavel de rota.

Etapas:
  1. **Normalizacao**: converte a definicao validada em estruturas prontas
     (anotacoes Python, kwargs de ``Path``/``Query``/``Header``/``Body``).
  2. **Validacao semantica**: confere tipos, coerencia de path, allow-list de objetos
     do banco, guarda de SQL e sandbox do modo avancado.
  3. **Modelo de resposta**: cria o modelo Pydantic dinamicamente.

O compilador nao conhece HTTP nem o banco: ele apenas produz dados. Quem materializa a
rota e ``app.runtime.builder``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.schemas.definition import EndpointDefinition, ParameterSpec, ResponseFieldSpec
from app.services import sql_guard
from app.services.types import UnsupportedTypeError, build_response_model, json_schema_for, python_type_for

_PATH_TEMPLATE = re.compile(r"\{([^{}]+)\}")


@dataclass
class CompiledParameter:
    """Parametro pronto para virar argumento de uma rota FastAPI."""

    name: str
    location: str
    annotation: Any
    required: bool
    default: Any
    schema: dict[str, Any] | None
    description: str
    alias: str | None = None
    is_body_field: bool = False


@dataclass
class CompiledEndpoint:
    """Resultado da compilacao, consumido pelo runtime."""

    endpoint_id: int
    version_id: int
    version_number: int
    project_id: int
    project_slug: str
    datasource_id: int | None
    method: str
    path: str
    operation_id: str
    tags: list[str]
    summary: str
    description: str
    deprecated: bool
    definition: EndpointDefinition
    parameters: list[CompiledParameter] = field(default_factory=list)
    response_model: Any = None
    response_fields: list[ResponseFieldSpec] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validacao
# ---------------------------------------------------------------------------
def validate_definition(
    definition: EndpointDefinition,
    *,
    method: str,
    path: str,
    allow_write: bool,
    allowed_objects: set[tuple[str | None, str]],
) -> list[str]:
    """Valida a definicao no contexto do projeto/datasource. Vazio = aprovado."""
    errors: list[str] = []

    # 1. Tipos e unicidade de nomes de parametro
    names: set[str] = set()
    for parameter in definition.parameters:
        try:
            python_type_for(parameter.type, item_type=parameter.item_type)
            json_schema_for(parameter.type, item_type=parameter.item_type, enum_values=parameter.enum)
        except UnsupportedTypeError as exc:
            errors.append(f"parametro '{parameter.name}': {exc}")
        if parameter.name in names:
            errors.append(f"parametro duplicado: '{parameter.name}'")
        names.add(parameter.name)

    # 2. Coerencia entre o caminho declarado e os parametros de path
    declared_path_params = set(_PATH_TEMPLATE.findall(path))
    spec_path_params = {p.name for p in definition.parameters if p.location == "path"}
    missing = declared_path_params - spec_path_params
    extra = spec_path_params - declared_path_params
    if missing:
        errors.append(
            "o caminho declara parametros sem definicao correspondente: "
            + ", ".join(sorted(missing))
        )
    if extra:
        errors.append(
            "parametros de path declarados que nao existem no caminho: "
            + ", ".join(sorted(extra))
        )

    # 3. Corpo em metodos que nao o suportam de forma previsivel
    if method.upper() in {"GET", "DELETE", "HEAD"}:
        body_params = [p.name for p in definition.parameters if p.location == "body"]
        if body_params:
            errors.append(
                f"o metodo {method.upper()} nao deve declarar corpo; "
                f"mova {', '.join(body_params)} para query/header"
            )

    # 4. Tipos dos campos de resposta
    response_names: set[str] = set()
    for response_field in definition.response.fields:
        try:
            python_type_for(response_field.type, item_type=response_field.item_type)
        except UnsupportedTypeError as exc:
            errors.append(f"campo de resposta '{response_field.name}': {exc}")
        if not response_field.name.isidentifier():
            errors.append(
                f"campo de resposta '{response_field.name}': o nome deve ser um identificador "
                "Python valido; use 'alias' para o nome real da coluna"
            )
        if response_field.name in response_names:
            errors.append(f"campo de resposta duplicado: '{response_field.name}'")
        response_names.add(response_field.name)

    # 5. Fonte de dados
    source = definition.source
    if source.mode == "sql":
        errors.extend(
            sql_guard.validate(
                source.sql,
                allow_write=allow_write,
                allowed_objects=allowed_objects,
            )
        )
        bound = set(sql_guard.extract_parameters(source.sql))
        provided = {p.name for p in definition.parameters}
        unknown = bound - provided
        if unknown:
            errors.append(
                "o SQL usa parametros nao declarados no endpoint: " + ", ".join(sorted(unknown))
            )
    elif source.mode == "procedure":
        target = (source.procedure_schema, source.procedure_name)
        # Deny-by-default: uma allow-list vazia significa "nenhum objeto autorizado".
        if target not in allowed_objects and (None, source.procedure_name) not in allowed_objects:
            errors.append(
                f"a procedure '{source.qualified_procedure}' nao esta autorizada nesta fonte de dados"
            )
        provided = {p.name for p in definition.parameters}
        for procedure_param, endpoint_param in source.procedure_bindings.items():
            if endpoint_param not in provided:
                errors.append(
                    f"a procedure usa o parametro '{endpoint_param}', que nao existe no endpoint"
                )
    elif source.mode == "advanced":
        errors.extend(validate_advanced(source.advanced_code))

    # 6. Paginacao declarada precisa existir como query param (quando o envelope exige)
    if definition.response.envelope == "paginated":
        pagination = definition.response.pagination
        for candidate in (pagination.page_param, pagination.page_size_param):
            if candidate not in {p.name for p in definition.parameters}:
                errors.append(
                    f"o envelope 'paginated' espera o parametro de query '{candidate}'"
                )

    return errors


def validate_advanced(code: str) -> list[str]:
    """Valida o codigo do modo avancado usando o sandbox (import tardio)."""
    from app.advanced.validator import validate_code  # noqa: PLC0415

    return validate_code(code)


# ---------------------------------------------------------------------------
# Compilacao
# ---------------------------------------------------------------------------
def parameter_kwargs(parameter: ParameterSpec) -> dict[str, Any]:
    """Converte as validacoes declaradas em kwargs aceitos pelo FastAPI.

    Consumido por ``app.runtime.builder`` ao montar ``Path``/``Query``/``Header``/``Body``.
    """
    kwargs: dict[str, Any] = {}
    if parameter.description:
        kwargs["description"] = parameter.description
    if parameter.enum:
        kwargs["enum"] = list(parameter.enum)
    if parameter.ge is not None:
        kwargs["ge"] = parameter.ge
    if parameter.le is not None:
        kwargs["le"] = parameter.le
    if parameter.min_length is not None:
        kwargs["min_length"] = parameter.min_length
    if parameter.max_length is not None:
        kwargs["max_length"] = parameter.max_length
    if parameter.pattern:
        kwargs["pattern"] = parameter.pattern
    if parameter.example is not None:
        kwargs["examples"] = [parameter.example]
    if parameter.alias:
        kwargs["alias"] = parameter.alias
    return kwargs


def compile_parameters(definition: EndpointDefinition) -> list[CompiledParameter]:
    """Prepara os parametros, acrescentando os de paginacao quando necessario."""
    compiled: list[CompiledParameter] = []
    seen: set[str] = set()

    for parameter in definition.parameters:
        annotation = python_type_for(
            parameter.type, item_type=parameter.item_type, enum_values=parameter.enum
        )
        required = parameter.required or parameter.location == "path"
        if not required:
            annotation = annotation | None
        compiled.append(
            CompiledParameter(
                name=parameter.name,
                location=parameter.location,
                annotation=annotation,
                required=required,
                default=parameter.default,
                schema=json_schema_for(
                    parameter.type, item_type=parameter.item_type, enum_values=parameter.enum
                ),
                description=parameter.description,
                alias=parameter.alias,
                is_body_field=parameter.location == "body",
            )
        )
        seen.add(parameter.name)

    if definition.response.envelope == "paginated":
        pagination = definition.response.pagination
        for name, default in (
            (pagination.page_param, 1),
            (pagination.page_size_param, pagination.default_page_size),
        ):
            if name in seen:
                continue
            compiled.append(
                CompiledParameter(
                    name=name,
                    location="query",
                    annotation=int | None,
                    required=False,
                    default=default,
                    schema={"type": "integer", "minimum": 1},
                    description="Parametro de paginacao gerado automaticamente pelo envelope.",
                )
            )
            seen.add(name)

    return compiled


def compile_endpoint(
    *,
    endpoint_id: int,
    version_id: int,
    version_number: int,
    project_id: int,
    project_slug: str,
    datasource_id: int | None,
    method: str,
    path: str,
    definition: EndpointDefinition,
) -> CompiledEndpoint:
    """Compila a definicao em uma especificacao executavel."""
    parameters = compile_parameters(definition)

    response_model = None
    if definition.response.fields:
        model_name = _model_name(project_slug, path, method, version_number)
        if definition.response.envelope == "paginated":
            response_model = build_response_model(
                model_name, _field_dicts(definition.response.fields), envelope="paginated"
            )
        elif definition.response.envelope == "list":
            item_model = build_response_model(model_name, _field_dicts(definition.response.fields))
            response_model = list[item_model]
        else:
            response_model = build_response_model(model_name, _field_dicts(definition.response.fields))

    return CompiledEndpoint(
        endpoint_id=endpoint_id,
        version_id=version_id,
        version_number=version_number,
        project_id=project_id,
        project_slug=project_slug,
        datasource_id=datasource_id,
        method=method.upper(),
        path=_normalize_path(path),
        operation_id=definition.operation_id or _operation_id(project_slug, method, path, version_number),
        tags=list(definition.tags),
        summary=definition.summary,
        description=definition.description,
        deprecated=definition.deprecated,
        definition=definition,
        parameters=parameters,
        response_model=response_model,
        response_fields=list(definition.response.fields),
    )


def _field_dicts(fields: list[ResponseFieldSpec]) -> list[dict[str, Any]]:
    return [field.model_dump() for field in fields]


def _normalize_path(path: str) -> str:
    candidate = "/" + (path or "").strip().strip("/")
    return candidate


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _model_name(project_slug: str, path: str, method: str, version_number: int) -> str:
    parts = [_slugify(project_slug), _slugify(path), method.lower(), f"v{version_number}"]
    return "_".join(part for part in parts if part) or "ResponseModel"


def _operation_id(project_slug: str, method: str, path: str, version_number: int) -> str:
    return f"{_slugify(project_slug)}_{_slugify(path)}_{method.lower()}_v{version_number}"
