"""Guarda de SQL: leitura semantica de um comando antes de executa-lo.

Objetivo: garantir que um endpoint publicado **so** execute leitura quando a fonte de
dados nao permite escrita, e permitir validar que todas as tabelas/views/procedures
referenciadas estao na allow-list de objetos autorizados.

A protecao principal contra injeção continua sendo o uso obrigatorio de bind parameters
(``sqlalchemy.text`` / ``cursor.execute(sql, params)``). Este modulo e a segunda camada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Comandos considerados somente-leitura.
READ_ONLY_COMMANDS = frozenset({"SELECT", "WITH", "EXEC", "EXECUTE"})
# Comandos de escrita/DDL explicitamente classificados (para mensagens claras).
WRITE_COMMANDS = frozenset(
    {"INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "DROP", "CREATE", "ALTER",
     "GRANT", "REVOKE", "DENY", "REPLACE", "UPSERT", "CALL"}
)
# Construcoes perigosas que nunca devem aparecer em um endpoint de dados.
FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("xp_cmdshell", re.compile(r"\bxp_cmdshell\b", re.IGNORECASE)),
    ("xp_regread", re.compile(r"\bxp_reg(?:read|write|delete)\b", re.IGNORECASE)),
    ("OPENROWSET", re.compile(r"\bOPENROWSET\b", re.IGNORECASE)),
    ("OPENDATASOURCE", re.compile(r"\bOPENDATASOURCE\b", re.IGNORECASE)),
    ("BULK INSERT", re.compile(r"\bBULK\s+INSERT\b", re.IGNORECASE)),
    ("SHUTDOWN", re.compile(r"\bSHUTDOWN\b", re.IGNORECASE)),
    ("RECONFIGURE", re.compile(r"\bRECONFIGURE\b", re.IGNORECASE)),
    ("WAITFOR DELAY", re.compile(r"\bWAITFOR\s+DELAY\b", re.IGNORECASE)),
)

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")
# Literais de texto (com escape '' dentro de '...'). Mantemos o conteudo fora da analise.
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
# Identificadores entre colchetes ou aspas duplas sao preservados (podem ser nomes).
_REFERENCE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE|EXEC(?:UTE)?)\s+((?:\[[^\]]+\]|\"[^\"]+\"|[\w$#@])+"
    r"(?:\s*\.\s*(?:\[[^\]]+\]|\"[^\"]+\"|[\w$#@])+)*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SqlAnalysis:
    """Resultado da analise de um comando SQL."""

    is_read_only: bool
    commands: list[str]
    referenced_objects: list[tuple[str | None, str]]
    forbidden: list[str]
    problems: list[str] = field(default_factory=list)


def strip_comments_and_literals(sql: str) -> str:
    """Remove comentarios e mascarando literais, para analise estrutural segura."""
    cleaned = _BLOCK_COMMENT.sub(" ", sql)
    cleaned = _LINE_COMMENT.sub(" ", cleaned)
    # Substitui o conteudo de literais por um marcador neutro.
    cleaned = _STRING_LITERAL.sub("'?'", cleaned)
    return cleaned


def split_statements(sql: str) -> list[str]:
    """Divide o comando em instrucoes, ignorando separadores vazios."""
    cleaned = strip_comments_and_literals(sql)
    return [part.strip() for part in cleaned.split(";") if part.strip()]


def _unquote(identifier: str) -> str:
    return identifier.strip().strip("[]\"").strip()


def parse_reference(raw: str) -> tuple[str | None, str]:
    """Converte ``dbo.Clientes`` / ``[dbo].[Clientes]`` em ``("dbo", "Clientes")``."""
    parts = [_unquote(part) for part in re.split(r"\s*\.\s*", raw.strip()) if part.strip()]
    if len(parts) == 1:
        return None, parts[0]
    return parts[-2], parts[-1]


def analyze(sql: str) -> SqlAnalysis:
    """Analisa o comando e devolve o diagnostico estrutural."""
    if not sql or not sql.strip():
        return SqlAnalysis(is_read_only=False, commands=[], referenced_objects=[],
                           forbidden=[], problems=["comando SQL vazio"])

    cleaned = strip_comments_and_literals(sql)
    statements = split_statements(sql)

    commands: list[str] = []
    for statement in statements:
        first = re.match(r"\s*([A-Za-z]+)", statement)
        if first:
            commands.append(first.group(1).upper())

    forbidden = [label for label, pattern in FORBIDDEN_PATTERNS if pattern.search(cleaned)]

    references: list[tuple[str | None, str]] = []
    seen: set[tuple[str | None, str]] = set()
    for match in _REFERENCE.finditer(cleaned):
        parsed = parse_reference(match.group(1))
        if parsed[1] and parsed not in seen:
            seen.add(parsed)
            references.append(parsed)

    problems: list[str] = []
    if len(statements) > 1:
        problems.append("apenas uma instrucao SQL por endpoint e permitida")
    if not commands:
        problems.append("nao foi possivel identificar o comando SQL")
    unknown = [cmd for cmd in commands if cmd not in READ_ONLY_COMMANDS | WRITE_COMMANDS]
    if unknown:
        problems.append(f"comando SQL nao reconhecido: {', '.join(unknown)}")

    is_read_only = bool(commands) and all(cmd in READ_ONLY_COMMANDS for cmd in commands)

    return SqlAnalysis(
        is_read_only=is_read_only,
        commands=commands,
        referenced_objects=references,
        forbidden=forbidden,
        problems=problems,
    )


def validate(
    sql: str,
    *,
    allow_write: bool,
    allowed_objects: set[tuple[str | None, str]] | None = None,
    allowed_schemas: set[str] | None = None,
) -> list[str]:
    """Valida o comando e devolve a lista de erros encontrados (vazia = aprovado)."""
    analysis = analyze(sql)
    errors = list(analysis.problems)

    if analysis.forbidden:
        errors.append(
            "construcao proibida no comando: " + ", ".join(analysis.forbidden)
        )

    if not allow_write and not analysis.is_read_only:
        commands = ", ".join(analysis.commands) or "desconhecido"
        errors.append(
            f"a fonte de dados esta em modo somente-leitura; comando detectado: {commands}"
        )

    if allowed_objects is not None:
        for schema_name, object_name in analysis.referenced_objects:
            if schema_name is None:
                # Sem schema explicito: aceita se qualquer schema autorizado tiver o objeto.
                if any(name == object_name for _, name in allowed_objects):
                    continue
                errors.append(
                    f"objeto '{object_name}' nao esta autorizado nesta fonte de dados"
                )
                continue
            if (schema_name, object_name) not in allowed_objects:
                errors.append(
                    f"objeto '{schema_name}.{object_name}' nao esta autorizado nesta fonte de dados"
                )
    elif allowed_schemas:
        for schema_name, object_name in analysis.referenced_objects:
            if schema_name and schema_name not in allowed_schemas:
                continue  # schema nao e objeto: tratado pela allow-list de objetos

    return errors


def extract_parameters(sql: str) -> list[str]:
    """Extrai os nomes de parametros nomeados (``:nome`` ou ``@nome``) do comando."""
    cleaned = strip_comments_and_literals(sql)
    names: list[str] = []
    for match in re.finditer(r"(?<!:)(?::|@)([A-Za-z_][A-Za-z0-9_]*)", cleaned):
        name = match.group(1)
        if name not in names:
            names.append(name)
    return names
