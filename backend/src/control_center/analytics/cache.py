"""Redis cache-aside helper for expensive analytics responses (task brief
Section 9). One small helper, not a framework -- every /analytics/*
route (a later PR) calls `get_or_set` with its own fully-qualified key
and a zero-arg `compute_fn`; this module owns none of the key-naming
convention itself (that lives with each caller, matching the brief's own
`analytics:{overview,queries,...}:{org_id}:{team_id}:{from}:{to}` scheme).

Fails open on any Redis error -- same convention every other Redis touch
in this codebase already uses (core/jwt_verify.py's blacklist check,
checks/gateway_traffic.py, RAG's ragbio/interactions.py): a cache outage
must degrade to "always recompute", never to a broken response.
"""
from __future__ import annotations

import json
import os
from typing import Any, Awaitable, Callable

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
DEFAULT_TTL_SECONDS = int(os.environ.get("ANALYTICS_CACHE_TTL_SECONDS", "300"))

_redis = redis.from_url(REDIS_URL, decode_responses=True)


def get_or_set(
    key: str,
    endpoint: str,
    compute_fn: Callable[[], Any],
    ttl: int = DEFAULT_TTL_SECONDS,
) -> Any:
    """Returns the JSON-decoded cached value at `key` if present, else
    calls `compute_fn()`, caches the (JSON-serializable) result for `ttl`
    seconds, and returns it. `endpoint` is only a metrics label (see
    metrics.py's CACHE_HITS/CACHE_MISSES) -- never part of the cache key
    itself, that's the caller's job.
    """
    # Import here, not at module top, so a test that only exercises
    # cache.py's Redis-failure paths doesn't have to know about the
    # metrics registry at all -- same "only pay for what you touch"
    # shape the rest of this package uses for its optional integrations.
    from control_center.analytics.metrics import CACHE_HITS, CACHE_MISSES

    try:
        cached = _redis.get(key)
    except Exception:
        cached = None

    if cached is not None:
        CACHE_HITS.labels(endpoint=endpoint).inc()
        try:
            return json.loads(cached)
        except (TypeError, ValueError):
            # Corrupted cache entry -- treat exactly like a miss rather
            # than raising out of what must remain a best-effort cache.
            pass

    CACHE_MISSES.labels(endpoint=endpoint).inc()
    value = compute_fn()
    try:
        _redis.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass
    return value


async def get_or_set_async(
    key: str,
    endpoint: str,
    compute_coro: Callable[[], Awaitable[Any]],
    ttl: int = DEFAULT_TTL_SECONDS,
) -> Any:
    """Async twin of `get_or_set` -- PR-C's service layer talks to other
    upstreams (billing/TES/team-roster) via `httpx.AsyncClient` from
    inside async FastAPI route handlers, so the compute side has to be
    awaitable. Redis itself is still touched synchronously (redis-py's
    sync client, same as the rest of this package) -- fine here since
    those calls are fast, in-network, and already wrapped in their own
    try/except; only `compute_coro` needs to be awaited.
    """
    from control_center.analytics.metrics import CACHE_HITS, CACHE_MISSES

    try:
        cached = _redis.get(key)
    except Exception:
        cached = None

    if cached is not None:
        CACHE_HITS.labels(endpoint=endpoint).inc()
        try:
            return json.loads(cached)
        except (TypeError, ValueError):
            pass

    CACHE_MISSES.labels(endpoint=endpoint).inc()
    value = await compute_coro()
    try:
        _redis.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass
    return value


def invalidate(key: str) -> None:
    """Best-effort explicit invalidation. Not required for correctness
    (every cache entry has a TTL and naturally expires -- Section 9's own
    "invalidate or naturally expire" wording), only used where a caller
    wants a stale response gone sooner than 5 minutes."""
    try:
        _redis.delete(key)
    except Exception:
        pass
