"""Fluxo vertical completo: projeto -> fonte -> introspeccao -> endpoint -> consumo.

Exercita o caminho real do produto: descoberta de objetos (deny-by-default), allow-list,
validacao, publicacao, rota nativa no runtime, API key, telemetria, OpenAPI e rollback.
"""

from __future__ import annotations

from pathlib import Path

DEFINICAO_LISTA = {
    "summary": "Lista clientes",
    "parameters": [
        {
            "name": "limite",
            "location": "query",
            "type": "integer",
            "required": False,
            "default": 10,
            "ge": 1,
            "le": 100,
        }
    ],
    "source": {"mode": "sql", "sql": "SELECT id, nome, saldo FROM clientes LIMIT :limite"},
    "response": {
        "envelope": "list",
        "fields": [
            {"name": "id", "type": "integer"},
            {"name": "nome", "type": "string"},
            {"name": "saldo", "type": "number"},
        ],
    },
    "auth": {"mode": "api_key"},
}


def _criar_projeto(client, admin_headers, slug: str) -> int:
    response = client.post(
        "/api/admin/projects",
        headers=admin_headers,
        json={"slug": slug, "name": slug.title()},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _criar_datasource(client, admin_headers, project_id: int, target_db: Path) -> int:
    response = client.post(
        "/api/admin/datasources",
        headers=admin_headers,
        json={
            "project_id": project_id,
            "slug": "alvo",
            "name": "Banco alvo",
            "kind": "sqlite",
            "file_path": str(target_db),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _descobrir_e_autorizar(client, admin_headers, datasource_id: int, *, autorizar: bool) -> list[int]:
    descoberta = client.post(
        f"/api/admin/datasources/{datasource_id}/discover",
        headers=admin_headers,
        json={"schemas": []},
    )
    assert descoberta.status_code == 200, descoberta.text
    assert descoberta.json()["objects"] >= 2

    objetos = client.get(
        f"/api/admin/datasources/{datasource_id}/objects", headers=admin_headers
    ).json()
    ids = [item["id"] for item in objetos]
    if autorizar:
        resposta = client.post(
            f"/api/admin/datasources/{datasource_id}/objects/authorize",
            headers=admin_headers,
            json={"object_ids": ids, "allowed": True},
        )
        assert resposta.status_code == 200
        assert resposta.json()["updated"] == len(ids)
    return ids


def _criar_endpoint(client, admin_headers, project_id: int, datasource_id: int, slug: str) -> dict:
    response = client.post(
        "/api/admin/endpoints",
        headers=admin_headers,
        json={
            "project_id": project_id,
            "datasource_id": datasource_id,
            "slug": slug,
            "name": slug.title(),
            "http_method": "GET",
            "path": f"/{slug}",
            "definition": DEFINICAO_LISTA,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_fluxo_vertical_completo(client, admin_headers, settings, target_db: Path):
    prefixo = settings.runtime_prefix

    project_id = _criar_projeto(client, admin_headers, "vendas")
    datasource_id = _criar_datasource(client, admin_headers, project_id, target_db)

    teste = client.post(
        f"/api/admin/datasources/{datasource_id}/test", headers=admin_headers
    )
    assert teste.status_code == 200
    assert teste.json()["ok"] is True

    objetos = client.get(
        f"/api/admin/datasources/{datasource_id}/objects", headers=admin_headers
    )
    assert objetos.status_code == 200

    _descobrir_e_autorizar(client, admin_headers, datasource_id, autorizar=True)

    endpoint = _criar_endpoint(client, admin_headers, project_id, datasource_id, "clientes")
    endpoint_id = endpoint["id"]
    version_id = endpoint["latest_version"]["id"]

    validacao = client.post(
        f"/api/admin/endpoints/{endpoint_id}/versions/{version_id}/validate",
        headers=admin_headers,
    )
    assert validacao.status_code == 200
    assert validacao.json()["ok"] is True, validacao.text

    publicacao = client.post(
        f"/api/admin/endpoints/{endpoint_id}/versions/{version_id}/publish",
        headers=admin_headers,
    )
    assert publicacao.status_code == 200, publicacao.text
    assert publicacao.json()["version"]["status"] == "published"
    assert publicacao.json()["runtime"]["endpoints"] == 1

    chave = client.post(
        "/api/admin/api-keys",
        headers=admin_headers,
        json={"name": "consumo", "project_id": project_id, "environment": "live"},
    )
    assert chave.status_code == 201, chave.text
    plaintext = chave.json()["plaintext"]

    caminho = f"{prefixo}/vendas/clientes"

    assert client.get(caminho).status_code == 401
    assert (
        client.get(caminho, headers={"X-API-Key": "sk_live_inexistente"}).status_code == 401
    )

    consumo = client.get(
        caminho, headers={"X-API-Key": plaintext}, params={"limite": 2}
    )
    assert consumo.status_code == 200, consumo.text
    linhas = consumo.json()
    assert isinstance(linhas, list)
    assert len(linhas) == 2
    assert {linha["nome"] for linha in linhas} == {"Ana", "Bruno"}
    # O campo declarado como `number` deve sair como numero JSON, nao como string.
    assert all(isinstance(linha["saldo"], (int, float)) for linha in linhas), linhas

    sem_limite = client.get(caminho, headers={"X-API-Key": plaintext})
    assert sem_limite.status_code == 200
    assert len(sem_limite.json()) == 3

    invalido = client.get(
        caminho, headers={"X-API-Key": plaintext}, params={"limite": "abc"}
    )
    assert invalido.status_code == 422
    assert invalido.json()["error"]["code"] == "request_validation_error"

    openapi = client.get("/api/openapi.json")
    assert openapi.status_code == 200
    assert caminho in openapi.json()["paths"]

    telemetria = client.get(
        "/api/admin/logs/requests",
        headers=admin_headers,
        params={"endpoint_id": endpoint_id},
    )
    assert telemetria.status_code == 200
    assert telemetria.json(), "o consumo do endpoint deve gerar telemetria"


def test_objeto_nao_autorizado_bloqueia_publicacao(client, admin_headers, target_db: Path):
    project_id = _criar_projeto(client, admin_headers, "financeiro")
    datasource_id = _criar_datasource(client, admin_headers, project_id, target_db)

    # Descobre os objetos, mas NAO autoriza nenhum (deny-by-default).
    objetos = _descobrir_e_autorizar(client, admin_headers, datasource_id, autorizar=False)
    assert objetos
    listagem = client.get(
        f"/api/admin/datasources/{datasource_id}/objects", headers=admin_headers
    ).json()
    assert all(item["allowed"] is False for item in listagem)

    endpoint = _criar_endpoint(client, admin_headers, project_id, datasource_id, "clientes")
    endpoint_id = endpoint["id"]
    version_id = endpoint["latest_version"]["id"]

    validacao = client.post(
        f"/api/admin/endpoints/{endpoint_id}/versions/{version_id}/validate",
        headers=admin_headers,
    )
    assert validacao.json()["ok"] is False
    assert any("nao esta autorizado" in erro for erro in validacao.json()["errors"])

    publicacao = client.post(
        f"/api/admin/endpoints/{endpoint_id}/versions/{version_id}/publish",
        headers=admin_headers,
    )
    assert publicacao.status_code == 422
    assert publicacao.json()["error"]["code"] == "validation_failed"


def test_rollback_cria_nova_versao(client, admin_headers, settings, target_db: Path):
    project_id = _criar_projeto(client, admin_headers, "rollback")
    datasource_id = _criar_datasource(client, admin_headers, project_id, target_db)
    _descobrir_e_autorizar(client, admin_headers, datasource_id, autorizar=True)

    endpoint = _criar_endpoint(client, admin_headers, project_id, datasource_id, "clientes")
    endpoint_id = endpoint["id"]
    version_id = endpoint["latest_version"]["id"]

    publicacao = client.post(
        f"/api/admin/endpoints/{endpoint_id}/versions/{version_id}/publish",
        headers=admin_headers,
    )
    assert publicacao.status_code == 200, publicacao.text
    assert publicacao.json()["version"]["version_number"] == 1

    rollback = client.post(
        f"/api/admin/endpoints/{endpoint_id}/versions/{version_id}/rollback",
        headers=admin_headers,
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["version"]["version_number"] == 2
    assert rollback.json()["version"]["status"] == "published"

    versoes = client.get(
        f"/api/admin/endpoints/{endpoint_id}/versions", headers=admin_headers
    ).json()
    assert [item["version_number"] for item in versoes] == [2, 1]

    # A rota continua disponivel apos o rollback.
    assert (
        client.get(f"{settings.runtime_prefix}/rollback/clientes").status_code == 401
    )
