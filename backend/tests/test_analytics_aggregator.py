"""
tests/test_analytics_aggregator.py

Unit tests for control_center.analytics.aggregator, using FakeRedis
(_fake_redis.py) so these exercise real hash/set semantics rather than
mock call counts.
"""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from control_center.analytics import aggregator
from control_center.analytics.schemas import AnalyticsEvent
from _fake_redis import FakeRedis


def _event(**overrides) -> AnalyticsEvent:
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
    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._patcher = patch.object(aggregator, "_redis", self.fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)


class TestApplyInteractionEvent(AggregatorTestCase):
    def test_first_apply_returns_true_and_increments_counters(self) -> None:
        applied = aggregator.apply_interaction_event(_event())
        self.assertTrue(applied)
        self.assertEqual(aggregator.read_agg("2026-01-15")["query_count"], 1)
        self.assertEqual(aggregator.read_agg("2026-01-15", org_id=1)["query_count"], 1)
        self.assertEqual(aggregator.read_agg("2026-01-15", org_id=1, service="rag")["query_count"], 1)

    def test_duplicate_event_id_is_noop(self) -> None:
        aggregator.apply_interaction_event(_event())
        applied_again = aggregator.apply_interaction_event(_event())
        self.assertFalse(applied_again)
        self.assertEqual(aggregator.read_agg("2026-01-15")["query_count"], 1)

    def test_failed_event_increments_error_count(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="evt-2", event_type="query.failed", status="error"))
        agg = aggregator.read_agg("2026-01-15", org_id=1)
        self.assertEqual(agg["query_count"], 1)
        self.assertEqual(agg["query_error_count"], 1)

    def test_non_query_event_increments_event_count_not_query_count(self) -> None:
        aggregator.apply_interaction_event(
            _event(event_id="evt-3", event_type="workflow.completed", status="success")
        )
        agg = aggregator.read_agg("2026-01-15", org_id=1)
        self.assertEqual(agg["query_count"], 0)
        self.assertEqual(agg["event_count"], 1)

    def test_non_query_failed_event_increments_event_error_count(self) -> None:
        aggregator.apply_interaction_event(
            _event(event_id="evt-4", event_type="workflow.failed", status="error")
        )
        agg = aggregator.read_agg("2026-01-15", org_id=1)
        self.assertEqual(agg["event_error_count"], 1)

    def test_no_org_id_skips_org_and_service_keys(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="evt-5", org_id=None))
        self.assertEqual(aggregator.read_agg("2026-01-15")["query_count"], 1)
        self.assertEqual(aggregator.read_agg("2026-01-15", org_id=1)["query_count"], 0)

    def test_active_user_tracked_platform_and_org_scoped(self) -> None:
        aggregator.apply_interaction_event(_event())
        self.assertEqual(aggregator.read_active_user_count(["2026-01-15"]), 1)
        self.assertEqual(aggregator.read_active_user_count(["2026-01-15"], org_id=1), 1)

    def test_no_user_id_skips_active_user_tracking(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="evt-6", user_id=None))
        self.assertEqual(aggregator.read_active_user_count(["2026-01-15"]), 0)

    def test_user_activity_hash_increments_per_user(self) -> None:
        aggregator.apply_interaction_event(_event())
        aggregator.apply_interaction_event(_event(event_id="evt-7"))
        activity = aggregator.read_user_activity(1, "2026-01-15")
        self.assertEqual(activity["42"], 2)


class TestMarkProcessedFailsOpen(AggregatorTestCase):
    def test_redis_error_treated_as_not_yet_seen(self) -> None:
        self.fake.raise_on = {"sadd"}
        # apply_interaction_event's own pipeline sadd calls would also
        # raise, but _mark_processed's direct sadd is checked first and
        # must fail open (return True) rather than silently dropping the
        # event before the real aggregation is even attempted.
        result = aggregator._mark_processed("analytics:processed:interactions:2026-01-15", "evt-x")
        self.assertTrue(result)


class TestApplyAuditEvent(AggregatorTestCase):
    def test_request_event_increments_platform_only(self) -> None:
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
        aggregator.apply_audit_event(
            event_id="audit-2", timestamp=datetime(2026, 1, 15, 10, 0),
            is_request=True, is_error=True, latency_ms=None,
        )
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_error_count"], 1)

    def test_non_request_event_does_not_touch_counters(self) -> None:
        applied = aggregator.apply_audit_event(
            event_id="audit-3", timestamp=datetime(2026, 1, 15, 10, 0),
            is_request=False, is_error=False, latency_ms=None,
        )
        self.assertTrue(applied)
        self.assertEqual(aggregator.read_agg("2026-01-15")["request_count"], 0)

    def test_duplicate_audit_event_is_noop(self) -> None:
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
        aggregator.apply_audit_event(
            event_id="audit-5", timestamp=datetime(2026, 1, 15, 10, 0),
            is_request=True, is_error=False, latency_ms=None,
        )
        agg = aggregator.read_agg("2026-01-15")
        self.assertEqual(agg["latency_count"], 0)
        self.assertEqual(agg["latency_sum"], 0.0)


class TestLatencyBucketLabel(unittest.TestCase):
    def test_exact_boundary_maps_to_that_bucket(self) -> None:
        self.assertEqual(aggregator._latency_bucket_label(50), "50")

    def test_value_above_boundary_maps_to_next_bucket(self) -> None:
        self.assertEqual(aggregator._latency_bucket_label(51), "100")

    def test_huge_value_maps_to_inf(self) -> None:
        self.assertEqual(aggregator._latency_bucket_label(999999), "inf")


class TestReadAgg(AggregatorTestCase):
    def test_missing_key_returns_zeroed_defaults(self) -> None:
        agg = aggregator.read_agg("2026-02-01")
        self.assertEqual(agg["query_count"], 0)
        self.assertEqual(agg["latency_sum"], 0.0)

    def test_service_without_org_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            aggregator.read_agg("2026-02-01", service="rag")

    def test_redis_error_returns_zeroed_defaults(self) -> None:
        self.fake.raise_on = {"hgetall"}
        agg = aggregator.read_agg("2026-02-01")
        self.assertEqual(agg["query_count"], 0)


class TestReadAggRangeAndDateRange(AggregatorTestCase):
    def test_sums_across_dates(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="a", timestamp=datetime(2026, 1, 1)))
        aggregator.apply_interaction_event(_event(event_id="b", timestamp=datetime(2026, 1, 2)))
        total = aggregator.read_agg_range(["2026-01-01", "2026-01-02"], org_id=1)
        self.assertEqual(total["query_count"], 2)

    def test_date_range_is_inclusive(self) -> None:
        from datetime import date
        result = aggregator.date_range(date(2026, 1, 1), date(2026, 1, 3))
        self.assertEqual(result, ["2026-01-01", "2026-01-02", "2026-01-03"])


class TestReadActiveUserCount(AggregatorTestCase):
    def test_empty_date_list_returns_zero(self) -> None:
        self.assertEqual(aggregator.read_active_user_count([]), 0)

    def test_single_date_uses_scard(self) -> None:
        aggregator.apply_interaction_event(_event())
        self.assertEqual(aggregator.read_active_user_count(["2026-01-15"], org_id=1), 1)

    def test_single_date_redis_error_returns_zero(self) -> None:
        self.fake.raise_on = {"scard"}
        self.assertEqual(aggregator.read_active_user_count(["2026-01-15"]), 0)

    def test_multiple_dates_unions_distinct_users(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="a", user_id=1, timestamp=datetime(2026, 1, 1)))
        aggregator.apply_interaction_event(_event(event_id="b", user_id=2, timestamp=datetime(2026, 1, 2)))
        aggregator.apply_interaction_event(_event(event_id="c", user_id=1, timestamp=datetime(2026, 1, 2)))
        count = aggregator.read_active_user_count(["2026-01-01", "2026-01-02"], org_id=1)
        self.assertEqual(count, 2)

    def test_multiple_dates_redis_error_returns_zero(self) -> None:
        self.fake.raise_on = {"sunion"}
        self.assertEqual(aggregator.read_active_user_count(["2026-01-01", "2026-01-02"]), 0)

    def test_read_daily_active_users_shape(self) -> None:
        aggregator.apply_interaction_event(_event())
        result = aggregator.read_daily_active_users(["2026-01-15"], org_id=1)
        self.assertEqual(result, [{"date": "2026-01-15", "count": 1}])


class TestReadUserActivity(AggregatorTestCase):
    def test_redis_error_returns_empty_dict(self) -> None:
        self.fake.raise_on = {"hgetall"}
        self.assertEqual(aggregator.read_user_activity(1, "2026-01-15"), {})


class TestReadActiveUserIds(AggregatorTestCase):
    def test_empty_dates_returns_empty_set(self) -> None:
        self.assertEqual(aggregator.read_active_user_ids([]), set())

    def test_single_date_returns_smembers(self) -> None:
        aggregator.apply_interaction_event(_event())
        self.assertEqual(aggregator.read_active_user_ids(["2026-01-15"], org_id=1), {"42"})

    def test_multiple_dates_unions(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="a", user_id=1, timestamp=datetime(2026, 1, 1)))
        aggregator.apply_interaction_event(_event(event_id="b", user_id=2, timestamp=datetime(2026, 1, 2)))
        result = aggregator.read_active_user_ids(["2026-01-01", "2026-01-02"], org_id=1)
        self.assertEqual(result, {"1", "2"})

    def test_redis_error_returns_empty_set(self) -> None:
        self.fake.raise_on = {"smembers"}
        self.assertEqual(aggregator.read_active_user_ids(["2026-01-15"]), set())

    def test_redis_error_on_multi_date_union_returns_empty_set(self) -> None:
        self.fake.raise_on = {"sunion"}
        self.assertEqual(aggregator.read_active_user_ids(["2026-01-01", "2026-01-02"]), set())


class TestReadKnownServices(AggregatorTestCase):
    def test_no_events_returns_empty_list(self) -> None:
        self.assertEqual(aggregator.read_known_services(1), [])

    def test_records_and_sorts_service_names(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="a", service="rag"))
        aggregator.apply_interaction_event(_event(event_id="b", service="workflow-bundles", event_type="workflow.completed"))
        self.assertEqual(aggregator.read_known_services(1), ["rag", "workflow-bundles"])

    def test_redis_error_returns_empty_list(self) -> None:
        self.fake.raise_on = {"smembers"}
        self.assertEqual(aggregator.read_known_services(1), [])


class TestPlatformLatencyPercentiles(AggregatorTestCase):
    def test_no_data_returns_all_none(self) -> None:
        result = aggregator.read_platform_latency_percentiles(["2026-01-15T10"])
        self.assertEqual(result, {"p50": None, "p95": None, "p99": None})

    def test_estimates_percentiles_from_buckets(self) -> None:
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
        self.fake.raise_on = {"hgetall"}
        result = aggregator.read_platform_latency_percentiles(["2026-01-15T10"])
        self.assertEqual(result["p50"], None)


class TestDateStr(unittest.TestCase):
    def test_accepts_plain_date(self) -> None:
        from datetime import date
        self.assertEqual(aggregator._date_str(date(2026, 3, 1)), "2026-03-01")


class TestHoursForRange(unittest.TestCase):
    def test_inclusive_hourly_list(self) -> None:
        start = datetime(2026, 1, 15, 10, 30)
        end = datetime(2026, 1, 15, 12, 0)
        result = aggregator.hours_for_range(start, end)
        self.assertEqual(result, ["2026-01-15T10", "2026-01-15T11", "2026-01-15T12"])
