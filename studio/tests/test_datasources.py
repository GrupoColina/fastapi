"""Testes das fontes de dados: adaptador SQLite e casos de uso (datasource_service).

O adaptador SQLite e usado como banco alvo de referencia porque exercita todo o pipeline
(introspeccao -> execucao -> allow-list) sem depender de um SQL Server real.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.core.security import SecretCipher
from app.db.models import Project
from app.db.session import Database
from app.runtime.state import StudioRuntime
from app.schemas.api import DatasourceCreate, DatasourceUpdate
from app.services import datasource_service
from app.services.datasources.base import DatasourceConfig, DatasourceError, sanitize_error
from app.services.datasources.sqlite import SqliteAdapter


# ---------------------------------------------------------------------------
# Fixtures locais
# ---------------------------------------------------------------------------
@pytest.fixture()
def database(settings: Settings) -> Database:
    db = Database(settings.database_url)
    db.create_all()
    try:
        yield db
    finally:
        db.dispose()


@pytest.fixture()
def session(database: Database) -> Session:
    with database.session() as active:
        yield active


@pytest.fixture()
def cipher(settings: Settings) -> SecretCipher:
    return SecretCipher(None, settings.secret_key)


@pytest.fixture()
def runtime(settings: Settings, database: Database, cipher: SecretCipher) -> StudioRuntime:
    return StudioRuntime(settings=settings, database=database, cipher=cipher)


@pytest.fixture()
def project(session: Session) -> Project:
    row = Project(slug="vendas", name="Vendas")
    session.add(row)
    session.flush()
    return row


def _criar_payload(project_id: int, target_db: Path, *, slug: str = "alvo") -> DatasourceCreate:
    return DatasourceCreate(
        project_id=project_id,
        slug=slug,
        name="Banco alvo",
        kind="sqlite",
        file_path=str(target_db),
        password="senha-do-banco",
    )


# ---------------------------------------------------------------------------
# Adaptador SQLite
# ---------------------------------------------------------------------------
def test_adaptador_testa_conexao(target_db: Path):
    adapter = SqliteAdapter(DatasourceConfig(kind="sqlite", file_path=str(target_db)))
    probe = adapter.test_connection()
    assert probe.ok is True
    assert probe.server_version.startswith("SQLite")
    assert probe.driver == "sqlite3"


def test_adaptador_introspecta_tabelas_e_views(target_db: Path):
    adapter = SqliteAdapter(DatasourceConfig(kind="sqlite", file_path=str(target_db)))
    objetos = adapter.introspect()
    por_nome = {(item.schema_name, item.object_name): item for item in objetos}

    assert ("main", "clientes") in por_nome
    assert ("main", "v_ativos") in por_nome
    assert por_nome[("main", "clientes")].object_type == "table"
    assert por_nome[("main", "v_ativos")].object_type == "view"

    colunas = {coluna.name for coluna in por_nome[("main", "clientes")].columns}
    assert {"id", "nome", "saldo", "ativo"} <= colunas
    assert any(coluna.is_primary_key for coluna in por_nome[("main", "clientes")].columns)


def test_adaptador_executa_com_bind_parameters(target_db: Path):
    adapter = SqliteAdapter(DatasourceConfig(kind="sqlite", file_path=str(target_db)))
    resultado = adapter.execute(
        "SELECT id, nome FROM clientes WHERE id = :id", {"id": 2}
    )
    assert resultado.row_count == 1
    assert resultado.rows[0]["nome"] == "Bruno"
    assert resultado.truncated is False


def test_adaptador_trunca_por_fetchmany(target_db: Path):
    adapter = SqliteAdapter(DatasourceConfig(kind="sqlite", file_path=str(target_db)))
    resultado = adapter.execute("SELECT id FROM clientes", max_rows=1)
    assert resultado.row_count == 1
    assert resultado.truncated is True


def test_adaptador_erro_vira_datasource_error(target_db: Path):
    adapter = SqliteAdapter(DatasourceConfig(kind="sqlite", file_path=str(target_db)))
    with pytest.raises(DatasourceError):
        adapter.execute("SELECT * FROM tabela_inexistente")


def test_sanitize_error_remove_credenciais():
    config = DatasourceConfig(
        kind="sqlserver", username="app_erp", password="SegredoDoBanco"
    )
    mensagem = sanitize_error(
        RuntimeError("login falhou para app_erp com a senha SegredoDoBanco"), config
    )
    assert "SegredoDoBanco" not in mensagem
    assert "app_erp" not in mensagem
    assert "***" in mensagem


# ---------------------------------------------------------------------------
# datasource_service
# ---------------------------------------------------------------------------
def test_create_datasource_cifra_a_senha(
    session: Session, cipher: SecretCipher, project: Project, target_db: Path
):
    source = datasource_service.create_datasource(
        session, cipher=cipher, payload=_criar_payload(project.id, target_db)
    )
    assert source.password_enc
    assert source.password_enc != "senha-do-banco"
    assert cipher.decrypt(source.password_enc) == "senha-do-banco"

    serializado = datasource_service.serialize(source)
    assert serializado["has_password"] is True
    assert "password" not in serializado


def test_create_datasource_recusa_slug_duplicado(
    session: Session, cipher: SecretCipher, project: Project, target_db: Path
):
    payload = _criar_payload(project.id, target_db)
    datasource_service.create_datasource(session, cipher=cipher, payload=payload)
    with pytest.raises(ConflictError):
        datasource_service.create_datasource(session, cipher=cipher, payload=payload)


def test_create_datasource_valida_campos_obrigatorios(
    session: Session, cipher: SecretCipher, project: Project, target_db: Path
):
    with pytest.raises(ValidationFailure):
        datasource_service.create_datasource(
            session,
            cipher=cipher,
            payload=DatasourceCreate(
                project_id=project.id, slug="ruim", name="Ruim", kind="sqlserver", host=""
            ),
        )

    with pytest.raises(ValidationFailure):
        datasource_service.create_datasource(
            session,
            cipher=cipher,
            payload=DatasourceCreate(
                project_id=project.id, slug="sqlite-sem-path", name="X", kind="sqlite", file_path=""
            ),
        )

    with pytest.raises(ValidationFailure):
        datasource_service.create_datasource(
            session,
            cipher=cipher,
            payload=DatasourceCreate(
                project_id=project.id, slug="kind-ruim", name="X", kind="oracle"
            ),
        )


def test_get_datasource_or_404(
    session: Session, cipher: SecretCipher, project: Project, target_db: Path
):
    with pytest.raises(NotFoundError):
        datasource_service.get_datasource_or_404(session, 9999)

    source = datasource_service.create_datasource(
        session, cipher=cipher, payload=_criar_payload(project.id, target_db)
    )
    assert datasource_service.get_datasource_or_404(session, source.id).id == source.id


def test_update_datasource_mantem_ou_limpa_a_senha(
    session: Session, cipher: SecretCipher, project: Project, target_db: Path
):
    source = datasource_service.create_datasource(
        session, cipher=cipher, payload=_criar_payload(project.id, target_db)
    )
    original = source.password_enc

    # password ausente (None) mantem a senha atual
    datasource_service.update_datasource(
        session, cipher=cipher, source=source, payload=DatasourceUpdate(name="Novo nome")
    )
    assert source.password_enc == original

    # string vazia limpa a senha
    datasource_service.update_datasource(
        session, cipher=cipher, source=source, payload=DatasourceUpdate(password="")
    )
    assert source.password_enc == ""


def test_test_connection_persiste_resultado(
    session: Session,
    cipher: SecretCipher,
    project: Project,
    target_db: Path,
    settings: Settings,
):
    source = datasource_service.create_datasource(
        session, cipher=cipher, payload=_criar_payload(project.id, target_db)
    )
    probe = datasource_service.test_connection(
        session, source, cipher=cipher, settings=settings
    )
    assert probe.ok is True
    assert source.last_test_ok is True
    assert source.last_test_at is not None


def test_introspect_sincroniza_objetos_nao_autorizados(
    session: Session,
    cipher: SecretCipher,
    project: Project,
    target_db: Path,
    runtime: StudioRuntime,
):
    source = datasource_service.create_datasource(
        session, cipher=cipher, payload=_criar_payload(project.id, target_db)
    )
    resultado = datasource_service.introspect(session, runtime, source)

    assert resultado["objects"] >= 2
    assert resultado["tables"] >= 1
    assert resultado["views"] >= 1

    objetos = datasource_service.list_objects(session, source.id)
    assert objetos, "os objetos descobertos devem ser persistidos"
    assert all(item.allowed is False for item in objetos)

    tabela = next(item for item in objetos if item.object_name == "clientes")
    datasource_service.set_objects_allowed(
        session, runtime, source, [tabela.id], allowed=True
    )

    autorizados = runtime.allowed_objects(source.id)
    assert ("main", "clientes") in autorizados
    assert (None, "clientes") in autorizados

    apenas = datasource_service.list_objects(session, source.id, only_allowed=True)
    assert [item.object_name for item in apenas] == ["clientes"]


def test_delete_datasource(
    session: Session, cipher: SecretCipher, project: Project, target_db: Path
):
    source = datasource_service.create_datasource(
        session, cipher=cipher, payload=_criar_payload(project.id, target_db)
    )
    source_id = source.id
    datasource_service.delete_datasource(session, source)
    with pytest.raises(NotFoundError):
        datasource_service.get_datasource_or_404(session, source_id)
