"""Testes da API administrativa: autenticacao, RBAC, CRUD, API keys e observabilidade."""

from __future__ import annotations

SENHA_ADMIN = "SenhaForte123"
SENHA_NOVA = "OutraSenhaForte456"


# ---------------------------------------------------------------------------
# Autenticacao
# ---------------------------------------------------------------------------
def test_login_retorna_tokens_e_usuario(client):
    response = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": SENHA_ADMIN},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["role"] == "admin"
    assert body["user"]["email"] == "admin@example.com"


def test_login_com_senha_errada_vira_401(client):
    response = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "senha-errada"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_login_bloqueia_apos_excesso_de_tentativas(client):
    payload = {"email": "fantasma@example.com", "password": "errada"}
    for _ in range(5):
        assert client.post("/api/admin/auth/login", json=payload).status_code == 401

    bloqueado = client.post("/api/admin/auth/login", json=payload)
    assert bloqueado.status_code == 429
    assert bloqueado.json()["error"]["code"] == "rate_limited"


def test_me_retorna_o_perfil(client, admin_headers):
    response = client.get("/api/admin/auth/me", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "admin@example.com"


def test_refresh_rotaciona_o_token(client):
    login = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": SENHA_ADMIN},
    ).json()
    refresh_token = login["refresh_token"]

    renovado = client.post("/api/admin/auth/refresh", json={"refresh_token": refresh_token})
    assert renovado.status_code == 200
    assert renovado.json()["refresh_token"] != refresh_token

    # O refresh anterior foi revogado pela rotacao.
    reutilizado = client.post(
        "/api/admin/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert reutilizado.status_code == 401


def test_logout_e_idempotente(client):
    login = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": SENHA_ADMIN},
    ).json()

    primeiro = client.post(
        "/api/admin/auth/logout", json={"refresh_token": login["refresh_token"]}
    )
    assert primeiro.status_code == 200
    assert primeiro.json() == {"revoked": True}

    segundo = client.post(
        "/api/admin/auth/logout", json={"refresh_token": login["refresh_token"]}
    )
    assert segundo.status_code == 200
    assert segundo.json() == {"revoked": True}

    invalido = client.post(
        "/api/admin/auth/logout", json={"refresh_token": "token-invalido-mas-longo"}
    )
    assert invalido.status_code == 200
    assert invalido.json() == {"revoked": False}


def test_change_password_atualiza_credencial(client, admin_headers):
    response = client.post(
        "/api/admin/auth/change-password",
        headers=admin_headers,
        json={"current_password": SENHA_ADMIN, "new_password": SENHA_NOVA},
    )
    assert response.status_code == 200

    assert (
        client.post(
            "/api/admin/auth/login",
            json={"email": "admin@example.com", "password": SENHA_ADMIN},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/admin/auth/login",
            json={"email": "admin@example.com", "password": SENHA_NOVA},
        ).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def _criar_usuario(client, admin_headers, *, email: str, role: str) -> None:
    response = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={"email": email, "password": SENHA_NOVA, "role": role},
    )
    assert response.status_code == 201, response.text


def _login(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/admin/auth/login", json={"email": email, "password": SENHA_NOVA}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_viewer_nao_pode_criar_projeto(client, admin_headers):
    _criar_usuario(client, admin_headers, email="viewer@example.com", role="viewer")
    viewer = _login(client, "viewer@example.com")

    response = client.post(
        "/api/admin/projects", headers=viewer, json={"slug": "bloqueado", "name": "Bloqueado"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_operador_nao_pode_criar_usuario(client, admin_headers):
    _criar_usuario(client, admin_headers, email="operador@example.com", role="operator")
    operador = _login(client, "operador@example.com")

    response = client.post(
        "/api/admin/users",
        headers=operador,
        json={"email": "novo@example.com", "password": SENHA_NOVA, "role": "viewer"},
    )
    assert response.status_code == 403


def test_admin_nao_pode_remover_o_proprio_papel(client, admin_headers):
    response = client.patch(
        "/api/admin/users/1", headers=admin_headers, json={"role": "viewer"}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# CRUD de projetos
# ---------------------------------------------------------------------------
def test_crud_de_projetos(client, admin_headers):
    criado = client.post(
        "/api/admin/projects",
        headers=admin_headers,
        json={"slug": "vendas", "name": "Vendas", "description": "API de vendas"},
    )
    assert criado.status_code == 201
    projeto_id = criado.json()["id"]

    duplicado = client.post(
        "/api/admin/projects", headers=admin_headers, json={"slug": "vendas", "name": "Outro"}
    )
    assert duplicado.status_code == 409

    listagem = client.get("/api/admin/projects", headers=admin_headers)
    assert listagem.status_code == 200
    assert any(item["slug"] == "vendas" for item in listagem.json())

    detalhe = client.get(f"/api/admin/projects/{projeto_id}", headers=admin_headers)
    assert detalhe.json()["name"] == "Vendas"

    atualizado = client.patch(
        f"/api/admin/projects/{projeto_id}", headers=admin_headers, json={"name": "Vendas v2"}
    )
    assert atualizado.json()["name"] == "Vendas v2"

    removido = client.delete(f"/api/admin/projects/{projeto_id}", headers=admin_headers)
    assert removido.status_code == 204
    assert client.get(f"/api/admin/projects/{projeto_id}", headers=admin_headers).status_code == 404


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
def test_api_key_mostra_o_segredo_apenas_uma_vez(client, admin_headers):
    criada = client.post(
        "/api/admin/api-keys",
        headers=admin_headers,
        json={"name": "consumo", "environment": "live"},
    )
    assert criada.status_code == 201
    body = criada.json()
    assert body["plaintext"].startswith("sk_live_")
    assert body["key_prefix"] == body["plaintext"][:12]

    listagem = client.get("/api/admin/api-keys", headers=admin_headers)
    assert listagem.status_code == 200
    assert "plaintext" not in listagem.text
    assert body["plaintext"] not in listagem.text

    revogada = client.post(
        f"/api/admin/api-keys/{body['id']}/revoke", headers=admin_headers
    )
    assert revogada.status_code == 200
    assert revogada.json()["is_active"] is False

    novamente = client.post(
        f"/api/admin/api-keys/{body['id']}/revoke", headers=admin_headers
    )
    assert novamente.status_code == 422


# ---------------------------------------------------------------------------
# Observabilidade e cabecalhos
# ---------------------------------------------------------------------------
def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] is True


def test_runtime_status(client, admin_headers):
    response = client.get("/api/admin/logs/runtime", headers=admin_headers)
    assert response.status_code == 200
    assert "endpoints" in response.json()


def test_stats_do_painel(client, admin_headers):
    response = client.get("/api/admin/logs/stats", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["users"] >= 1
    assert "runtime" in body


def test_trilha_de_auditoria_nao_vaza_segredos(client, admin_headers):
    client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "senha-errada"},
    )
    response = client.get(
        "/api/admin/logs/audit", headers=admin_headers, params={"action": "auth.login.failure"}
    )
    assert response.status_code == 200
    assert response.json(), "a falha de login deve gerar auditoria"
    assert "senha-errada" not in response.text


def test_request_id_e_ecoado_e_cabecalhos_de_seguranca(client):
    response = client.get("/health", headers={"X-Request-ID": "rid-abc"})
    assert response.headers["X-Request-ID"] == "rid-abc"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
