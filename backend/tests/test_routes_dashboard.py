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
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from control_center.main import app

client = TestClient(app)


def _resp(status_code: int, json_body=None) -> MagicMock:
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
    def test_populates_from_platform_orgs_users_roles(self) -> None:
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
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})):
            resp = client.get("/dashboard/summary")
        identity = resp.json()["identity"]
        self.assertEqual(identity, {
            "organizations": None, "users": None, "teams": None, "roles": None, "active_sessions": None,
        })

    def test_upstream_unreachable_degrades_to_null_without_failing_request(self) -> None:
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
    def test_dedupes_versions_into_distinct_models_and_counts_active(self) -> None:
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
    def test_null_when_ragbio_api_key_not_configured(self) -> None:
        with patch("control_center.api.routes_dashboard.RAGBIO_API_KEY", ""):
            with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({"/v1/studies": _resp(200, STUDIES)})):
                resp = client.get("/dashboard/summary")
        knowledge = resp.json()["knowledge"]
        self.assertIsNone(knowledge["rag_collections"])

    def test_malformed_upstream_response_yields_null_not_a_crash(self) -> None:
        with patch("control_center.api.routes_dashboard.RAGBIO_API_KEY", "test-key"):
            with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({"/v1/studies": _resp(200, {"detail": "unexpected shape"})})):
                resp = client.get("/dashboard/summary")
        knowledge = resp.json()["knowledge"]
        self.assertIsNone(knowledge["rag_collections"])
        self.assertIsNone(knowledge["indexed_documents"])

    def test_sums_abstract_counts_when_configured(self) -> None:
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
    def test_bundle_count_sums_categories(self) -> None:
        routes = {"/v1/categories": _resp(200, CATEGORIES)}
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary")
        self.assertEqual(resp.json()["workflow"]["workflow_bundles"], 7)  # 4 + 3

    def test_job_counts_filtered_by_state_and_require_authorization(self) -> None:
        routes = {"/v1/categories": _resp(200, []), "/api/runs": _resp(200, RUNS)}
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        wf = resp.json()["workflow"]
        self.assertEqual(wf["running_jobs"], 2)
        self.assertEqual(wf["queued_jobs"], 1)
        self.assertEqual(wf["failed_jobs"], 1)

    def test_job_counts_null_without_authorization(self) -> None:
        routes = {"/v1/categories": _resp(200, []), "/api/runs": _resp(200, RUNS)}
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client(routes)):
            resp = client.get("/dashboard/summary")
        wf = resp.json()["workflow"]
        self.assertIsNone(wf["running_jobs"])
        self.assertIsNone(wf["queued_jobs"])
        self.assertIsNone(wf["failed_jobs"])


class TestInfrastructureAndOperationsSection(unittest.TestCase):
    def test_included_when_caller_has_platform_manage_infra(self) -> None:
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
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})):
            with patch("control_center.api.routes_dashboard.get_containers_status") as mock_containers:
                resp = client.get("/dashboard/summary")
        mock_containers.assert_not_called()
        self.assertIsNone(resp.json()["infrastructure"]["containers_running"])


class TestBusinessSection(unittest.TestCase):
    def test_always_placeholder(self) -> None:
        with patch("control_center.api.routes_dashboard.httpx.AsyncClient", return_value=_mock_client({})):
            resp = client.get("/dashboard/summary", headers={"Authorization": "Bearer tok"})
        business = resp.json()["business"]
        self.assertEqual(business, {"organizations": None, "subscription": None, "billing": None, "credits": None})


class TestResponseShape(unittest.TestCase):
    def test_top_level_keys_and_generated_at(self) -> None:
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
