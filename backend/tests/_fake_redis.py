"""A minimal in-memory stand-in for the small subset of the redis-py API
the analytics package uses (hashes, sets, string get/setex, pipelines).
Not a test file itself (no test_ prefix, pytest won't collect it) --
shared by test_analytics_aggregator.py/test_analytics_consumer.py/
test_analytics_cache.py so those tests exercise real Redis *semantics*
(actual hash increments, actual set membership) instead of asserting on
mock call counts, without adding a new dependency (no `fakeredis` package
exists anywhere in this repo's dependency tree).
"""
from __future__ import annotations


class FakePipeline:
    def __init__(self, redis: "FakeRedis"):
        self._redis = redis
        self._ops: list[tuple[str, tuple, dict]] = []

    def hincrby(self, *a, **kw):
        self._ops.append(("hincrby", a, kw))
        return self

    def hincrbyfloat(self, *a, **kw):
        self._ops.append(("hincrbyfloat", a, kw))
        return self

    def expire(self, *a, **kw):
        self._ops.append(("expire", a, kw))
        return self

    def sadd(self, *a, **kw):
        self._ops.append(("sadd", a, kw))
        return self

    def execute(self):
        results = []
        for name, args, kwargs in self._ops:
            results.append(getattr(self._redis, name)(*args, **kwargs))
        self._ops = []
        return results


class FakeRedis:
    def __init__(self, *, raise_on: set[str] | None = None):
        self._hashes: dict[str, dict[str, str]] = {}
        self._sets: dict[str, set[str]] = {}
        self._strings: dict[str, str] = {}
        self._ttls: dict[str, int] = {}
        # Method names in this set raise ConnectionError when called --
        # used to exercise every fail-open path.
        self.raise_on = raise_on or set()

    def _maybe_raise(self, name: str):
        if name in self.raise_on:
            raise ConnectionError(f"simulated redis failure: {name}")

    def pipeline(self):
        self._maybe_raise("pipeline")
        return FakePipeline(self)

    def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        self._maybe_raise("hincrby")
        h = self._hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, "0")) + amount)
        return int(h[field])

    def hincrbyfloat(self, key: str, field: str, amount: float) -> float:
        self._maybe_raise("hincrbyfloat")
        h = self._hashes.setdefault(key, {})
        h[field] = str(float(h.get(field, "0")) + amount)
        return float(h[field])

    def hgetall(self, key: str) -> dict[str, str]:
        self._maybe_raise("hgetall")
        return dict(self._hashes.get(key, {}))

    def sadd(self, key: str, *members) -> int:
        self._maybe_raise("sadd")
        s = self._sets.setdefault(key, set())
        added = 0
        for m in members:
            m = str(m)
            if m not in s:
                s.add(m)
                added += 1
        return added

    def scard(self, key: str) -> int:
        self._maybe_raise("scard")
        return len(self._sets.get(key, set()))

    def sunion(self, *keys) -> set:
        self._maybe_raise("sunion")
        result: set = set()
        for key in keys:
            result |= self._sets.get(key, set())
        return result

    def smembers(self, key: str) -> set:
        self._maybe_raise("smembers")
        return set(self._sets.get(key, set()))

    def expire(self, key: str, seconds: int) -> bool:
        self._maybe_raise("expire")
        self._ttls[key] = seconds
        return True

    def get(self, key: str):
        self._maybe_raise("get")
        return self._strings.get(key)

    def setex(self, key: str, ttl: int, value: str) -> bool:
        self._maybe_raise("setex")
        self._strings[key] = value
        self._ttls[key] = ttl
        return True

    def delete(self, key: str) -> int:
        self._maybe_raise("delete")
        existed = key in self._strings or key in self._hashes or key in self._sets
        self._strings.pop(key, None)
        self._hashes.pop(key, None)
        self._sets.pop(key, None)
        return 1 if existed else 0

    def xgroup_create(self, *a, **kw):  # pragma: no cover - not exercised via FakeRedis in these tests
        raise NotImplementedError

    def xreadgroup(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError
