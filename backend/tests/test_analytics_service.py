"""
tests/test_analytics_service.py

Unit tests for control_center.analytics.service. Uses FakeRedis for the
real aggregator behind these functions (so counts/percentiles are real,
not mocked), and mocks httpx for the team-roster/TES/billing/Prometheus
upstreams.

Covers resolve_date_range()'s default-last-30-days behavior,
_team_roster()'s auth-service call and its own caching, team-scope
resolution and its unavailable-roster degrade path, and each of
get_overview()/get_queries()/get_users()/get_services()/get_performance()/
get_workflows()/get_usage()'s org-vs-team-vs-platform scoping and their
individual upstream-unavailable fallbacks.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from control_center.analytics import aggregator, billing_client, prometheus, service, tes_client
from control_center.analytics.permissions import AnalyticsScope
from _fake_redis import FakeRedis


def _event(**overrides):
    """An AnalyticsEvent for a successful rag.query interaction, with overrides merged in."""
    from control_center.analytics.schemas import AnalyticsEvent
    fields = dict(
        event_id="evt-1", event_type="query.completed", timestamp=datetime(2026, 1, 15, 10),
        org_id=1, team_id=None, user_id=42, service="rag", action="rag.query",
        status="success", duration_ms=None, request_id=None, metadata={},
    )
    fields.update(overrides)
    return AnalyticsEvent(**fields)


def _resp(status_code: int, json_body=None) -> MagicMock:
    """A mock httpx.Response with the given status code and .json() return value."""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    return r


def _mock_ctx(response):
    """A mock async context manager whose __aenter__ yields a client whose .get() resolves to `response`."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


class ServiceTestCase(unittest.IsolatedAsyncioTestCase):
    """Base fixture: aggregator and service.cache backed by a shared FakeRedis instance."""

    def setUp(self) -> None:
        self.fake = FakeRedis()
        self._agg_patcher = patch.object(aggregator, "_redis", self.fake)
        self._agg_patcher.start()
        self.addCleanup(self._agg_patcher.stop)
        self._cache_patcher = patch.object(service.cache, "_redis", self.fake)
        self._cache_patcher.start()
        self.addCleanup(self._cache_patcher.stop)


class ResolveDateRangeTestCase(unittest.TestCase):
    """resolve_date_range()'s default-to-last-30-days behavior when both bounds are omitted."""

    def test_both_none_defaults_to_last_30_days(self) -> None:
        """With no from/to given, the range defaults to [today - 29 days, today]."""
        with patch("control_center.analytics.service.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 30)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            frm, to = service.resolve_date_range(None, None)
        self.assertEqual(to, date(2026, 1, 30))
        self.assertEqual(frm, date(2026, 1, 1))

    def test_both_given_passed_through(self) -> None:
        """Explicit from/to dates are returned unchanged."""
        frm, to = service.resolve_date_range(date(2026, 1, 1), date(2026, 1, 5))
        self.assertEqual((frm, to), (date(2026, 1, 1), date(2026, 1, 5)))


class TeamRosterTestCase(ServiceTestCase):
    """_team_roster()'s auth-service HTTP call, its response validation, and its own result caching."""

    async def test_success_returns_user_id_set(self) -> None:
        """A 200 response's member list is reduced to a set of stringified user_ids."""
        body = [{"user_id": 1, "role": "admin"}, {"user_id": 2, "role": "member"}]
        with patch("control_center.analytics.service.httpx.AsyncClient", return_value=_mock_ctx(_resp(200, body))):
            roster = await service._team_roster(1, 10, "Bearer tok")
        self.assertEqual(roster, {"1", "2"})

    async def test_non_200_returns_none(self) -> None:
        """A non-200 response from the auth service returns None (roster unavailable)."""
        with patch("control_center.analytics.service.httpx.AsyncClient", return_value=_mock_ctx(_resp(404))):
            roster = await service._team_roster(1, 10, "Bearer tok")
        self.assertIsNone(roster)

    async def test_unreachable_returns_none(self) -> None:
        """A connection failure to the auth service returns None rather than raising."""
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
        """A 200 response whose body isn't a JSON list returns None."""
        with patch("control_center.analytics.service.httpx.AsyncClient", return_value=_mock_ctx(_resp(200, {"not": "a list"}))):
            roster = await service._team_roster(1, 10, "Bearer tok")
        self.assertIsNone(roster)

    async def test_member_missing_user_id_is_skipped(self) -> None:
        """A roster entry with no user_id key is skipped rather than raising or producing a bogus entry."""
        body = [{"user_id": 1}, {"role": "member"}]
        with patch("control_center.analytics.service.httpx.AsyncClient", return_value=_mock_ctx(_resp(200, body))):
            roster = await service._team_roster(1, 10, "Bearer tok")
        self.assertEqual(roster, {"1"})

    async def test_result_is_cached(self) -> None:
        """A second call for the same (org_id, team_id) reuses the cached roster instead of issuing another HTTP request."""
        body = [{"user_id": 1}]
        with patch("control_center.analytics.service.httpx.AsyncClient", return_value=_mock_ctx(_resp(200, body))) as mock_cls:
            await service._team_roster(1, 10, "Bearer tok")
            await service._team_roster(1, 10, "Bearer tok")
        self.assertEqual(mock_cls.call_count, 1)


class ResolveTeamRosterIfNeededTestCase(unittest.IsolatedAsyncioTestCase):
    """_resolve_team_roster_if_needed()'s decision of whether team-roster scoping applies to a given AnalyticsScope."""

    async def test_no_team_id_not_applicable(self) -> None:
        """A scope with no team_id is not team-scoped: roster resolution is skipped."""
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        roster, applicable = await service._resolve_team_roster_if_needed(scope, "Bearer tok")
        self.assertIsNone(roster)
        self.assertFalse(applicable)

    async def test_no_org_id_not_applicable(self) -> None:
        """A scope with a team_id but no org_id is not team-scoped: roster resolution is skipped."""
        scope = AnalyticsScope(is_platform_admin=True, org_id=None, team_id=5, user_id="1")
        roster, applicable = await service._resolve_team_roster_if_needed(scope, "Bearer tok")
        self.assertIsNone(roster)
        self.assertFalse(applicable)

    async def test_team_scoped_delegates_to_team_roster(self) -> None:
        """A scope with both org_id and team_id delegates to _team_roster() and reports the scope as applicable."""
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value={"1", "2"})):
            roster, applicable = await service._resolve_team_roster_if_needed(scope, "Bearer tok")
        self.assertEqual(roster, {"1", "2"})
        self.assertTrue(applicable)


class GetOverviewTestCase(ServiceTestCase):
    """get_overview()'s org/platform/team scoping, its error-rate computation, and its TES-backed workflow count."""

    async def test_org_scoped_success(self) -> None:
        """An org-scoped overview reports the real total_queries, active_users, and error_rate from applied events."""
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
        """A platform-admin-scoped (no org_id) overview always reports workflows_run as None."""
        scope = AnalyticsScope(is_platform_admin=True, org_id=None, team_id=None, user_id="1")
        result = await service.get_overview(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        self.assertIsNone(result["workflows_run"])

    async def test_team_scoped_roster_unavailable_returns_none_and_flag(self) -> None:
        """When the team roster can't be resolved, total_queries/active_users are None and team_scope_available is False."""
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value=None)):
            result = await service.get_overview(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        self.assertIsNone(result["total_queries"])
        self.assertIsNone(result["active_users"])
        self.assertFalse(result["team_scope_available"])

    async def test_team_scoped_roster_available_sums_only_roster_members(self) -> None:
        """With a resolved roster, only events from roster members count toward total_queries/active_users."""
        aggregator.apply_interaction_event(_event(event_id="a", user_id=1))
        aggregator.apply_interaction_event(_event(event_id="b", user_id=2))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value={"1"})):
            result = await service.get_overview(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        self.assertEqual(result["total_queries"], 1)
        self.assertEqual(result["active_users"], 1)
        self.assertTrue(result["team_scope_available"])

    async def test_zero_queries_gives_zero_error_rate(self) -> None:
        """With zero queries recorded, error_rate is 0.0, not a division-by-zero error."""
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        result = await service.get_overview(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        self.assertEqual(result["error_rate"], 0.0)

    async def test_org_admin_workflow_count_from_tes(self) -> None:
        """An org-scoped overview's workflows_run is populated from tes_client.get_runs()."""
        runs = [{"created_epoch": int(datetime(2026, 1, 15, 10).timestamp()), "state": "COMPLETED"}]
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        with patch.object(tes_client, "get_runs", AsyncMock(return_value=runs)):
            result = await service.get_overview(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        self.assertEqual(result["workflows_run"], 1)


class GetQueriesTestCase(ServiceTestCase):
    """get_queries()'s per-day breakdown and total, plus its team-scope roster gating."""

    async def test_daily_breakdown_and_total(self) -> None:
        """Two events on two different days produce a 2-day daily breakdown summing to total_queries=2."""
        aggregator.apply_interaction_event(_event(event_id="a", timestamp=datetime(2026, 1, 1)))
        aggregator.apply_interaction_event(_event(event_id="b", timestamp=datetime(2026, 1, 2)))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        result = await service.get_queries(scope, date(2026, 1, 1), date(2026, 1, 2), "Bearer tok")
        self.assertEqual(result["total_queries"], 2)
        self.assertEqual(len(result["daily"]), 2)

    async def test_team_scope_unavailable_returns_null_daily(self) -> None:
        """When the team roster can't be resolved, total_queries and each daily count are None, with team_scope_available False."""
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value=None)):
            result = await service.get_queries(scope, date(2026, 1, 1), date(2026, 1, 1), "Bearer tok")
        self.assertIsNone(result["total_queries"])
        self.assertIsNone(result["daily"][0]["count"])
        self.assertFalse(result["team_scope_available"])

    async def test_team_scope_available_sums_roster_members_only(self) -> None:
        """With a resolved roster, only events from roster members are counted toward total_queries."""
        aggregator.apply_interaction_event(_event(event_id="a", user_id=1, timestamp=datetime(2026, 1, 1)))
        aggregator.apply_interaction_event(_event(event_id="b", user_id=2, timestamp=datetime(2026, 1, 1)))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value={"1"})):
            result = await service.get_queries(scope, date(2026, 1, 1), date(2026, 1, 1), "Bearer tok")
        self.assertEqual(result["total_queries"], 1)
        self.assertTrue(result["team_scope_available"])


class GetUsersTestCase(ServiceTestCase):
    """get_users()'s dau/wau/mau computation, its team-scope roster gating, and its no-raw-user-id guarantee."""

    async def test_dau_wau_mau(self) -> None:
        """A user active only on day 30 and another active on day 25 give dau=1, wau=2, mau=2 as of day 30."""
        aggregator.apply_interaction_event(_event(event_id="a", user_id=1, timestamp=datetime(2026, 1, 30)))
        aggregator.apply_interaction_event(_event(event_id="b", user_id=2, timestamp=datetime(2026, 1, 25)))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        result = await service.get_users(scope, date(2026, 1, 30), date(2026, 1, 30), "Bearer tok")
        self.assertEqual(result["dau"], 1)
        self.assertEqual(result["wau"], 2)
        self.assertEqual(result["mau"], 2)

    async def test_team_scope_unavailable(self) -> None:
        """When the team roster can't be resolved, dau is None and team_scope_available is False."""
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value=None)):
            result = await service.get_users(scope, date(2026, 1, 30), date(2026, 1, 30), "Bearer tok")
        self.assertIsNone(result["dau"])
        self.assertFalse(result["team_scope_available"])

    async def test_team_scope_available(self) -> None:
        """With a resolved roster, dau counts only roster members and team_scope_available is True."""
        aggregator.apply_interaction_event(_event(user_id=1, timestamp=datetime(2026, 1, 30)))
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=10, user_id="1")
        with patch.object(service, "_team_roster", AsyncMock(return_value={"1"})):
            result = await service.get_users(scope, date(2026, 1, 30), date(2026, 1, 30), "Bearer tok")
        self.assertEqual(result["dau"], 1)
        self.assertTrue(result["team_scope_available"])

    async def test_never_returns_raw_user_ids(self) -> None:
        """The result never contains the raw user_id string, only aggregate counts."""
        aggregator.apply_interaction_event(_event())
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        result = await service.get_users(scope, date(2026, 1, 15), date(2026, 1, 15), "Bearer tok")
        dumped = str(result)
        self.assertNotIn("42", dumped)  # the user_id from _event()


class GetServicesTestCase(ServiceTestCase):
    """get_services()'s per-service call/error breakdown, and its no-org-id empty fallback."""

    async def test_no_org_id_returns_empty_with_note(self) -> None:
        """With no org_id (a platform-wide view), services is an empty list with an explanatory "note"."""
        scope = AnalyticsScope(is_platform_admin=True, org_id=None, team_id=None, user_id="1")
        result = await service.get_services(scope, date(2026, 1, 15), date(2026, 1, 15))
        self.assertEqual(result["services"], [])
        self.assertIn("note", result)

    async def test_breaks_down_by_service(self) -> None:
        """A success and a failure event for the same service are grouped into one row with the correct error_rate."""
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
    """get_performance()'s Prometheus-vs-events latency source selection, and its error-rate/throughput computation."""

    async def test_events_fallback_when_prometheus_unavailable(self) -> None:
        """With Prometheus unavailable, latency falls back to the "events" source, scoped platform-wide."""
        aggregator.apply_audit_event(event_id="a1", timestamp=datetime(2026, 1, 15, 10), is_request=True, is_error=False, latency_ms=100)
        with patch.object(prometheus, "query_latency_quantiles", AsyncMock(return_value={"available": False, "result": None})):
            result = await service.get_performance(date(2026, 1, 15), date(2026, 1, 15))
        self.assertEqual(result["latency_source"], "events")
        self.assertEqual(result["scope"], "platform")
        self.assertIsNone(result["org_id"])
        self.assertIsNone(result["team_id"])

    async def test_prometheus_used_when_available(self) -> None:
        """When Prometheus is available, its quantiles (in seconds) are converted to milliseconds and used as latency_source="prometheus"."""
        prom_result = {"available": True, "p50": 0.05, "p95": 0.2, "p99": 0.5}
        with patch.object(prometheus, "query_latency_quantiles", AsyncMock(return_value=prom_result)):
            result = await service.get_performance(date(2026, 1, 15), date(2026, 1, 15))
        self.assertEqual(result["latency_source"], "prometheus")
        self.assertEqual(result["p50_latency_ms"], 50.0)
        self.assertEqual(result["p95_latency_ms"], 200.0)
        self.assertEqual(result["p99_latency_ms"], 500.0)

    async def test_error_rate_and_throughput_computed(self) -> None:
        """One error and one success across two requests give error_rate=0.5 and the correct throughput_per_day."""
        aggregator.apply_audit_event(event_id="a1", timestamp=datetime(2026, 1, 15, 10), is_request=True, is_error=True, latency_ms=100)
        aggregator.apply_audit_event(event_id="a2", timestamp=datetime(2026, 1, 15, 11), is_request=True, is_error=False, latency_ms=100)
        with patch.object(prometheus, "query_latency_quantiles", AsyncMock(return_value={"available": False, "result": None})):
            result = await service.get_performance(date(2026, 1, 15), date(2026, 1, 15))
        self.assertEqual(result["error_rate"], 0.5)
        self.assertEqual(result["throughput_per_day"], 2.0)


class GetWorkflowsTestCase(ServiceTestCase):
    """get_workflows()'s platform-wide null-with-note fallback, TES-unavailable handling, and its run-counting/success-rate math."""

    async def test_platform_admin_gets_none_with_note(self) -> None:
        """With no org_id (a platform admin's view), workflows_run is None and a "note" explains why."""
        scope = AnalyticsScope(is_platform_admin=True, org_id=None, team_id=None, user_id="1")
        result = await service.get_workflows(scope, date(2026, 1, 1), date(2026, 1, 31), "Bearer tok")
        self.assertIsNone(result["workflows_run"])
        self.assertIn("note", result)

    async def test_tes_unavailable_returns_none(self) -> None:
        """When tes_client.get_runs() returns None (TES unreachable), workflows_run is None."""
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        with patch.object(tes_client, "get_runs", AsyncMock(return_value=None)):
            result = await service.get_workflows(scope, date(2026, 1, 1), date(2026, 1, 31), "Bearer tok")
        self.assertIsNone(result["workflows_run"])

    async def test_counts_runs_in_range_and_success_rate(self) -> None:
        """Only runs created within the date range are counted, and success_rate reflects the COMPLETED-vs-FAILED split among them."""
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
    """get_usage()'s no-org-id fallback, its pass-through of successful billing data, and its billing-unavailable degrade."""

    async def test_no_org_id_returns_unavailable(self) -> None:
        """With no org_id (a platform admin's unscoped view), billing_available is False with an explanatory "note"."""
        scope = AnalyticsScope(is_platform_admin=True, org_id=None, team_id=None, user_id="1")
        result = await service.get_usage(scope, "Bearer tok")
        self.assertFalse(result["billing_available"])
        self.assertIn("note", result)

    async def test_success_passes_through_billing_data(self) -> None:
        """When both billing calls succeed, their usage/limits payloads are passed through unchanged with billing_available=True."""
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
        """When get_usage() reports unavailable, billing_available is False even if get_usage_limits() succeeded."""
        scope = AnalyticsScope(is_platform_admin=False, org_id=1, team_id=None, user_id="1")
        with (
            patch.object(billing_client, "get_usage", AsyncMock(return_value=(False, None))),
            patch.object(billing_client, "get_usage_limits", AsyncMock(return_value=(True, {}))),
        ):
            result = await service.get_usage(scope, "Bearer tok")
        self.assertFalse(result["billing_available"])


if __name__ == "__main__":
    unittest.main()
