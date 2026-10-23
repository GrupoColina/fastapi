"""Testes dos handlers de erro: status HTTP e envelope de resposta uniforme.

Os casos de dominio sao exercitados em uma aplicacao de sondagem isolada (apenas o
middleware de contexto e os handlers), o que evita interferencia com o painel. Os
casos nativos (validacao, 404 e 405) sao exercitados na aplicacao real.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import (
    ConflictError,
    ExecutionTimeoutError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
    UpstreamError,
    ValidationFailure,
    register_exception_handlers,
)
from app.core.middleware import RequestContextMiddleware


def _probe_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    return app


def _raiser(exc: Exception):
    def _handler() -> None:
        raise exc

    return _handler


CASOS = [
    (UnauthorizedError("sem credencial"), 401, "unauthorized"),
    (ForbiddenError("sem papel"), 403, "forbidden"),
    (NotFoundError("nao existe"), 404, "not_found"),
    (ConflictError("duplicado"), 409, "conflict"),
    (ValidationFailure("invalido"), 422, "validation_failed"),
    (RateLimitedError("limite excedido"), 429, "rate_limited"),
    (UpstreamError("erp fora do ar"), 502, "upstream_error"),
    (ExecutionTimeoutError("demorou demais"), 504, "execution_timeout"),
]


@pytest.mark.parametrize("exc,status,code", CASOS)
def test_studio_error_vira_status_e_envelope(exc: Exception, status: int, code: str):
    app = _probe_app()
    app.add_api_route("/dispara", _raiser(exc), methods=["GET"])

    with TestClient(app) as client:
        response = client.get("/dispara", headers={"X-Request-ID": "rid-teste"})

    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"] == exc.message
    assert body["error"]["request_id"] == "rid-teste"


def test_validation_failure_inclui_details():
    app = _probe_app()
    app.add_api_route(
        "/detalhes",
        _raiser(ValidationFailure("ruim", details={"errors": ["a", "b"]})),
        methods=["GET"],
    )
    with TestClient(app) as client:
        response = client.get("/detalhes")

    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"errors": ["a", "b"]}


def test_excecao_nao_tratada_vira_500_sem_vazar_detalhes():
    app = _probe_app()

    def _boom() -> None:
        raise ValueError("segredo interno do processo")

    app.add_api_route("/boom", _boom, methods=["GET"])

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom", headers={"X-Request-ID": "rid-500"})

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "segredo interno do processo" not in response.text
    assert body["error"]["request_id"] == "rid-500"


def test_validacao_de_request_vira_422(client):
    response = client.post("/api/admin/auth/login", json={"email": "admin@example.com"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "request_validation_error"
    assert isinstance(body["error"]["details"], list)


def test_credencial_ausente_vira_401(client):
    response = client.get("/api/admin/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_recurso_inexistente_vira_404(client, admin_headers):
    response = client.get("/api/admin/projects/999999", headers=admin_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_rota_de_api_inexistente_nao_e_mascarada_pela_spa(client):
    # A rota "cauda" da SPA (GET /{full_path:path}) nao pode devolver HTML 200 para
    # caminhos sob /api: eles precisam virar 404 com envelope JSON.
    response = client.get("/api/rota-que-nao-existe")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "not_found"


def test_metodo_nao_permitido_vira_405(client):
    response = client.delete("/api/admin/auth/login")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
