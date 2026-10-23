"""Contexto de requisicao propagado sem depender da assinatura da rota gerada.

As rotas do runtime sao construidas dinamicamente; em vez de exigir ``Request`` na
assinatura compilada, o middleware grava o contexto em um ``ContextVar`` e a dependencia
de autenticacao enriquece esse mesmo contexto com o principal autenticado.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimePrincipal:
    """Identidade autenticada no consumo de uma API publicada."""

    kind: str  # "api_key" | "jwt" | "none"
    subject: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    api_key_id: int | None = None
    user_id: int | None = None
    project_id: int | None = None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes or "*" in self.scopes


@dataclass
class RequestContext:
    """Dados volateis da requisicao em andamento."""

    request_id: str = ""
    client_ip: str = ""
    method: str = ""
    path: str = ""
    principal: RuntimePrincipal | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_current: ContextVar[RequestContext | None] = ContextVar("studio_request_context", default=None)


def set_request_context(context: RequestContext) -> None:
    _current.set(context)


def get_request_context() -> RequestContext:
    """Devolve o contexto atual, criando um vazio se necessario (fora de request)."""
    context = _current.get()
    if context is None:
        context = RequestContext()
        _current.set(context)
    return context


def clear_request_context() -> None:
    _current.set(None)
