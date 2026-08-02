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


def _mock_response(
    status_code: int,
    json_body=None,
    raise_json_error: bool = False,
    set_cookies: list[str] | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if raise_json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    resp.headers = MagicMock()
    resp.headers.get_list.return_value = set_cookies or []
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


class TestAuthRefreshProxy(unittest.TestCase):
    """SSO Phase 2 PR8: /auth/refresh -- PR7 confirmed this 404'd in
    production before this route existed."""

    def test_request_reaches_auth_service_at_correct_path(self) -> None:
        upstream = _mock_response(200, {"access_token": "new-tok", "refresh_token": "new-rtok"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.post("/auth/refresh", json={"refresh_token": "old-rtok"})
        call_args = mock_ctx.__aenter__.return_value.post.call_args
        self.assertEqual(call_args.args[0], "http://auth-service:8001/auth/refresh")

    def test_successful_response_returned(self) -> None:
        upstream = _mock_response(200, {"access_token": "new-tok", "refresh_token": "new-rtok"})
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/refresh", json={"refresh_token": "old-rtok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["access_token"], "new-tok")

    def test_failure_response_propagated(self) -> None:
        upstream = _mock_response(401, {"detail": "Invalid refresh token"})
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/refresh", json={"refresh_token": "expired"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["detail"], "Invalid refresh token")

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_auth_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.post("/auth/refresh", json={"refresh_token": "x"})
        self.assertEqual(resp.status_code, 503)

    def test_forwards_request_body_unchanged(self) -> None:
        upstream = _mock_response(200, {"access_token": "tok"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.post("/auth/refresh", json={"refresh_token": "exact-token-value"})
        call_kwargs = mock_ctx.__aenter__.return_value.post.call_args.kwargs
        self.assertIn(b'"exact-token-value"', call_kwargs["content"])


class TestAuthLogoutProxy(unittest.TestCase):
    """SSO Phase 2 PR8: /auth/logout -- PR7 confirmed this 404'd in
    production before this route existed."""

    def test_request_reaches_auth_service_at_correct_path(self) -> None:
        upstream = _mock_response(200, {"message": "Logged out"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.post("/auth/logout", json={"refresh_token": "rtok", "access_token": "atok"})
        call_args = mock_ctx.__aenter__.return_value.post.call_args
        self.assertEqual(call_args.args[0], "http://auth-service:8001/auth/logout")

    def test_successful_logout_response_returned(self) -> None:
        upstream = _mock_response(200, {"message": "Logged out"})
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/logout", json={"refresh_token": "rtok", "access_token": "atok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["message"], "Logged out")

    def test_failure_response_propagated(self) -> None:
        upstream = _mock_response(400, {"detail": "Malformed request"})
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/logout", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Malformed request")

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_auth_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.post("/auth/logout", json={"refresh_token": "rtok"})
        self.assertEqual(resp.status_code, 503)


class TestSessionCookieForwarding(unittest.TestCase):
    """SSO Phase 2 PR13: _proxy_to_auth relays the omnibioai_session cookie
    in both directions -- previously it silently dropped Set-Cookie from
    auth-service's response and never forwarded the browser's own Cookie
    header upstream."""

    def test_login_forwards_set_cookie_to_browser(self) -> None:
        upstream = _mock_response(
            200,
            {"access_token": "tok", "refresh_token": "rtok", "token_type": "bearer"},
            set_cookies=["omnibioai_session=rtok; Domain=.omnibioai.org; HttpOnly; Path=/; Secure"],
        )
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/login", json={"email": "a@b.com", "password": "x"})
        self.assertIn("omnibioai_session=rtok", resp.headers.get("set-cookie", ""))

    def test_refresh_forwards_set_cookie_to_browser(self) -> None:
        upstream = _mock_response(
            200,
            {"access_token": "new-tok", "refresh_token": "new-rtok"},
            set_cookies=["omnibioai_session=new-rtok; Domain=.omnibioai.org; HttpOnly; Path=/; Secure"],
        )
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/refresh", json={})
        self.assertIn("omnibioai_session=new-rtok", resp.headers.get("set-cookie", ""))

    def test_logout_forwards_clearing_set_cookie_to_browser(self) -> None:
        upstream = _mock_response(
            200,
            {"message": "Logged out"},
            set_cookies=['omnibioai_session=""; Domain=.omnibioai.org; HttpOnly; Max-Age=0; Path=/; Secure'],
        )
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/auth/logout", json={"refresh_token": "rtok"})
        self.assertIn("Max-Age=0", resp.headers.get("set-cookie", ""))

    def test_refresh_forwards_incoming_session_cookie_upstream(self) -> None:
        """auth-service's own /auth/refresh has a body-or-cookie fallback
        (PR10) -- but only if the cookie actually reaches it. Each proxy
        hop is an independent httpx request that doesn't automatically
        carry the original request's cookies, so this must be explicit."""
        upstream = _mock_response(200, {"access_token": "tok", "refresh_token": "rtok"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.post("/auth/refresh", json={}, cookies={"omnibioai_session": "cookie-rtok"})
        call_kwargs = mock_ctx.__aenter__.return_value.post.call_args.kwargs
        self.assertEqual(call_kwargs["headers"].get("Cookie"), "omnibioai_session=cookie-rtok")

    def test_unrelated_cookies_are_not_forwarded_upstream(self) -> None:
        """Only omnibioai_session is relayed -- not the raw incoming
        Cookie header verbatim, so no unrelated cookie a browser might
        hold for this domain leaks to auth-service."""
        upstream = _mock_response(200, {"access_token": "tok", "refresh_token": "rtok"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.post(
                "/auth/refresh",
                json={},
                cookies={"omnibioai_session": "cookie-rtok", "some_other_cookie": "unrelated"},
            )
        call_kwargs = mock_ctx.__aenter__.return_value.post.call_args.kwargs
        self.assertNotIn("some_other_cookie", call_kwargs["headers"].get("Cookie", ""))

    def test_logout_injects_refresh_token_from_cookie_when_body_omits_it(self) -> None:
        upstream = _mock_response(200, {"message": "Logged out"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.post("/auth/logout", json={}, cookies={"omnibioai_session": "cookie-rtok"})
        call_kwargs = mock_ctx.__aenter__.return_value.post.call_args.kwargs
        self.assertIn(b'"cookie-rtok"', call_kwargs["content"])

    def test_logout_body_refresh_token_takes_priority_over_cookie(self) -> None:
        upstream = _mock_response(200, {"message": "Logged out"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.post(
                "/auth/logout",
                json={"refresh_token": "body-rtok"},
                cookies={"omnibioai_session": "cookie-rtok"},
            )
        call_kwargs = mock_ctx.__aenter__.return_value.post.call_args.kwargs
        import json as _json
        sent = _json.loads(call_kwargs["content"])
        self.assertEqual(sent["refresh_token"], "body-rtok")

    def test_logout_without_cookie_or_body_token_forwards_empty(self) -> None:
        """No cookie, no body token -- nothing to inject; auth-service's
        own required-field validation (unchanged, out of scope) is what
        ultimately rejects this, not this proxy."""
        upstream = _mock_response(422, {"detail": "field required"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_auth_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/auth/logout", json={})
        self.assertEqual(resp.status_code, 422)


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
