"""
tests/test_routes_tes_proxy.py

Unit tests for:
  - control_center.api.routes_tes_proxy
    (GET /tes/tools, GET /tes/tools/capabilities, GET /tes/runs,
    GET /tes/runs/{run_id})

Mirrors test_routes_billing_proxy.py's exact conventions -- these routes
are a thin relay, no authorization decision is made here (that's
entirely omnibioai-tes's own job, via require_permission(WORKFLOW_EXECUTE)
for /runs, unauthenticated for /tools per api/routes_tools.py). All four
routes are GET-only.
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


_TOOLS_OUT = [{"tool_id": "fastqc", "name": "FastQC"}]
_CAPABILITIES_OUT = [{"tool_id": "fastqc", "backends": ["http", "slurm"]}]
_RUNS_OUT = [{"run_id": "r-1", "tool_id": "fastqc", "state": "RUNNING", "organization_id": 7}]
_RUN_DETAIL_OUT = {"run_id": "r-1", "tool_id": "fastqc", "state": "RUNNING", "organization_id": 7}


class TestListToolsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _TOOLS_OUT)
        with patch("control_center.api.routes_tes_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/tes/tools")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _TOOLS_OUT)

    def test_works_without_authorization_header(self) -> None:
        # /api/tools is unauthenticated upstream -- no Authorization
        # header should still be forwarded successfully (nothing to
        # forward, not an error).
        upstream = _mock_response(200, _TOOLS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_tes_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/tes/tools")
        self.assertEqual(resp.status_code, 200)
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertNotIn("Authorization", call_kwargs["headers"])

    def test_tes_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_tes_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/tes/tools")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("tes-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_tes_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/tes/tools")
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestToolsCapabilitiesProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _CAPABILITIES_OUT)
        with patch("control_center.api.routes_tes_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/tes/tools/capabilities")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _CAPABILITIES_OUT)


class TestListRunsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _RUNS_OUT)
        with patch("control_center.api.routes_tes_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/tes/runs", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _RUNS_OUT)

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, _RUNS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_tes_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/tes/runs", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_401_for_missing_permission(self) -> None:
        upstream = _mock_response(401, {"detail": "Not authenticated"})
        with patch("control_center.api.routes_tes_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/tes/runs")
        self.assertEqual(resp.status_code, 401)

    def test_forwards_403_for_missing_workflow_execute_permission(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_tes_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/tes/runs", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_tes_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_tes_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/tes/runs", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)


class TestGetRunProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _RUN_DETAIL_OUT)
        with patch("control_center.api.routes_tes_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/tes/runs/r-1", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["run_id"], "r-1")

    def test_forwards_run_id_in_path(self) -> None:
        upstream = _mock_response(200, _RUN_DETAIL_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_tes_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/tes/runs/r-42", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.get.call_args
        self.assertTrue(call_args.args[0].endswith("/api/runs/r-42"))

    def test_forwards_404_for_run_in_different_org(self) -> None:
        # TES treats a wrong-org run identically to "not found" (_require_
        # same_org raises KeyError -> 404), deliberately not a 403, to
        # avoid an enumeration oracle -- this proxy just relays that.
        upstream = _mock_response(404, {"detail": "run not found: r-1"})
        with patch("control_center.api.routes_tes_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/tes/runs/r-1", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
