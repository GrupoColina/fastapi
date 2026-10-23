"""Registro de adaptadores e construcao de configuracao a partir do ORM."""

from __future__ import annotations

from app.core.logging import get_logger
from app.core.security import SecretCipher
from app.db.models import DS_KIND_SQLITE, DS_KIND_SQLSERVER, Datasource
from app.services.datasources.base import BaseAdapter, DatasourceConfig, DatasourceError
from app.services.datasources.sqlite import SqliteAdapter
from app.services.datasources.sqlserver import SqlServerAdapter

logger = get_logger(__name__)

_ADAPTERS: dict[str, type[BaseAdapter]] = {
    DS_KIND_SQLSERVER: SqlServerAdapter,
    DS_KIND_SQLITE: SqliteAdapter,
}


def register_adapter(kind: str, adapter: type[BaseAdapter]) -> None:
    """Permite registrar adaptadores adicionais (ponto de extensao)."""
    _ADAPTERS[kind] = adapter


def adapter_for(config: DatasourceConfig) -> BaseAdapter:
    """Instancia o adaptador correspondente ao tipo da fonte de dados."""
    adapter_class = _ADAPTERS.get(config.kind)
    if adapter_class is None:
        raise DatasourceError(f"tipo de fonte de dados nao suportado: {config.kind}")
    return adapter_class(config)


def config_from_model(source: Datasource, cipher: SecretCipher, *, settings) -> DatasourceConfig:  # noqa: ANN001
    """Monta a configuracao de conexao, decifrando a senha armazenada."""
    password = ""
    if source.password_enc:
        password = cipher.decrypt(source.password_enc)

    options = dict(source.options or {})
    # O flag de escrita precisa do consentimento global e do consentimento da fonte.
    options["allow_write"] = bool(
        source.allow_write and getattr(settings, "allow_write_operations", False)
    )

    return DatasourceConfig(
        kind=source.kind,
        host=source.host,
        port=source.port,
        database=source.database,
        username=source.username,
        password=password,
        file_path=source.file_path,
        options=options,
        driver=getattr(settings, "mssql_driver", "ODBC Driver 18 for SQL Server"),
        query_timeout=getattr(settings, "query_timeout", 30),
        max_rows=getattr(settings, "max_rows", 1000),
    )


def build_adapter(source: Datasource, cipher: SecretCipher, *, settings) -> BaseAdapter:  # noqa: ANN001
    """Atalho: modelo ORM -> adaptador pronto para uso."""
    return adapter_for(config_from_model(source, cipher, settings=settings))
