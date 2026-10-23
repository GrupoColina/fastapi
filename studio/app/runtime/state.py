"""Estado compartilhado da aplicacao Studio.

Uma unica instancia (:class:`StudioRuntime`) e criada no ``lifespan`` e publicada em
``app.state.runtime``. Testes podem construir instancias isoladas, o que permite apontar
para um banco de metadados temporario sem tocar no ambiente global.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from sqlalchemy import select

from app.core.config import Settings
from app.core.rate_limit import LoginAttemptTracker, SlidingWindowRateLimiter
from app.core.security import SecretCipher
from app.db.models import Datasource, DatasourceObject
from app.db.session import Database

# ---------------------------------------------------------------------------
# Cache de introspeccao / allow-list
# ---------------------------------------------------------------------------
@dataclass
class _CacheEntry:
    value: object
    expires_at: float


class TtlCache:
    """Cache simples com TTL, seguro para uso concorrente."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._data: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: str):  # noqa: ANN201
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.expires_at < now:
                del self._data[key]
                return None
            return entry.value

    def set(self, key: str, value: object) -> None:
        with self._lock:
            self._data[key] = _CacheEntry(value=value, expires_at=time.monotonic() + self._ttl)

    def invalidate(self, prefix: str | None = None) -> None:
        with self._lock:
            if prefix is None:
                self._data.clear()
                return
            for key in list(self._data):
                if key.startswith(prefix):
                    del self._data[key]

    def clear(self) -> None:
        self.invalidate(None)


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
@dataclass
class StudioRuntime:
    """Dependencias compartilhadas da aplicacao."""

    settings: Settings
    database: Database
    cipher: SecretCipher
    rate_limiter: SlidingWindowRateLimiter = field(
        default_factory=lambda: SlidingWindowRateLimiter(60)
    )
    login_tracker: LoginAttemptTracker = field(default_factory=LoginAttemptTracker)
    cache: TtlCache | None = None
    # Preenchido em app.main apos o registry existir (evita import circular).
    registry: object | None = None

    def __post_init__(self) -> None:
        if self.cache is None:
            self.cache = TtlCache(self.settings.introspection_cache_ttl)

    # -- Allow-list de objetos --------------------------------------------
    def allowed_objects(self, datasource_id: int) -> set[tuple[str | None, str]]:
        """Conjunto de objetos autorizados da fonte de dados (com cache TTL)."""
        key = f"allowed:{datasource_id}"
        cached = self.cache.get(key) if self.cache else None
        if cached is not None:
            return cached  # type: ignore[return-value]

        with self.database.session() as session:
            rows = session.execute(
                select(DatasourceObject.schema_name, DatasourceObject.object_name).where(
                    DatasourceObject.datasource_id == datasource_id,
                    DatasourceObject.allowed.is_(True),
                )
            ).all()

        result: set[tuple[str | None, str]] = set()
        for schema_name, object_name in rows:
            result.add((schema_name, object_name))
            # Permite referenciar sem qualificar o schema quando ele e o padrao.
            if schema_name in (None, "", "dbo", "main"):
                result.add((None, object_name))

        if self.cache:
            self.cache.set(key, result)
        if self.cache:
            self.cache.set(f"has_allowlist:{datasource_id}", bool(result))
        return result

    def has_allow_list(self, datasource_id: int) -> bool:
        """Informa se a fonte possui pelo menos um objeto autorizado."""
        key = f"has_allowlist:{datasource_id}"
        cached = self.cache.get(key) if self.cache else None
        if cached is None:
            self.allowed_objects(datasource_id)
            cached = self.cache.get(key) if self.cache else None
        return bool(cached)

    def invalidate_datasource(self, datasource_id: int | None = None) -> None:
        """Invalida o cache de allow-list."""
        if self.cache is None:
            return
        if datasource_id is None:
            self.cache.invalidate("allowed:")
            self.cache.invalidate("has_allowlist:")
        else:
            self.cache.invalidate(f"allowed:{datasource_id}")
            self.cache.invalidate(f"has_allowlist:{datasource_id}")

    def get_datasource(self, datasource_id: int) -> Datasource | None:
        with self.database.session() as session:
            return session.get(Datasource, datasource_id)

    def dispose(self) -> None:
        self.database.dispose()


_runtime_holder: dict[str, StudioRuntime | None] = {"value": None}


def set_runtime(runtime: StudioRuntime | None) -> None:
    _runtime_holder["value"] = runtime


def get_runtime() -> StudioRuntime:
    """Devolve o runtime ativo; erro claro se a aplicacao nao inicializou."""
    runtime = _runtime_holder["value"]
    if runtime is None:
        raise RuntimeError(
            "runtime do Studio nao inicializado; a aplicacao foi iniciada sem lifespan?"
        )
    return runtime


def runtime_or_none() -> StudioRuntime | None:
    return _runtime_holder["value"]
