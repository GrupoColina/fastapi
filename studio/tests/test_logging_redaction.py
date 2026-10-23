"""Testes da redacao de PII no logging estruturado.

Regra do projeto: senhas, tokens e chaves de API nunca aparecem em log; quando o
campo tem nome sensivel, preservamos a chave e o comprimento, nao o valor.
"""

from __future__ import annotations

import json
import logging

from app.core.logging import REDACTED, JsonFormatter, PIIRedactor


def test_redact_text_esconde_senha_em_connection_string():
    texto = "Server=erp;Database=com;User Id=app;Password=Segredo123;"
    redigido = PIIRedactor.redact_text(texto)
    assert "Segredo123" not in redigido
    assert "Password=***REDACTED***" in redigido


def test_redact_text_esconde_credenciais_de_url():
    redigido = PIIRedactor.redact_text("postgresql://usuario:segredo@host:5432/banco")
    assert "segredo" not in redigido
    assert "usuario:***REDACTED***@host" in redigido


def test_redact_text_esconde_bearer_token():
    redigido = PIIRedactor.redact_text("Authorization: Bearer abcdefghij123456")
    assert "abcdefghij123456" not in redigido
    assert "Bearer ***REDACTED***" in redigido


def test_redact_text_esconde_json_inline_e_api_key():
    payload = '{"password": "abc", "api_key": "sk_live_abcdef123"}'
    redigido = PIIRedactor.redact_text(payload)
    assert "abc" not in redigido
    assert "sk_live_abcdef123" not in redigido
    assert redigido.count(REDACTED) == 2


def test_redact_text_esconde_jwt():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefgh"
    redigido = PIIRedactor.redact_text(f"credencial={jwt}")
    assert jwt not in redigido
    assert "credencial=***REDACTED***" in redigido


def test_redact_text_texto_vazio_e_preservado():
    assert PIIRedactor.redact_text("") == ""


def test_redact_mapping_preserva_chave_e_comprimento():
    entrada = {
        "senha": "abcdef",
        "usuario": "ana",
        "token": 1234,
        "aninhado": {"password": "xy"},
    }
    saida = PIIRedactor.redact_mapping(entrada)
    assert saida["senha"] == f"{REDACTED}(len=6)"
    assert saida["usuario"] == "ana"
    assert saida["token"] == REDACTED
    assert saida["aninhado"]["password"] == f"{REDACTED}(len=2)"


def test_redact_mapping_de_lista_de_dicionarios():
    entrada = {"itens": [{"token": "abcd"}, {"nome": "ok"}]}
    saida = PIIRedactor.redact_mapping(entrada)
    assert saida["itens"][0]["token"] == f"{REDACTED}(len=4)"
    assert saida["itens"][1]["nome"] == "ok"


def test_redact_value_por_nome_de_campo():
    assert PIIRedactor.redact_value("api_key", "segredo") == f"{REDACTED}(len=7)"
    assert PIIRedactor.redact_value("nome", "ana") == "ana"
    assert PIIRedactor.redact_value("password", 123) == REDACTED


def test_json_formatter_redige_mensagem_e_inclui_metadados():
    record = logging.LogRecord(
        name="studio.teste",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="falha ao conectar com password=%s",
        args=("SenhaMuitoSecreta",),
        exc_info=None,
    )
    record.request_id = "rid-1"
    record.status_code = 200

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "studio.teste"
    assert "SenhaMuitoSecreta" not in payload["message"]
    assert payload["message"] == "falha ao conectar com password=***REDACTED***"
    assert payload["request_id"] == "rid-1"
    assert payload["status_code"] == 200
    assert "ts" in payload
