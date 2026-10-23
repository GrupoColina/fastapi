"""Validacao por AST do codigo do modo avancado.

Politica: **negar por padrao**. O codigo so roda se a arvore sintatica nao contiver
nenhuma construcao fora da allow-list. A execucao em si ocorre em subprocesso isolado
(``app.advanced.runner``); esta camada evita que codigo claramente perigoso chegue la.
"""

from __future__ import annotations

import ast

MAX_NODES = 4000

ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {"json", "re", "math", "datetime", "decimal", "uuid", "base64", "hashlib", "statistics"}
)

# Chamadas proibidas (por nome da funcao).
FORBIDDEN_CALLS: frozenset[str] = frozenset(
    {
        "__import__", "eval", "exec", "compile", "open", "input", "globals", "locals",
        "vars", "dir", "getattr", "setattr", "delattr", "breakpoint", "memoryview",
        "exit", "quit", "help",
        # `print` fica fora: o protocolo do sandbox usa stdout para serializar o JSON
        # de resposta. O codigo devolve dados, o runtime cuida do logging.
        "print",
    }
)

# Modulos claramente perigosos, apenas para produzir mensagem melhor.
DANGEROUS_MODULES: frozenset[str] = frozenset(
    {"os", "sys", "subprocess", "socket", "shutil", "pathlib", "ctypes", "importlib",
     "pickle", "marshal", "tempfile", "signal", "multiprocessing", "threading",
     "requests", "httpx", "urllib", "http", "sqlite3", "sqlalchemy", "builtins"}
)

_FORBIDDEN_NODES: tuple[type[ast.AST], ...] = (
    ast.Global,
    ast.Nonlocal,
    ast.With,
    ast.AsyncWith,
    ast.AsyncFunctionDef,
    ast.AsyncFor,
    ast.Await,
    ast.ClassDef,
    ast.Delete,
)


def validate_code(code: str, *, max_bytes: int = 65536) -> list[str]:
    """Valida o codigo e devolve a lista de problemas encontrados."""
    errors: list[str] = []

    if not code or not code.strip():
        return ["o modo avancado exige que o campo 'advanced_code' seja preenchido"]

    if len(code.encode("utf-8")) > max_bytes:
        return [f"codigo do modo avancado excede {max_bytes} bytes"]

    try:
        tree = ast.parse(code, filename="<studio-advanced>", mode="exec")
    except SyntaxError as exc:
        return [f"erro de sintaxe na linha {exc.lineno}: {exc.msg}"]

    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > MAX_NODES:
        errors.append(f"codigo muito complexo ({node_count} nos; maximo {MAX_NODES})")

    has_handle = False

    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODES):
            errors.append(f"{type(node).__name__} nao e permitido no modo avancado")

        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    reasons = "modulo sensivel" if root in DANGEROUS_MODULES else "fora da allow-list"
                    errors.append(f"import nao permitido: '{alias.name}' ({reasons})")

        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORTS:
                reasons = "modulo sensivel" if root in DANGEROUS_MODULES else "fora da allow-list"
                errors.append(f"import nao permitido: 'from {node.module} import ...' ({reasons})")

        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in FORBIDDEN_CALLS:
                errors.append(f"chamada nao permitida: {name}()")

        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                errors.append(f"acesso a atributo especial nao permitido: .{node.attr}")

        elif isinstance(node, ast.Name):
            if node.id in {"__builtins__", "__loader__", "__spec__"}:
                errors.append(f"acesso a '{node.id}' nao permitido")

        elif isinstance(node, ast.FunctionDef) and node.name == "handle":
            has_handle = True

    if not has_handle:
        errors.append("o codigo deve definir uma funcao 'handle(ctx)'")

    return errors


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""
