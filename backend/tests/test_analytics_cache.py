"""
tests/test_analytics_cache.py

Unit tests for control_center.analytics.cache.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from control_center.analytics import cache
from _fake_redis import FakeRedis


class GetOrSetTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(cache, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_cache_miss_computes_and_stores(self) -> None:
        calls = []

        def compute():
            calls.append(1)
            return {"total": 5}

        result = cache.get_or_set("k1", "overview", compute)
        self.assertEqual(result, {"total": 5})
        self.assertEqual(len(calls), 1)

    def test_cache_hit_skips_compute(self) -> None:
        cache.get_or_set("k2", "overview", lambda: {"total": 1})
        result = cache.get_or_set("k2", "overview", lambda: (_ for _ in ()).throw(AssertionError("should not compute")))
        self.assertEqual(result, {"total": 1})

    def test_corrupted_cache_entry_falls_back_to_compute(self) -> None:
        self.fake._strings["k3"] = "not-json{"
        result = cache.get_or_set("k3", "overview", lambda: {"total": 9})
        self.assertEqual(result, {"total": 9})

    def test_redis_get_failure_falls_back_to_compute(self) -> None:
        self.fake.raise_on = {"get"}
        result = cache.get_or_set("k4", "overview", lambda: {"total": 2})
        self.assertEqual(result, {"total": 2})

    def test_redis_setex_failure_still_returns_value(self) -> None:
        self.fake.raise_on = {"setex"}
        result = cache.get_or_set("k5", "overview", lambda: {"total": 3})
        self.assertEqual(result, {"total": 3})


class InvalidateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(cache, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_invalidate_deletes_key(self) -> None:
        cache.get_or_set("k6", "overview", lambda: {"total": 1})
        cache.invalidate("k6")
        self.assertIsNone(self.fake.get("k6"))

    def test_invalidate_swallows_redis_error(self) -> None:
        self.fake.raise_on = {"delete"}
        cache.invalidate("k7")  # must not raise
