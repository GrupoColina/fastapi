"""Testes do modo avancado: validacao por AST e execucao em subprocesso isolado."""

from __future__ import annotations

import pytest

from app.advanced.runner import run_advanced
from app.advanced.validator import validate_code

CODIGO_VALIDO = (
    "def handle(ctx):\n"
    "    total = sum(ctx['params'].get('valores', []))\n"
    "    return {'total': total}\n"
)


# ---------------------------------------------------------------------------
# validate_code: allow-list por AST
# ---------------------------------------------------------------------------
def test_codigo_valido_e_aprovado():
    assert validate_code(CODIGO_VALIDO) == []


def test_codigo_vazio_e_recusado():
    assert validate_code("") == ["o modo avancado exige que o campo 'advanced_code' seja preenchido"]


def test_erro_de_sintaxe():
    erros = validate_code("def handle(ctx) return {}")
    assert any("erro de sintaxe" in erro for erro in erros)


def test_exige_funcao_handle():
    erros = validate_code("def outra(ctx):\n    return {}\n")
    assert "o codigo deve definir uma funcao 'handle(ctx)'" in erros


@pytest.mark.parametrize(
    "codigo",
    [
        "import os\n\ndef handle(ctx):\n    return {}\n",
        "import sys\n\ndef handle(ctx):\n    return {}\n",
        "from subprocess import run\n\ndef handle(ctx):\n    return {}\n",
        "def handle(ctx):\n    print('oi')\n    return {}\n",
        "def handle(ctx):\n    return eval('1')\n",
        "def handle(ctx):\n    exec('x = 1')\n    return {}\n",
        "def handle(ctx):\n    return open('/etc/passwd').read()\n",
        "def handle(ctx):\n    return __import__('os')\n",
    ],
)
def test_imports_e_chamadas_proibidas(codigo: str):
    erros = validate_code(codigo)
    assert erros, f"o codigo deveria ser recusado: {codigo!r}"


def test_atributo_especial_e_recusado():
    erros = validate_code("def handle(ctx):\n    return ctx.__class__\n")
    assert any("atributo especial" in erro for erro in erros)


@pytest.mark.parametrize(
    "codigo",
    [
        "def handle(ctx):\n    with open('x') as f:\n        return {}\n",
        "class X:\n    pass\n\ndef handle(ctx):\n    return {}\n",
        "def handle(ctx):\n    async def interno():\n        return 1\n    return {}\n",
        "def handle(ctx):\n    global x\n    return {}\n",
        "def handle(ctx):\n    del ctx\n    return {}\n",
    ],
)
def test_nodes_proibidos(codigo: str):
    erros = validate_code(codigo)
    assert any("nao e permitido" in erro for erro in erros)


# ---------------------------------------------------------------------------
# run_advanced: execucao isolada
# ---------------------------------------------------------------------------
def test_run_advanced_executa_caso_valido():
    outcome = run_advanced(
        CODIGO_VALIDO, {"params": {"valores": [1, 2, 3]}}, timeout_seconds=15
    )
    assert outcome.ok is True
    assert outcome.result == {"total": 6}


def test_run_advanced_recusa_codigo_invalido_sem_executar():
    outcome = run_advanced("import os\n\ndef handle(ctx):\n    return {}\n", {})
    assert outcome.ok is False
    assert "import" in outcome.error


def test_run_advanced_trata_excecao_do_codigo():
    codigo = "def handle(ctx):\n    return 1 / 0\n"
    outcome = run_advanced(codigo, {}, timeout_seconds=15)
    assert outcome.ok is False
    assert "ZeroDivisionError" in outcome.error
    assert outcome.timed_out is False


def test_run_advanced_estoura_timeout():
    codigo = "def handle(ctx):\n    while True:\n        pass\n"
    outcome = run_advanced(codigo, {}, timeout_seconds=1)
    assert outcome.ok is False
    assert outcome.timed_out is True
    assert "excedeu o limite" in outcome.error
