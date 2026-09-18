"""
tests/test_analytics_cache.py

Unit tests for control_center.analytics.cache: get_or_set()/
get_or_set_async() compute-and-cache with graceful degradation on a
corrupted cache entry or a Redis GET/SETEX failure (always falls back to
calling `compute`, never raises), and invalidate()'s best-effort delete.
Uses the repo's own FakeRedis (tests/_fake_redis.py) rather than mocking
Redis calls individually, since real get/setex/delete round-trip
semantics (including its `raise_on` failure-injection) are what these
tests need.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from control_center.analytics import cache
from _fake_redis import FakeRedis


class GetOrSetAsyncTestCase(unittest.IsolatedAsyncioTestCase):
    """get_or_set_async()'s compute-and-cache behavior against a FakeRedis,
    including graceful fallback on a corrupted entry or a Redis failure."""

    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(cache, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    async def test_cache_miss_awaits_compute_and_stores(self) -> None:
        """A cache miss awaits `compute` exactly once and returns its result."""
        calls = []

        async def compute():
            calls.append(1)
            return {"total": 5}

        result = await cache.get_or_set_async("ak1", "overview", compute)
        self.assertEqual(result, {"total": 5})
        self.assertEqual(len(calls), 1)

    async def test_cache_hit_skips_compute(self) -> None:
        """A cache hit returns the stored value without ever awaiting
        `compute` again."""
        async def compute():
            return {"total": 1}

        await cache.get_or_set_async("ak2", "overview", compute)

        async def should_not_run():
            raise AssertionError("should not compute")

        result = await cache.get_or_set_async("ak2", "overview", should_not_run)
        self.assertEqual(result, {"total": 1})

    async def test_corrupted_cache_entry_falls_back_to_compute(self) -> None:
        """A cache value that isn't valid JSON is treated as a miss --
        `compute` runs and its result is returned."""
        self.fake._strings["ak3"] = "not-json{"

        async def compute():
            return {"total": 9}

        result = await cache.get_or_set_async("ak3", "overview", compute)
        self.assertEqual(result, {"total": 9})

    async def test_redis_get_failure_falls_back_to_compute(self) -> None:
        """A Redis GET failure is treated as a miss -- `compute` still
        runs and its result is returned."""
        self.fake.raise_on = {"get"}

        async def compute():
            return {"total": 2}

        result = await cache.get_or_set_async("ak4", "overview", compute)
        self.assertEqual(result, {"total": 2})

    async def test_redis_setex_failure_still_returns_value(self) -> None:
        """A Redis SETEX failure after a successful compute still returns
        the computed value -- caching is best-effort."""
        self.fake.raise_on = {"setex"}

        async def compute():
            return {"total": 3}

        result = await cache.get_or_set_async("ak5", "overview", compute)
        self.assertEqual(result, {"total": 3})


class GetOrSetTestCase(unittest.TestCase):
    """get_or_set()'s synchronous equivalent of the async cache tests above."""

    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(cache, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_cache_miss_computes_and_stores(self) -> None:
        """A cache miss calls `compute` exactly once and returns its result."""
        calls = []

        def compute():
            calls.append(1)
            return {"total": 5}

        result = cache.get_or_set("k1", "overview", compute)
        self.assertEqual(result, {"total": 5})
        self.assertEqual(len(calls), 1)

    def test_cache_hit_skips_compute(self) -> None:
        """A cache hit returns the stored value without calling `compute`
        again."""
        cache.get_or_set("k2", "overview", lambda: {"total": 1})
        result = cache.get_or_set("k2", "overview", lambda: (_ for _ in ()).throw(AssertionError("should not compute")))
        self.assertEqual(result, {"total": 1})

    def test_corrupted_cache_entry_falls_back_to_compute(self) -> None:
        """A cache value that isn't valid JSON is treated as a miss."""
        self.fake._strings["k3"] = "not-json{"
        result = cache.get_or_set("k3", "overview", lambda: {"total": 9})
        self.assertEqual(result, {"total": 9})

    def test_redis_get_failure_falls_back_to_compute(self) -> None:
        """A Redis GET failure is treated as a miss."""
        self.fake.raise_on = {"get"}
        result = cache.get_or_set("k4", "overview", lambda: {"total": 2})
        self.assertEqual(result, {"total": 2})

    def test_redis_setex_failure_still_returns_value(self) -> None:
        """A Redis SETEX failure still returns the computed value."""
        self.fake.raise_on = {"setex"}
        result = cache.get_or_set("k5", "overview", lambda: {"total": 3})
        self.assertEqual(result, {"total": 3})


class InvalidateTestCase(unittest.TestCase):
    """invalidate()'s delete behavior, including failing silently on a
    Redis error."""

    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(cache, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_invalidate_deletes_key(self) -> None:
        """invalidate() removes the cached key -- a subsequent get()
        returns nothing."""
        cache.get_or_set("k6", "overview", lambda: {"total": 1})
        cache.invalidate("k6")
        self.assertIsNone(self.fake.get("k6"))

    def test_invalidate_swallows_redis_error(self) -> None:
        """A Redis DELETE failure is swallowed rather than raised."""
        self.fake.raise_on = {"delete"}
        cache.invalidate("k7")  # must not raise
