"""Execucao isolada do codigo do modo avancado.

Modelo de ameaca e limitacoes (declaradas explicitamente):

* O codigo roda em um **subprocesso Python** iniciado com ``-I`` (modo isolado: sem
  ``PYTHONPATH``, sem *user site*), com diretorio de trabalho em pasta temporaria vazia.
* A comunicacao e **apenas JSON** por stdin/stdout: nao ha objetos compartilhados com o
  processo principal.
* Ha um **timeout** por execucao; ao estourar, o processo e morto e o endpoint responde
  504 sem derrubar a aplicacao.
* O ``stdout`` do codigo do usuario e capturado para nao corromper o protocolo.

**Isto nao e uma jail de sistema operacional** (nao usa namespaces/seccomp). E um sandbox
defensivo de camada de aplicacao, adequado para operadores internos autorizados. Para
execucao multi-inquilino hostil, o passo seguinte e rodar este subprocesso dentro de um
container dedicado com ``--network none --read-only``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.advanced.validator import validate_code

MAX_CAPTURED_OUTPUT = 4000

_RUNNER = r'''
import io
import json
import sys

def _main():
    payload = json.loads(sys.stdin.read() or "{}")
    code = payload.get("code", "")
    ctx = payload.get("ctx", {}) or {}

    real_stdout = sys.stdout
    buffer = io.StringIO()
    sys.stdout = buffer
    try:
        namespace = {"__name__": "studio_advanced"}
        exec(compile(code, "<studio-advanced>", "exec"), namespace)
        handler = namespace.get("handle")
        if not callable(handler):
            outcome = {"ok": False, "error": "o codigo nao define a funcao handle(ctx)"}
        else:
            result = handler(ctx)
            outcome = {"ok": True, "result": result}
    except Exception as exc:
        outcome = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    finally:
        captured = buffer.getvalue()
        sys.stdout = real_stdout

    outcome["captured_output"] = captured[-4000:]
    real_stdout.write(json.dumps(outcome, default=str))

_main()
'''


@dataclass
class AdvancedOutcome:
    """Resultado da execucao do codigo personalizado."""

    ok: bool
    result: Any = None
    error: str = ""
    captured_output: str = ""
    duration_ms: int = 0
    timed_out: bool = False


def run_advanced(code: str, ctx: dict[str, Any], *, timeout_seconds: int = 10,
                 max_code_bytes: int = 65536) -> AdvancedOutcome:
    """Valida e executa o codigo do modo avancado."""
    errors = validate_code(code, max_bytes=max_code_bytes)
    if errors:
        return AdvancedOutcome(ok=False, error="; ".join(errors))

    started = time.perf_counter()
    payload = json.dumps({"code": code, "ctx": ctx}, default=str)

    with tempfile.TemporaryDirectory(prefix="studio-advanced-") as workdir:
        try:
            completed = subprocess.run(  # noqa: S603
                [sys.executable, "-I", "-c", _RUNNER],
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=Path(workdir),
                check=False,
                encoding="utf-8",
            )
        except subprocess.TimeoutExpired:
            return AdvancedOutcome(
                ok=False,
                error=f"a execucao excedeu o limite de {timeout_seconds}s",
                duration_ms=int((time.perf_counter() - started) * 1000),
                timed_out=True,
            )

    duration_ms = int((time.perf_counter() - started) * 1000)

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip().splitlines()
        detail = stderr[-1] if stderr else "processo terminou com erro"
        return AdvancedOutcome(
            ok=False,
            error=f"falha ao executar o codigo personalizado: {detail[:300]}",
            duration_ms=duration_ms,
        )

    raw = (completed.stdout or "").strip()
    if not raw:
        return AdvancedOutcome(
            ok=False, error="o codigo personalizado nao produziu resultado", duration_ms=duration_ms
        )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return AdvancedOutcome(
            ok=False,
            error=f"resposta invalida do sandbox: {raw[:200]}",
            duration_ms=duration_ms,
        )

    return AdvancedOutcome(
        ok=bool(parsed.get("ok")),
        result=parsed.get("result"),
        error=str(parsed.get("error") or ""),
        captured_output=str(parsed.get("captured_output") or "")[:MAX_CAPTURED_OUTPUT],
        duration_ms=duration_ms,
    )
