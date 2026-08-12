"""
tests/test_analytics_service.py

Unit tests for control_center.analytics.service. Uses FakeRedis for the
real aggregator behind these functions (so counts/percentiles are real,
not mocked), and mocks httpx for the team-roster/TES/billing/Prometheus
upstreams.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from control_center.analytics import aggregator, billing_client, prometheus, service, tes_client
from control_center.analytics.permissions import AnalyticsScope
from _fake_redis import FakeRedis


def _event(**overrides):
    from control_center.analytics.schemas import AnalyticsEvent
    fields = dict(
        event_id="evt-1", event_type="query.completed", timestamp=datetime(2026, 1, 15, 10),
        org_id=1, team_id=None, user_id=42, service="rag", action="rag.query",
        status="success", duration_ms=None, request_id=None, metadata={},
    )
    fields.update(overrides)
    return AnalyticsEvent(**fields)


def _resp(status_code: int, json_body=None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    return r


def _mock_ctx(response):
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


class ServiceTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._agg_patcher = patch.object(aggregator, "_redis", self.fake)
        self._agg_patcher.start()
        self.addCleanup(self._agg_patcher.stop)
        self._cache_patcher = patch.object(service.cache, "_redis", self.fake)
        self._cache_patcher.start()
        self.addCleanup(self._cache_patcher.stop)


class ResolveDateRangeTestCase(unittest.TestCase):
    def test_both_none_defaults_to_last_30_days(self) -> None:
        with patch("control_center.analytics.service.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 30)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            frm, to = service.resolve_date_range(None, None)
        self.assertEqual(to, date(2026, 1, 30))
        self.assertEqual(frm, date(2026, 1, 1))

    def test_both_given_passed_through(self) -> None:
        frm, to = service.resolve_date_range(date(2026, 1, 1), date(2026, 1, 5))
        self.assertEqual((frm, to), (date(2026, 1, 1), date(2026, 1, 5)))


class TeamRosterTestCase(ServiceTestCase):
    async def test_success_returns_user_id_set(self) -> None:
        body = [{"user_id": 1, "role": "admin"}, {"user_id": 2, "role": "member"}]
        with patch("control_center.analytics.service.httpx.AsyncClient", return_value=_mock_ctx(_resp(200, body))):
            roster = await service._team_roster(1, 10, "Bearer tok")
        self.assertEqual(roster, {"1", "2"})

    async def test_non_200_returns_none(self) -> None:
        with patch("control_center.analytics.service.httpx.AsyncClient", return_value=_mock_ctx(_resp(404))):
            roster = await service._team_roster(1, 10, "Bearer tok")
        self.assertIsNone(roster)

    async def test_unreachable_returns_none(self) -> None:
        import httpx
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.analytics.service.httpx.AsyncClient", return_value=mock_ctx):
            roster = await service._team_roster(1, 10, "Bearer tok")
        self.assertIsNone(roster)

    async def test_non_list_body_returns_none(self) -> None:
        with patch("control_center.analytics.service.httpx.AsyncClient", return_value=_mock_ctx(_resp(200, {"not": "a list"}))):
            roster = await service._team_roster(1, 10, "Bearer tok")
        self.assertIsNone(roster)

    async def test_member_missing_user_id_is_skipped(self) -> None:
        body = [{"user_id": 1}, {"role": "member"}]
        with patch("control_center.analytics.service.httpx.AsyncClient", return_value=_mock_ctx(_resp(200, body))):
            roster = await service._team_roster(1, 10, "Bearer tok")
        self.assertEqual(roster, {"1"})

    async def test_result_is_cached(self) -> None:
        body = [{"user_id": 1}]
        with patch("control_center.analytics.service.httpx.AsyncClient", return_value=_mock_ctx(_resp(200, body))) as mock_cls:
            await service._team_roster(1, 10, "Bearer tok")
            await service._team_roster(1, 10, "Bearer tok")
        self.assertEqual(mock_cls.call_count, 1)


class ResolveTeamRosterIfNeededTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_no_team_id_not_applicable(self) -> None:
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        roster, applicable = await service._resolve_team_roster_if_needed(scope, "Bearer tok")
        self.assertIsNone(roster)
        self.assertFalse(applicable)

    async def test_no_org_id_not_applicable(self) -> None:
        scope = AnalyticsScope(is_platform_admin=True, org_id=None, team_id=5, user_id="1")
        roster, applicable = await service._resolve_team_roster_if_needed(scope, "Bearer tok")
        self.assertIsNone(roster)
        self.assertFalse(applicable)

    async def test_team_scoped_delegates_to_team_roster(self) -> None:
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value={"1", "2"})):
            roster, applicable = await service._resolve_team_roster_if_needed(scope, "Bearer tok")
        self.assertEqual(roster, {"1", "2"})
        self.assertTrue(applicable)


class GetOverviewTestCase(ServiceTestCase):
    async def test_org_scoped_success(self) -> None:
        aggregator.apply_interaction_event(_event())
        aggregator.apply_interaction_event(_event(event_id="evt-2", event_type="query.failed", status="error"))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        with patch.object(tes_client, "get_runs", AsyncMock(return_value=None)):
            result = await service.get_overview(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        self.assertEqual(result["total_queries"], 2)
        self.assertEqual(result["active_users"], 1)
        self.assertEqual(result["error_rate"], 0.5)
        self.assertIsNone(result["workflows_run"])
        self.assertEqual(result["org_id"], 1)

    async def test_platform_admin_workflows_run_always_none(self) -> None:
        scope = AnalyticsScope(is_platform_admin=True, org_id=None, team_id=None, user_id="1")
        result = await service.get_overview(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        self.assertIsNone(result["workflows_run"])

    async def test_team_scoped_roster_unavailable_returns_none_and_flag(self) -> None:
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value=None)):
            result = await service.get_overview(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        self.assertIsNone(result["total_queries"])
        self.assertIsNone(result["active_users"])
        self.assertFalse(result["team_scope_available"])

    async def test_team_scoped_roster_available_sums_only_roster_members(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="a", user_id=1))
        aggregator.apply_interaction_event(_event(event_id="b", user_id=2))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value={"1"})):
            result = await service.get_overview(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        self.assertEqual(result["total_queries"], 1)
        self.assertEqual(result["active_users"], 1)
        self.assertTrue(result["team_scope_available"])

    async def test_zero_queries_gives_zero_error_rate(self) -> None:
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        result = await service.get_overview(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        self.assertEqual(result["error_rate"], 0.0)

    async def test_org_admin_workflow_count_from_tes(self) -> None:
        runs = [{"created_epoch": int(datetime(2026, 1, 15, 10).timestamp()), "state": "COMPLETED"}]
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        with patch.object(tes_client, "get_runs", AsyncMock(return_value=runs)):
            result = await service.get_overview(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        self.assertEqual(result["workflows_run"], 1)


class GetQueriesTestCase(ServiceTestCase):
    async def test_daily_breakdown_and_total(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="a", timestamp=datetime(2026, 1, 1)))
        aggregator.apply_interaction_event(_event(event_id="b", timestamp=datetime(2026, 1, 2)))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        result = await service.get_queries(scope, date(2026, 1, 1), date(2026, 1, 2), "Bearer tok")
        self.assertEqual(result["total_queries"], 2)
        self.assertEqual(len(result["daily"]), 2)

    async def test_team_scope_unavailable_returns_null_daily(self) -> None:
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value=None)):
            result = await service.get_queries(scope, date(2026, 1, 1), date(2026, 1, 1), "Bearer tok")
        self.assertIsNone(result["total_queries"])
        self.assertIsNone(result["daily"][0]["count"])
        self.assertFalse(result["team_scope_available"])

    async def test_team_scope_available_sums_roster_members_only(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="a", user_id=1, timestamp=datetime(2026, 1, 1)))
        aggregator.apply_interaction_event(_event(event_id="b", user_id=2, timestamp=datetime(2026, 1, 1)))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value={"1"})):
            result = await service.get_queries(scope, date(2026, 1, 1), date(2026, 1, 1), "Bearer tok")
        self.assertEqual(result["total_queries"], 1)
        self.assertTrue(result["team_scope_available"])


class GetUsersTestCase(ServiceTestCase):
    async def test_dau_wau_mau(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="a", user_id=1, timestamp=datetime(2026, 1, 30)))
        aggregator.apply_interaction_event(_event(event_id="b", user_id=2, timestamp=datetime(2026, 1, 25)))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        result = await service.get_users(scope, date(2026, 1, 30), date(2026, 1, 30), "Bearer tok")
        self.assertEqual(result["dau"], 1)
        self.assertEqual(result["wau"], 2)
        self.assertEqual(result["mau"], 2)

    async def test_team_scope_unavailable(self) -> None:
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value=None)):
            result = await service.get_users(scope, date(2026, 1, 30), date(2026, 1, 30), "Bearer tok")
        self.assertIsNone(result["dau"])
        self.assertFalse(result["team_scope_available"])

    async def test_team_scope_available(self) -> None:
        aggregator.apply_interaction_event(_event(user_id=1, timestamp=datetime(2026, 1, 30)))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value={"1"})):
            result = await service.get_users(scope, date(2026, 1, 30), date(2026, 1, 30), "Bearer tok")
        self.assertEqual(result["dau"], 1)
        self.assertTrue(result["team_scope_available"])

    async def test_never_returns_raw_user_ids(self) -> None:
        aggregator.apply_interaction_event(_event())
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        result = await service.get_users(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        dumped = str(result)
        self.assertNotIn("42", dumped)  # the user_id from _event()


class GetServicesTestCase(ServiceTestCase):
    async def test_no_org_id_returns_empty_with_note(self) -> None:
        scope = AnalyticsScope(is_platform_admin=True, org_id=None, team_id=None, user_id="1")
        result = await service.get_services(scope, date(2026, 1, 15), date(2026, 1, 15))
        self.assertEqual(result["services"], [])
        self.assertIn("note", result)

    async def test_breaks_down_by_service(self) -> None:
        aggregator.apply_interaction_event(_event(event_id="a", service="rag"))
        aggregator.apply_interaction_event(_event(event_id="b", service="rag", event_type="query.failed", status="error"))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        result = await service.get_services(scope, date(2026, 1, 15), date(2026, 1, 15))
        self.assertEqual(len(result["services"]), 1)
        row = result["services"][0]
        self.assertEqual(row["service"], "rag")
        self.assertEqual(row["total_calls"], 2)
        self.assertEqual(row["errors"], 1)
        self.assertEqual(row["error_rate"], 0.5)
        self.assertIsNone(row["avg_latency_ms"])


class GetPerformanceTestCase(ServiceTestCase):
    async def test_events_fallback_when_prometheus_unavailable(self) -> None:
        aggregator.apply_audit_event(event_id="a1", timestamp=datetime(2026, 1, 15, 10), is_request=True, is_error=False, latency_ms=100)
        with patch.object(prometheus, "query_latency_quantiles", AsyncMock(return_value={"available": False, "result": None})):
            result = await service.get_performance(date(2026, 1, 15), date(2026, 1, 15))
        self.assertEqual(result["latency_source"], "events")
        self.assertEqual(result["scope"], "platform")
        self.assertIsNone(result["org_id"])
        self.assertIsNone(result["team_id"])

    async def test_prometheus_used_when_available(self) -> None:
        prom_result = {"available": True, "p50": 0.05, "p95": 0.2, "p99": 0.5}
        with patch.object(prometheus, "query_latency_quantiles", AsyncMock(return_value=prom_result)):
            result = await service.get_performance(date(2026, 1, 15), date(2026, 1, 15))
        self.assertEqual(result["latency_source"], "prometheus")
        self.assertEqual(result["p50_latency_ms"], 50.0)
        self.assertEqual(result["p95_latency_ms"], 200.0)
        self.assertEqual(result["p99_latency_ms"], 500.0)

    async def test_error_rate_and_throughput_computed(self) -> None:
        aggregator.apply_audit_event(event_id="a1", timestamp=datetime(2026, 1, 15, 10), is_request=True, is_error=True, latency_ms=100)
        aggregator.apply_audit_event(event_id="a2", timestamp=datetime(2026, 1, 15, 11), is_request=True, is_error=False, latency_ms=100)
        with patch.object(prometheus, "query_latency_quantiles", AsyncMock(return_value={"available": False, "result": None})):
            result = await service.get_performance(date(2026, 1, 15), date(2026, 1, 15))
        self.assertEqual(result["error_rate"], 0.5)
        self.assertEqual(result["throughput_per_day"], 2.0)


class GetWorkflowsTestCase(ServiceTestCase):
    async def test_platform_admin_gets_none_with_note(self) -> None:
        scope = AnalyticsScope(is_platform_admin=True, org_id=None, team_id=None, user_id="1")
        result = await service.get_workflows(scope, date(2026, 1, 1), date(2026, 1, 31), "Bearer tok")
        self.assertIsNone(result["workflows_run"])
        self.assertIn("note", result)

    async def test_tes_unavailable_returns_none(self) -> None:
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        with patch.object(tes_client, "get_runs", AsyncMock(return_value=None)):
            result = await service.get_workflows(scope, date(2026, 1, 1), date(2026, 1, 31), "Bearer tok")
        self.assertIsNone(result["workflows_run"])

    async def test_counts_runs_in_range_and_success_rate(self) -> None:
        runs = [
            {"created_epoch": int(datetime(2026, 1, 15, 10).timestamp()), "state": "COMPLETED"},
            {"created_epoch": int(datetime(2026, 1, 16, 10).timestamp()), "state": "FAILED"},
            {"created_epoch": int(datetime(2025, 1, 1, 10).timestamp()), "state": "COMPLETED"},  # out of range
        ]
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        with patch.object(tes_client, "get_runs", AsyncMock(return_value=runs)):
            result = await service.get_workflows(scope, date(2026, 1, 1), date(2026, 1, 31), "Bearer tok")
        self.assertEqual(result["workflows_run"], 2)
        self.assertEqual(result["success_rate"], 0.5)
        self.assertEqual(len(result["daily"]), 2)


class GetUsageTestCase(ServiceTestCase):
    async def test_no_org_id_returns_unavailable(self) -> None:
        scope = AnalyticsScope(is_platform_admin=True, org_id=None, team_id=None, user_id="1")
        result = await service.get_usage(scope, "Bearer tok")
        self.assertFalse(result["billing_available"])
        self.assertIn("note", result)

    async def test_success_passes_through_billing_data(self) -> None:
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        with (
            patch.object(billing_client, "get_usage", AsyncMock(return_value=(True, {"services": []}))),
            patch.object(billing_client, "get_usage_limits", AsyncMock(return_value=(True, {"limit": 100}))),
        ):
            result = await service.get_usage(scope, "Bearer tok")
        self.assertTrue(result["billing_available"])
        self.assertEqual(result["usage"], {"services": []})
        self.assertEqual(result["limits"], {"limit": 100})

    async def test_billing_unavailable(self) -> None:
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        with (
            patch.object(billing_client, "get_usage", AsyncMock(return_value=(False, None))),
            patch.object(billing_client, "get_usage_limits", AsyncMock(return_value=(True, {}))),
        ):
            result = await service.get_usage(scope, "Bearer tok")
        self.assertFalse(result["billing_available"])


if __name__ == "__main__":
    unittest.main()
