"""Testes do adaptador de SQL Server.

Todos os testes exigem um SQL Server real. A suite so roda quando a variavel
``STUDIO_TEST_MSSQL_DSN`` esta definida com uma connection string ODBC, por
exemplo::

    Server=localhost,1433;Database=erp;User Id=sa;Password=segredo

Sem a variavel os testes sao pulados (marcador ``mssql``), pois dependem de
infraestrutura externa genuinamente ausente.
"""

from __future__ import annotations

import os

import pytest

from app.services.datasources.base import DatasourceConfig
from app.services.datasources.sqlserver import (
    DRIVER_PYODBC,
    DRIVER_PYTDS,
    SqlServerAdapter,
    available_pyodbc_drivers,
)

DSN = os.getenv("STUDIO_TEST_MSSQL_DSN", "")

pytestmark = [
    pytest.mark.mssql,
    pytest.mark.skipif(
        not DSN.strip(), reason="STUDIO_TEST_MSSQL_DSN nao definido"
    ),
]


def _parse_dsn(dsn: str) -> DatasourceConfig:
    """Converte uma connection string ODBC em ``DatasourceConfig``."""
    partes: dict[str, str] = {}
    for trecho in dsn.split(";"):
        if "=" not in trecho:
            continue
        chave, _, valor = trecho.partition("=")
        partes[chave.strip().lower()] = valor.strip()

    host = partes.get("server") or partes.get("data source") or partes.get("host", "")
    # Instancia nomeada (host\\INSTANCIA) nao entra no host do URL.
    if "\\" in host:
        host = host.split("\\", 1)[0]

    porta: int | None = None
    if "," in host:
        host, _, bruto = host.partition(",")
        try:
            porta = int(bruto)
        except ValueError:
            porta = None

    driver = partes.get("driver", "")
    options: dict[str, str] = {}
    if driver:
        options["driver"] = driver

    return DatasourceConfig(
        kind="sqlserver",
        host=host,
        port=porta,
        database=partes.get("database") or partes.get("initial catalog", ""),
        username=partes.get("uid") or partes.get("user id") or partes.get("user", ""),
        password=partes.get("pwd") or partes.get("password", ""),
        driver=driver or "ODBC Driver 18 for SQL Server",
        options=options,
    )


@pytest.fixture()
def config() -> DatasourceConfig:
    """Configuracao decifrada do SQL Server de teste."""
    return _parse_dsn(DSN)


@pytest.fixture()
def adapter(config: DatasourceConfig) -> SqlServerAdapter:
    """Adaptador pronto para uso."""
    return SqlServerAdapter(config)


def test_escolhe_um_driver_disponivel(adapter: SqlServerAdapter) -> None:
    """O adaptador deve resolver pyodbc ou pytds sem levantar erro."""
    assert adapter.driver in {DRIVER_PYODBC, DRIVER_PYTDS}


def test_url_sqlalchemy_nao_expoe_a_senha(
    adapter: SqlServerAdapter, config: DatasourceConfig
) -> None:
    """A URL retornada nunca deve conter a senha em texto claro."""
    url = adapter.sqlalchemy_url()
    assert url.startswith("mssql+")
    if config.password:
        assert config.password not in url


def test_test_connection_le_a_versao(adapter: SqlServerAdapter) -> None:
    """test_connection deve conectar e devolver a versao do servidor."""
    probe = adapter.test_connection()
    assert probe.ok is True, probe.message
    assert probe.driver
    assert probe.server_version


def test_introspect_lista_objetos(adapter: SqlServerAdapter) -> None:
    """A introspeccao devolve tabelas/views/procedures como objetos."""
    objetos = adapter.introspect()
    assert isinstance(objetos, list)
    for objeto in objetos:
        assert objeto.object_type in {"table", "view", "procedure"}
        assert objeto.schema_name
        assert objeto.object_name


def test_introspect_filtra_por_schema(adapter: SqlServerAdapter) -> None:
    """O filtro de schema restringe os objetos devolvidos."""
    todos = adapter.introspect()
    if not todos:
        pytest.skip("SQL Server de teste nao possui objetos de usuario")
    schema = todos[0].schema_name
    filtrados = adapter.introspect(schemas={schema})
    assert filtrados
    assert all(item.schema_name == schema for item in filtrados)


def test_execute_retorna_linhas(adapter: SqlServerAdapter) -> None:
    """Uma consulta parametrizada simples devolve as linhas esperadas."""
    resultado = adapter.execute("SELECT 1 AS valor")
    assert resultado.columns == ["valor"]
    assert resultado.row_count == 1
    assert resultado.rows[0]["valor"] == 1
