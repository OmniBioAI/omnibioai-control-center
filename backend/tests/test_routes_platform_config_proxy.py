"""
tests/test_routes_platform_config_proxy.py

Unit tests for:
  - control_center.api.routes_platform_config_proxy (GET /auth/config)

Mirrors test_routes_org_proxy.py's/test_routes_billing_proxy.py's exact
conventions -- this route is a thin relay, no authorization decision is
made here (that's entirely omnibioai-auth's own job: GET /auth/config
itself requires no permission, just a valid token -- confirmed by
reading app/api/routes_config.py directly). Read-only (GET) only, per
this PR's own deliberate scope -- no PUT /auth/config route or test
here (see routes_platform_config_proxy.py's own module comment for why).
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


_CONFIG_OUT = {
    "llm_provider": "anthropic", "has_llm_api_key": True,
    "cloud_provider": "aws", "has_cloud_credentials": True,
    "work_directory": "/workspace/work", "data_directory": "/workspace/data",
    "updated_at": "2026-08-01T00:00:00", "updated_by_email": "admin@omnibioai.org",
}
_CONFIG_UNSET_OUT = {
    "llm_provider": None, "has_llm_api_key": False,
    "cloud_provider": None, "has_cloud_credentials": False,
    "work_directory": None, "data_directory": None,
    "updated_at": None, "updated_by_email": None,
}


class TestGetPlatformConfigProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _CONFIG_OUT)
        with patch("control_center.api.routes_platform_config_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/auth/config", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["llm_provider"], "anthropic")

    def test_never_echoes_a_credential_field_because_upstream_never_sends_one(self) -> None:
        # Not this proxy's job to strip credentials -- GlobalConfigOut
        # never includes them upstream in the first place. This test
        # documents that invariant against the exact fixture shape, so a
        # future change to this file that started passing through a
        # richer payload would be caught here.
        upstream = _mock_response(200, _CONFIG_OUT)
        with patch("control_center.api.routes_platform_config_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/auth/config", headers={"Authorization": "Bearer tok"})
        body = resp.json()
        self.assertNotIn("llm_api_key", body)
        self.assertNotIn("cloud_credentials", body)
        self.assertIn("has_llm_api_key", body)
        self.assertIn("has_cloud_credentials", body)

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, _CONFIG_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_platform_config_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/auth/config", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_works_when_no_config_has_ever_been_set(self) -> None:
        upstream = _mock_response(200, _CONFIG_UNSET_OUT)
        with patch("control_center.api.routes_platform_config_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/auth/config", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["llm_provider"])

    def test_forwards_401_for_missing_or_invalid_token(self) -> None:
        upstream = _mock_response(401, {"detail": "Not authenticated"})
        with patch("control_center.api.routes_platform_config_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/auth/config")
        self.assertEqual(resp.status_code, 401)

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_platform_config_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/auth/config", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_platform_config_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/auth/config", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


if __name__ == "__main__":
    unittest.main()
