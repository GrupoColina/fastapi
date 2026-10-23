"""Configuracao central do FastAPI Studio.

Todas as variaveis de ambiente usam o prefixo ``STUDIO_`` e sao carregadas via
``pydantic-settings`` (arquivo ``.env`` + ambiente do processo).
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]

INSECURE_SECRET_MARKERS = (
    "troque-esta-chave",
    "changeme",
    "secret",
    "insecure",
)


class Settings(BaseSettings):
    """Configuracao da aplicacao."""

    model_config = SettingsConfigDict(
        env_prefix="STUDIO_",
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Aplicacao ---------------------------------------------------------
    env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    app_name: str = "FastAPI Studio"
    base_dir: Path = BASE_DIR

    # -- Seguranca ---------------------------------------------------------
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    encryption_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    refresh_token_days: int = 7
    password_min_length: int = 10

    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "TroqueEstaSenha123!"
    bootstrap_admin_name: str = "Administrador"

    # -- Banco de metadados ------------------------------------------------
    database_url: str = "sqlite:///./data/studio.db"
    run_migrations_on_startup: bool = True

    # -- Banco alvo --------------------------------------------------------
    allow_write_operations: bool = False
    mssql_driver: str = "ODBC Driver 18 for SQL Server"
    introspection_cache_ttl: int = 300
    query_timeout: int = 30
    max_rows: int = 1000

    # -- Runtime -----------------------------------------------------------
    runtime_prefix: str = "/api/v1"
    rate_limit_per_minute: int = 120
    cors_origins: str = "*"

    # -- Modo avancado -----------------------------------------------------
    advanced_enabled: bool = True
    advanced_timeout_seconds: int = 10
    advanced_max_code_bytes: int = 65536

    # ---------------------------------------------------------------------
    @field_validator("runtime_prefix")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        value = "/" + value.strip().strip("/")
        if value == "/":
            raise ValueError("runtime_prefix nao pode ser vazio")
        return value

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"log_level invalido: {value}")
        return level

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.env == "production":
            lowered = self.secret_key.lower()
            if any(marker in lowered for marker in INSECURE_SECRET_MARKERS):
                raise ValueError(
                    "STUDIO_SECRET_KEY insegura para STUDIO_ENV=production. "
                    'Gere uma com: python -c "import secrets;print(secrets.token_urlsafe(48))"'
                )
            if len(self.secret_key) < 32:
                raise ValueError("STUDIO_SECRET_KEY deve ter ao menos 32 caracteres em producao")
            if self.debug:
                raise ValueError("STUDIO_DEBUG nao pode ser true em producao")
        return self

    # -- Derivados ---------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return (self.base_dir / "data").resolve()

    @property
    def is_sqlite_metadata(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if not raw or raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def web_dir(self) -> Path:
        return (self.base_dir / "app" / "web").resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instancia unica de configuracao (cacheada)."""
    return Settings()


def reset_settings_cache() -> None:
    """Limpa o cache de configuracao (util em testes)."""
    get_settings.cache_clear()
