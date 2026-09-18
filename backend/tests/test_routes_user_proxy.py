"""
tests/test_routes_user_proxy.py

Unit tests for:
  - control_center.api.routes_user_proxy
    (GET /platform/users, GET/PATCH /platform/users/{user_id},
    POST /platform/users/{user_id}/mfa/reset)

Mirrors test_routes_org_proxy.py's exact conventions (Phase 3 PR2) --
these routes are a thin relay, no authorization decision is made here.

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


def _mock_async_client(response: MagicMock = None, side_effect=None):
    """An async-context-manager mock of httpx.AsyncClient whose
    .request() returns `response`, or raises `side_effect` if given."""
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


class TestListPlatformUsersProxy(unittest.TestCase):
    """GET /platform/users's thin-relay behavior: success passthrough,
    auth/query forwarding, and fail-safe error mapping."""

    def test_forwards_success_response(self) -> None:
        """A successful upstream response's body is relayed unchanged."""
        upstream = _mock_response(200, {"items": [{"id": 1, "email": "a@b.com"}], "total": 1, "page": 1, "page_size": 20, "total_pages": 1})
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/users", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["items"][0]["email"], "a@b.com")

    def test_forwards_authorization_header(self) -> None:
        """The caller's Authorization header is forwarded to the
        upstream auth-service call unchanged."""
        upstream = _mock_response(200, {"items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 0})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/platform/users", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_query_params(self) -> None:
        """page/page_size/search/sort_by/sort_order query params are all
        forwarded to the upstream request."""
        upstream = _mock_response(200, {"items": [], "total": 0, "page": 2, "page_size": 10, "total_pages": 0})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get(
                "/platform/users",
                params={"page": 2, "page_size": 10, "search": "acme", "sort_by": "email", "sort_order": "asc"},
                headers={"Authorization": "Bearer tok"},
            )
        forwarded_params = mock_ctx.__aenter__.return_value.request.call_args.kwargs["params"]
        self.assertEqual(forwarded_params["search"], "acme")
        self.assertEqual(forwarded_params["sort_by"], "email")

    def test_forwards_403_for_non_platform_admin(self) -> None:
        """A 403 from the upstream auth-service (non-platform-admin
        caller) is relayed as a 403."""
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/users", headers={"Authorization": "Bearer org-admin-token"})
        self.assertEqual(resp.status_code, 403)

    def test_auth_service_unreachable_returns_503(self) -> None:
        """A connection failure to the auth-service returns 503 with an
        "auth-service unreachable" message."""
        with patch(
            "control_center.api.routes_user_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/platform/users", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        """A non-JSON upstream response body maps to a 500 error naming
        "non-JSON" rather than propagating the parse exception."""
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/users", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestGetPlatformUserProxy(unittest.TestCase):
    """GET /platform/users/{user_id}'s thin-relay behavior."""

    def test_forwards_user_id_in_path(self) -> None:
        """The path's user_id segment is forwarded into the upstream
        request URL, and a successful response is relayed unchanged."""
        upstream = _mock_response(200, {"id": 42, "email": "a@b.com", "memberships": []})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/platform/users/42", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], 42)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/platform/users/42"))

    def test_forwards_404_for_nonexistent_user(self) -> None:
        """A 404 for a nonexistent user is relayed as a 404."""
        upstream = _mock_response(404, {"detail": "User not found"})
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/users/999999", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestUpdatePlatformUserProxy(unittest.TestCase):
    """PATCH /platform/users/{user_id}'s thin-relay behavior: the
    request body/method are forwarded, and upstream statuses pass through."""

    def test_forwards_patch_body_and_method(self) -> None:
        """The PATCH method and JSON body reach the upstream call
        unchanged, and a successful response is relayed."""
        upstream = _mock_response(200, {"id": 1, "status": "suspended"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.patch(
                "/platform/users/1", json={"status": "suspended"}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "PATCH")
        self.assertIn(b'"suspended"', call_args.kwargs["content"])

    def test_forwards_403_unchanged(self) -> None:
        """A 403 from the upstream auth-service is relayed as a 403."""
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.patch(
                "/platform/users/1", json={"status": "suspended"}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 403)

    def test_forwards_400_for_invalid_status(self) -> None:
        """A 400 for an invalid status value is relayed as a 400."""
        upstream = _mock_response(400, {"detail": "Unknown status: 'deleted'"})
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.patch(
                "/platform/users/1", json={"status": "deleted"}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 400)


class TestResetPlatformUserMFAProxy(unittest.TestCase):
    """PR11.5.6. Same reasoning as TestUpdatePlatformUserProxy above --
    omnibioai-auth's own require_permission(MANAGE_ALL_ORGS)
    (routes_platform_users.py, PR11.5.4, unmodified) is what actually
    decides every request."""

    def test_forwards_post_and_status(self) -> None:
        """The POST method reaches the upstream call correctly, and the
        successful response's body is relayed unchanged."""
        upstream = _mock_response(200, {"user_id": 1, "mfa_enabled": False, "mfa_status": "disabled"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/platform/users/1/mfa/reset", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["mfa_enabled"])
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertTrue(call_args.args[1].endswith("/platform/users/1/mfa/reset"))

    def test_forwards_403_for_non_platform_admin(self) -> None:
        """A 403 from the upstream auth-service is relayed as a 403."""
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/platform/users/1/mfa/reset", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_forwards_404_for_nonexistent_user(self) -> None:
        """A 404 for a nonexistent user is relayed as a 404."""
        upstream = _mock_response(404, {"detail": "User not found"})
        with patch("control_center.api.routes_user_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/platform/users/999999/mfa/reset", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
