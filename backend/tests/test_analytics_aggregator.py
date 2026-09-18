"""
tests/test_analytics_aggregator.py

Unit tests for control_center.analytics.aggregator, using FakeRedis
(_fake_redis.py) so these exercise real hash/set semantics rather than
mock call counts.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from control_center.analytics import aggregator
from control_center.analytics.schemas import AnalyticsEvent
from _fake_redis import FakeRedis


def _event(**overrides) -> AnalyticsEvent:
    """A baseline AnalyticsEvent (a successful rag.query for org 1,
    user 42), with any field overridden by keyword."""
    fields = dict(
        event_id="evt-1",
        event_type="query.completed",
        timestamp=datetime(2026, 1, 15, 10, 30),
        org_id=1,
        team_id=None,
        user_id=42,
        service="rag",
        action="rag.query",
        status="success",
        duration_ms=None,
        request_id=None,
        metadata={},
    )
    fields.update(overrides)
    return AnalyticsEvent(**fields)


class AggregatorTestCase(unittest.TestCase):
    """Base fixture: patches aggregator._redis with a fresh FakeRedis
    per test."""

    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(aggregator, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)


class TestApplyInteractionEvent(AggregatorTestCase):
    """apply_interaction_event()'s idempotent counter/user-tracking updates."""

    def test_first_apply_returns_true_and_increments_counters(self) -> None:
        """A first-time event returns True and increments the
        platform, org, and org+service query counters."""
        applied = aggregator.apply_interaction_event(_event())
        self.assertTrue(applied)
        self.assertEqual(aggregator.read_agg("2026-01-15")["query_count"], 1)
        self.assertEqual(aggregator.read_agg("2026-01-15", org_id=1)["query_count"], 1)
        self.assertEqual(aggregator.read_agg("2026-01-15", org_id=1, service="rag")["query_count"], 1)

    def test_duplicate_event_id_is_noop(self) -> None:
        """Applying the same event_id twice only counts it once."""
        aggregator.apply_interaction_event(_event())
        applied_again = aggregator.apply_interaction_event(_event())
        self.assertFalse(applied_again)
        self.assertEqual(aggregator.read_agg("2026-01-15")["query_count"], 1)

    def test_failed_event_increments_error_count(self) -> None:
        """A failed query event increments both query_count and
        query_error_count."""
        aggregator.apply_interaction_event(_event(event_id="evt-2", event_type="query.failed", status="error"))
        agg = aggregator.read_agg("2026-01-15", org_id=1)
        self.assertEqual(agg["query_count"], 1)
        self.assertEqual(agg["query_error_count"], 1)

    def test_non_query_event_increments_event_count_not_query_count(self) -> None:
        """A non-query event type increments event_count, not query_count."""
        aggregator.apply_interaction_event(
            _event(event_id="evt-3", event_type="workflow.completed", status="success")
        )
        agg = aggregator.read_agg("2026-01-15", org_id=1)
        self.assertEqual(agg["query_count"], 0)
        self.assertEqual(agg["event_count"], 1)

    def test_non_query_failed_event_increments_event_error_count(self) -> None:
        """A failed non-query event increments event_error_count."""
        aggregator.apply_interaction_event(
            _event(event_id="evt-4", event_type="workflow.failed", status="error")
        )
        agg = aggregator.read_agg("2026-01-15", org_id=1)
        self.assertEqual(agg["event_error_count"], 1)

    def test_no_org_id_skips_org_and_service_keys(self) -> None:
        """An event with no org_id still increments the platform-wide
        counter, but not any org-scoped one."""
        aggregator.apply_interaction_event(_event(event_id="evt-5", org_id=None))
        self.assertEqual(aggregator.read_agg("2026-01-15")["query_count"], 1)
        self.assertEqual(aggregator.read_agg("2026-01-15", org_id=1)["query_count"], 0)

    def test_active_user_tracked_platform_and_org_scoped(self) -> None:
        """A user is tracked as active both platform-wide and within
        their org."""
        aggregator.apply_interaction_event(_event())
        self.assertEqual(aggregator.read_active_user_count(["2026-01-15"]), 1)
        self.assertEqual(aggregator.read_active_user_count(["2026-01-15"], org_id=1), 1)

    def test_no_user_id_skips_active_user_tracking(self) -> None:
        """An event with no user_id is not tracked as an active user."""
        aggregator.apply_interaction_event(_event(event_id="evt-6", user_id=None))
        self.assertEqual(aggregator.read_active_user_count(["2026-01-15"]), 0)

    def test_user_activity_hash_increments_per_user(self) -> None:
        """Multiple events from the same user increment that user's
        activity count in the per-user hash."""
        aggregator.apply_interaction_event(_event())
        aggregator.apply_interaction_event(_event(event_id="evt-7"))
        activity = aggregator.read_user_activity(1, "2026-01-15")
        self.assertEqual(activity["42"], 2)


class TestMarkProcessedFailsOpen(AggregatorTestCase):
    """_mark_processed()'s fail-open behavior on a Redis error."""

    def test_redis_error_treated_as_not_yet_seen(self) -> None:
        """A Redis error on the dedup-marking sadd is treated as "not
        yet seen" (returns True) rather than silently dropping the event."""
        self.fake.raise_on = {"sadd"}
        # apply_interaction_event's own pipeline sadd calls would also
        # raise, but _mark_processed's direct sadd is checked first and
        # must fail open (return True) rather than silently dropping the
        # event before the real aggregation is even attempted.
        result = aggregator._mark_processed("analytics:processed:interactions:2026-01-15", "evt-x")
        self.assertTrue(result)


class TestApplyAuditEvent(AggregatorTestCase):
    """apply_audit_event()'s request/error/latency counter updates."""

    def test_request_event_increments_platform_only(self) -> None:
        """A request event increments request_count and the latency
        histogram/sum."""
        applied = aggregator.apply_audit_event(
            event_id="audit-1",
            timestamp=datetime(2026, 1, 15, 10, 0),
            is_request=True,
            is_error=False,
            latency_ms=120,
        )
        self.assertTrue(applied)
        agg = aggregator.read_agg("2026-01-15")
        self.assertEqual(agg["request_count"], 1)
        self.assertEqual(agg["request_error_count"], 0)
        self.assertEqual(agg["latency_count"], 1)
        self.assertEqual(agg["latency_sum"], 120.0)

    def test_error_event_increments_error_count(self) -> None:
        """An error-flagged request event increments request_error_count."""
        aggregator.apply_audit_event(
            event_id="audit-2", timestamp=datetime(2026, 1, 15, 10, 0),
            is_request=True, is_error=True, latency_ms=None,
        )
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_error_count"], 1)

    def test_non_request_event_does_not_touch_counters(self) -> None:
        """A non-request audit event returns True (applied) but leaves
        request_count untouched."""
        applied = aggregator.apply_audit_event(
            event_id="audit-3", timestamp=datetime(2026, 1, 15, 10, 0),
            is_request=False, is_error=False, latency_ms=None,
        )
        self.assertTrue(applied)
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_count"], 0)

    def test_duplicate_audit_event_is_noop(self) -> None:
        """Applying the same audit event_id twice only counts it once."""
        aggregator.apply_audit_event(
            event_id="audit-4", timestamp=datetime(2026, 1, 15, 10, 0),
            is_request=True, is_error=False, latency_ms=10,
        )
        applied_again = aggregator.apply_audit_event(
            event_id="audit-4", timestamp=datetime(2026, 1, 15, 10, 0),
            is_request=True, is_error=False, latency_ms=10,
        )
        self.assertFalse(applied_again)
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_count"], 1)

    def test_latency_none_skips_histogram_and_sum(self) -> None:
        """A None latency_ms is excluded from both the histogram count
        and the running sum."""
        aggregator.apply_audit_event(
            event_id="audit-5", timestamp=datetime(2026, 1, 15, 10, 0),
            is_request=True, is_error=False, latency_ms=None,
        )
        agg = aggregator.read_agg("2026-01-15")
        self.assertEqual(agg["latency_count"], 0)
        self.assertEqual(agg["latency_sum"], 0.0)


class TestLatencyBucketLabel(unittest.TestCase):
    """_latency_bucket_label()'s bucket assignment, inclusive of exact
    boundaries and clamping huge values to "inf"."""

    def test_exact_boundary_maps_to_that_bucket(self) -> None:
        """A value exactly on a bucket boundary maps to that bucket."""
        self.assertEqual(aggregator._latency_bucket_label(50), "50")

    def test_value_above_boundary_maps_to_next_bucket(self) -> None:
        """A value just above a boundary maps to the next bucket up."""
        self.assertEqual(aggregator._latency_bucket_label(51), "100")

    def test_huge_value_maps_to_inf(self) -> None:
        """A value beyond every real bucket maps to "inf"."""
        self.assertEqual(aggregator._latency_bucket_label(999999), "inf")


class TestReadAgg(AggregatorTestCase):
    """read_agg()'s zeroed-default fallback and its org/service scoping rule."""

    def test_missing_key_returns_zeroed_defaults(self) -> None:
        """A date with no recorded data returns all-zero defaults."""
        agg = aggregator.read_agg("2026-02-01")
        self.assertEqual(agg["query_count"], 0)
        self.assertEqual(agg["latency_sum"], 0.0)

    def test_service_without_org_id_raises(self) -> None:
        """Passing service= without org_id= raises ValueError -- a
        service scope is only meaningful within an org."""
        with self.assertRaises(ValueError):
            aggregator.read_agg("2026-02-01", service="rag")

    def test_redis_error_returns_zeroed_defaults(self) -> None:
        """A Redis error reading the hash returns all-zero defaults
        rather than raising."""
        self.fake.raise_on = {"hgetall"}
        agg = aggregator.read_agg("2026-02-01")
        self.assertEqual(agg["query_count"], 0)


class TestReadAggRangeAndDateRange(AggregatorTestCase):
    """read_agg_range()'s summation across dates and date_range()'s
    inclusive date-list generation."""

    def test_sums_across_dates(self) -> None:
        """Counts from two different dates are summed into one total."""
        aggregator.apply_interaction_event(_event(event_id="a", timestamp=datetime(2026, 1, 1)))
        aggregator.apply_interaction_event(_event(event_id="b", timestamp=datetime(2026, 1, 2)))
        total = aggregator.read_agg_range(["2026-01-01", "2026-01-02"], org_id=1)
        self.assertEqual(total["query_count"], 2)

    def test_date_range_is_inclusive(self) -> None:
        """date_range() includes both the start and end dates."""
        from datetime import date
        result = aggregator.date_range(date(2026, 1, 1), date(2026, 1, 3))
        self.assertEqual(result, ["2026-01-01", "2026-01-02", "2026-01-03"])


class TestReadActiveUserCount(AggregatorTestCase):
    """read_active_user_count()'s single-date SCARD vs. multi-date
    SUNION paths, and their fail-safe zero on a Redis error."""

    def test_empty_date_list_returns_zero(self) -> None:
        """An empty date list returns 0 without touching Redis."""
        self.assertEqual(aggregator.read_active_user_count([]), 0)

    def test_single_date_uses_scard(self) -> None:
        """A single date returns the exact active-user count for that day."""
        aggregator.apply_interaction_event(_event())
        self.assertEqual(aggregator.read_active_user_count(["2026-01-15"], org_id=1), 1)

    def test_single_date_redis_error_returns_zero(self) -> None:
        """A Redis error on the single-date SCARD path returns 0."""
        self.fake.raise_on = {"scard"}
        self.assertEqual(aggregator.read_active_user_count(["2026-01-15"]), 0)

    def test_multiple_dates_unions_distinct_users(self) -> None:
        """Multiple dates union to a distinct-user count, not a naive sum."""
        aggregator.apply_interaction_event(_event(event_id="a", user_id=1, timestamp=datetime(2026, 1, 1)))
        aggregator.apply_interaction_event(_event(event_id="b", user_id=2, timestamp=datetime(2026, 1, 2)))
        aggregator.apply_interaction_event(_event(event_id="c", user_id=1, timestamp=datetime(2026, 1, 2)))
        count = aggregator.read_active_user_count(["2026-01-01", "2026-01-02"], org_id=1)
        self.assertEqual(count, 2)

    def test_multiple_dates_redis_error_returns_zero(self) -> None:
        """A Redis error on the multi-date SUNION path returns 0."""
        self.fake.raise_on = {"sunion"}
        self.assertEqual(aggregator.read_active_user_count(["2026-01-01", "2026-01-02"]), 0)

    def test_read_daily_active_users_shape(self) -> None:
        """read_daily_active_users() returns one {date, count} entry per date."""
        aggregator.apply_interaction_event(_event())
        result = aggregator.read_daily_active_users(["2026-01-15"], org_id=1)
        self.assertEqual(result, [{"date": "2026-01-15", "count": 1}])


class TestReadUserActivity(AggregatorTestCase):
    """read_user_activity()'s fail-safe empty-dict on a Redis error."""

    def test_redis_error_returns_empty_dict(self) -> None:
        """A Redis error reading the activity hash returns an empty dict."""
        self.fake.raise_on = {"hgetall"}
        self.assertEqual(aggregator.read_user_activity(1, "2026-01-15"), {})


class TestReadActiveUserIds(AggregatorTestCase):
    """read_active_user_ids()'s single/multi-date set union, and its
    fail-safe empty set on a Redis error."""

    def test_empty_dates_returns_empty_set(self) -> None:
        """An empty date list returns an empty set."""
        self.assertEqual(aggregator.read_active_user_ids([]), set())

    def test_single_date_returns_smembers(self) -> None:
        """A single date returns the exact set of active user ids for that day."""
        aggregator.apply_interaction_event(_event())
        self.assertEqual(aggregator.read_active_user_ids(["2026-01-15"], org_id=1), {"42"})

    def test_multiple_dates_unions(self) -> None:
        """Multiple dates union to the distinct set of user ids across them."""
        aggregator.apply_interaction_event(_event(event_id="a", user_id=1, timestamp=datetime(2026, 1, 1)))
        aggregator.apply_interaction_event(_event(event_id="b", user_id=2, timestamp=datetime(2026, 1, 2)))
        result = aggregator.read_active_user_ids(["2026-01-01", "2026-01-02"], org_id=1)
        self.assertEqual(result, {"1", "2"})

    def test_redis_error_returns_empty_set(self) -> None:
        """A Redis error on the single-date path returns an empty set."""
        self.fake.raise_on = {"smembers"}
        self.assertEqual(aggregator.read_active_user_ids(["2026-01-15"]), set())

    def test_redis_error_on_multi_date_union_returns_empty_set(self) -> None:
        """A Redis error on the multi-date union path returns an empty set."""
        self.fake.raise_on = {"sunion"}
        self.assertEqual(aggregator.read_active_user_ids(["2026-01-01", "2026-01-02"]), set())


class TestReadKnownServices(AggregatorTestCase):
    """read_known_services()'s sorted service-name listing, and its
    fail-safe empty list on a Redis error."""

    def test_no_events_returns_empty_list(self) -> None:
        """No recorded events for the org returns an empty list."""
        self.assertEqual(aggregator.read_known_services(1), [])

    def test_records_and_sorts_service_names(self) -> None:
        """Every service that has emitted an event is recorded and the
        result is returned sorted."""
        aggregator.apply_interaction_event(_event(event_id="a", service="rag"))
        aggregator.apply_interaction_event(_event(event_id="b", service="workflow-bundles", event_type="workflow.completed"))
        self.assertEqual(aggregator.read_known_services(1), ["rag", "workflow-bundles"])

    def test_redis_error_returns_empty_list(self) -> None:
        """A Redis error returns an empty list rather than raising."""
        self.fake.raise_on = {"smembers"}
        self.assertEqual(aggregator.read_known_services(1), [])


class TestPlatformLatencyPercentiles(AggregatorTestCase):
    """read_platform_latency_percentiles()'s bucket-based percentile
    estimation across hourly windows."""

    def test_no_data_returns_all_none(self) -> None:
        """No recorded latency data returns all three percentiles as None."""
        result = aggregator.read_platform_latency_percentiles(["2026-01-15T10"])
        self.assertEqual(result, {"p50": None, "p95": None, "p99": None})

    def test_estimates_percentiles_from_buckets(self) -> None:
        """p50/p95/p99 are estimated correctly from a realistic mix of
        fast/mid/slow latency buckets."""
        ts = datetime(2026, 1, 15, 10, 0)
        for _ in range(50):
            aggregator.apply_audit_event(
                event_id=f"fast-{_}", timestamp=ts, is_request=True, is_error=False, latency_ms=10,
            )
        for _ in range(45):
            aggregator.apply_audit_event(
                event_id=f"mid-{_}", timestamp=ts, is_request=True, is_error=False, latency_ms=200,
            )
        for _ in range(5):
            aggregator.apply_audit_event(
                event_id=f"slow-{_}", timestamp=ts, is_request=True, is_error=False, latency_ms=6000,
            )
        result = aggregator.read_platform_latency_percentiles(["2026-01-15T10"])
        self.assertEqual(result["p50"], 50.0)
        self.assertEqual(result["p95"], 250.0)
        self.assertEqual(result["p99"], 5000.0)

    def test_redis_error_on_one_hour_contributes_nothing(self) -> None:
        """A Redis error reading one hour's bucket contributes nothing
        (that hour's data is simply absent, not a raised exception)."""
        self.fake.raise_on = {"hgetall"}
        result = aggregator.read_platform_latency_percentiles(["2026-01-15T10"])
        self.assertEqual(result["p50"], None)


class TestDateStr(unittest.TestCase):
    """_date_str()'s date-to-string formatting."""

    def test_accepts_plain_date(self) -> None:
        """A plain date.date object formats to "YYYY-MM-DD"."""
        from datetime import date
        self.assertEqual(aggregator._date_str(date(2026, 3, 1)), "2026-03-01")


class TestHoursForRange(unittest.TestCase):
    """hours_for_range()'s inclusive hourly bucket-label generation."""

    def test_inclusive_hourly_list(self) -> None:
        """The hour range includes both the start and end hours."""
        start = datetime(2026, 1, 15, 10, 30)
        end = datetime(2026, 1, 15, 12, 0)
        result = aggregator.hours_for_range(start, end)
        self.assertEqual(result, ["2026-01-15T10", "2026-01-15T11", "2026-01-15T12"])
