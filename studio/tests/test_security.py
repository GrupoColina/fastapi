"""Testes das primitivas de seguranca (app.core.security)."""

from __future__ import annotations

import hashlib

import jwt
import pytest
from cryptography.fernet import Fernet

from app.core.security import (
    SecretCipher,
    SecretDecryptionError,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    password_policy_errors,
    public_prefix_of,
    verify_password,
)

SEGREDO = "s" * 48
ALGO = "HS256"


# ---------------------------------------------------------------------------
# Senhas
# ---------------------------------------------------------------------------
def test_hash_de_senha_usa_argon2id_e_verifica():
    digest = hash_password("SenhaForte123")
    assert digest.startswith("$argon2id$")
    assert verify_password("SenhaForte123", digest) is True
    assert verify_password("outra-senha", digest) is False


def test_verify_com_hash_ausente_retorna_false():
    assert verify_password("x", "") is False


def test_verify_com_hash_corrompido_nao_levanta():
    assert verify_password("x", "isto-nao-e-um-hash") is False


def test_politica_de_senha_valida():
    assert password_policy_errors("SenhaForte123", 10) == []


def test_politica_de_senha_reprova_violacoes():
    erros = password_policy_errors("a1", 10)
    assert any("10 caracteres" in erro for erro in erros)
    somente_letras = password_policy_errors("somenteletras", 5)
    assert any("digito" in erro for erro in somente_letras)
    somente_digitos = password_policy_errors("123456789", 5)
    assert any("letra" in erro for erro in somente_digitos)


def test_politica_de_senha_reprova_comuns():
    assert any(
        "comum" in erro for erro in password_policy_errors("password", 5)
    )


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def test_access_token_possui_claims_esperados():
    token, expira_em = create_access_token(
        subject="7", secret=SEGREDO, algorithm=ALGO, minutes=60
    )
    claims = decode_token(token, secret=SEGREDO, algorithm=ALGO, expected_type="access")
    assert claims["typ"] == "access"
    assert claims["iss"] == "fastapi-studio"
    assert claims["sub"] == "7"
    assert claims["jti"]
    assert claims["exp"] > claims["iat"]
    assert expira_em is not None


def test_refresh_token_possui_claims_esperados():
    token, _ = create_refresh_token(subject="7", secret=SEGREDO, algorithm=ALGO, days=7)
    claims = decode_token(token, secret=SEGREDO, algorithm=ALGO, expected_type="refresh")
    assert claims["typ"] == "refresh"
    assert claims["jti"]


def test_rejeita_token_com_tipo_trocado():
    token, _ = create_access_token(subject="7", secret=SEGREDO, algorithm=ALGO, minutes=60)
    with pytest.raises(TokenError):
        decode_token(token, secret=SEGREDO, algorithm=ALGO, expected_type="refresh")


def test_rejeita_assinatura_invalida():
    token, _ = create_access_token(subject="7", secret=SEGREDO, algorithm=ALGO, minutes=60)
    with pytest.raises(TokenError):
        decode_token(token, secret="outro-segredo", algorithm=ALGO, expected_type="access")


def test_rejeita_token_expirado():
    token, _ = create_access_token(subject="7", secret=SEGREDO, algorithm=ALGO, minutes=-1)
    with pytest.raises(TokenError):
        decode_token(token, secret=SEGREDO, algorithm=ALGO, expected_type="access")


def test_rejeita_token_sem_issuer():
    token = jwt.encode({"sub": "7", "typ": "access"}, SEGREDO, algorithm=ALGO)
    with pytest.raises(TokenError):
        decode_token(token, secret=SEGREDO, algorithm=ALGO, expected_type="access")


def test_rejeita_token_sem_subject():
    token = jwt.encode(
        {"typ": "access", "iss": "fastapi-studio"}, SEGREDO, algorithm=ALGO
    )
    with pytest.raises(TokenError):
        decode_token(token, secret=SEGREDO, algorithm=ALGO, expected_type="access")


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
def test_gera_api_key_formato_e_hash():
    chave = generate_api_key("live")
    assert chave.plaintext.startswith("sk_live_")
    assert chave.environment == "live"
    assert chave.prefix == public_prefix_of(chave.plaintext)
    assert chave.prefix == chave.plaintext[:12]
    assert chave.hashed == hash_api_key(chave.plaintext)
    assert chave.hashed == hashlib.sha256(chave.plaintext.encode("utf-8")).hexdigest()
    # Apenas o hash e persistido: o segredo em claro nunca aparece nele.
    assert chave.plaintext not in chave.hashed


def test_ambiente_desconhecido_vira_test():
    chave = generate_api_key("producao")
    assert chave.environment == "test"
    assert chave.plaintext.startswith("sk_test_")


def test_api_keys_geradas_sao_distintas():
    assert generate_api_key().plaintext != generate_api_key().plaintext


def test_hash_api_key_e_deterministico():
    assert hash_api_key("abc") == hash_api_key("abc")
    assert hash_api_key("abc") != hash_api_key("abd")


# ---------------------------------------------------------------------------
# Cifra de segredos
# ---------------------------------------------------------------------------
def test_cipher_round_trip_com_chave_fernet():
    cipher = SecretCipher(Fernet.generate_key().decode("ascii"), SEGREDO)
    cifrado = cipher.encrypt("senha-do-erp")
    assert cifrado != "senha-do-erp"
    assert cipher.decrypt(cifrado) == "senha-do-erp"


def test_cipher_deriva_chave_quando_ausente_ou_invalida():
    sem_chave = SecretCipher(None, SEGREDO)
    chave_invalida = SecretCipher("nao-e-uma-chave-fernet", SEGREDO)
    outra_sem_chave = SecretCipher(None, SEGREDO)
    assert sem_chave.decrypt(chave_invalida.encrypt("valor")) == "valor"
    assert sem_chave.decrypt(outra_sem_chave.encrypt("valor")) == "valor"


def test_cipher_falha_ao_decifrar_com_chave_diferente():
    a = SecretCipher(None, "segredo-um")
    b = SecretCipher(None, "segredo-dois")
    with pytest.raises(SecretDecryptionError):
        b.decrypt(a.encrypt("valor"))
