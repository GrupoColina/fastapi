"""Testes da guarda de SQL (analise semantica e allow-list de objetos).

A guarda e a segunda camada de defesa; a primeira e o uso obrigatorio de bind
parameters. Estes testes fixam o contrato: comando unico, somente leitura quando a fonte
nao permite escrita, padroes proibidos recusados e objetos fora da allow-list rejeitados.
"""

from __future__ import annotations

from app.services import sql_guard


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------
def test_select_parametrizado_e_somente_leitura():
    analise = sql_guard.analyze("SELECT id, nome FROM clientes WHERE id = :id")
    assert analise.is_read_only is True
    assert analise.commands == ["SELECT"]
    assert (None, "clientes") in analise.referenced_objects
    assert analise.problems == []


def test_comando_vazio_e_problema():
    analise = sql_guard.analyze("   ")
    assert analise.problems == ["comando SQL vazio"]


def test_multiplos_statements_e_problema():
    analise = sql_guard.analyze("SELECT 1; SELECT 2")
    assert "apenas uma instrucao SQL por endpoint e permitida" in analise.problems


def test_comando_desconhecido_e_problema():
    analise = sql_guard.analyze("BEGIN TRANSACTION")
    assert any("nao reconhecido" in problema for problema in analise.problems)


def test_referencias_com_schema():
    analise = sql_guard.analyze("SELECT * FROM dbo.Clientes")
    assert (None, "dbo") not in analise.referenced_objects
    assert ("dbo", "Clientes") in analise.referenced_objects


def test_comentarios_e_literais_mascaram_padroes_perigosos():
    comentario = sql_guard.analyze("SELECT 1 -- xp_cmdshell")
    assert comentario.forbidden == []

    literal = sql_guard.analyze("SELECT 'OPENROWSET' AS valor")
    assert literal.forbidden == []


def test_padrao_proibido_e_detectado():
    analise = sql_guard.analyze("EXEC xp_cmdshell 'dir'")
    assert "xp_cmdshell" in analise.forbidden


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
def test_read_only_aprova_select():
    assert sql_guard.validate("SELECT id FROM clientes", allow_write=False) == []


def test_read_only_recusa_ddl():
    erros = sql_guard.validate("DROP TABLE clientes", allow_write=False)
    assert any("somente-leitura" in erro for erro in erros)


def test_read_only_recusa_dml():
    erros = sql_guard.validate("INSERT INTO clientes (nome) VALUES ('x')", allow_write=False)
    assert any("somente-leitura" in erro for erro in erros)


def test_allow_write_aceita_dml():
    assert sql_guard.validate("UPDATE clientes SET nome = :nome WHERE id = :id", allow_write=True) == []


def test_construcao_proibida_e_recusada():
    erros = sql_guard.validate("EXEC xp_cmdshell 'dir'", allow_write=False)
    assert any("construcao proibida" in erro for erro in erros)


def test_objeto_fora_da_allow_list_e_recusado():
    erros = sql_guard.validate(
        "SELECT id FROM clientes",
        allow_write=False,
        allowed_objects={("main", "outra_tabela")},
    )
    assert any("nao esta autorizado" in erro for erro in erros)


def test_objeto_com_schema_autorizado_e_aprovado():
    assert (
        sql_guard.validate(
            "SELECT * FROM dbo.Clientes",
            allow_write=False,
            allowed_objects={("dbo", "Clientes")},
        )
        == []
    )


def test_allow_list_vazia_recusa_tudo():
    erros = sql_guard.validate(
        "SELECT id FROM clientes", allow_write=False, allowed_objects=set()
    )
    assert any("nao esta autorizado" in erro for erro in erros)


def test_exec_de_procedure_exige_autorizacao():
    erros = sql_guard.validate(
        "EXEC dbo.minha_proc @p = :p",
        allow_write=False,
        allowed_objects=set(),
    )
    assert any("nao esta autorizado" in erro for erro in erros)


# ---------------------------------------------------------------------------
# extract_parameters
# ---------------------------------------------------------------------------
def test_extract_parameters_nomeados():
    nomes = sql_guard.extract_parameters(
        "SELECT * FROM t WHERE a = :a AND b = @b AND c::text = :c"
    )
    assert nomes == ["a", "b", "c"]


def test_extract_parameters_ignora_literais():
    assert sql_guard.extract_parameters("SELECT ':nao_conta' FROM t") == []


def test_parse_reference_remove_colchetes_e_aspas():
    assert sql_guard.parse_reference("[dbo].[Clientes]") == ("dbo", "Clientes")
    assert sql_guard.parse_reference('"main"."clientes"') == ("main", "clientes")
    assert sql_guard.parse_reference("clientes") == (None, "clientes")
