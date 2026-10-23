"""Ambiente Alembic do banco de metadados do Studio.

A URL vem de ``STUDIO_DATABASE_URL`` (via :class:`app.core.config.Settings`), de modo que
``alembic upgrade head`` funciona sem editar o ``alembic.ini``.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

# Importa os modelos para popular Base.metadata (necessario para o autogenerate).
from app.core.config import get_settings
from app.db.base import Base, UTCDateTime
from app.db.session import build_engine
from app.db import models  # noqa: F401  (efeito colateral: registra as tabelas)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context) -> str | bool:  # noqa: ANN001
    """Renderiza tipos customizados como tipos SQLAlchemy equivalentes.

    Sem isto o autogenerate emite ``app.db.base.UTCDateTime(...)``, que nao existe no
    namespace das migracoes. O tipo do banco e o mesmo (DATETIME/TIMESTAMP com timezone).
    """
    if type_ == "type" and isinstance(obj, UTCDateTime):
        autogen_context.imports.add("import sqlalchemy as sa")
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    """Executa as migracoes gerando SQL, sem conexao ativa."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=settings.is_sqlite_metadata,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Executa as migracoes conectando ao banco."""
    # build_engine garante a criacao do diretorio do arquivo quando o alvo e SQLite.
    connectable = build_engine(settings.database_url, pool_pre_ping=False)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=settings.is_sqlite_metadata,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
