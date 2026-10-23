"""Testes do compilador visual -> especificacao de rota.

Cobrem a validacao semantica (tipos, coerencia de path, corpo, allow-list, SQL, sandbox)
e a producao do ``CompiledEndpoint`` consumido pelo runtime.
"""

from __future__ import annotations

from app.schemas.definition import definition_from_json
from app.services.compiler import (
    compile_endpoint,
    compile_parameters,
    parameter_kwargs,
    validate_advanced,
    validate_definition,
)


def _definicao(**overrides) -> object:
    base: dict = {
        "source": {"mode": "sql", "sql": "SELECT id FROM clientes"},
        "response": {"envelope": "list", "fields": []},
        "parameters": [],
    }
    base.update(overrides)
    return definition_from_json(base)


ALLOW = {("main", "clientes")}


# ---------------------------------------------------------------------------
# validate_definition
# ---------------------------------------------------------------------------
def test_definicao_valida_com_path_param():
    definicao = definition_from_json(
        {
            "parameters": [
                {"name": "cliente_id", "location": "path", "type": "integer", "required": True}
            ],
            "source": {"mode": "sql", "sql": "SELECT id FROM clientes WHERE id = :cliente_id"},
            "response": {"envelope": "object", "fields": [{"name": "id", "type": "integer"}]},
        }
    )
    erros = validate_definition(
        definicao,
        method="GET",
        path="/clientes/{cliente_id}",
        allow_write=False,
        allowed_objects=ALLOW,
    )
    assert erros == []


def test_tipo_de_parametro_invalido():
    definicao = _definicao(
        parameters=[{"name": "x", "location": "query", "type": "geometria"}]
    )
    erros = validate_definition(
        definicao, method="GET", path="/x", allow_write=False, allowed_objects=ALLOW
    )
    assert any("nao suportado" in erro for erro in erros)


def test_parametro_duplicado():
    definicao = _definicao(
        parameters=[
            {"name": "x", "location": "query", "type": "string"},
            {"name": "x", "location": "query", "type": "string"},
        ]
    )
    erros = validate_definition(
        definicao, method="GET", path="/x", allow_write=False, allowed_objects=ALLOW
    )
    assert any("duplicado" in erro for erro in erros)


def test_path_declara_parametro_sem_definicao():
    definicao = _definicao()
    erros = validate_definition(
        definicao, method="GET", path="/x/{faltante}", allow_write=False, allowed_objects=ALLOW
    )
    assert any("sem definicao correspondente" in erro for erro in erros)


def test_parametro_de_path_inexistente_no_caminho():
    definicao = _definicao(
        parameters=[{"name": "extra", "location": "path", "type": "string"}]
    )
    erros = validate_definition(
        definicao, method="GET", path="/x", allow_write=False, allowed_objects=ALLOW
    )
    assert any("nao existem no caminho" in erro for erro in erros)


def test_corpo_em_get_e_recusado():
    definicao = _definicao(
        parameters=[{"name": "corpo", "location": "body", "type": "string"}]
    )
    erros = validate_definition(
        definicao, method="GET", path="/x", allow_write=False, allowed_objects=ALLOW
    )
    assert any("nao deve declarar corpo" in erro for erro in erros)


def test_campo_de_resposta_deve_ser_identificador():
    definicao = _definicao(
        response={
            "envelope": "list",
            "fields": [{"name": "total geral", "type": "integer"}],
        }
    )
    erros = validate_definition(
        definicao, method="GET", path="/x", allow_write=False, allowed_objects=ALLOW
    )
    assert any("identificador" in erro for erro in erros)


def test_sql_com_parametro_nao_declarado():
    definicao = _definicao(source={"mode": "sql", "sql": "SELECT id FROM clientes WHERE id = :x"})
    erros = validate_definition(
        definicao, method="GET", path="/x", allow_write=False, allowed_objects=ALLOW
    )
    assert any("nao declarados no endpoint" in erro for erro in erros)


def test_objeto_nao_autorizado_bloqueia_validacao():
    definicao = _definicao(source={"mode": "sql", "sql": "SELECT id FROM pagamentos"})
    erros = validate_definition(
        definicao, method="GET", path="/x", allow_write=False, allowed_objects=ALLOW
    )
    assert any("nao esta autorizado" in erro for erro in erros)


def test_envelope_paginado_exige_parametros_de_query():
    definicao = _definicao(
        response={"envelope": "paginated", "fields": [{"name": "id", "type": "integer"}]}
    )
    erros = validate_definition(
        definicao, method="GET", path="/x", allow_write=False, allowed_objects=ALLOW
    )
    assert any("espera o parametro de query 'page'" in erro for erro in erros)
    assert any("espera o parametro de query 'page_size'" in erro for erro in erros)


def test_procedure_exige_autorizacao():
    definicao = definition_from_json(
        {
            "source": {
                "mode": "procedure",
                "procedure_schema": "dbo",
                "procedure_name": "listar",
            },
            "response": {"envelope": "list", "fields": []},
        }
    )
    erros = validate_definition(
        definicao, method="GET", path="/x", allow_write=False, allowed_objects=set()
    )
    assert any("nao esta autorizada" in erro for erro in erros)


def test_validate_advanced_delega_para_o_sandbox():
    assert validate_advanced("def outra(): pass") == ["o codigo deve definir uma funcao 'handle(ctx)'"]
    assert validate_advanced("def handle(ctx): return {}") == []


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------
def test_compile_parameters_adiciona_paginacao():
    definicao = _definicao(
        response={
            "envelope": "paginated",
            "fields": [{"name": "id", "type": "integer"}],
            "pagination": {"page_param": "pagina", "page_size_param": "tamanho"},
        }
    )
    nomes = {param.name for param in compile_parameters(definicao)}
    assert {"pagina", "tamanho"} <= nomes


def test_parameter_kwargs_traduz_validacoes():
    definicao = _definicao(
        parameters=[
            {
                "name": "limite",
                "location": "query",
                "type": "integer",
                "ge": 1,
                "le": 100,
                "description": "tamanho da pagina",
                "example": 10,
            }
        ]
    )
    kwargs = parameter_kwargs(definicao.parameters[0])
    assert kwargs["ge"] == 1
    assert kwargs["le"] == 100
    assert kwargs["description"] == "tamanho da pagina"
    assert kwargs["examples"] == [10]


def test_compile_endpoint_normaliza_path_e_operacao():
    definicao = _definicao()
    compilado = compile_endpoint(
        endpoint_id=1,
        version_id=2,
        version_number=3,
        project_id=4,
        project_slug="vendas",
        datasource_id=5,
        method="get",
        path="clientes/",
        definition=definicao,
    )
    assert compilado.method == "GET"
    assert compilado.path == "/clientes"
    assert compilado.operation_id.startswith("vendas_clientes_get")


def test_compile_endpoint_monta_modelo_de_lista():
    definicao = definition_from_json(
        {
            "source": {"mode": "sql", "sql": "SELECT id FROM clientes"},
            "response": {
                "envelope": "list",
                "fields": [{"name": "id", "type": "integer"}],
            },
        }
    )
    compilado = compile_endpoint(
        endpoint_id=1,
        version_id=1,
        version_number=1,
        project_id=1,
        project_slug="vendas",
        datasource_id=None,
        method="GET",
        path="/clientes",
        definition=definicao,
    )
    assert compilado.response_model is not None
    assert len(compilado.response_fields) == 1
