"""Engine, sessao e ciclo de vida do banco de metadados."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base


def build_engine(database_url: str, *, echo: bool = False, pool_pre_ping: bool = True) -> Engine:
    """Cria o engine de metadados, aplicando ajustes especificos de SQLite."""
    url = database_url
    connect_args: dict[str, object] = {}

    if url.startswith("sqlite"):
        # Garante que o diretorio do arquivo exista antes do connect.
        prefix = "sqlite:///"
        if url.startswith(prefix):
            raw_path = url[len(prefix):]
            if raw_path and raw_path != ":memory:":
                Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False

    engine = create_engine(
        url,
        echo=echo,
        future=True,
        pool_pre_ping=pool_pre_ping and not url.startswith("sqlite"),
        connect_args=connect_args,
    )

    if url.startswith("sqlite"):
        _enable_sqlite_foreign_keys(engine)

    return engine


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    """SQLite ignora FK por padrao; habilita em toda conexao."""

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, connection_record):  # noqa: ANN001, ANN202
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


class Database:
    """Agrupa engine e session factory, permitindo instancias isoladas em testes."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        self.url = database_url
        self.engine = build_engine(database_url, echo=echo)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )

    # -- Ciclo de vida -----------------------------------------------------
    def create_all(self) -> None:
        """Cria o schema a partir dos modelos (usado em testes e bancos efemeros)."""
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()

    # -- Helpers -----------------------------------------------------------
    @contextmanager
    def session(self) -> Iterator[Session]:
        """Context manager transacional: commit no sucesso, rollback no erro."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def ping(self) -> bool:
        """Verifica se o banco de metadados responde."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001
            return False
