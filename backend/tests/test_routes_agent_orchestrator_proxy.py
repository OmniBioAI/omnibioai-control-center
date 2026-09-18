"""
tests/test_routes_agent_orchestrator_proxy.py

Unit tests for:
  - control_center.api.routes_agent_orchestrator_proxy
    (GET /agent-orchestrator/graphs)

Mirrors test_routes_tes_proxy.py's / test_routes_model_registry_proxy.py's
exact conventions -- this route is a thin relay, no authorization decision
is made here (GET /api/agent/graphs/ has no auth requirement upstream at
all, confirmed by reading omnibioai-workbench's
services/agent_orchestrator/views.py directly).

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


def _mock_response(status_code: int, json_body=None, raise_json_error: bool = False) -> MagicMock:
    """A MagicMock httpx.Response stand-in; raise_json_error makes
    .json() raise ValueError instead of returning json_body."""
    resp = MagicMock()
    resp.status_code = status_code
    if raise_json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    return resp


def _mock_async_client(response: MagicMock | None = None, side_effect=None):
    """An async-context-manager mock of httpx.AsyncClient whose .get()
    returns `response`, or raises `side_effect` if given."""
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


_GRAPHS_OUT = {
    "graphs": [
        {
            "graph_id": "de_analysis",
            "display_name": "Differential Expression",
            "description": "DE: quant -> DESeq2 -> volcano -> summary",
            "version": "0.1.0",
            "enabled": True,
            "inputs_schema": {},
            "dag": {"nodes": [{"id": "counts", "label": "Counts/Matrix"}], "edges": []},
        },
    ],
}


class TestListAgentGraphsProxy(unittest.TestCase):
    """GET /agent-orchestrator/graphs's thin-relay behavior: success
    passthrough, optional auth forwarding, the real upstream path, and
    fail-safe error mapping."""

    def test_forwards_success_response(self) -> None:
        """A successful upstream response's status and body are relayed
        unchanged."""
        upstream = _mock_response(200, _GRAPHS_OUT)
        with patch("control_center.api.routes_agent_orchestrator_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/agent-orchestrator/graphs")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _GRAPHS_OUT)

    def test_works_without_authorization_header(self) -> None:
        """No Authorization header on the inbound request means none is
        forwarded upstream -- and the call still succeeds, since GET
        /api/agent/graphs/ is unauthenticated upstream."""
        # GET /api/agent/graphs/ is unauthenticated upstream -- no
        # Authorization header should still be forwarded successfully
        # (nothing to forward, not an error).
        upstream = _mock_response(200, _GRAPHS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_agent_orchestrator_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/agent-orchestrator/graphs")
        self.assertEqual(resp.status_code, 200)
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertNotIn("Authorization", call_kwargs["headers"])

    def test_forwards_authorization_header_when_present(self) -> None:
        """An inbound Authorization header is forwarded to the upstream
        call unchanged."""
        upstream = _mock_response(200, _GRAPHS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_agent_orchestrator_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/agent-orchestrator/graphs", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_requests_the_real_upstream_path(self) -> None:
        """The proxy requests the real workbench URL path
        /api/agent/graphs/."""
        upstream = _mock_response(200, _GRAPHS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_agent_orchestrator_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/agent-orchestrator/graphs")
        call_args = mock_ctx.__aenter__.return_value.get.call_args
        self.assertTrue(call_args.args[0].endswith("/api/agent/graphs/"))

    def test_workbench_unreachable_returns_503(self) -> None:
        """A connection failure to workbench returns 503 with an
        error message naming "workbench-service unreachable"."""
        with patch(
            "control_center.api.routes_agent_orchestrator_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/agent-orchestrator/graphs")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("workbench-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        """A non-JSON upstream response body maps to a 500 error naming
        "non-JSON" rather than propagating the parse exception."""
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_agent_orchestrator_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/agent-orchestrator/graphs")
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


if __name__ == "__main__":
    unittest.main()
