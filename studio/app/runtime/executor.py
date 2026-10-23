"""Execucao de um endpoint compilado contra o banco alvo.

Responsabilidades:
  * resolver a fonte de dados e decifrar a credencial;
  * revalidar o comando (guarda de SQL + allow-list) **em tempo de execucao**, nao
    apenas na publicacao;
  * executar com bind parameters;
  * mapear as linhas para o contrato de resposta declarado;
  * devolver um envelope de resultado com metricas.

Erros do driver nunca chegam crus ao cliente: sao convertidos em erro de dominio com
identificador de correlacao.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.core.errors import StudioError
from app.core.logging import get_logger
from app.runtime.state import StudioRuntime
from app.schemas.definition import ResponseFieldSpec
from app.services import sql_guard
from app.services.compiler import CompiledEndpoint
from app.services.datasources.base import DatasourceError, ExecutionResult
from app.services.datasources.registry import build_adapter

logger = get_logger("studio.executor")


@dataclass
class ExecutionOutcome:
    """Resultado de uma execucao, pronto para virar resposta HTTP."""

    payload: Any = None
    rows: int = 0
    truncated: bool = False
    duration_ms: int = 0
    mode: str = "visual"
    error_code: str = ""
    error_message: str = ""
    columns: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error_code


class ExecutionFailure(StudioError):
    """Falha de execucao ja traduzida para erro de dominio."""

    def __init__(self, code: str, message: str, *, status_code: int, mode: str = "visual",
                 duration_ms: int = 0) -> None:
        super().__init__(message, status_code=status_code)
        self.code = code
        self.mode = mode
        self.duration_ms = duration_ms


def run_endpoint(
    compiled: CompiledEndpoint,
    arguments: dict[str, Any],
    runtime: StudioRuntime,
) -> ExecutionOutcome:
    """Executa o endpoint compilado e devolve o envelope de resposta."""
    definition = compiled.definition

    if definition.source.mode == "advanced":
        return _run_advanced(compiled, arguments, runtime)

    if compiled.datasource_id is None:
        raise ExecutionFailure(
            "datasource_missing",
            "o endpoint nao esta vinculado a uma fonte de dados",
            status_code=409,
        )

    source = runtime.get_datasource(compiled.datasource_id)
    if source is None or not source.is_active:
        raise ExecutionFailure(
            "datasource_unavailable",
            "a fonte de dados do endpoint nao esta disponivel",
            status_code=503,
        )

    adapter = build_adapter(source, runtime.cipher, settings=runtime.settings)
    allowed = runtime.allowed_objects(source.id)

    sql, parameters = _build_command(compiled, arguments, allowed_objects=allowed,
                                     allow_write=adapter.config.options.get("allow_write", False))

    try:
        result = adapter.execute(
            sql,
            parameters,
            max_rows=definition.response.max_rows or runtime.settings.max_rows,
        )
    except DatasourceError as exc:
        logger.warning("falha ao executar no banco alvo: %s", exc)
        raise ExecutionFailure(
            "upstream_error",
            "falha ao executar o comando na fonte de dados",
            status_code=502,
        ) from exc

    rows = _map_rows(result.rows, compiled.response_fields)
    payload = _build_envelope(compiled, rows, result, arguments)

    return ExecutionOutcome(
        payload=payload,
        rows=len(rows),
        truncated=result.truncated,
        duration_ms=result.duration_ms,
        mode="visual",
        columns=result.columns,
    )


# ---------------------------------------------------------------------------
# Comando
# ---------------------------------------------------------------------------
def _build_command(
    compiled: CompiledEndpoint,
    arguments: dict[str, Any],
    *,
    allowed_objects: set[tuple[str | None, str]],
    allow_write: bool,
) -> tuple[str, dict[str, Any]]:
    """Monta o comando final e o dicionario de bind parameters."""
    definition = compiled.definition
    source = definition.source

    if source.mode == "sql":
        sql = source.sql
        errors = sql_guard.validate(sql, allow_write=allow_write, allowed_objects=allowed_objects)
        if errors:
            raise ExecutionFailure(
                "sql_rejected",
                "o comando do endpoint nao passou na validacao: " + "; ".join(errors),
                status_code=403,
            )
        bound = set(sql_guard.extract_parameters(sql))
        parameters = {name: arguments.get(name) for name in bound}
        return sql, parameters

    # procedure
    target = (source.procedure_schema, source.procedure_name)
    # Deny-by-default: allow-list vazia significa "nenhum objeto autorizado".
    if target not in allowed_objects and (None, source.procedure_name) not in allowed_objects:
        raise ExecutionFailure(
            "object_not_allowed",
            f"a procedure '{target[0]}.{target[1]}' nao esta autorizada nesta fonte de dados",
            status_code=403,
        )

    assignments: list[str] = []
    parameters = {}
    for procedure_param, endpoint_param in source.procedure_bindings.items():
        assignments.append(f"@{procedure_param} = :{procedure_param}")
        parameters[procedure_param] = arguments.get(endpoint_param)

    if not assignments:
        raise ExecutionFailure(
            "procedure_binding_missing",
            "a procedure nao tem mapeamento de parametros configurado",
            status_code=409,
        )

    sql = f"EXEC {target[0]}.{target[1]} " + ", ".join(assignments)
    return sql, parameters


# ---------------------------------------------------------------------------
# Mapeamento de resposta
# ---------------------------------------------------------------------------
def _normalize_key(value: str) -> str:
    return str(value).strip().lower()


def _map_rows(rows: list[dict[str, Any]], fields: list[ResponseFieldSpec]) -> list[dict[str, Any]]:
    """Projeta as colunas do banco nos campos declarados do contrato de resposta.

    Quando nenhum campo foi declarado, as linhas passam como vieram do banco.
    """
    if not fields:
        return [_jsonable(row) for row in rows]

    lookup: dict[str, str] = {}
    for response_field in fields:
        lookup[_normalize_key(response_field.alias or response_field.name)] = response_field.name

    mapped: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {}
        for key, value in row.items():
            target = lookup.get(_normalize_key(key))
            if target is not None:
                item[target] = value
        mapped.append(_jsonable(item))
    return mapped


def _build_envelope(
    compiled: CompiledEndpoint,
    rows: list[dict[str, Any]],
    result: ExecutionResult,
    arguments: dict[str, Any],
) -> Any:
    """Aplica o envelope declarado (objeto, lista ou paginado).

    Em ``paginated``, o envelope devolve os itens da pagina corrente. A paginacao real
    e responsabilidade do SQL do endpoint (que recebe ``page``/``page_size`` como bind
    parameters e usa ``OFFSET ... FETCH NEXT``); por isso ``total`` refere-se ao numero
    de itens deste envelope e ``has_more`` indica que o banco devolveu mais linhas do
    que o limite configurado.
    """
    response = compiled.definition.response
    if response.envelope == "object":
        return rows[0] if rows else {}
    if response.envelope == "list":
        return rows

    pagination = response.pagination

    def _positive_int(key: str, default: int) -> int:
        raw = arguments.get(key)
        try:
            value = int(raw) if raw is not None else default
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    page = _positive_int(pagination.page_param, 1)
    page_size = _positive_int(pagination.page_size_param, pagination.default_page_size)

    return {
        "items": rows,
        "total": len(rows),
        "page": page,
        "page_size": page_size,
        "has_more": result.truncated,
    }


def _jsonable(value: Any) -> Any:
    """Converte tipos do banco (Decimal, datetime, UUID, bytes) em JSON."""
    return jsonable_encoder(
        value,
        custom_encoder={
            Decimal: lambda item: float(item),
            dt.datetime: lambda item: item.isoformat(),
            dt.date: lambda item: item.isoformat(),
            dt.time: lambda item: item.isoformat(),
            uuid.UUID: lambda item: str(item),
            bytes: lambda item: item.decode("utf-8", errors="replace"),
        },
    )


# ---------------------------------------------------------------------------
# Modo avancado
# ---------------------------------------------------------------------------
def _run_advanced(
    compiled: CompiledEndpoint, arguments: dict[str, Any], runtime: StudioRuntime
) -> ExecutionOutcome:
    if not runtime.settings.advanced_enabled:
        raise ExecutionFailure(
            "advanced_disabled",
            "o modo avancado esta desabilitado nesta instalacao",
            status_code=403,
        )

    from app.advanced.runner import run_advanced  # noqa: PLC0415

    ctx = {
        "params": _jsonable(arguments),
        "method": compiled.method,
        "path": compiled.path,
        "endpoint_id": compiled.endpoint_id,
        "version": compiled.version_number,
    }
    outcome = run_advanced(
        compiled.definition.source.advanced_code,
        ctx,
        timeout_seconds=runtime.settings.advanced_timeout_seconds,
        max_code_bytes=runtime.settings.advanced_max_code_bytes,
    )

    if outcome.timed_out:
        raise ExecutionFailure(
            "execution_timeout",
            outcome.error,
            status_code=504,
            mode="advanced",
            duration_ms=outcome.duration_ms,
        )
    if not outcome.ok:
        raise ExecutionFailure(
            "advanced_error",
            outcome.error,
            status_code=422,
            mode="advanced",
            duration_ms=outcome.duration_ms,
        )

    result = outcome.result
    rows = len(result) if isinstance(result, list) else 1
    return ExecutionOutcome(
        payload=result,
        rows=rows,
        duration_ms=outcome.duration_ms,
        mode="advanced",
    )
