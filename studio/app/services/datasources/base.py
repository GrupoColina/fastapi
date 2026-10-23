"""Contrato comum dos adaptadores de banco alvo.

Os adaptadores falam com o banco usando SQLAlchemy. Isso garante que os parametros
nomeados (``:param``) sejam sempre traduzidos para o estilo correto do driver, o que
e a defesa primaria contra injeção de SQL. A segunda camada e ``sql_guard``.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.pool import NullPool


@dataclass
class ConnectionProbe:
    """Resultado de um teste de conexao."""

    ok: bool
    message: str
    latency_ms: int
    server_version: str = ""
    driver: str = ""


@dataclass
class DiscoveredColumn:
    """Coluna de uma tabela/view descoberta na introspeccao."""

    name: str
    native_type: str
    studio_type: str
    nullable: bool
    max_length: int | None = None
    precision: int | None = None
    scale: int | None = None
    ordinal: int = 0
    is_primary_key: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "native_type": self.native_type,
            "type": self.studio_type,
            "nullable": self.nullable,
            "max_length": self.max_length,
            "precision": self.precision,
            "scale": self.scale,
            "ordinal": self.ordinal,
            "is_primary_key": self.is_primary_key,
        }


@dataclass
class DiscoveredParameter:
    """Parametro de entrada de uma procedure."""

    name: str
    native_type: str
    studio_type: str
    ordinal: int
    has_default: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "native_type": self.native_type,
            "type": self.studio_type,
            "ordinal": self.ordinal,
            "has_default": self.has_default,
        }


@dataclass
class DiscoveredObject:
    """Tabela, view ou procedure descoberta."""

    schema_name: str
    object_name: str
    object_type: str
    columns: list[DiscoveredColumn] = field(default_factory=list)
    parameters: list[DiscoveredParameter] = field(default_factory=list)
    row_count_estimate: int | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.object_name}"


@dataclass
class ExecutionResult:
    """Resultado da execucao de um comando no banco alvo."""

    rows: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    truncated: bool
    duration_ms: int


@dataclass
class DatasourceConfig:
    """Configuracao de conexao ja decifrada, independente do ORM."""

    kind: str
    host: str = ""
    port: int | None = None
    database: str = ""
    username: str = ""
    password: str = ""
    file_path: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    driver: str = "ODBC Driver 18 for SQL Server"
    query_timeout: int = 30
    max_rows: int = 1000

    @property
    def is_read_only(self) -> bool:
        return not bool(self.options.get("allow_write", False))

    @property
    def configured_schemas(self) -> set[str]:
        raw = self.options.get("schemas")
        if isinstance(raw, list):
            return {str(item) for item in raw if str(item).strip()}
        return set()


class DatasourceError(RuntimeError):
    """Falha controlada ao falar com o banco alvo."""


class BaseAdapter(ABC):
    """Interface que todo adaptador de banco alvo implementa."""

    kind: str = ""

    def __init__(self, config: DatasourceConfig) -> None:
        self.config = config
        self._engine: Engine | None = None

    # -- Conexao -----------------------------------------------------------
    @abstractmethod
    def sqlalchemy_url(self) -> str:
        """URL SQLAlchemy (a senha nao deve ser logada)."""

    def engine(self) -> Engine:
        """Engine SQLAlchemy com pool nulo (uma conexao por requisicao)."""
        if self._engine is None:
            self._engine = self._create_engine()
        return self._engine

    @abstractmethod
    def _create_engine(self) -> Engine:
        """Cria o engine com os ``connect_args`` corretos para o driver."""

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    # -- Operacoes ---------------------------------------------------------
    def test_connection(self) -> ConnectionProbe:
        """Abre a conexao, mede a latencia e le a versao do servidor."""
        started = time.perf_counter()
        try:
            with self.engine().connect() as connection:
                version = self._server_version(connection)
                driver = self._driver_name(connection)
        except Exception as exc:  # noqa: BLE001 - devolvemos diagnostico, nao stack
            return ConnectionProbe(
                ok=False,
                message=sanitize_error(exc, self.config),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        finally:
            self.dispose()

        return ConnectionProbe(
            ok=True,
            message="conexao estabelecida",
            latency_ms=int((time.perf_counter() - started) * 1000),
            server_version=version,
            driver=driver,
        )

    @abstractmethod
    def introspect(self, *, schemas: set[str] | None = None) -> list[DiscoveredObject]:
        """Descobre tabelas, views, colunas e procedures."""

    def execute(
        self,
        sql: str,
        parameters: dict[str, Any] | None = None,
        *,
        max_rows: int | None = None,
    ) -> ExecutionResult:
        """Executa um comando parametrizado e devolve as linhas.

        O limite de linhas e aplicado por ``fetchmany``: a query do usuario nao e
        reescrita, e ainda assim a memoria fica limitada.
        """
        limit = max_rows or self.config.max_rows
        started = time.perf_counter()
        try:
            with self.engine().connect() as connection:
                return self._execute_on(connection, sql, parameters or {}, limit, started)
        except DatasourceError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DatasourceError(sanitize_error(exc, self.config)) from exc
        finally:
            self.dispose()

    def _execute_on(
        self,
        connection,  # noqa: ANN001 - sqlalchemy.Connection
        sql: str,
        parameters: dict[str, Any],
        limit: int,
        started: float,
    ) -> ExecutionResult:
        statement = text(sql)
        result = connection.execution_options(stream_results=True).execute(statement, parameters)
        columns = list(result.keys())
        if not result.returns_rows:
            return ExecutionResult(
                rows=[],
                columns=columns,
                row_count=result.rowcount if result.rowcount and result.rowcount > 0 else 0,
                truncated=False,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        fetched = result.fetchmany(limit + 1)
        truncated = len(fetched) > limit
        rows = [dict(zip(columns, row, strict=False)) for row in fetched[:limit]]
        return ExecutionResult(
            rows=rows,
            columns=columns,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    # -- Hooks -------------------------------------------------------------
    def _server_version(self, connection) -> str:  # noqa: ANN001
        return ""

    def _driver_name(self, connection) -> str:  # noqa: ANN001
        return self.kind


def sanitize_error(exc: Exception, config: DatasourceConfig) -> str:
    """Mensagem do driver sem vazar credenciais."""
    message = str(exc)
    if config.password:
        message = message.replace(config.password, "***")
    if config.username:
        message = message.replace(config.username, "***")
    return " ".join(message.split())[:500]
