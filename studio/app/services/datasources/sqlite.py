"""Adaptador SQLite.

Usado para desenvolvimento local, para o ambiente de testes de integracao e para
exercitar todo o pipeline (introspeccao -> construtor -> publicacao -> consumo) sem
depender de um SQL Server real. O contrato e exatamente o mesmo do adaptador de
SQL Server, portanto o restante da plataforma nao sabe qual dos dois esta em uso.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from app.services.datasources.base import (
    BaseAdapter,
    DatasourceConfig,
    DiscoveredColumn,
    DiscoveredObject,
)
from app.services.types import studio_type_from_native

_TABLES_SQL = text(
    """
    SELECT name, type FROM sqlite_master
    WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
    ORDER BY type, name
    """
)


class SqliteAdapter(BaseAdapter):
    """Adaptador de banco SQLite (arquivo local)."""

    kind = "sqlite"

    def _resolved_path(self) -> str:
        raw = self.config.file_path or self.config.database
        if not raw:
            raise ValueError("informe 'file_path' para uma fonte de dados SQLite")
        if raw == ":memory:":
            return raw
        return str(Path(raw).expanduser().resolve())

    def sqlalchemy_url(self) -> str:
        return f"sqlite:///{self._resolved_path()}"

    def _create_engine(self) -> Engine:
        return create_engine(
            self.sqlalchemy_url(),
            poolclass=NullPool,
            future=True,
            connect_args={"check_same_thread": False, "timeout": self.config.query_timeout},
        )

    def _server_version(self, connection) -> str:  # noqa: ANN001
        row = connection.execute(text("SELECT sqlite_version()")).first()
        return f"SQLite {row[0]}" if row else ""

    def _driver_name(self, connection) -> str:  # noqa: ANN001
        return "sqlite3"

    def introspect(self, *, schemas: set[str] | None = None) -> list[DiscoveredObject]:
        with self.engine().connect() as connection:
            entries = list(connection.execute(_TABLES_SQL))
            objects: list[DiscoveredObject] = []
            for name, kind in entries:
                object_type = "table" if kind == "table" else "view"
                discovered = DiscoveredObject(
                    schema_name="main", object_name=str(name), object_type=object_type
                )
                discovered.columns = self._columns_for(connection, str(name))
                objects.append(discovered)
        return objects

    @staticmethod
    def _columns_for(connection, table_name: str) -> list[DiscoveredColumn]:  # noqa: ANN001
        # PRAGMA nao aceita bind parameter para o nome da tabela; o nome vem do
        # catalogo do proprio banco (sqlite_master) e e escapado manualmente.
        safe = table_name.replace('"', '""')
        rows = list(connection.execute(text(f'PRAGMA table_info("{safe}")')))
        columns: list[DiscoveredColumn] = []
        for row in rows:
            # cid, name, type, notnull, dflt_value, pk
            native = str(row[2] or "text")
            columns.append(
                DiscoveredColumn(
                    name=str(row[1]),
                    native_type=native,
                    studio_type=studio_type_from_native(native),
                    nullable=not bool(row[3]),
                    ordinal=int(row[0]),
                    is_primary_key=bool(row[5]),
                )
            )
        return columns
