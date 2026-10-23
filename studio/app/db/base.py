"""Declarative base e utilitarios de tempo para o ORM."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, TypeDecorator
from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    """Instante atual em UTC com timezone (formato canonico do Studio)."""
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Guarda ``datetime`` sempre em UTC.

    O SQLite descarta o timezone; este tipo garante que o valor lido de volta seja
    novamente timezone-aware em UTC, mantendo o comportamento identico entre
    SQLite (desenvolvimento/teste) e Postgres (producao).
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value: datetime | None, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    """Base declarativa do banco de metadados."""

    type_annotation_map = {  # noqa: RUF012
        datetime: UTCDateTime,
        str: String(255),
    }

    def to_dict(self) -> dict[str, object]:
        """Representacao simples das colunas mapeadas."""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
