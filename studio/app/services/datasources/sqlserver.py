"""Adaptador para SQL Server (ERP).

Preferencia de driver:
  1. ``pyodbc`` com o driver ODBC configurado (``STUDIO_MSSQL_DRIVER``), se presente;
  2. ``python-tds`` (puro Python) como alternativa quando nao ha driver ODBC instalado.

O adaptador nao muda o comportamento do FastAPI: ele apenas abre conexoes e executa
comandos parametrizados em nome dos endpoints publicados.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from app.services.datasources.base import (
    BaseAdapter,
    ConnectionProbe,
    DatasourceConfig,
    DiscoveredColumn,
    DiscoveredObject,
    DiscoveredParameter,
)
from app.services.types import studio_type_from_native

DRIVER_PYODBC = "pyodbc"
DRIVER_PYTDS = "pytds"

_OBJECTS_SQL = text("""
SELECT s.name AS schema_name,
       o.name AS object_name,
       CASE o.type WHEN 'U' THEN 'table' WHEN 'V' THEN 'view' END AS object_type
FROM sys.objects AS o
JOIN sys.schemas AS s ON s.schema_id = o.schema_id
WHERE o.type IN ('U', 'V') AND o.is_ms_shipped = 0
ORDER BY s.name, o.name
""")

_COLUMNS_SQL = text("""
SELECT s.name AS schema_name,
       o.name AS object_name,
       c.name AS column_name,
       t.name AS native_type,
       c.max_length AS max_length,
       c.precision AS precision,
       c.scale AS scale,
       c.is_nullable AS is_nullable,
       c.column_id AS ordinal,
       CASE WHEN pk.column_id IS NULL THEN 0 ELSE 1 END AS is_primary_key
FROM sys.columns AS c
JOIN sys.objects AS o ON o.object_id = c.object_id
JOIN sys.schemas AS s ON s.schema_id = o.schema_id
JOIN sys.types AS t ON t.user_type_id = c.user_type_id
LEFT JOIN (
    SELECT ic.object_id, ic.column_id
    FROM sys.index_columns AS ic
    JOIN sys.indexes AS i
      ON i.object_id = ic.object_id AND i.index_id = ic.index_id
    WHERE i.is_primary_key = 1
) AS pk ON pk.object_id = c.object_id AND pk.column_id = c.column_id
WHERE o.type IN ('U', 'V') AND o.is_ms_shipped = 0
ORDER BY s.name, o.name, c.column_id
""")

_PROCEDURES_SQL = text("""
SELECT s.name AS schema_name, p.name AS object_name
FROM sys.procedures AS p
JOIN sys.schemas AS s ON s.schema_id = p.schema_id
WHERE p.is_ms_shipped = 0
ORDER BY s.name, p.name
""")

_PARAMETERS_SQL = text("""
SELECT s.name AS schema_name,
       p.name AS object_name,
       pr.name AS parameter_name,
       t.name AS native_type,
       pr.parameter_id AS ordinal,
       pr.has_default_value AS has_default
FROM sys.parameters AS pr
JOIN sys.procedures AS p ON p.object_id = pr.object_id
JOIN sys.schemas AS s ON s.schema_id = p.schema_id
JOIN sys.types AS t ON t.user_type_id = pr.user_type_id
WHERE p.is_ms_shipped = 0
ORDER BY s.name, p.name, pr.parameter_id
""")


def available_pyodbc_drivers() -> list[str]:
    """Lista os drivers ODBC instalados no host (vazia se pyodbc nao existir)."""
    try:
        import pyodbc  # noqa: PLC0415
    except ImportError:
        return []
    try:
        return list(pyodbc.drivers())
    except Exception:  # noqa: BLE001
        return []


def _pytds_available() -> bool:
    try:
        import pytds  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


class SqlServerAdapter(BaseAdapter):
    """Adaptador de SQL Server."""

    kind = "sqlserver"

    def __init__(self, config: DatasourceConfig) -> None:
        super().__init__(config)
        self.driver = self._pick_driver()

    # -- Driver ------------------------------------------------------------
    def _pick_driver(self) -> str:
        preferred = str(self.config.options.get("driver") or self.config.driver or "").strip()
        installed = available_pyodbc_drivers()
        if preferred and installed:
            normalized = preferred.lower()
            for candidate in installed:
                if candidate.lower() == normalized:
                    return DRIVER_PYODBC
            for candidate in installed:
                if "sql server" in candidate.lower():
                    return DRIVER_PYODBC
        elif installed and any("sql server" in name.lower() for name in installed):
            return DRIVER_PYODBC
        if _pytds_available():
            return DRIVER_PYTDS
        if installed:
            return DRIVER_PYODBC
        raise DatasourceErrorRuntime(
            "nenhum driver de SQL Server disponivel: instale o ODBC Driver 18 "
            "ou o pacote python-tds"
        )

    def _effective_odbc_driver(self) -> str:
        preferred = str(self.config.options.get("driver") or self.config.driver or "").strip()
        installed = available_pyodbc_drivers()
        if preferred:
            for candidate in installed:
                if candidate.lower() == preferred.lower():
                    return candidate
        for candidate in installed:
            if "sql server" in candidate.lower():
                return candidate
        return preferred or "ODBC Driver 18 for SQL Server"

    # -- Conexao -----------------------------------------------------------
    def sqlalchemy_url(self) -> str:
        query: dict[str, str] = {}
        options = self.config.options

        if self.driver == DRIVER_PYODBC:
            query["driver"] = self._effective_odbc_driver()
            query["TrustServerCertificate"] = "yes" if options.get("trust_server_certificate", True) else "no"
            query["Encrypt"] = "yes" if options.get("encrypt", True) else "no"
            if options.get("application_intent_read_only"):
                query["ApplicationIntent"] = "ReadOnly"
        else:
            query["cafile"] = str(options.get("cafile", "")) if options.get("cafile") else ""
            if not query["cafile"]:
                query.pop("cafile")
            if options.get("application_intent_read_only"):
                query["appname"] = "fastapi-studio-readonly"

        url = URL.create(
            f"mssql+{self.driver}",
            username=self.config.username or None,
            password=self.config.password or None,
            host=self.config.host or None,
            port=self.config.port or None,
            database=self.config.database or None,
            query=query,
        )
        return url.render_as_string(hide_password=True)

    def _url_object(self) -> URL:
        query: dict[str, str] = {}
        options = self.config.options
        if self.driver == DRIVER_PYODBC:
            query["driver"] = self._effective_odbc_driver()
            query["TrustServerCertificate"] = "yes" if options.get("trust_server_certificate", True) else "no"
            query["Encrypt"] = "yes" if options.get("encrypt", True) else "no"
            if options.get("application_intent_read_only"):
                query["ApplicationIntent"] = "ReadOnly"
        return URL.create(
            f"mssql+{self.driver}",
            username=self.config.username or None,
            password=self.config.password or None,
            host=self.config.host or None,
            port=self.config.port or None,
            database=self.config.database or None,
            query=query,
        )

    def _create_engine(self) -> Engine:
        connect_args: dict[str, Any] = {}
        if self.driver == DRIVER_PYODBC:
            connect_args["timeout"] = self.config.query_timeout
            # Leitura nao deve deixar transacao aberta no ERP.
            connect_args["autocommit"] = True
        return create_engine(
            self._url_object(),
            poolclass=NullPool,
            future=True,
            connect_args=connect_args,
        )

    def _server_version(self, connection) -> str:  # noqa: ANN001
        try:
            row = connection.execute(text("SELECT @@VERSION AS v")).first()
        except Exception:  # noqa: BLE001
            return ""
        if not row:
            return ""
        return str(row[0]).splitlines()[0][:200]

    def _driver_name(self, connection) -> str:  # noqa: ANN001
        if self.driver == DRIVER_PYODBC:
            return f"pyodbc / {self._effective_odbc_driver()}"
        return "python-tds"

    # -- Introspeccao ------------------------------------------------------
    def introspect(self, *, schemas: set[str] | None = None) -> list[DiscoveredObject]:
        with self.engine().connect() as connection:
            objects: dict[tuple[str, str], DiscoveredObject] = {}
            for row in connection.execute(_OBJECTS_SQL):
                schema_name, object_name, object_type = row[0], row[1], row[2]
                objects[(schema_name, object_name)] = DiscoveredObject(
                    schema_name=schema_name,
                    object_name=object_name,
                    object_type=object_type,
                )

            for row in connection.execute(_COLUMNS_SQL):
                key = (row[0], row[1])
                target = objects.get(key)
                if target is None:
                    continue
                native = str(row[3])
                max_length = row[4]
                if max_length is not None and max_length < 0:
                    max_length = None
                target.columns.append(
                    DiscoveredColumn(
                        name=row[2],
                        native_type=native,
                        studio_type=studio_type_from_native(native),
                        nullable=bool(row[7]),
                        max_length=max_length,
                        precision=row[5],
                        scale=row[6],
                        ordinal=int(row[8]),
                        is_primary_key=bool(row[9]),
                    )
                )

            for row in connection.execute(_PROCEDURES_SQL):
                objects[(row[0], row[1])] = DiscoveredObject(
                    schema_name=row[0], object_name=row[1], object_type="procedure"
                )

            for row in connection.execute(_PARAMETERS_SQL):
                key = (row[0], row[1])
                target = objects.get(key)
                if target is None:
                    continue
                native = str(row[3])
                target.parameters.append(
                    DiscoveredParameter(
                        name=str(row[2]).lstrip("@"),
                        native_type=native,
                        studio_type=studio_type_from_native(native),
                        ordinal=int(row[4]),
                        has_default=bool(row[5]),
                    )
                )

        result = list(objects.values())
        if schemas:
            result = [item for item in result if item.schema_name in schemas]
        return sorted(result, key=lambda item: (item.object_type, item.schema_name, item.object_name))


class DatasourceErrorRuntime(RuntimeError):
    """Driver indisponivel no host."""
