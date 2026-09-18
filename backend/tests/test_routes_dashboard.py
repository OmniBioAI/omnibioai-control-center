"""
tests/test_routes_dashboard.py

Unit tests for control_center.api.routes_dashboard (PR10: Live Platform
Dashboard). GET /dashboard/summary aggregates several upstream services
(omnibioai-auth, omnibioai-model-registry, omnibioai-rag,
omnibioai-workflow-bundles, omnibioai-tes) plus control-center's own
in-process checks. These tests prove:
  - each section reads the right upstream endpoint and extracts the
    right numbers (including the model dedup and category-sum logic);
  - the Authorization header is forwarded to the services whose data is
    caller-scoped, and never fabricated when absent;
  - the in-process Infrastructure/Operations section is included only
    when the caller's token actually carries platform.manage_infra, and
    is null (not merely empty) otherwise;
  - any single unreachable/erroring upstream degrades only its own
    section to null instead of failing the whole request.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from control_center.main import app

client = TestClient(app)


def _resp(status_code: int, json_body=None) -> MagicMock:
    """A mock httpx.Response with the given status code and .json() return value."""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    return r


def _mock_get_by_url(routes: dict[str, MagicMock], default_status=404):
    """Returns an AsyncMock suitable for `client.get = ...` whose response
    is chosen by matching the request URL against a substring -> response
    map, so each test only has to describe the endpoints it cares about."""
    async def _get(url, headers=None, params=None, timeout=None):
        for substring, response in routes.items():
            if substring in url:
                return response
        return _resp(default_status, {})
    return AsyncMock(side_effect=_get)


def _mock_client(routes: dict[str, MagicMock]):
    """A mock async context manager whose __aenter__ yields a client whose .get() is routed by URL substring via `routes`."""
    mock_client = MagicMock()
    mock_client.get = _mock_get_by_url(routes)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


ORGS_PAGE = {
    "items": [
        {"id": 1, "team_count": 3}, {"id": 2, "team_count": 5},
    ],
    "total": 12, "page": 1, "page_size": 100, "total_pages": 1,
}
USERS_PAGE = {"items": [], "total": 246, "page": 1, "page_size": 1, "total_pages": 246}
ROLES = [{"id": 1, "name": "admin", "permissions": []}, {"id": 2, "name": "member", "permissions": []}]
MODELS = [
    {"task": "celltype_sc", "model_name": "scanvi", "version": "1", "stage": "production"},
    {"task": "celltype_sc", "model_name": "scanvi", "version": "2", "stage": "staging"},
    {"task": "variant_call", "model_name": "deepvar", "version": "1", "stage": "none"},
]
CATEGORIES = [{"category": "qc", "count": 4, "enabled_count": 4}, {"category": "alignment", "count": 3, "enabled_count": 2}]
STUDIES = {"studies": [{"name": "s1", "abstract_count": 100}, {"name": "s2", "abstract_count": 28}]}
RUNS = [
    {"id": "r1", "state": "RUNNING"}, {"id": "r2", "state": "RUNNING"},
    {"id": "r3", "state": "QUEUED"}, {"id": "r4", "state": "FAILED"}, {"id": "r5", "state": "COMPLETED"},
]


class TestIdentitySection(unittest.TestCase):
    """The dashboard's identity section: aggregation from auth's orgs/users/roles endpoints."""

    def test_populates_from_platform_orgs_users_roles(self) -> None:
        """organizations/users/teams/roles are correctly extracted from their respective upstream responses, with active_sessions left null (no upstream concept)."""
        routes = {
            "/platform/orgs": _resp(200, ORGS_PAGE),
            "/platform/users": _resp(200, USERS_PAGE),
            "/platform/roles": _resp(200, ROLES),
        }
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        identity = resp.json()["identity"]
        self.assertEqual(identity["organizations"], 12)
        self.assertEqual(identity["users"], 246)
        self.assertEqual(identity["teams"], 8)  # 3 + 5
        self.assertEqual(identity["roles"], 2)
        self.assertIsNone(identity["active_sessions"])

    def test_missing_authorization_never_fabricates_identity(self) -> None:
        """With no Authorization header, every identity field is null rather than a fabricated value."""
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})):
            resp = client.get("/dashboard/summary")
        identity = resp.json()["identity"]
        self.assertEqual(identity, {
            "organizations": None, "users": None, "teams": None, "roles": None, "active_sessions": None,
        })

    def test_upstream_unreachable_degrades_to_null_without_failing_request(self) -> None:
        """A connection failure to auth-service degrades only the identity section to null, not the whole request."""
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["identity"]["organizations"])


class TestAiPlatformSection(unittest.TestCase):
    """The dashboard's ai_platform section: model-registry model counting and LLM
    provider counting."""
    def test_dedupes_versions_into_distinct_models_and_counts_active(self) -> None:
        """Three model-registry rows collapse to 2 distinct (task, model_name) models,
        only the model with a staging or production version counts as active, and
        embedding_models stays null."""
        routes = {"/v1/models": _resp(200, MODELS)}
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary")
        ai = resp.json()["ai_platform"]
        # 3 rows -> 2 distinct (task, model_name) pairs
        self.assertEqual(ai["registered_models"], 2)
        # scanvi has a staging+production version -> active; deepvar's only version is "none" -> not active
        self.assertEqual(ai["active_models"], 1)
        self.assertIsNone(ai["embedding_models"])

    def test_no_auth_header_required_for_model_registry(self) -> None:
        """model-registry's GET /v1/models has no auth in its own source
        -- this section must work even for an anonymous dashboard call."""
        routes = {"/v1/models": _resp(200, [])}
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary")
        self.assertEqual(resp.json()["ai_platform"]["registered_models"], 0)

    def test_llm_providers_counts_configured_keys_plus_running_ollama(self) -> None:
        """llm_providers counts each configured API key plus one for a running Ollama,
        so one configured key and a running Ollama give 2; get_llms is stubbed."""
        from fastapi.responses import JSONResponse

        fake_llms = JSONResponse({
            "ollama": {"status": "running", "url": "http://ollama:11434", "models": []},
            "api_keys": {"anthropic": {"configured": True}, "openai": {"configured": False}},
        })
        with (
            patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})),
            patch("control_center.api.routes_dashboard.get_llms", new=AsyncMock(return_value=fake_llms)),
        ):
            resp = client.get("/dashboard/summary")
        # 1 configured key (anthropic) + 1 for running ollama
        self.assertEqual(resp.json()["ai_platform"]["llm_providers"], 2)


class TestKnowledgeSection(unittest.TestCase):
    """The dashboard's knowledge section: RAG collection and document counts from
    /v1/studies, null when RAG is not configured or its response is malformed."""
    def test_null_when_ragbio_api_key_not_configured(self) -> None:
        """With RAGBIO_API_KEY unset, rag_collections is null even though /v1/studies
        would return studies."""
        with patch("control_center.api.routes_dashboard.RAGBIO_API_KEY", ""):
            with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({"/v1/studies": _resp(200, STUDIES)})):
                resp = client.get("/dashboard/summary")
        knowledge = resp.json()["knowledge"]
        self.assertIsNone(knowledge["rag_collections"])

    def test_malformed_upstream_response_yields_null_not_a_crash(self) -> None:
        """An unexpected /v1/studies response shape yields null rag_collections and
        indexed_documents instead of a crash."""
        with patch("control_center.api.routes_dashboard.RAGBIO_API_KEY", "test-key"):
            with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({"/v1/studies": _resp(200, {"detail": "unexpected shape"})})):
                resp = client.get("/dashboard/summary")
        knowledge = resp.json()["knowledge"]
        self.assertIsNone(knowledge["rag_collections"])
        self.assertIsNone(knowledge["indexed_documents"])

    def test_sums_abstract_counts_when_configured(self) -> None:
        """With the API key configured, rag_collections is 2 and indexed_documents is
        128 (the summed abstract counts), with indexed_publications and knowledge_bases
        mirroring the same figures."""
        with patch("control_center.api.routes_dashboard.RAGBIO_API_KEY", "test-key"):
            with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({"/v1/studies": _resp(200, STUDIES)})):
                resp = client.get("/dashboard/summary")
        knowledge = resp.json()["knowledge"]
        self.assertEqual(knowledge["rag_collections"], 2)
        self.assertEqual(knowledge["indexed_documents"], 128)
        # Same underlying figures under two names -- documented, not a bug.
        self.assertEqual(knowledge["indexed_publications"], 128)
        self.assertEqual(knowledge["knowledge_bases"], 2)


class TestWorkflowSection(unittest.TestCase):
    """The dashboard's workflow section: bundle counts from /v1/categories and job
    counts by state from /api/runs."""
    def test_bundle_count_sums_categories(self) -> None:
        """workflow_bundles sums the category counts (4 + 3 = 7)."""
        routes = {"/v1/categories": _resp(200, CATEGORIES)}
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary")
        self.assertEqual(resp.json()["workflow"]["workflow_bundles"], 7)  # 4 + 3

    def test_job_counts_filtered_by_state_and_require_authorization(self) -> None:
        """With an Authorization header, running, queued and failed job counts are taken
        from /api/runs by state (2, 1 and 1)."""
        routes = {"/v1/categories": _resp(200, []), "/api/runs": _resp(200, RUNS)}
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        wf = resp.json()["workflow"]
        self.assertEqual(wf["running_jobs"], 2)
        self.assertEqual(wf["queued_jobs"], 1)
        self.assertEqual(wf["failed_jobs"], 1)

    def test_job_counts_null_without_authorization(self) -> None:
        """Without an Authorization header, running, queued and failed job counts are
        all null."""
        routes = {"/v1/categories": _resp(200, []), "/api/runs": _resp(200, RUNS)}
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary")
        wf = resp.json()["workflow"]
        self.assertIsNone(wf["running_jobs"])
        self.assertIsNone(wf["queued_jobs"])
        self.assertIsNone(wf["failed_jobs"])


class TestInfrastructureAndOperationsSection(unittest.TestCase):
    """The dashboard's infrastructure and operations sections, which are populated only
    for callers holding platform.manage_infra and are null otherwise."""
    def test_included_when_caller_has_platform_manage_infra(self) -> None:
        """A caller holding platform.manage_infra gets populated infrastructure
        (containers, healthy services, GPU utilization, storage used) and operations
        (health UP, one open alert) sections, with cpu_pct and uptime left null; all
        in-process collectors are stubbed."""
        with (
            patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})),
            patch("control_center.api.routes_dashboard.verify_token", return_value={"permissions": ["platform.manage_infra"]}),
            patch("control_center.api.routes_dashboard.get_containers_status", return_value={"running": 9, "stopped": 1}),
            patch("control_center.api.routes_dashboard.load_settings", return_value=object()),
            patch("control_center.api.routes_dashboard.run_all_checks", return_value=[{"status": "UP"}, {"status": "UP"}]),
            patch("control_center.api.routes_dashboard.run_disk_checks", return_value=[]),
            patch("control_center.api.routes_dashboard.get_gpu_status", return_value={"reachable": True, "utilization_pct": 68.0}),
            patch(
                "control_center.api.routes_dashboard._compute_storage",
                return_value={"disk": {"total": 1000, "used": 400, "free": 600, "pct_used": 40.0}, "categories": {}, "reference_indexes": {}, "work_breakdown": {}, "docker_raw": ""},
            ),
            patch("control_center.api.routes_dashboard.list_known_issues", return_value=[{"status": "open"}, {"status": "resolved"}]),
        ):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        infra = resp.json()["infrastructure"]
        ops = resp.json()["operations"]
        self.assertEqual(infra["containers_running"], 9)
        self.assertEqual(infra["services_healthy"], 2)
        self.assertEqual(infra["gpu_utilization_pct"], 68.0)
        self.assertEqual(infra["storage_used_bytes"], 400)
        self.assertIsNone(infra["cpu_pct"])
        self.assertEqual(ops["health"], "UP")
        self.assertEqual(ops["alerts"], 1)
        self.assertIsNone(ops["uptime"])

    def test_null_without_platform_manage_infra_and_upstream_not_called(self) -> None:
        """A token lacking platform.manage_infra gets every infrastructure and
        operations field null, and get_containers_status is never called."""
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})):
            with patch("control_center.api.routes_dashboard.verify_token", return_value={"permissions": []}):
                with patch("control_center.api.routes_dashboard.get_containers_status") as mock_containers:
                    resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        mock_containers.assert_not_called()
        infra = resp.json()["infrastructure"]
        ops = resp.json()["operations"]
        self.assertTrue(all(v is None for v in infra.values()))
        self.assertTrue(all(v is None for v in ops.values()))

    def test_health_reflects_worst_service_status(self) -> None:
        """operations.health is the worst service status: WARN for [UP, WARN] and DOWN
        for [UP, DOWN, WARN]."""
        for statuses, expected in [
            (["UP", "WARN"], "WARN"),
            (["UP", "DOWN", "WARN"], "DOWN"),
        ]:
            with (
                patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})),
                patch("control_center.api.routes_dashboard.verify_token", return_value={"permissions": ["platform.manage_infra"]}),
                patch("control_center.api.routes_dashboard.get_containers_status", return_value={"running": 0, "stopped": 0}),
                patch("control_center.api.routes_dashboard.load_settings", return_value=object()),
                patch("control_center.api.routes_dashboard.run_all_checks", return_value=[{"status": s} for s in statuses]),
                patch("control_center.api.routes_dashboard.run_disk_checks", return_value=[]),
                patch("control_center.api.routes_dashboard.get_gpu_status", return_value={"reachable": False}),
                patch(
                    "control_center.api.routes_dashboard._compute_storage",
                    return_value={"disk": {"total": 0, "used": 0, "free": 0, "pct_used": 0}, "categories": {}, "reference_indexes": {}, "work_breakdown": {}, "docker_raw": ""},
                ),
                patch("control_center.api.routes_dashboard.list_known_issues", return_value=[]),
            ):
                resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
            self.assertEqual(resp.json()["operations"]["health"], expected)

    def test_load_settings_failure_yields_zero_services_not_a_500(self) -> None:
        """When load_settings raises FileNotFoundError the request still returns 200,
        with services_total 0 and operations.health UP."""
        with (
            patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})),
            patch("control_center.api.routes_dashboard.verify_token", return_value={"permissions": ["platform.manage_infra"]}),
            patch("control_center.api.routes_dashboard.get_containers_status", return_value={"running": 0, "stopped": 0}),
            patch("control_center.api.routes_dashboard.load_settings", side_effect=FileNotFoundError("no config")),
            patch("control_center.api.routes_dashboard.get_gpu_status", return_value={"reachable": False}),
            patch(
                "control_center.api.routes_dashboard._compute_storage",
                return_value={"disk": {"total": 0, "used": 0, "free": 0, "pct_used": 0}, "categories": {}, "reference_indexes": {}, "work_breakdown": {}, "docker_raw": ""},
            ),
            patch("control_center.api.routes_dashboard.list_known_issues", return_value=[]),
        ):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["infrastructure"]["services_total"], 0)
        self.assertEqual(resp.json()["operations"]["health"], "UP")

    def test_known_issues_read_failure_yields_null_alerts_not_a_500(self) -> None:
        """When list_known_issues raises, the request still returns 200 with
        operations.alerts null."""
        with (
            patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})),
            patch("control_center.api.routes_dashboard.verify_token", return_value={"permissions": ["platform.manage_infra"]}),
            patch("control_center.api.routes_dashboard.get_containers_status", return_value={"running": 0, "stopped": 0}),
            patch("control_center.api.routes_dashboard.load_settings", return_value=object()),
            patch("control_center.api.routes_dashboard.run_all_checks", return_value=[]),
            patch("control_center.api.routes_dashboard.run_disk_checks", return_value=[]),
            patch("control_center.api.routes_dashboard.get_gpu_status", return_value={"reachable": False}),
            patch(
                "control_center.api.routes_dashboard._compute_storage",
                return_value={"disk": {"total": 0, "used": 0, "free": 0, "pct_used": 0}, "categories": {}, "reference_indexes": {}, "work_breakdown": {}, "docker_raw": ""},
            ),
            patch("control_center.api.routes_dashboard.list_known_issues", side_effect=RuntimeError("boom")),
        ):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["operations"]["alerts"])

    def test_null_without_any_authorization_header(self) -> None:
        """With no Authorization header, containers_running is null and
        get_containers_status is never called."""
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})):
            with patch("control_center.api.routes_dashboard.get_containers_status") as mock_containers:
                resp = client.get("/dashboard/summary")
        mock_containers.assert_not_called()
        self.assertIsNone(resp.json()["infrastructure"]["containers_running"])


MY_ORGS = [{"id": 7, "slug": "acme", "name": "Acme Corp", "plan": "beta", "status": "active"}]
SUBSCRIPTION = {
    "organization_id": 7, "billing_plan_id": 1, "plan_name": "Enterprise", "billing_interval": "monthly",
    "currency": "usd", "status": "active", "start_date": "2026-01-01", "end_date": None,
    "renewal_date": "2026-02-01", "features": [],
}
USAGE = {
    "organization_id": 7, "period_start": "2026-08-01", "period_end": "2026-08-31",
    "services": [
        {"service": "tes", "action": "run", "resource": "compute_minutes", "unit": "minutes", "quantity": "120.0"},
        {"service": "rag", "action": "query", "resource": "queries", "unit": "count", "quantity": "40"},
    ],
}
_BUSINESS_NULL = {
    "organization_id": None, "organization_name": None, "plan_name": None,
    "subscription_status": None, "usage_services_count": None, "billing_service_available": None,
}


class TestBusinessSection(unittest.TestCase):
    """The dashboard's business section: the caller's own organization, subscription
    plan and usage from the orgs, subscription and usage endpoints."""
    def test_populates_plan_and_subscription_for_callers_own_org(self) -> None:
        """For the caller's own org, the business section reports the organization id
        and name, plan name, subscription status, a usage service count of 2 and
        billing_service_available true."""
        routes = {
            "/orgs": _resp(200, MY_ORGS),
            "/subscription": _resp(200, SUBSCRIPTION),
            "/usage": _resp(200, USAGE),
        }
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        business = resp.json()["business"]
        self.assertEqual(business["organization_id"], 7)
        self.assertEqual(business["organization_name"], "Acme Corp")
        self.assertEqual(business["plan_name"], "Enterprise")
        self.assertEqual(business["subscription_status"], "active")
        self.assertEqual(business["usage_services_count"], 2)
        self.assertTrue(business["billing_service_available"])

    def test_missing_authorization_never_fabricates_business(self) -> None:
        """With no Authorization header, the business section equals the all-null shape."""
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})):
            resp = client.get("/dashboard/summary")
        self.assertEqual(resp.json()["business"], _BUSINESS_NULL)

    def test_no_organization_membership_returns_all_null(self) -> None:
        """A caller who belongs to no organization gets the all-null business section."""
        routes = {"/orgs": _resp(200, [])}
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.json()["business"], _BUSINESS_NULL)

    def test_no_active_subscription_distinguishes_from_billing_service_down(self) -> None:
        """A 404 for the subscription (no active subscription) leaves plan_name and
        subscription_status null but billing_service_available true and usage still
        populated, which differs from the billing service being down."""
        # 404 (no subscription for this org) is NOT the same as the
        # billing service being unreachable -- both must not collapse
        # into the same "billing_service_available: null" the generic
        # _get_json() helper would otherwise produce.
        routes = {
            "/orgs": _resp(200, MY_ORGS),
            "/subscription": _resp(404, {"detail": "organization_id=7 has no active subscription"}),
            "/usage": _resp(200, USAGE),
        }
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        business = resp.json()["business"]
        self.assertIsNone(business["plan_name"])
        self.assertIsNone(business["subscription_status"])
        self.assertTrue(business["billing_service_available"])
        # Usage is independent of subscription -- still populated.
        self.assertEqual(business["usage_services_count"], 2)

    def test_billing_service_unreachable_sets_available_false(self) -> None:
        """A connection error on the subscription endpoint sets
        billing_service_available to false and plan_name to null."""
        async def _get(url, headers=None, params=None, timeout=None):
            if "/orgs" in url:
                return _resp(200, MY_ORGS)
            if "/subscription" in url:
                raise httpx.ConnectError("refused")
            return _resp(404, {})

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=_get)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        business = resp.json()["business"]
        self.assertFalse(business["billing_service_available"])
        self.assertIsNone(business["plan_name"])

    def test_usage_failure_does_not_block_subscription_data(self) -> None:
        """A 503 from the usage endpoint leaves usage_services_count null while the
        subscription's plan_name is still populated."""
        # Partial-failure case: usage endpoint down/404, subscription
        # still succeeds -- each upstream degrades independently, same
        # convention every other section in this file already follows.
        routes = {
            "/orgs": _resp(200, MY_ORGS),
            "/subscription": _resp(200, SUBSCRIPTION),
            "/usage": _resp(503, {"error": "unavailable"}),
        }
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        business = resp.json()["business"]
        self.assertEqual(business["plan_name"], "Enterprise")
        self.assertIsNone(business["usage_services_count"])


class TestPublicFieldsContract(unittest.TestCase):
    """Regression guard for routes_dashboard.PUBLIC_FIELDS: proves a fully
    anonymous caller (no Authorization header) never sees a non-null field
    in ai_platform/knowledge/workflow that isn't explicitly allowlisted --
    even if a future edit adds a new field to one of those sections'
    computation and forgets to update PUBLIC_FIELDS to match. Every
    currently-known field is populated with a real, non-null value via the
    same mock fixtures the section-specific tests above use, so the only
    way this test can fail is an *unlisted* field coming back non-null."""

    def _anonymous_response(self) -> dict:
        routes = {
            "/v1/models": _resp(200, MODELS),
            "/v1/categories": _resp(200, CATEGORIES),
            "/v1/studies": _resp(200, STUDIES),
        }
        with patch("control_center.api.routes_dashboard.RAGBIO_API_KEY", "test-key"):
            with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
                resp = client.get("/dashboard/summary")  # deliberately no Authorization header
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_no_unlisted_field_is_non_null_for_anonymous_caller(self) -> None:
        """For an anonymous caller, no ai_platform, knowledge or workflow field outside
        PUBLIC_FIELDS comes back non-null."""
        from control_center.api import routes_dashboard as rd

        body = self._anonymous_response()
        for section_name, allowed in rd.PUBLIC_FIELDS.items():
            section = body[section_name]
            leaked = sorted(k for k, v in section.items() if v is not None and k not in allowed)
            self.assertEqual(
                leaked, [],
                f"{section_name!r} returned ungated field(s) to an anonymous caller: {leaked} "
                f"-- add them to PUBLIC_FIELDS deliberately (routes_dashboard.py) if they're "
                f"meant to be public, or gate their computation on `authorization` if not.",
            )

    def test_allowlisted_fields_are_still_populated_anonymously(self) -> None:
        """Every field listed in PUBLIC_FIELDS, except the always-null embedding_models,
        is non-null for an anonymous caller when all upstreams are reachable, so the
        allowlist is not stale."""
        # The inverse check: PUBLIC_FIELDS isn't accidentally stale either
        # -- every field it claims is public actually comes back non-null
        # for an anonymous caller under these fixtures (all upstreams
        # reachable, all with real data), not silently gated by some other
        # code path.
        from control_center.api import routes_dashboard as rd

        body = self._anonymous_response()
        for section_name, allowed in rd.PUBLIC_FIELDS.items():
            section = body[section_name]
            for field in allowed:
                if field == "embedding_models":
                    continue  # always null -- no upstream concept exists (see _ai_platform_section)
                self.assertIsNotNone(
                    section[field],
                    f"{section_name}.{field} is listed in PUBLIC_FIELDS but came back null for an "
                    f"anonymous caller under fully-reachable-upstream fixtures",
                )


class TestResponseShape(unittest.TestCase):
    """The top-level shape of the /dashboard/summary response."""
    def test_top_level_keys_and_generated_at(self) -> None:
        """The response has exactly the keys generated_at, identity, ai_platform,
        knowledge, workflow, infrastructure, operations and business, and generated_at
        is non-empty."""
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})):
            resp = client.get("/dashboard/summary")
        body = resp.json()
        self.assertEqual(
            set(body.keys()),
            {"generated_at", "identity", "ai_platform", "knowledge", "workflow", "infrastructure", "operations", "business"},
        )
        self.assertTrue(body["generated_at"])


if __name__ == "__main__":
    unittest.main()
