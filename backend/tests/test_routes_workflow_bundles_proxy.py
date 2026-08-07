"""
tests/test_routes_workflow_bundles_proxy.py

Unit tests for:
  - control_center.api.routes_workflow_bundles_proxy
    (GET /workflow-bundles/workflows, GET /workflow-bundles/workflows/{name},
    GET /workflow-bundles/categories, GET /workflow-bundles/workflows/{id}/inputs,
    GET /workflow-bundles/runs, GET /workflow-bundles/runs/{run_id})

Mirrors test_routes_tes_proxy.py's exact conventions -- these routes are
a thin relay, no authorization decision is made here (that's entirely
omnibioai-workflow-bundles' own job, via require_permission("workflow.read")
for the catalog routes and require_permission("workflow.execute") for
the two /runs routes -- both raise 401 for a missing/invalid token, 403
for a valid token missing the permission, confirmed by reading
api/iam.py directly).

The TestListRunsProxy class additionally asserts what this proxy
deliberately does NOT do: no organization filtering, no reshaping of
the upstream response. GET /v1/runs has no org-scoping upstream (its
own source comment states organization_id on each run is "logging/
audit context only -- not an access-control boundary," org isolation
for runs is a tracked upstream follow-up) -- this proxy is a
transparent forwarder, so a multi-org upstream payload must come back
through it completely unchanged, organization_id included, with no
control-center-side filtering added. Adding such filtering here would
itself violate this PR's own rule against duplicating/inventing
authorization logic outside the service that owns it.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from control_center.main import app

client = TestClient(app)


def _mock_response(status_code: int, json_body=None, raise_json_error: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if raise_json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    return resp


def _mock_async_client(response: MagicMock = None, side_effect=None):
    mock_client = MagicMock()
    mock_get = AsyncMock()
    if side_effect is not None:
        mock_get.side_effect = side_effect
    else:
        mock_get.return_value = response
    mock_client.get = mock_get

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


_WORKFLOWS_OUT = [
    {
        "id": 1, "category": "rnaseq", "engine": "nextflow", "name": "star-salmon",
        "display_name": "STAR + Salmon RNA-seq", "version": "1.0.0", "entrypoint": "main.nf",
        "configs": ["config/inputs.json"], "description": "Standard RNA-seq quantification pipeline",
        "inputs_schema": None, "outputs": None, "container_image": None,
        "object_id": "obj-1", "enabled": True, "created_by": "api", "created_at": "2026-07-01T00:00:00",
    },
]
_CATEGORIES_OUT = [{"category": "rnaseq", "count": 3, "enabled_count": 2}]
_INPUTS_OUT = {
    "inputs": {"reads": "s3://bucket/reads.fastq.gz"}, "engine": "nextflow",
    "container_image": "ghcr.io/omnibioai/runner:1.0.0", "entrypoint": "main.nf",
    "config_file": "config/inputs.json", "inputs_schema": None,
    "manifest": {"name": "star-salmon", "display_name": "STAR + Salmon RNA-seq", "version": "1.0.0", "category": "rnaseq"},
}
# Deliberately includes runs from two different organizations -- this is
# what a real upstream response looks like today, per GET /v1/runs'
# documented lack of org-scoping.
_RUNS_OUT = [
    {"run_id": "r-1", "workflow_id": 1, "workflow_name": "star-salmon", "status": "running", "engine": "nextflow", "requested_by": "u-1", "organization_id": 3, "started_at": "2026-08-05T10:00:00"},
    {"run_id": "r-2", "workflow_id": 2, "workflow_name": "other-pipeline", "status": "success", "engine": "nextflow", "requested_by": "u-9", "organization_id": 7, "started_at": "2026-08-05T09:00:00"},
]
_RUN_DETAIL_OUT = {"run_id": "r-1", "workflow_id": 1, "workflow_name": "star-salmon", "status": "running", "engine": "nextflow", "requested_by": "u-1", "organization_id": 3, "logs": ["line 1"]}


class TestListWorkflowsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _WORKFLOWS_OUT)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/workflows", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _WORKFLOWS_OUT)

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, _WORKFLOWS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/workflow-bundles/workflows", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_401_for_missing_token(self) -> None:
        upstream = _mock_response(401, {"detail": "Missing or malformed Authorization header"})
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/workflows")
        self.assertEqual(resp.status_code, 401)

    def test_forwards_403_for_missing_workflow_read_permission(self) -> None:
        upstream = _mock_response(403, {"detail": "Missing required permission: workflow.read"})
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/workflows", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_workflow_bundles_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/workflow-bundles/workflows", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("workflow-bundles-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/workflows", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestGetWorkflowVersionsProxy(unittest.TestCase):
    def test_forwards_name_in_path(self) -> None:
        upstream = _mock_response(200, _WORKFLOWS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/workflow-bundles/workflows/star-salmon", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.get.call_args
        self.assertTrue(call_args.args[0].endswith("/v1/workflows/star-salmon"))

    def test_forwards_404_for_unknown_workflow(self) -> None:
        upstream = _mock_response(404, {"detail": "No workflow named 'bogus'"})
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/workflows/bogus", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestListCategoriesProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _CATEGORIES_OUT)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/categories", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _CATEGORIES_OUT)


class TestGetWorkflowInputsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _INPUTS_OUT)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/workflows/1/inputs", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["manifest"]["name"], "star-salmon")

    def test_forwards_workflow_id_in_path(self) -> None:
        upstream = _mock_response(200, _INPUTS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/workflow-bundles/workflows/42/inputs", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.get.call_args
        self.assertTrue(call_args.args[0].endswith("/v1/workflows/42/inputs"))


class TestListRunsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _RUNS_OUT)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/runs", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _RUNS_OUT)

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, _RUNS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/workflow-bundles/runs", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_403_for_missing_workflow_execute_permission(self) -> None:
        upstream = _mock_response(403, {"detail": "Missing required permission: workflow.execute"})
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/runs", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_multi_organization_response_passes_through_unfiltered(self) -> None:
        # The key behavioral guarantee for this endpoint: this proxy does
        # NOT filter, group, or otherwise reshape the upstream payload by
        # organization_id -- a response spanning multiple orgs (as GET
        # /v1/runs genuinely can, per its own documented lack of
        # org-scoping) comes back through this proxy exactly as-is, same
        # length, same organization_id values, same order. Enforcing (or
        # even silently narrowing) that boundary here would be exactly
        # the kind of control-center-side authorization logic this PR is
        # explicitly forbidden from adding.
        upstream = _mock_response(200, _RUNS_OUT)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/runs", headers={"Authorization": "Bearer tok"})
        body = resp.json()
        self.assertEqual(len(body), 2)
        self.assertEqual({r["organization_id"] for r in body}, {3, 7})

    def test_workflow_bundles_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/workflow-bundles/runs", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)


class TestGetRunProxy(unittest.TestCase):
    def test_forwards_success_response_including_organization_id(self) -> None:
        # organization_id is rendered straight from the upstream response
        # -- not derived, computed, or checked against the caller's own
        # identity anywhere in this file.
        upstream = _mock_response(200, _RUN_DETAIL_OUT)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/runs/r-1", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["organization_id"], 3)

    def test_forwards_run_id_in_path(self) -> None:
        upstream = _mock_response(200, _RUN_DETAIL_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/workflow-bundles/runs/r-42", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.get.call_args
        self.assertTrue(call_args.args[0].endswith("/v1/runs/r-42"))

    def test_forwards_404_for_unknown_run(self) -> None:
        upstream = _mock_response(404, {"detail": "Run r-999 not found"})
        with patch("control_center.api.routes_workflow_bundles_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/workflow-bundles/runs/r-999", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
