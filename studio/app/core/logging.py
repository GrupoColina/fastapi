"""Logging estruturado em JSON com redacao de PII.

Regra do projeto: senhas, tokens, chaves de API e strings de conexao **nunca** aparecem
em log. O ``PIIRedactor`` e aplicado ao formatter, portanto vale para qualquer logger da
aplicacao, inclusive os de terceiros que usem o mesmo handler.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

REDACTED = "***REDACTED***"

_SENSITIVE_KEYS = (
    "password",
    "passwd",
    "senha",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
)

# Padroes aplicados ao texto livre (mensagens, tracebacks, DSNs).
_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # DSN/connection string com senha:  Server=x;User Id=y;Password=z;
    (
        re.compile(r"(?i)\b(password|pwd)\s*=\s*([^;&\s\"']+)"),
        rf"\1={REDACTED}",
    ),
    # URL com credenciais:  scheme://user:pass@host
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^:/\s@]+):([^@/\s]+)@"),
        rf"\1:{REDACTED}@",
    ),
    # Bearer tokens
    (
        re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}"),
        rf"\1 {REDACTED}",
    ),
    # JSON inline: "password": "valor"
    (
        re.compile(r"(?i)\"(password|senha|secret|token|api_key)\"\s*:\s*\"[^\"]*\""),
        rf'"\1": "{REDACTED}"',
    ),
    # Chave publica de API key do Studio: sk_live_xxx / sk_test_xxx
    (re.compile(r"\bsk_(live|test)_[A-Za-z0-9_\-]{6,}"), REDACTED),
    # JWT
    (
        re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}"),
        REDACTED,
    ),
)


class PIIRedactor:
    """Utilitario de sanitizacao de dados sensiveis."""

    @staticmethod
    def redact_text(text: str) -> str:
        if not text:
            return text
        for pattern, replacement in _TEXT_PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    @classmethod
    def redact_mapping(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Redige recursivamente um dicionario preservando chaves e comprimentos."""
        result: dict[str, Any] = {}
        for key, value in data.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SENSITIVE_KEYS):
                if isinstance(value, str):
                    result[key] = f"{REDACTED}(len={len(value)})"
                else:
                    result[key] = REDACTED
            elif isinstance(value, dict):
                result[key] = cls.redact_mapping(value)
            elif isinstance(value, (list, tuple)):
                result[key] = [
                    cls.redact_mapping(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    @classmethod
    def redact_value(cls, key: str, value: Any) -> Any:
        """Redige um unico valor de acordo com o nome do campo."""
        lowered = key.lower()
        if any(marker in lowered for marker in _SENSITIVE_KEYS):
            if isinstance(value, str):
                return f"{REDACTED}(len={len(value)})"
            return REDACTED
        return value


class JsonFormatter(logging.Formatter):
    """Formatter que serializa cada registro como uma linha JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": PIIRedactor.redact_text(record.getMessage()),
        }

        for attr in ("request_id", "method", "path", "status_code", "duration_ms", "user", "extra_data"):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = value

        if record.exc_info:
            formatter = logging.Formatter()
            payload["exception"] = PIIRedactor.redact_text(formatter.formatException(record.exc_info))

        return json.dumps(payload, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    """Formatter legivel para desenvolvimento local, tambem com redacao."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        return PIIRedactor.redact_text(base)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configura o logging raiz da aplicacao (idempotente)."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            HumanFormatter("%(asctime)s %(levelname)-8s %(name)s :: %(message)s")
        )
    root.addHandler(handler)

    # Reduz ruido de bibliotecas de terceiros.
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine", "multipart"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, logging.getLogger().level))


def get_logger(name: str) -> logging.Logger:
    """Atalho para obter um logger nomeado."""
    return logging.getLogger(name)
