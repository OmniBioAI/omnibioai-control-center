"""
tests/test_routes_auth_proxy.py

Unit tests for:
  - control_center.api.routes_auth_proxy  (POST /auth/login, /auth/validate)
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
    mock_post = AsyncMock()
    if side_effect is not None:
        mock_post.side_effect = side_effect
    else:
        mock_post.return_value = response
    mock_client.post = mock_post

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


class TestAuthLoginProxy(unittest.TestCase):

    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, {"access_token": "tok", "refresh_token": "rtok", "token_type": "bearer"})
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/login", json={"email": "a@b.com", "password": "x"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["access_token"], "tok")

    def test_forwards_upstream_error_status(self) -> None:
        upstream = _mock_response(401, {"detail": "Invalid credentials"})
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/login", json={"email": "a@b.com", "password": "wrong"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["detail"], "Invalid credentials")

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_auth_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.post("/auth/login", json={"email": "a@b.com", "password": "x"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/login", json={"email": "a@b.com", "password": "x"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])

    def test_forwards_request_body_unchanged(self) -> None:
        upstream = _mock_response(200, {"access_token": "tok"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.post("/auth/login", json={"email": "someone@x.com", "password": "secret"})
        call_kwargs = mock_ctx.__aenter__.return_value.post.call_args.kwargs
        self.assertIn(b'"someone@x.com"', call_kwargs["content"])


class TestAuthValidateProxy(unittest.TestCase):

    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, {"valid": True, "user_id": 1, "roles": ["admin"], "permissions": ["manage_roles"]})
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/validate", json={"token": "sometoken"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["roles"], ["admin"])

    def test_invalid_token_forwarded(self) -> None:
        upstream = _mock_response(200, {"valid": False})
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/validate", json={"token": "garbage"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["valid"])

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_auth_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.post("/auth/validate", json={"token": "x"})
        self.assertEqual(resp.status_code, 503)


class TestIamUrlDefault(unittest.TestCase):

    def test_default_matches_ecosystem_convention(self) -> None:
        from control_center.api import routes_auth_proxy
        with patch.dict("os.environ", {}, clear=True):
            import importlib
            importlib.reload(routes_auth_proxy)
            self.assertEqual(routes_auth_proxy.IAM_URL, "http://auth-service:8001")
        importlib.reload(routes_auth_proxy)


if __name__ == "__main__":
    unittest.main()
