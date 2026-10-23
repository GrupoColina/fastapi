"""Testes da configuracao central (app.core.config.Settings)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _segredo_valido() -> str:
    return "k" * 48


def make(**overrides) -> Settings:
    base = {"env": "test", "secret_key": _segredo_valido()}
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# Validacao de producao
# ---------------------------------------------------------------------------
def test_producao_recusa_segredo_inseguro():
    with pytest.raises(ValidationError):
        Settings(env="production", secret_key="changeme-com-marcador-insegura")


def test_producao_recusa_segredo_curto():
    with pytest.raises(ValidationError):
        Settings(env="production", secret_key="a" * 30)


def test_producao_recusa_debug_ligado():
    with pytest.raises(ValidationError):
        Settings(env="production", secret_key=_segredo_valido(), debug=True)


def test_producao_aceita_configuracao_valida():
    config = Settings(env="production", secret_key=_segredo_valido(), debug=False)
    assert config.env == "production"
    assert config.debug is False


# ---------------------------------------------------------------------------
# Normalizacao
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/api/v1", "/api/v1"),
        ("api/v1/", "/api/v1"),
        ("v2", "/v2"),
        ("///x//", "/x"),
    ],
)
def test_normaliza_runtime_prefix(raw: str, expected: str):
    assert make(runtime_prefix=raw).runtime_prefix == expected


def test_runtime_prefix_vazio_e_invalido():
    with pytest.raises(ValidationError):
        make(runtime_prefix="/")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("info", "INFO"), ("debug", "DEBUG"), ("Warning", "WARNING")],
)
def test_normaliza_log_level(raw: str, expected: str):
    assert make(log_level=raw).log_level == expected


def test_log_level_invalido():
    with pytest.raises(ValidationError):
        make(log_level="verbose")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("*", ["*"]),
        ("", ["*"]),
        ("a,b", ["a", "b"]),
        ("a, b ,", ["a", "b"]),
    ],
)
def test_cors_origin_list(raw: str, expected: list[str]):
    assert make(cors_origins=raw).cors_origin_list == expected


def test_is_sqlite_metadata():
    assert make(database_url="sqlite:///./x.db").is_sqlite_metadata is True
    assert make(database_url="postgresql+psycopg://u:p@h/d").is_sqlite_metadata is False
