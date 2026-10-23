"""Limitador de taxa em janela deslizante, em memoria.

Suficiente e correto para uma instancia. Em execucao com multiplos workers, cada worker
mantem sua propria contagem: o limite efetivo passa a ser ``limite x workers``. Essa
limitacao esta registrada no relatorio final; a evolucao natural e um contador
compartilhado (Redis).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class RateLimitState:
    """Estado de uma chave de limitacao."""

    allowed: bool
    remaining: int
    retry_after_seconds: int
    limit: int


class SlidingWindowRateLimiter:
    """Janela deslizante de 60 segundos por chave."""

    def __init__(self, window_seconds: int = 60) -> None:
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> RateLimitState:
        """Registra um acesso e informa se ele esta dentro do limite."""
        if limit <= 0:
            return RateLimitState(allowed=True, remaining=0, retry_after_seconds=0, limit=0)

        now = time.monotonic()
        cutoff = now - self._window

        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                bucket = deque()
                self._hits[key] = bucket
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, int(bucket[0] + self._window - now) + 1)
                return RateLimitState(
                    allowed=False,
                    remaining=0,
                    retry_after_seconds=retry_after,
                    limit=limit,
                )

            bucket.append(now)
            remaining = max(0, limit - len(bucket))
            return RateLimitState(
                allowed=True, remaining=remaining, retry_after_seconds=0, limit=limit
            )

    def reset(self, key: str | None = None) -> None:
        """Limpa o estado (usado em testes)."""
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)

    def prune(self) -> int:
        """Remove chaves ociosas e devolve quantas foram removidas."""
        cutoff = time.monotonic() - self._window
        removed = 0
        with self._lock:
            for key in list(self._hits):
                bucket = self._hits[key]
                while bucket and bucket[0] < cutoff:
                    bucket.popleft()
                if not bucket:
                    del self._hits[key]
                    removed += 1
        return removed


class LoginAttemptTracker:
    """Bloqueio progressivo de tentativas de login por identificador."""

    def __init__(self, threshold: int = 5, lock_minutes: int = 15) -> None:
        self._threshold = threshold
        self._lock_minutes = lock_minutes
        self._attempts: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def register_failure(self, key: str) -> int:
        """Registra uma falha e devolve o total acumulado."""
        now = time.time()
        with self._lock:
            count, expires = self._attempts.get(key, (0, 0.0))
            if expires and expires < now:
                count = 0
            count += 1
            self._attempts[key] = (count, now + self._lock_minutes * 60)
            return count

    def register_success(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def is_locked(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            entry = self._attempts.get(key)
            if entry is None:
                return False
            count, expires = entry
            if expires < now:
                self._attempts.pop(key, None)
                return False
            return count >= self._threshold

    def reset(self) -> None:
        with self._lock:
            self._attempts.clear()
