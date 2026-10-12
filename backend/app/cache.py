"""Optional, fail-open cache-aside layer. PostgreSQL remains authoritative.

Redis only ever holds disposable copies. Every helper here treats a Redis
error, timeout, or undecodable value as a cache miss so requests continue
against the database. See docs/REDIS_CACHE_ASIDE_IMPLEMENTATION.md.

Invalidation uses per-(namespace, scope) generation counters. Readers capture
the generation *before* loading from the database; writers bump it only after
their transaction commits (see ``Store.transaction``). A slow reader can then
only populate a key that no future reader requests.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import random
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

T = TypeVar("T")

# Bump whenever any cached payload shape changes so overlapping deploys never
# decode each other's entries.
CACHE_SCHEMA = 1
NAMESPACES = frozenset({"web_evidence", "material_blocks", "concept_graph", "course", "calendar", "usage_display"})
# Generation keys must outlive every data key, otherwise an expired counter
# could reset to a generation whose stale data is still cached.
GENERATION_TTL_SECONDS = 7 * 24 * 3600
MAX_DATA_TTL_SECONDS = 2 * 24 * 3600
BREAKER_THRESHOLD = 5
BREAKER_COOLDOWN_SECONDS = 30.0
LOCK_TTL_MS = 5000
LOCK_POLLS = 3
LOCK_POLL_SECONDS = 0.05

logger = logging.getLogger("openlearn.cache")


def owner_scope(owner_id: str) -> str:
    """Stable, non-reversible owner segment; raw owner IDs never enter keys."""
    return hashlib.sha256(str(owner_id).encode("utf-8")).hexdigest()[:24]


def owner_child_scope(owner_id: str, child: str) -> str:
    """Scope for per-resource generations that still erase with their owner."""
    return f"{owner_scope(owner_id)}.{hashlib.sha256(str(child).encode('utf-8')).hexdigest()[:24]}"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def json_codec() -> dict[str, Callable]:
    return {"encode": _canonical, "decode": lambda raw: json.loads(raw.decode("utf-8"))}


def model_codec(adapter) -> dict[str, Callable]:
    """Codec for Pydantic models or ``list[Model]`` via a ``TypeAdapter``."""
    return {"encode": lambda value: adapter.dump_json(value), "decode": lambda raw: adapter.validate_json(raw)}


def data_key(namespace: str, scope: str, generation: int, parts: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(_canonical(dict(parts))).hexdigest()[:32]
    return f"ol:c{CACHE_SCHEMA}:{namespace}:{scope}:g{generation}:{digest}"


def generation_key(namespace: str, scope: str) -> str:
    return f"ol:gen:{namespace}:{scope}"


def jittered(ttl_seconds: int) -> int:
    return max(1, int(round(min(ttl_seconds, MAX_DATA_TTL_SECONDS) * random.uniform(0.9, 1.1))))


class CacheMetrics:
    """Bounded, content-free counters per namespace (no keys, scopes, or values)."""

    EVENTS = ("hit", "miss", "error", "decode_error", "bypass", "set_error", "invalidate",
              "invalidate_error", "shadow_match", "shadow_mismatch", "breaker_open", "breaker_close")

    def __init__(self):
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, str], int] = {}

    def count(self, namespace: str, event: str, amount: int = 1) -> None:
        if event not in self.EVENTS:
            return
        name = namespace if namespace in NAMESPACES else "other"
        with self._lock:
            self._counts[(name, event)] = self._counts.get((name, event), 0) + amount

    def snapshot(self) -> dict:
        with self._lock:
            rows: dict[str, dict[str, int]] = {}
            for (namespace, event), value in sorted(self._counts.items()):
                rows.setdefault(namespace, {})[event] = value
        return rows

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


metrics = CacheMetrics()


class CircuitBreaker:
    """Per-process breaker so an outage costs one timeout, not one per request."""

    def __init__(self, threshold: int = BREAKER_THRESHOLD, cooldown: float = BREAKER_COOLDOWN_SECONDS, clock=time.monotonic):
        self.threshold, self.cooldown, self.clock = threshold, cooldown, clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._probing = False

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._opened_at is not None and self.clock() - self._opened_at < self.cooldown

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self.clock() - self._opened_at < self.cooldown or self._probing:
                return False
            self._probing = True  # half-open: admit exactly one probe
            return True

    def success(self) -> None:
        with self._lock:
            reopened = self._opened_at is not None
            self._failures, self._opened_at, self._probing = 0, None, False
        if reopened:
            metrics.count("other", "breaker_close")

    def failure(self) -> None:
        with self._lock:
            self._failures += 1
            opened = self._probing or (self._opened_at is None and self._failures >= self.threshold)
            if opened:
                self._opened_at, self._probing = self.clock(), False
        if opened:
            metrics.count("other", "breaker_open")
            logger.warning("openlearn.cache breaker opened; serving from the database")


class NullCache:
    enabled = False
    serving: frozenset = frozenset()
    shadow: frozenset = frozenset()

    def get(self, key, namespace="other"):
        return None

    def set(self, key, value, ttl_seconds, namespace="other"):
        return None

    def delete(self, *keys, namespace="other"):
        return None

    def generation(self, namespace, scope):
        return None

    def bump(self, namespace, scope):
        return None

    def acquire_lock(self, key):
        return None

    def release_lock(self, key):
        return None

    def erase_scope(self, scope):
        return None

    def status(self) -> str:
        return "disabled"


class _Unavailable(Exception):
    pass


class RedisCache:
    """Thin fail-open wrapper. ``client`` is a redis-py compatible client."""

    enabled = True

    def __init__(self, client, *, serving=frozenset(), shadow=frozenset(), breaker: CircuitBreaker | None = None):
        self.client = client
        self.shadow = frozenset(shadow) & NAMESPACES
        self.serving = (frozenset(serving) & NAMESPACES) - self.shadow
        self.breaker = breaker or CircuitBreaker()

    def _call(self, namespace: str, event: str, fn):
        if not self.breaker.allow():
            raise _Unavailable()
        try:
            result = fn()
        except Exception:
            self.breaker.failure()
            metrics.count(namespace, event)
            raise _Unavailable() from None
        self.breaker.success()
        return result

    def get(self, key, namespace="other"):
        try:
            return self._call(namespace, "error", lambda: self.client.get(key))
        except _Unavailable:
            return None

    def set(self, key, value, ttl_seconds, namespace="other"):
        try:
            self._call(namespace, "set_error", lambda: self.client.set(key, value, ex=jittered(ttl_seconds)))
        except _Unavailable:
            return None

    def delete(self, *keys, namespace="other"):
        if not keys:
            return None
        try:
            self._call(namespace, "error", lambda: self.client.delete(*keys))
        except _Unavailable:
            return None

    def generation(self, namespace, scope):
        try:
            raw = self._call(namespace, "error", lambda: self.client.get(generation_key(namespace, scope)))
        except _Unavailable:
            return None
        try:
            return int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            metrics.count(namespace, "decode_error")
            return None

    def bump(self, namespace, scope):
        key = generation_key(namespace, scope)

        def run():
            pipeline = self.client.pipeline(transaction=True)
            pipeline.incr(key)
            pipeline.expire(key, GENERATION_TTL_SECONDS)
            pipeline.execute()
        try:
            self._call(namespace, "invalidate_error", run)
            metrics.count(namespace, "invalidate")
        except _Unavailable:
            # TTLs bound staleness when an invalidation is lost.
            return None

    def acquire_lock(self, key):
        try:
            return bool(self._call("other", "error", lambda: self.client.set("ol:lock:" + key, b"1", nx=True, px=LOCK_TTL_MS)))
        except _Unavailable:
            return None

    def release_lock(self, key):
        self.delete("ol:lock:" + key)

    def erase_scope(self, scope):
        """Remove every data and generation key for an owner scope (account erasure)."""
        # Owner scopes are fixed-width hex; child scopes append ".<hash>".
        patterns = (f"ol:c*:*:{scope}:*", f"ol:c*:*:{scope}.*", f"ol:gen:*:{scope}", f"ol:gen:*:{scope}.*")

        def run():
            for pattern in patterns:
                batch = []
                for key in self.client.scan_iter(match=pattern, count=500):
                    batch.append(key)
                    if len(batch) >= 500:
                        self.client.unlink(*batch)
                        batch = []
                if batch:
                    self.client.unlink(*batch)
        try:
            self._call("other", "error", run)
            return True
        except _Unavailable:
            logger.warning("openlearn.cache erase_scope failed; entries expire by TTL")
            return False

    def status(self) -> str:
        return "degraded" if self.breaker.is_open else "ok"


_lock = threading.Lock()
_cache: NullCache | RedisCache | None = None


def _env_set(name: str) -> frozenset:
    return frozenset(part.strip() for part in os.getenv(name, "").split(",") if part.strip())


def _truthy(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def redis_pool_size() -> int:
    from .capacity import redis_pool_size as configured
    return configured()


def build_cache_from_env():
    url = os.getenv("REDIS_URL", "").strip()
    if not _truthy("OPENLEARN_CACHE_ENABLED"):
        return NullCache()
    if not url:
        logger.warning("OPENLEARN_CACHE_ENABLED is true but REDIS_URL is unset; caching disabled")
        return NullCache()
    try:
        import redis  # lazy: local and desktop installs never need it
        pool = redis.ConnectionPool.from_url(url, max_connections=redis_pool_size(), socket_connect_timeout=0.2,
                                             socket_timeout=0.1, health_check_interval=30)
        client = redis.Redis(connection_pool=pool)
    except Exception:
        logger.warning("Redis client unavailable; caching disabled")
        return NullCache()
    return RedisCache(client, serving=_env_set("OPENLEARN_CACHE_NAMESPACES"), shadow=_env_set("OPENLEARN_CACHE_SHADOW"))


def get_cache():
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:
                _cache = build_cache_from_env()
    return _cache


def configure_cache(cache) -> None:
    """Install a cache explicitly (tests, embedded runtimes)."""
    global _cache
    with _lock:
        _cache = cache


def reset_cache() -> None:
    configure_cache(None)


def namespace_active(namespace: str) -> bool:
    cache = get_cache()
    return bool(cache.enabled) and (namespace in cache.serving or namespace in cache.shadow)


def cache_status() -> str:
    return get_cache().status()


def _observe(stage: str, started: float) -> None:
    from .performance import observe
    observe(stage, (time.perf_counter() - started) * 1000)


def get_or_load(namespace: str, scope: str, parts: Mapping[str, Any], loader: Callable[[], T], *,
                ttl_seconds: int, encode: Callable[[T], bytes], decode: Callable[[bytes], T],
                single_flight: bool = False) -> T:
    """Cache-aside read. Always returns the loader's result shape; never raises cache errors."""
    if namespace not in NAMESPACES:
        raise ValueError("Unknown cache namespace")
    cache = get_cache()
    shadow = cache.enabled and namespace in cache.shadow
    if not cache.enabled or (namespace not in cache.serving and not shadow) or ttl_seconds <= 0:
        return loader()
    started = time.perf_counter()
    generation = cache.generation(namespace, scope)  # read BEFORE loading; see module docstring
    if generation is None:
        metrics.count(namespace, "bypass")
        return loader()
    key = data_key(namespace, scope, generation, parts)
    raw = cache.get(key, namespace=namespace)
    _observe("cache_get", started)
    if shadow:
        value = _load(loader)
        fresh = _safe_encode(namespace, encode, value)
        if raw is None:
            metrics.count(namespace, "miss")
            if fresh is not None:
                cache.set(key, fresh, ttl_seconds, namespace=namespace)
        else:
            try:
                cached = _canonical_bytes(encode(decode(raw)))
                metrics.count(namespace, "shadow_match" if fresh is not None and cached == _canonical_bytes(fresh) else "shadow_mismatch")
            except Exception:
                metrics.count(namespace, "decode_error")
                cache.delete(key, namespace=namespace)
        return value
    if raw is not None:
        try:
            value = decode(raw)
            metrics.count(namespace, "hit")
            return value
        except Exception:
            metrics.count(namespace, "decode_error")
            cache.delete(key, namespace=namespace)
    metrics.count(namespace, "miss")
    locked = False
    if single_flight:
        acquired = cache.acquire_lock(key)  # None = Redis unavailable: load without waiting
        locked = acquired is True
        if acquired is False:
            for _ in range(LOCK_POLLS):
                time.sleep(LOCK_POLL_SECONDS)
                raw = cache.get(key, namespace=namespace)
                if raw is not None:
                    try:
                        return decode(raw)
                    except Exception:
                        break
    try:
        value = _load(loader)
        encoded = _safe_encode(namespace, encode, value)
        if encoded is not None:
            cache.set(key, encoded, ttl_seconds, namespace=namespace)
        return value
    finally:
        if locked:
            cache.release_lock(key)


def _load(loader):
    started = time.perf_counter()
    try:
        return loader()
    finally:
        _observe("cache_load", started)


def _safe_encode(namespace, encode, value):
    try:
        return encode(value)
    except Exception:
        metrics.count(namespace, "set_error")
        return None


def _canonical_bytes(raw: bytes) -> bytes:
    """Normalize JSON so key order/whitespace never registers as a shadow mismatch."""
    try:
        return _canonical(json.loads(raw))
    except Exception:
        return raw


# --- After-commit invalidation -------------------------------------------------
# Each Store.transaction pushes a pending list. ``invalidate`` appends to the
# innermost active list; the owning transaction flushes it only after commit and
# discards it on rollback. Writes outside Store.transaction bump immediately, so
# such callers must invalidate after their own commit.

_pending: contextvars.ContextVar[tuple[list, ...]] = contextvars.ContextVar("openlearn_cache_pending", default=())


def begin_pending():
    frame: list[tuple[str, str]] = []
    token = _pending.set(_pending.get() + (frame,))
    return token, frame


def end_pending(handle, committed: bool) -> None:
    token, frame = handle
    _pending.reset(token)
    if not committed or not frame:
        return
    cache = get_cache()
    if not cache.enabled:
        return
    for namespace, scope in dict.fromkeys(frame):
        try:
            cache.bump(namespace, scope)
        except Exception:
            metrics.count(namespace, "invalidate_error")


def invalidate(namespace: str, scope: str) -> None:
    """Bump a generation after the current transaction commits (or now, outside one)."""
    if namespace not in NAMESPACES:
        raise ValueError("Unknown cache namespace")
    stack = _pending.get()
    if stack:
        stack[-1].append((namespace, scope))
        return
    cache = get_cache()
    if cache.enabled:
        try:
            cache.bump(namespace, scope)
        except Exception:
            metrics.count(namespace, "invalidate_error")


def invalidate_owner(owner_id: str, *namespaces: str) -> None:
    for namespace in namespaces or tuple(sorted(NAMESPACES - {"web_evidence", "material_blocks"})):
        invalidate(namespace, owner_scope(owner_id))


def erase_owner(owner_id: str) -> None:
    cache = get_cache()
    if cache.enabled:
        cache.erase_scope(owner_scope(owner_id))
