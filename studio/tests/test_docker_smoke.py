"""Smoke test de Docker.

Valida a composicao do projeto quando existe um arquivo ``docker compose``.
A suite so roda quando o binario ``docker`` esta disponivel E a variavel
``STUDIO_TEST_DOCKER`` vale ``"1"``. Como o repositorio nao traz nenhum arquivo
de composicao, o teste detecta a ausencia e e pulado (marcador ``docker``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        shutil.which("docker") is None or os.getenv("STUDIO_TEST_DOCKER") != "1",
        reason="docker indisponivel ou STUDIO_TEST_DOCKER != 1",
    ),
]

RAIZ = Path(__file__).resolve().parents[1]

COMPOSE_CANDIDATOS = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)


def _arquivo_compose() -> Path | None:
    """Devolve o primeiro arquivo de composicao encontrado na raiz do projeto."""
    for nome in COMPOSE_CANDIDATOS:
        candidato = RAIZ / nome
        if candidato.is_file():
            return candidato
    return None


def test_compose_config_valido() -> None:
    """``docker compose config`` deve validar o arquivo de composicao."""
    compose = _arquivo_compose()
    if compose is None:
        pytest.skip("nenhum arquivo docker compose encontrado no repositorio")

    resultado = subprocess.run(
        ["docker", "compose", "-f", str(compose), "config", "--quiet"],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr
