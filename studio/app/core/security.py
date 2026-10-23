"""Primitivas de seguranca: senhas, JWT, API keys e cifra de segredos.

Decisoes:
* Senhas com **Argon2id** via ``pwdlib``.
* JWT **HS256** com distincao explicita entre ``access`` e ``refresh`` (claim ``typ``).
* API keys no formato ``sk_<env>_<prefixo>_<segredo>``. Apenas o **hash SHA-256** e o
  prefixo sao persistidos; o segredo em claro existe somente no momento da criacao.
* Segredos de datasource cifrados com **Fernet**; a chave e ``STUDIO_ENCRYPTION_KEY`` ou,
  na ausencia dela, derivada da ``STUDIO_SECRET_KEY`` via SHA-256.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash

API_KEY_PREFIX = "sk"
API_KEY_PUBLIC_PREFIX_LENGTH = 12
API_KEY_SECRET_BYTES = 32

TokenType = Literal["access", "refresh"]

_password_hash = PasswordHash.recommended()


# ---------------------------------------------------------------------------
# Senhas
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Gera o hash Argon2id da senha."""
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica a senha contra o hash, sem lancar excecao em hash invalido."""
    if not password_hash:
        return False
    try:
        return _password_hash.verify(password, password_hash)
    except Exception:  # noqa: BLE001 - hash corrompido/legado nao deve derrubar o login
        return False


def password_policy_errors(password: str, min_length: int) -> list[str]:
    """Valida a politica minima de senha e devolve a lista de violacoes."""
    errors: list[str] = []
    if len(password) < min_length:
        errors.append(f"senha deve ter ao menos {min_length} caracteres")
    if not any(char.isdigit() for char in password):
        errors.append("senha deve conter ao menos um digito")
    if not any(char.isalpha() for char in password):
        errors.append("senha deve conter ao menos uma letra")
    if password.lower() in {"password", "senha", "123456", "admin"}:
        errors.append("senha demasiadamente comum")
    return errors


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def _encode(payload: dict[str, Any], secret: str, algorithm: str) -> str:
    return jwt.encode(payload, secret, algorithm=algorithm)


def create_token(
    *,
    subject: str,
    token_type: TokenType,
    secret: str,
    algorithm: str,
    access_minutes: int = 60,
    refresh_days: int = 7,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, datetime]:
    """Cria um JWT e devolve ``(token, expira_em)``."""
    now = datetime.now(timezone.utc)
    if token_type == "access":
        expires_at = now + timedelta(minutes=access_minutes)
    else:
        expires_at = now + timedelta(days=refresh_days)

    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
        "iss": "fastapi-studio",
    }
    if extra_claims:
        payload.update(extra_claims)
    return _encode(payload, secret, algorithm), expires_at


def create_access_token(*, subject: str, secret: str, algorithm: str, minutes: int,
                        extra_claims: dict[str, Any] | None = None) -> tuple[str, datetime]:
    return create_token(
        subject=subject, token_type="access", secret=secret, algorithm=algorithm,
        access_minutes=minutes, extra_claims=extra_claims,
    )


def create_refresh_token(*, subject: str, secret: str, algorithm: str, days: int) -> tuple[str, datetime]:
    return create_token(
        subject=subject, token_type="refresh", secret=secret, algorithm=algorithm,
        refresh_days=days,
    )


class TokenError(Exception):
    """Token ausente, expirado, com assinatura invalida ou de tipo incorreto."""


def decode_token(token: str, *, secret: str, algorithm: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Decodifica e valida um JWT."""
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm], issuer="fastapi-studio")
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expirado") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token invalido") from exc

    if expected_type is not None and payload.get("typ") != expected_type:
        raise TokenError(f"tipo de token invalido: esperado {expected_type}")
    if not payload.get("sub"):
        raise TokenError("token sem subject")
    return payload


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GeneratedApiKey:
    """Resultado da geracao de uma API key."""

    plaintext: str
    prefix: str
    hashed: str
    environment: str


def hash_api_key(plaintext: str) -> str:
    """Hash SHA-256 (hex) do segredo completo da API key."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def public_prefix_of(plaintext: str) -> str:
    """Extrai o prefixo publico usado para localizar a chave no banco."""
    return plaintext[:API_KEY_PUBLIC_PREFIX_LENGTH]


def generate_api_key(environment: str = "live") -> GeneratedApiKey:
    """Gera uma nova API key. O texto em claro deve ser mostrado apenas uma vez."""
    env = "test" if environment not in {"live", "test"} else environment
    secret = secrets.token_urlsafe(API_KEY_SECRET_BYTES)
    plaintext = f"{API_KEY_PREFIX}_{env}_{secrets.token_hex(4)}_{secret}"
    return GeneratedApiKey(
        plaintext=plaintext,
        prefix=public_prefix_of(plaintext),
        hashed=hash_api_key(plaintext),
        environment=env,
    )


def constant_time_equals(left: str, right: str) -> bool:
    """Comparacao resistente a ataques de temporizacao."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


# ---------------------------------------------------------------------------
# Cifra de segredos (senhas de datasource)
# ---------------------------------------------------------------------------
class SecretCipher:
    """Cifra simetrica de segredos armazenados no banco de metadados."""

    def __init__(self, key: str | None, fallback_secret: str) -> None:
        material = (key or "").strip()
        if material:
            try:
                self._fernet = Fernet(material.encode("utf-8"))
                return
            except (ValueError, TypeError):
                # Chave fora do formato Fernet: deriva deterministicamente.
                pass
        digest = hashlib.sha256(fallback_secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise SecretDecryptionError(
                "nao foi possivel decifrar o segredo; a STUDIO_ENCRYPTION_KEY pode ter mudado"
            ) from exc


class SecretDecryptionError(Exception):
    """Segredo armazenado nao pode ser decifrado com a chave atual."""
