"""Fixtures compartilhadas da suite de testes do FastAPI Studio.

Os testes que tocam estado global (``set_runtime``) devem rodar de forma sequencial;
a suite nao usa ``pytest-xdist``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def sqlite_url(path: Path) -> str:
    """Monta uma URL SQLite valida em qualquer sistema operacional."""
    return f"sqlite:///{path.as_posix()}"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Configuracao isolada apontando para um banco de metadados temporario."""
    return Settings(
        env="test",
        database_url=sqlite_url(tmp_path / "meta.db"),
        run_migrations_on_startup=False,
        secret_key="x" * 48,
        bootstrap_admin_email="admin@example.com",
        bootstrap_admin_password="SenhaForte123",
        password_min_length=10,
    )


@pytest.fixture()
def app(settings: Settings):
    """Aplicacao completa (painel + runtime) construida sobre as settings de teste."""
    return create_app(settings)


@pytest.fixture()
def client(app):
    """TestClient com o lifespan ativo (cria schema, runtime, admin e registry)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def admin_headers(client) -> dict[str, str]:
    """Cabecalho Authorization do administrador inicial."""
    response = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "SenhaForte123"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def target_db(tmp_path: Path) -> Path:
    """SQLite alvo com a tabela ``clientes`` e a view ``v_ativos``."""
    path = tmp_path / "alvo.db"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nome TEXT NOT NULL,
                saldo NUMERIC,
                ativo INTEGER NOT NULL DEFAULT 1
            );
            INSERT INTO clientes (id, nome, saldo, ativo) VALUES
                (1, 'Ana', 100.5, 1),
                (2, 'Bruno', 200.0, 1),
                (3, 'Carla', 0.0, 0);
            CREATE VIEW v_ativos AS
                SELECT id, nome, saldo FROM clientes WHERE ativo = 1;
            """
        )
        connection.commit()
    finally:
        connection.close()
    return path
