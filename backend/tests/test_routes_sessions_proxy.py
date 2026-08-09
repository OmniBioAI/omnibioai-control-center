"""
tests/test_routes_sessions_proxy.py

Unit tests for:
  - control_center.api.routes_sessions_proxy
    (GET /sessions, GET /sessions/{session_id}, POST /sessions/{session_id}/revoke)

Mirrors test_routes_audit_proxy.py's exact conventions -- this route is a
thin relay, no authorization decision is made here (that's entirely
omnibioai-auth's job: every /sessions endpoint there is self-service,
scoped to the caller's own `sub` claim, Phase 4 PR-A).
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from control_center.main import app

client = TestClient(app)


def _mock_response(status_code: int, json_body=None, raise_json_error: bool = False, content: bytes = b"x") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    if raise_json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    return resp


def _mock_async_client(response: MagicMock = None, side_effect=None):
    mock_client = MagicMock()
    mock_request = AsyncMock()
    if side_effect is not None:
        mock_request.side_effect = side_effect
    else:
        mock_request.return_value = response
    mock_client.request = mock_request

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


_SESSION = {
    "session_id": "5c16797d-8a05-4d63-9022-6a49979406a0",
    "organization_id": None,
    "auth_method": "password",
    "mfa_verified": True,
    "status": "active",
    "created_at": "2026-08-09T00:00:30",
    "last_activity_at": "2026-08-09T00:00:30",
    "expires_at": "2026-08-16T00:00:30",
    "revoked_at": None,
    "revoked_reason": None,
    "client_ip": "172.17.0.1",
    "user_agent": "curl/8.5.0",
}

_OTHER_SESSION = {**_SESSION, "session_id": "not-mine-session-id"}


class TestListMySessionsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, [_SESSION])
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/sessions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["session_id"], _SESSION["session_id"])
        # Never leaks anything token/secret-shaped, even indirectly.
        # ("password" alone is NOT checked here -- auth_method can
        # legitimately hold the literal value "password", a safe,
        # documented field per PR-A's own SessionOut contract, not a
        # leak of a credential.)
        body_text = resp.text
        for forbidden in ("access_token", "refresh_token", "hashed_password", "jwt", "cookie"):
            self.assertNotIn(forbidden, body_text.lower())

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, [_SESSION])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/sessions", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_missing_authorization_header_is_not_forged(self) -> None:
        # No Authorization header on the incoming request -- the proxy
        # must not invent one; omnibioai-auth's own get_current_user is
        # what actually rejects the request (mocked here as a 401, same
        # as test_upstream_401_is_forwarded_for_unauthenticated_request
        # below covers end-to-end).
        upstream = _mock_response(200, [_SESSION])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/sessions")
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertNotIn("Authorization", call_kwargs["headers"])

    def test_upstream_401_is_forwarded_for_unauthenticated_request(self) -> None:
        # No credentials (or an invalid/expired token) -- this proxy makes
        # no authorization decision itself, so the existing authentication
        # error behavior is entirely whatever omnibioai-auth's own
        # get_current_user returns, forwarded unchanged.
        upstream = _mock_response(401, {"detail": "Not authenticated"})
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/sessions")
        self.assertEqual(resp.status_code, 401)

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_sessions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/sessions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_network_timeout_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_sessions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.TimeoutException("timed out")),
        ):
            resp = client.get("/sessions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/sessions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])

    def test_upstream_5xx_is_forwarded(self) -> None:
        upstream = _mock_response(500, {"detail": "Internal Server Error"})
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/sessions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)

    def test_empty_upstream_body_preserved(self) -> None:
        upstream = MagicMock()
        upstream.status_code = 200
        upstream.content = b""
        upstream.json.side_effect = ValueError("no content to parse")
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/sessions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"")


class TestGetMySessionProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _SESSION)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get(f"/sessions/{_SESSION['session_id']}", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["session_id"], _SESSION["session_id"])
        forwarded_path = mock_ctx.__aenter__.return_value.request.call_args.args[1]
        self.assertTrue(forwarded_path.endswith(f"/sessions/{_SESSION['session_id']}"))

    def test_other_users_session_id_is_not_exposed(self) -> None:
        # The proxy relays exactly whatever omnibioai-auth returns for
        # this session_id -- since that endpoint 404s a session_id that
        # doesn't belong to the caller (Phase 4 PR-A, ownership enforced
        # server-side), this proxy must forward that 404 unchanged, never
        # substitute a different (e.g. cached) session or a 200.
        upstream = _mock_response(404, {"detail": "Session not found"})
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get(f"/sessions/{_OTHER_SESSION['session_id']}", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("session_id", resp.text)

    def test_upstream_404_for_unknown_session_id(self) -> None:
        upstream = _mock_response(404, {"detail": "Session not found"})
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/sessions/does-not-exist", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestRevokeMySessionProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        revoked = {**_SESSION, "status": "revoked", "revoked_reason": "user_revoked", "revoked_at": "2026-08-09T00:05:00"}
        upstream = _mock_response(200, revoked)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post(f"/sessions/{_SESSION['session_id']}/revoke", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "revoked")
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_kwargs.args[0], "POST")
        forwarded_path = call_kwargs.args[1]
        self.assertTrue(forwarded_path.endswith(f"/sessions/{_SESSION['session_id']}/revoke"))

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, {**_SESSION, "status": "revoked"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.post(f"/sessions/{_SESSION['session_id']}/revoke", headers={"Authorization": "Bearer owner-token"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer owner-token")

    def test_cannot_revoke_another_users_session(self) -> None:
        # Same ownership boundary as the GET case -- omnibioai-auth 404s
        # a revoke attempt against a session_id the caller doesn't own;
        # this proxy must not turn that into a success or otherwise
        # bypass it.
        upstream = _mock_response(404, {"detail": "Session not found"})
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(f"/sessions/{_OTHER_SESSION['session_id']}/revoke", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_revoke_is_idempotent_through_the_proxy(self) -> None:
        # Revoking an already-revoked session is a safe 200 no-op
        # upstream (Phase 4 PR-A) -- confirm the proxy doesn't add any
        # special-casing (e.g. erroring on a second call) of its own.
        already_revoked = {**_SESSION, "status": "revoked", "revoked_reason": "user_revoked", "revoked_at": "2026-08-09T00:05:00"}
        upstream = _mock_response(200, already_revoked)
        with patch("control_center.api.routes_sessions_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            first = client.post(f"/sessions/{_SESSION['session_id']}/revoke", headers={"Authorization": "Bearer tok"})
            second = client.post(f"/sessions/{_SESSION['session_id']}/revoke", headers={"Authorization": "Bearer tok"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["revoked_at"], first.json()["revoked_at"])

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_sessions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.post(f"/sessions/{_SESSION['session_id']}/revoke", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)

    def test_get_method_not_allowed_on_revoke_path(self) -> None:
        resp = client.get(f"/sessions/{_SESSION['session_id']}/revoke", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 405)


if __name__ == "__main__":
    unittest.main()
