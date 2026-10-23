"""Casos de uso de fontes de dados: CRUD, teste de conexao e introspeccao.

Este modulo **nao** pode se chamar ``datasources``: existe o pacote
``app.services.datasources`` (adaptadores). Em CPython o pacote tem precedencia sobre
um modulo de mesmo nome, o que tornaria este arquivo inalcancavel.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.core.logging import get_logger
from app.core.security import SecretCipher
from app.db.base import utcnow
from app.db.models import (
    DS_KIND_SQLITE,
    DS_KIND_SQLSERVER,
    DS_KINDS,
    Datasource,
    DatasourceObject,
)
from app.schemas.api import DatasourceCreate, DatasourceUpdate, DiscoveredObjectOut  # noqa: F401
from app.services.datasources.base import ConnectionProbe, ExecutionResult  # noqa: F401
from app.services.datasources.registry import build_adapter

logger = get_logger("studio.datasources")


# ---------------------------------------------------------------------------
# Leitura e validacao
# ---------------------------------------------------------------------------
def get_datasource_or_404(session: Session, datasource_id: int) -> Datasource:
    source = session.get(Datasource, datasource_id)
    if source is None:
        raise NotFoundError(f"fonte de dados {datasource_id} nao encontrada")
    return source


def _validate(payload: DatasourceCreate) -> None:
    if payload.kind not in DS_KINDS:
        raise ValidationFailure(f"tipo de fonte de dados invalido: {payload.kind}")
    if payload.kind == DS_KIND_SQLSERVER:
        missing = [
            field
            for field, value in (("host", payload.host), ("database", payload.database))
            if not str(value or "").strip()
        ]
        if missing:
            raise ValidationFailure(
                "campos obrigatorios para SQL Server: " + ", ".join(missing)
            )
    if payload.kind == DS_KIND_SQLITE and not payload.file_path.strip():
        raise ValidationFailure("informe 'file_path' para uma fonte SQLite")


def _options_from_payload(payload: DatasourceCreate | DatasourceUpdate) -> dict[str, Any] | None:
    """Extrai as opcoes, promovendo ``discover_schemas`` para ``options['schemas']``."""
    schemas = getattr(payload, "discover_schemas", None)
    options = getattr(payload, "options", None)
    if options is None and schemas is None:
        return None
    merged = dict(options or {})
    if schemas:
        merged["schemas"] = [item.strip() for item in schemas if item.strip()]
    return merged


def serialize(source: Datasource) -> dict[str, Any]:
    """Serializa a fonte **sem nunca expor** a senha."""
    return {
        "id": source.id,
        "project_id": source.project_id,
        "slug": source.slug,
        "name": source.name,
        "kind": source.kind,
        "host": source.host,
        "port": source.port,
        "database": source.database,
        "username": source.username,
        "file_path": source.file_path,
        "options": dict(source.options or {}),
        "is_active": source.is_active,
        "allow_write": source.allow_write,
        "has_password": bool(source.password_enc),
        "last_test_at": source.last_test_at,
        "last_test_ok": source.last_test_ok,
        "last_test_message": source.last_test_message,
        "last_test_latency_ms": source.last_test_latency_ms,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def create_datasource(
    session: Session, *, cipher: SecretCipher, payload: DatasourceCreate
) -> Datasource:
    _validate(payload)
    duplicated = session.scalar(
        select(Datasource).where(
            Datasource.project_id == payload.project_id, Datasource.slug == payload.slug
        )
    )
    if duplicated is not None:
        raise ConflictError(f"ja existe uma fonte com o slug '{payload.slug}' neste projeto")

    source = Datasource(
        project_id=payload.project_id,
        slug=payload.slug,
        name=payload.name,
        kind=payload.kind,
        host=payload.host,
        port=payload.port,
        database=payload.database,
        username=payload.username,
        password_enc=cipher.encrypt(payload.password) if payload.password else "",
        options=_options_from_payload(payload) or {},
        file_path=payload.file_path,
        is_active=payload.is_active,
        allow_write=payload.allow_write,
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def update_datasource(
    session: Session, *, cipher: SecretCipher, source: Datasource, payload: DatasourceUpdate
) -> Datasource:
    if payload.name is not None:
        source.name = payload.name
    if payload.host is not None:
        source.host = payload.host
    if payload.port is not None:
        source.port = payload.port
    if payload.database is not None:
        source.database = payload.database
    if payload.username is not None:
        source.username = payload.username
    if payload.file_path is not None:
        source.file_path = payload.file_path
    if payload.is_active is not None:
        source.is_active = payload.is_active
    if payload.allow_write is not None:
        source.allow_write = payload.allow_write
    if payload.password is not None:
        source.password_enc = cipher.encrypt(payload.password) if payload.password else ""
    options = _options_from_payload(payload)
    if options is not None:
        source.options = options

    source.last_test_ok = None
    source.last_test_message = ""
    session.commit()
    session.refresh(source)
    return source


def delete_datasource(session: Session, source: Datasource) -> None:
    session.delete(source)
    session.commit()


# ---------------------------------------------------------------------------
# Conexao
# ---------------------------------------------------------------------------
def test_connection(
    session: Session, source: Datasource, *, cipher: SecretCipher, settings
) -> ConnectionProbe:  # noqa: ANN001
    """Abre a conexao, mede a latencia e persiste o resultado do teste."""
    adapter = build_adapter(source, cipher, settings=settings)
    probe = adapter.test_connection()

    source.last_test_at = utcnow()
    source.last_test_ok = probe.ok
    source.last_test_message = probe.message
    source.last_test_latency_ms = probe.latency_ms
    session.commit()
    return probe


# ---------------------------------------------------------------------------
# Introspeccao
# ---------------------------------------------------------------------------
def introspect(
    session: Session,
    runtime,  # noqa: ANN001 - StudioRuntime
    source: Datasource,
    *,
    schemas: list[str] | None = None,
) -> dict[str, Any]:
    """Descobre objetos do banco alvo e sincroniza a tabela de objetos.

    Novos objetos entram **nao autorizados** (deny-by-default). Objetos que deixaram de
    existir no banco sao removidos da base de metadados, o que tambem os retira da
    allow-list.
    """
    configured = schemas or (source.options or {}).get("schemas") or None
    adapter = build_adapter(source, runtime.cipher, settings=runtime.settings)

    started = time.perf_counter()
    discovered = adapter.introspect(schemas=set(configured) if configured else None)
    duration_ms = int((time.perf_counter() - started) * 1000)

    existing = {
        (item.schema_name, item.object_name): item
        for item in session.scalars(
            select(DatasourceObject).where(DatasourceObject.datasource_id == source.id)
        )
    }

    seen: set[tuple[str, str]] = set()
    counts = {"table": 0, "view": 0, "procedure": 0}

    for item in discovered:
        key = (item.schema_name, item.object_name)
        seen.add(key)
        record = existing.get(key)
        if record is None:
            record = DatasourceObject(
                datasource_id=source.id,
                schema_name=item.schema_name,
                object_name=item.object_name,
                object_type=item.object_type,
                allowed=False,
            )
            session.add(record)
        record.object_type = item.object_type
        record.columns = [column.as_dict() for column in item.columns]
        record.parameters = [parameter.as_dict() for parameter in item.parameters]
        record.row_count_estimate = item.row_count_estimate
        record.updated_at = utcnow()
        counts[item.object_type] = counts.get(item.object_type, 0) + 1

    for key, record in existing.items():
        if key not in seen:
            session.delete(record)

    session.commit()
    runtime.invalidate_datasource(source.id)

    return {
        "objects": len(seen),
        "tables": counts.get("table", 0),
        "views": counts.get("view", 0),
        "procedures": counts.get("procedure", 0),
        "duration_ms": duration_ms,
    }


def list_objects(
    session: Session,
    datasource_id: int,
    *,
    object_type: str | None = None,
    only_allowed: bool = False,
) -> list[DatasourceObject]:
    statement = select(DatasourceObject).where(DatasourceObject.datasource_id == datasource_id)
    if object_type:
        statement = statement.where(DatasourceObject.object_type == object_type)
    if only_allowed:
        statement = statement.where(DatasourceObject.allowed.is_(True))
    statement = statement.order_by(
        DatasourceObject.object_type, DatasourceObject.schema_name, DatasourceObject.object_name
    )
    return list(session.scalars(statement))


def set_objects_allowed(
    session: Session,
    runtime,  # noqa: ANN001 - StudioRuntime
    source: Datasource,
    object_ids: list[int],
    *,
    allowed: bool,
) -> int:
    """Autoriza/desautoriza objetos e invalida o cache do runtime."""
    records = list(
        session.scalars(
            select(DatasourceObject).where(
                DatasourceObject.datasource_id == source.id,
                DatasourceObject.id.in_(object_ids),
            )
        )
    )
    for record in records:
        record.allowed = allowed
        record.updated_at = utcnow()
    session.commit()
    runtime.invalidate_datasource(source.id)
    return len(records)
