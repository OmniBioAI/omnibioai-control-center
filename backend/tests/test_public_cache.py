"""
tests/test_public_cache.py
Unit tests for:
  - control_center.core.public_cache (TTL cache for anonymous responses)
  - the routes that use it, and main.py's Cache-Control middleware

Anonymous responses of the expensive public routes are served from a short
cache; any caller with a token gets a fresh response every time.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
from fastapi.testclient import TestClient

from control_center.api import routes_dashboard, routes_infra
from control_center.core import public_cache
from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app

client = TestClient(app)
_INFRA = {"Authorization": "Bearer " + jwt.encode(
    {"sub": "1", "permissions": ["platform.manage_infra"]}, JWT_SECRET, algorithm="HS256")}


class _CacheOn(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"PUBLIC_CACHE_SECONDS": "60"})
        self.env.start()
        public_cache.clear()

    def tearDown(self) -> None:
        public_cache.clear()
        self.env.stop()


class TestTtl(unittest.TestCase):
    def test_parsing(self) -> None:
        for raw, expected in (("30", 30.0), ("-5", 0.0), ("nope", 60.0)):
            with patch.dict(os.environ, {"PUBLIC_CACHE_SECONDS": raw}):
                self.assertEqual(public_cache.ttl_seconds(), expected)


class TestCached(_CacheOn):
    def test_computes_once_until_expiry(self) -> None:
        compute = MagicMock(side_effect=[1, 2])
        with patch.object(public_cache.time, "monotonic", side_effect=[100.0, 110.0, 200.0]):
            self.assertEqual(public_cache.cached("k", compute), 1)
            self.assertEqual(public_cache.cached("k", compute), 1)
            self.assertEqual(public_cache.cached("k", compute), 2)
        self.assertEqual(compute.call_count, 2)

    def test_disabled_always_computes(self) -> None:
        compute = MagicMock(return_value=1)
        with patch.dict(os.environ, {"PUBLIC_CACHE_SECONDS": "0"}):
            public_cache.cached("k", compute)
            public_cache.cached("k", compute)
        self.assertEqual(compute.call_count, 2)

    def test_async_variant(self) -> None:
        compute = AsyncMock(return_value={"a": 1})
        run = asyncio.run
        self.assertEqual(run(public_cache.cached_async("a", compute)), {"a": 1})
        self.assertEqual(run(public_cache.cached_async("a", compute)), {"a": 1})
        compute.assert_awaited_once()
        with patch.dict(os.environ, {"PUBLIC_CACHE_SECONDS": "0"}):
            run(public_cache.cached_async("a", compute))
        self.assertEqual(compute.await_count, 2)


class TestTtlOverride(_CacheOn):
    def test_override_extends_and_zero_disables(self) -> None:
        compute = AsyncMock(return_value=1)
        clock = SimpleNamespace(monotonic=MagicMock(side_effect=[0.0, 120.0]))
        with patch.object(public_cache, "time", clock):  # not asyncio's own clock
            asyncio.run(public_cache.cached_async("long", compute, ttl=3600))
            asyncio.run(public_cache.cached_async("long", compute, ttl=3600))
        compute.assert_awaited_once()  # still cached at 120 s, past the 60 s default
        asyncio.run(public_cache.cached_async("off", compute, ttl=0))
        asyncio.run(public_cache.cached_async("off", compute, ttl=0))
        self.assertEqual(compute.await_count, 3)

    def test_global_disable_wins_over_override(self) -> None:
        compute = AsyncMock(return_value=1)
        with patch.dict(os.environ, {"PUBLIC_CACHE_SECONDS": "0"}):
            asyncio.run(public_cache.cached_async("k", compute, ttl=3600))
            asyncio.run(public_cache.cached_async("k", compute, ttl=3600))
        self.assertEqual(compute.await_count, 2)


class TestRoutesUseCacheForAnonymousOnly(_CacheOn):
    def test_anonymous_cached_operator_fresh(self) -> None:
        with patch.object(routes_infra, "get_celery_status", return_value={"workers": []}) as check:
            client.get("/celery")
            client.get("/celery")
            self.assertEqual(check.call_count, 1)
            client.get("/celery", headers=_INFRA)
            client.get("/celery", headers=_INFRA)
            self.assertEqual(check.call_count, 3)

    def test_usage_is_cached(self) -> None:
        with patch.object(routes_infra, "get_usage_status", return_value={"runs_by_day": []}) as usage:
            client.get("/usage")
            client.get("/usage")
        usage.assert_called_once()

    def test_dashboard_summary_anonymous_cached(self) -> None:
        summary = AsyncMock(return_value={"ai_platform": None})
        with patch.object(routes_dashboard, "_summary", summary):
            client.get("/dashboard/summary")
            client.get("/dashboard/summary")
            self.assertEqual(summary.await_count, 1)
            client.get("/dashboard/summary", headers={"Authorization": "Bearer x"})
            self.assertEqual(summary.await_count, 2)


class TestCacheControlHeader(_CacheOn):
    def test_public_get_is_cacheable(self) -> None:
        with patch.object(routes_infra, "get_usage_status", return_value={}):
            resp = client.get("/usage")
        self.assertEqual(resp.headers["cache-control"], "public, max-age=60")
        self.assertEqual(resp.headers["vary"], "Authorization")

    def test_authenticated_is_private(self) -> None:
        with patch.object(routes_infra, "get_usage_status", return_value={}):
            resp = client.get("/usage", headers=_INFRA)
        self.assertEqual(resp.headers["cache-control"], "private, no-store")

    def test_other_paths_and_disabled_cache_untouched(self) -> None:
        self.assertNotIn("public", client.get("/health").headers.get("cache-control", ""))
        with patch.dict(os.environ, {"PUBLIC_CACHE_SECONDS": "0"}), \
                patch.object(routes_infra, "get_usage_status", return_value={}):
            self.assertNotIn("cache-control", client.get("/usage").headers)


if __name__ == "__main__":
    unittest.main()
