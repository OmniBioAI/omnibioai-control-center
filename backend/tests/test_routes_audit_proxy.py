"""
tests/test_routes_audit_proxy.py

Unit tests for:
  - control_center.api.routes_audit_proxy
    (GET /platform/audit-events)

Mirrors test_routes_service_accounts_proxy.py's exact conventions -- this
route is a thin relay, no authorization decision is made here (that's
entirely omnibioai-auth's job, via require_permission(manage_all_orgs),
pre-existing and unmodified).
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


_EVENT_LIST = {
    "items": [
        {
            "id": 1, "event_type": "api_key_created", "actor_user_id": 7, "actor_email": "owner@acme.test",
            "target_user_id": None, "target_email": None, "organization_id": 3, "organization_name": "Acme",
            "resource_type": "api_key", "resource_id": "9", "before_state": None,
            "after_state": {"name": "CI", "scopes": [], "status": "active"},
            "metadata": {"api_key_name": "CI", "scopes": []}, "created_at": "2026-08-05T00:00:00",
        }
    ],
    "total": 1, "page": 1, "page_size": 20, "total_pages": 1,
}


class TestListAuditEventsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _EVENT_LIST)
        with patch("control_center.api.routes_audit_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/audit-events", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["items"][0]["event_type"], "api_key_created")
        # Never leaks a secret field, even indirectly.
        body_text = resp.text
        for forbidden in ("client_secret", "key_hash", "client_secret_hash", "client_secret_encrypted"):
            self.assertNotIn(forbidden, body_text)

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, _EVENT_LIST)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_audit_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/platform/audit-events", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_query_params(self) -> None:
        upstream = _mock_response(200, _EVENT_LIST)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_audit_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get(
                "/platform/audit-events",
                params={"organization_id": "3", "event_type": "api_key_created", "page": "2"},
                headers={"Authorization": "Bearer tok"},
            )
        forwarded_params = mock_ctx.__aenter__.return_value.request.call_args.kwargs["params"]
        self.assertEqual(forwarded_params["organization_id"], "3")
        self.assertEqual(forwarded_params["event_type"], "api_key_created")
        self.assertEqual(forwarded_params["page"], "2")

    def test_forwards_403_for_non_platform_admin(self) -> None:
        # manage_all_orgs is platform-admin-only -- a caller with only
        # manage_api_keys/manage_oauth_clients for one org gets 403 here,
        # by design. See discovery doc §5.
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_audit_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/audit-events", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_audit_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/platform/audit-events", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_audit_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/audit-events", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])

    def test_empty_upstream_body_preserved(self) -> None:
        # Not a real omnibioai-auth response shape for this route today
        # (GET /platform/audit-events always returns a body) -- covers
        # the shared _proxy() empty-body branch every proxy file in this
        # directory carries, for parity with the rest of the suite.
        upstream = MagicMock()
        upstream.status_code = 200
        upstream.content = b""
        upstream.json.side_effect = ValueError("no content to parse")
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_audit_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/platform/audit-events", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"")

    def test_no_delete_route_exists(self) -> None:
        # Immutability: this proxy defines GET only -- confirm there is
        # no DELETE (or PATCH/PUT) route registered for this path at all,
        # not just that one happens to fail.
        resp = client.delete("/platform/audit-events", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 405)


if __name__ == "__main__":
    unittest.main()
