"""
tests/test_routes_model_registry_proxy.py

Unit tests for:
  - control_center.api.routes_model_registry_proxy
    (GET /model-registry/models, GET /model-registry/health,
    GET /model-registry/auth-status)

Mirrors test_routes_tes_proxy.py's exact conventions -- these routes are
a thin relay, no authorization decision is made here. Unlike TES's
/runs endpoints, none of these three routes are gated at all on the
omnibioai-model-registry side today (confirmed by reading
service/app/main.py directly -- no Depends(require_auth) on list_models,
health, or api_auth_status), so there is no "wrong permission" case to
cover here the way test_routes_tes_proxy.py's TestListRunsProxy has --
only success / auth-forwarding / upstream-failure / invalid-response /
status-propagation, per this PR's own scope.

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


_MODELS_OUT = [
    {"task": "classification", "model_name": "tissue-classifier", "version": "1.0.0", "created_at": "2026-07-01T00:00:00", "stage": "production"},
    {"task": "classification", "model_name": "tissue-classifier", "version": "1.1.0", "created_at": "2026-08-01T00:00:00"},
]
_HEALTH_OUT = {"ok": True, "service": "omnibioai-model-registry", "version": "1.4.0"}
_AUTH_STATUS_OUT = {"auth_enabled": True, "mode": "jwt", "iam_url": "http://auth-service:8001"}


class TestListModelsProxy(unittest.TestCase):
    """GET /model-registry/models's thin-relay behavior: success
    passthrough, optional auth/query forwarding, and fail-safe error mapping."""

    def test_forwards_success_response(self) -> None:
        """A successful upstream response's body is relayed unchanged."""
        upstream = _mock_response(200, _MODELS_OUT)
        with patch("control_center.api.routes_model_registry_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/model-registry/models")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _MODELS_OUT)

    def test_forwards_authorization_header_when_present(self) -> None:
        """An inbound Authorization header is forwarded to the upstream
        call unchanged."""
        upstream = _mock_response(200, _MODELS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_model_registry_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/model-registry/models", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_works_without_authorization_header(self) -> None:
        """No inbound Authorization header still succeeds -- nothing is
        forwarded, since GET /v1/models is unauthenticated upstream today."""
        # GET /v1/models is unauthenticated upstream today -- no
        # Authorization header should still be forwarded successfully
        # (nothing to forward, not an error).
        upstream = _mock_response(200, _MODELS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_model_registry_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/model-registry/models")
        self.assertEqual(resp.status_code, 200)
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertNotIn("Authorization", call_kwargs["headers"])

    def test_forwards_task_and_model_name_query_params(self) -> None:
        """task/model_name query params are forwarded to the upstream call."""
        upstream = _mock_response(200, _MODELS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_model_registry_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/model-registry/models?task=classification&model_name=tissue-classifier")
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["params"]["task"], "classification")
        self.assertEqual(call_kwargs["params"]["model_name"], "tissue-classifier")

    def test_forwards_400_for_invalid_metric_gte(self) -> None:
        """An upstream 400 (e.g. invalid metric_gte format) is relayed as a 400."""
        upstream = _mock_response(400, {"ok": False, "error": "Invalid metric_gte format"})
        with patch("control_center.api.routes_model_registry_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/model-registry/models?metric_gte=bogus")
        self.assertEqual(resp.status_code, 400)

    def test_model_registry_service_unreachable_returns_503(self) -> None:
        """A connection failure to model-registry returns 503 with a
        "model-registry-service unreachable" message."""
        with patch(
            "control_center.api.routes_model_registry_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/model-registry/models")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("model-registry-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        """A non-JSON upstream response body maps to a 500 error naming
        "non-JSON" rather than propagating the parse exception."""
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_model_registry_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/model-registry/models")
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestHealthProxy(unittest.TestCase):
    """GET /model-registry/health's thin-relay behavior."""

    def test_forwards_success_response(self) -> None:
        """A successful upstream health response's body is relayed unchanged."""
        upstream = _mock_response(200, _HEALTH_OUT)
        with patch("control_center.api.routes_model_registry_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/model-registry/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _HEALTH_OUT)

    def test_model_registry_service_unreachable_returns_503(self) -> None:
        """A connection failure to model-registry returns 503."""
        with patch(
            "control_center.api.routes_model_registry_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/model-registry/health")
        self.assertEqual(resp.status_code, 503)


class TestAuthStatusProxy(unittest.TestCase):
    """GET /model-registry/auth-status's thin-relay behavior."""

    def test_forwards_success_response(self) -> None:
        """A successful upstream auth-status response's body is relayed unchanged."""
        upstream = _mock_response(200, _AUTH_STATUS_OUT)
        with patch("control_center.api.routes_model_registry_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/model-registry/auth-status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["mode"], "jwt")

    def test_non_json_upstream_response_handled(self) -> None:
        """A non-JSON upstream response body maps to the same status
        code with a "non-JSON" error message."""
        upstream = _mock_response(502, raise_json_error=True)
        with patch("control_center.api.routes_model_registry_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/model-registry/auth-status")
        self.assertEqual(resp.status_code, 502)
        self.assertIn("non-JSON", resp.json()["error"])


if __name__ == "__main__":
    unittest.main()
