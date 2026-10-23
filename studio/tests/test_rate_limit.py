"""Testes do limitador de taxa em janela deslizante e do bloqueio de login."""

from __future__ import annotations

import time

from app.core.rate_limit import LoginAttemptTracker, SlidingWindowRateLimiter


def test_janela_deslizante_bloqueia_apos_o_limite():
    limiter = SlidingWindowRateLimiter(60)

    primeiro = limiter.check("chave", 2)
    segundo = limiter.check("chave", 2)
    terceiro = limiter.check("chave", 2)

    assert primeiro.allowed is True
    assert primeiro.remaining == 1
    assert segundo.allowed is True
    assert segundo.remaining == 0
    assert terceiro.allowed is False
    assert terceiro.remaining == 0
    assert terceiro.retry_after_seconds >= 1
    assert terceiro.limit == 2


def test_limite_zero_libera_sem_contar():
    limiter = SlidingWindowRateLimiter(60)
    estado = limiter.check("chave", 0)
    assert estado.allowed is True
    assert estado.limit == 0


def test_chaves_diferentes_nao_interferem():
    limiter = SlidingWindowRateLimiter(60)
    assert limiter.check("a", 1).allowed is True
    assert limiter.check("a", 1).allowed is False
    assert limiter.check("b", 1).allowed is True


def test_reset_limpa_apenas_a_chave_informada():
    limiter = SlidingWindowRateLimiter(60)
    limiter.check("a", 1)
    assert limiter.check("a", 1).allowed is False
    limiter.reset("a")
    assert limiter.check("a", 1).allowed is True


def test_prune_remove_chaves_ociosas():
    limiter = SlidingWindowRateLimiter(0)
    limiter.check("a", 1)
    time.sleep(0.01)
    assert limiter.prune() >= 1


def test_tracker_bloqueia_no_limite():
    tracker = LoginAttemptTracker(threshold=3, lock_minutes=15)
    assert tracker.register_failure("a@b.com") == 1
    assert tracker.is_locked("a@b.com") is False
    assert tracker.register_failure("a@b.com") == 2
    assert tracker.is_locked("a@b.com") is False
    assert tracker.register_failure("a@b.com") == 3
    assert tracker.is_locked("a@b.com") is True


def test_tracker_limpa_no_sucesso():
    tracker = LoginAttemptTracker(threshold=2)
    tracker.register_failure("x")
    tracker.register_failure("x")
    assert tracker.is_locked("x") is True
    tracker.register_success("x")
    assert tracker.is_locked("x") is False


def test_tracker_reset():
    tracker = LoginAttemptTracker(threshold=1)
    tracker.register_failure("y")
    assert tracker.is_locked("y") is True
    tracker.reset()
    assert tracker.is_locked("y") is False


def test_tracker_chave_desconhecida_nao_esta_bloqueada():
    tracker = LoginAttemptTracker(threshold=3)
    assert tracker.is_locked("desconhecido") is False
