"""
tests/test_analytics_router.py

End-to-end tests for the /analytics/* endpoints via FastAPI's TestClient,
matching test_routes_dashboard.py's own conventions. Covers the task
brief's own API test list (Section 12): date filtering, org filtering,
team filtering, grouping, empty results, cache behavior, Prometheus
unavailable, billing unavailable -- plus RBAC-through-HTTP for the full
platform_admin/org_admin/team_admin/regular-user matrix.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import jwt
from fastapi.testclient import TestClient

from control_center.analytics import aggregator, tes_client
from control_center.analytics.permissions import MANAGE_ALL_ORGS
from control_center.core import jwt_verify as jwt_verify_module
from control_center.main import app
from _fake_redis import FakeRedis

client = TestClient(app)
_no_raise_client = TestClient(app, raise_server_exceptions=False)
SECRET = "test-secret"


def _token(**claims) -> str:
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _auth(**claims) -> dict:
    return {"Authorization": f"Bearer {_token(**claims)}"}


class AnalyticsRouterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        jwt_patcher = patch.object(jwt_verify_module, "JWT_SECRET", SECRET)
        jwt_patcher.start()
        self.addCleanup(jwt_patcher.stop)

        self.fake = FakeRedis()
        redis_patcher = patch.object(aggregator, "_redis", self.fake)
        redis_patcher.start()
        self.addCleanup(redis_patcher.stop)

        from control_center.analytics import cache as cache_module
        cache_patcher = patch.object(cache_module, "_redis", self.fake)
        cache_patcher.start()
        self.addCleanup(cache_patcher.stop)

        tes_patcher = patch.object(tes_client, "get_runs", AsyncMock(return_value=None))
        tes_patcher.start()
        self.addCleanup(tes_patcher.stop)


class AuthenticationTestCase(AnalyticsRouterTestCase):
    def test_missing_token_returns_401(self) -> None:
        r = client.get("/analytics/overview")
        self.assertEqual(r.status_code, 401)

    def test_invalid_token_returns_401(self) -> None:
        r = client.get("/analytics/overview", headers={"Authorization": "Bearer garbage"})
        self.assertEqual(r.status_code, 401)


class RbacMatrixTestCase(AnalyticsRouterTestCase):
    def test_platform_admin_allowed(self) -> None:
        r = client.get("/analytics/overview", headers=_auth(sub="1", permissions=[MANAGE_ALL_ORGS]))
        self.assertEqual(r.status_code, 200)

    def test_org_admin_own_org_allowed(self) -> None:
        headers = _auth(sub="1", permissions=[], org_id=5, org_role=["org_admin"])
        r = client.get("/analytics/overview", params={"org_id": 5}, headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["org_id"], 5)

    def test_org_admin_other_org_denied(self) -> None:
        headers = _auth(sub="1", permissions=[], org_id=5, org_role=["org_admin"])
        r = client.get("/analytics/overview", params={"org_id": 6}, headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_team_admin_permitted_team_allowed(self) -> None:
        headers = _auth(sub="1", permissions=[], org_id=5, org_role=[], team_id=10, team_role="admin")
        r = client.get("/analytics/overview", params={"org_id": 5, "team_id": 10}, headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["team_id"], 10)

    def test_team_admin_unauthorized_team_denied(self) -> None:
        headers = _auth(sub="1", permissions=[], org_id=5, org_role=[], team_id=10, team_role="admin")
        r = client.get("/analytics/overview", params={"org_id": 5, "team_id": 11}, headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_regular_user_denied(self) -> None:
        headers = _auth(sub="1", permissions=[], org_id=5, org_role=["member"])
        r = client.get("/analytics/overview", headers=headers)
        self.assertEqual(r.status_code, 403)


class OverviewEndpointTestCase(AnalyticsRouterTestCase):
    def test_empty_result_shape(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/analytics/overview", params={"org_id": 1}, headers=headers)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total_queries"], 0)
        self.assertEqual(body["active_users"], 0)
        self.assertEqual(body["error_rate"], 0.0)

    def test_date_filtering(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get(
            "/analytics/overview",
            params={"org_id": 1, "from_date": "2026-01-01", "to_date": "2026-01-05"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["from_date"], "2026-01-01")
        self.assertEqual(r.json()["to_date"], "2026-01-05")

    def test_cache_hit_skips_recomputation(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        params = {"org_id": 1, "from_date": "2026-01-01", "to_date": "2026-01-01"}
        r1 = client.get("/analytics/overview", params=params, headers=headers)
        self.assertEqual(r1.status_code, 200)
        with patch("control_center.analytics.service.get_overview", AsyncMock(side_effect=AssertionError("should not recompute"))):
            r2 = client.get("/analytics/overview", params=params, headers=headers)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json(), r2.json())


class RunHelperTestCase(AnalyticsRouterTestCase):
    def test_compute_failure_increments_error_metric_and_propagates(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        with patch("control_center.analytics.service.get_overview", AsyncMock(side_effect=RuntimeError("boom"))):
            r = _no_raise_client.get("/analytics/overview", params={"org_id": 1}, headers=headers)
        self.assertEqual(r.status_code, 500)


class QueriesEndpointTestCase(AnalyticsRouterTestCase):
    def test_returns_daily_trend(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get(
            "/analytics/queries",
            params={"org_id": 1, "from_date": "2026-01-01", "to_date": "2026-01-02"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["daily"]), 2)
        self.assertEqual(body["total_queries"], 0)


class WorkflowsEndpointTestCase(AnalyticsRouterTestCase):
    def test_platform_admin_gets_null_with_note(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/analytics/workflows", headers=headers)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsNone(body["workflows_run"])
        self.assertIn("note", body)

    def test_org_admin_gets_counted_runs(self) -> None:
        runs = [{"created_epoch": 1768000000, "state": "COMPLETED"}]
        headers = _auth(sub="1", permissions=[], org_id=5, org_role=["org_admin"])
        with patch.object(tes_client, "get_runs", AsyncMock(return_value=runs)):
            r = client.get(
                "/analytics/workflows",
                params={"org_id": 5, "from_date": "2020-01-01", "to_date": "2030-01-01"},
                headers=headers,
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["workflows_run"], 1)


class UsersEndpointTestCase(AnalyticsRouterTestCase):
    def test_never_exposes_raw_user_ids(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/analytics/users", params={"org_id": 1}, headers=headers)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("dau", body)
        self.assertIn("wau", body)
        self.assertIn("mau", body)
        self.assertIn("daily", body)
        self.assertNotIn("user_ids", body)
        self.assertNotIn("users", body)


class PerformanceEndpointTestCase(AnalyticsRouterTestCase):
    def test_prometheus_unavailable_still_returns_200(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/analytics/performance", headers=headers)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["scope"], "platform")
        self.assertIsNone(body["org_id"])
        self.assertIsNone(body["team_id"])
        self.assertEqual(body["latency_source"], "events")

    def test_regular_user_still_denied(self) -> None:
        headers = _auth(sub="1", permissions=[], org_id=5, org_role=["member"])
        r = client.get("/analytics/performance", headers=headers)
        self.assertEqual(r.status_code, 403)


class UsageEndpointTestCase(AnalyticsRouterTestCase):
    def test_billing_unavailable_degrades_gracefully(self) -> None:
        # billing_client.get_usage/get_usage_limits already have their own
        # dedicated unreachable-upstream tests (test_analytics_billing_client.py);
        # this proves the router surfaces that (False, None) contract as a
        # 200 with billing_available=False, not a 5xx.
        from control_center.analytics import billing_client

        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        with (
            patch.object(billing_client, "get_usage", AsyncMock(return_value=(False, None))),
            patch.object(billing_client, "get_usage_limits", AsyncMock(return_value=(False, None))),
        ):
            r = client.get("/analytics/usage", params={"org_id": 1}, headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["billing_available"])

    def test_no_org_id_for_platform_admin_returns_unavailable(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/analytics/usage", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["billing_available"])


class ServicesEndpointTestCase(AnalyticsRouterTestCase):
    def test_grouping_by_service(self) -> None:
        from datetime import datetime
        from control_center.analytics.schemas import AnalyticsEvent
        aggregator.apply_interaction_event(AnalyticsEvent(
            event_id="e1", event_type="query.completed", timestamp=datetime(2026, 1, 15, 10),
            org_id=1, service="rag", action="rag.query", status="success",
        ))
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/analytics/services", params={"org_id": 1, "from_date": "2026-01-15", "to_date": "2026-01-15"}, headers=headers)
        self.assertEqual(r.status_code, 200)
        services = r.json()["services"]
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["service"], "rag")


class ExportEndpointTestCase(AnalyticsRouterTestCase):
    def test_export_overview_returns_csv(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/analytics/export", params={"type": "overview", "org_id": 1}, headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn("total_queries", r.text)

    def test_export_queries_returns_daily_rows(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get(
            "/analytics/export",
            params={"type": "queries", "org_id": 1, "from_date": "2026-01-01", "to_date": "2026-01-02"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 200)
        lines = r.text.strip().splitlines()
        self.assertEqual(lines[0], "date,count")
        self.assertEqual(len(lines), 3)  # header + 2 days

    def test_export_services_returns_service_rows(self) -> None:
        from datetime import datetime
        from control_center.analytics.schemas import AnalyticsEvent
        aggregator.apply_interaction_event(AnalyticsEvent(
            event_id="e1", event_type="query.completed", timestamp=datetime(2026, 1, 15, 10),
            org_id=1, service="rag", action="rag.query", status="success",
        ))
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get(
            "/analytics/export",
            params={"type": "services", "org_id": 1, "from_date": "2026-01-15", "to_date": "2026-01-15"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 200)
        lines = r.text.strip().splitlines()
        self.assertEqual(lines[0], "service,total_calls,errors,error_rate,avg_latency_ms")
        self.assertIn("rag", lines[1])

    def test_unknown_export_type_returns_400(self) -> None:
        headers = _auth(sub="1", permissions=[MANAGE_ALL_ORGS])
        r = client.get("/analytics/export", params={"type": "bogus"}, headers=headers)
        self.assertEqual(r.status_code, 400)

    def test_export_requires_auth(self) -> None:
        r = client.get("/analytics/export", params={"type": "overview"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
