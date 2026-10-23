"""Materializa uma rota **nativa** do FastAPI a partir de um endpoint compilado.

A rota recebe uma ``inspect.Signature`` real, com parametros ``KEYWORD_ONLY`` anotados
e defaults ``Path``/``Query``/``Header``/``Body``. Consequencias diretas:

* a validacao de tipo e feita pelo Pydantic do FastAPI (erro 422 nativo);
* o schema OpenAPI, o Swagger UI e o ReDoc descrevem os parametros sem codigo extra;
* nao existe nenhuma reimplementacao do framework — apenas configuracao programatica
  do que o FastAPI ja oferece.
"""

from __future__ import annotations

import inspect
import time
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Path, Query
from fastapi.routing import APIRoute

from app.core.context import get_request_context
from app.core.errors import StudioError
from app.core.logging import get_logger
from app.runtime.auth import runtime_auth_dependency
from app.runtime.executor import ExecutionOutcome, run_endpoint
from app.runtime.state import get_runtime
from app.schemas.definition import ParameterSpec
from app.services import audit
from app.services.compiler import CompiledEndpoint, CompiledParameter, parameter_kwargs

logger = get_logger("studio.runtime.builder")


def build_route(compiled: CompiledEndpoint, *, full_path: str) -> APIRoute:
    """Cria a ``APIRoute`` correspondente ao endpoint compilado."""
    router = APIRouter()
    router.add_api_route(
        path=full_path,
        endpoint=_make_handler(compiled),
        methods=[compiled.method],
        name=compiled.operation_id,
        operation_id=compiled.operation_id,
        summary=compiled.summary or None,
        description=compiled.description or None,
        tags=compiled.tags or [compiled.project_slug],
        deprecated=compiled.deprecated,
        response_model=compiled.response_model,
        response_model_exclude_unset=compiled.definition.response_model_exclude_unset,
        dependencies=[Depends(runtime_auth_dependency(compiled))],
    )
    route = router.routes[-1]
    if not isinstance(route, APIRoute):  # pragma: no cover - invariante do FastAPI
        raise TypeError("o FastAPI nao produziu uma APIRoute para o endpoint compilado")
    return route


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def _make_handler(compiled: CompiledEndpoint):
    """Cria o handler sincrono que executa o endpoint compilado.

    O handler e sincrono de proposito: o FastAPI o executa em thread pool, o que
    mantem o event loop livre durante as consultas ao banco alvo.
    """
    parameter_names = [parameter.name for parameter in compiled.parameters]
    alias_to_name = {
        parameter.alias: parameter.name
        for parameter in compiled.parameters
        if parameter.alias
    }

    def _handler(**kwargs: Any) -> Any:
        values = dict(kwargs)
        # O FastAPI entrega o valor sob o alias quando ele existe; normalizamos aqui.
        for alias, name in alias_to_name.items():
            if alias in values and name not in values:
                values[name] = values.pop(alias)
        arguments = {name: values.get(name) for name in parameter_names}
        return _execute(compiled, arguments)

    _handler.__name__ = compiled.operation_id
    _handler.__doc__ = compiled.description or compiled.summary or None
    _handler.__signature__ = build_signature(compiled)  # type: ignore[attr-defined]
    return _handler


def _execute(compiled: CompiledEndpoint, arguments: dict[str, Any]) -> Any:
    """Executa o endpoint, devolve o payload e sempre registra telemetria."""
    runtime = get_runtime()
    context = get_request_context()
    started = time.perf_counter()
    outcome = ExecutionOutcome()
    failure: Exception | None = None
    try:
        outcome = run_endpoint(compiled, arguments, runtime)
        return outcome.payload
    except StudioError as exc:
        failure = exc
        raise
    finally:
        _record(runtime, compiled, outcome, failure, started, context)


def _record(
    runtime,  # noqa: ANN001 - StudioRuntime
    compiled: CompiledEndpoint,
    outcome: ExecutionOutcome,
    failure: Exception | None,
    started: float,
    context,  # noqa: ANN001 - RequestContext
) -> None:
    """Grava a telemetria da requisicao sem nunca derrubar a resposta."""
    principal = context.principal
    duration_ms = outcome.duration_ms or int((time.perf_counter() - started) * 1000)
    try:
        with runtime.database.session() as session:
            audit.record_request(
                session,
                request_id=context.request_id,
                method=compiled.method,
                path=context.path or compiled.path,
                status_code=_status_of(failure),
                duration_ms=duration_ms,
                project_id=compiled.project_id,
                endpoint_id=compiled.endpoint_id,
                version_id=compiled.version_id,
                api_key_id=getattr(principal, "api_key_id", None),
                user_id=getattr(principal, "user_id", None),
                rows_returned=outcome.rows,
                client_ip=context.client_ip,
                mode=outcome.mode,
                error_code=(getattr(failure, "code", "") or outcome.error_code or ""),
                error_message=str(failure) if failure is not None else outcome.error_message,
            )
    except Exception:  # noqa: BLE001 - telemetria nunca invalida a resposta
        logger.exception("falha ao gravar telemetria da requisicao")


def _status_of(failure: Exception | None) -> int:
    if isinstance(failure, StudioError):
        return failure.status_code
    if failure is not None:
        return 500
    return 200


# ---------------------------------------------------------------------------
# Assinatura nativa
# ---------------------------------------------------------------------------
def build_signature(compiled: CompiledEndpoint) -> inspect.Signature:
    """Monta a assinatura que o FastAPI usa para extrair e validar os parametros."""
    specs = {spec.name: spec for spec in compiled.definition.parameters}
    parameters = [
        inspect.Parameter(
            parameter.name,
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=_default_for(parameter, specs.get(parameter.name)),
            annotation=parameter.annotation,
        )
        for parameter in compiled.parameters
    ]
    return inspect.Signature(parameters=parameters)


def _default_for(parameter: CompiledParameter, spec: ParameterSpec | None) -> Any:
    """Traduz o parametro compilado no default de FastAPI correspondente."""
    extra = parameter_kwargs(spec) if spec is not None else {}
    value = ... if parameter.required else parameter.default

    if parameter.location == "path":
        extra.pop("alias", None)  # o nome do path param tem de casar com o placeholder
        return Path(..., **extra)
    if parameter.location == "query":
        return Query(value, **extra)
    if parameter.location == "header":
        return Header(value, **extra)
    # Corpo: declara-se como objeto JSON com campos nomeados (embed), o formato
    # previsivel para um construtor visual.
    return Body(value, embed=True, **extra)
