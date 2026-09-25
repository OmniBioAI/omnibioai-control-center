"""Short-lived cache for anonymous responses of the public routes.

control.omnibioai.org is a public page: every visit calls routes that scan
run directories (/usage), glob reference data on disk (/reference), query
MySQL/Redis/Prometheus/Docker (/database, /activity, ...) or fan out to
other services (/dashboard/summary). Without a cache, visitor traffic
lands directly on those backends.

Only the anonymous (public) shape is cached, and only for
PUBLIC_CACHE_SECONDS (default 60; 0 disables caching). Operators with a
token always get a fresh, uncached response. The cache is per process and
bounded by the fixed set of keys the routes use.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}


def ttl_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("PUBLIC_CACHE_SECONDS", "60")))
    except ValueError:
        return 60.0


def _get(key: str, now: float) -> tuple[bool, Any]:
    with _lock:
        hit = _store.get(key)
    if hit and hit[0] > now:
        return True, hit[1]
    return False, None


def _put(key: str, value: Any, now: float, ttl: float) -> None:
    with _lock:
        _store[key] = (now + ttl, value)


def cached(key: str, compute: Callable[[], T]) -> T:
    """Return the cached value for `key`, computing it when missing/expired."""
    ttl = ttl_seconds()
    if ttl <= 0:
        return compute()
    now = time.monotonic()
    found, value = _get(key, now)
    if found:
        return value
    value = compute()
    _put(key, value, now, ttl)
    return value


async def cached_async(key: str, compute: Callable[[], Awaitable[T]]) -> T:
    """Async counterpart of cached() for async route handlers."""
    ttl = ttl_seconds()
    if ttl <= 0:
        return await compute()
    now = time.monotonic()
    found, value = _get(key, now)
    if found:
        return value
    value = await compute()
    _put(key, value, now, ttl)
    return value


def clear() -> None:
    with _lock:
        _store.clear()
