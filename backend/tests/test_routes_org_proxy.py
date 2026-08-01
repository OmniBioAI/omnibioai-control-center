"""
tests/test_routes_org_proxy.py

Unit tests for:
  - control_center.api.routes_org_proxy
    (GET/POST /orgs, GET/PATCH /orgs/{org_id}, GET /platform/orgs,
    GET /platform/orgs/{org_id})

Mirrors test_routes_auth_proxy.py's exact conventions -- these routes are
a thin relay, no authorization decision is made here (that's entirely
omnibioai-auth's job, via require_permission/require_org_permission_or_
platform_admin), so these tests only prove: the right upstream path is
called, the Authorization header is forwarded, query params are
forwarded, and upstream status/body/unreachable/non-JSON cases are
relayed unchanged -- the same four things test_routes_auth_proxy.py
already proves for /auth/login and /auth/validate.
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


class TestListMyOrgsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, [{"id": 1, "slug": "acme", "name": "Acme", "plan": "beta", "status": "active"}])
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["slug"], "acme")

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, [])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_missing_authorization_header_not_fabricated(self) -> None:
        """No Authorization header on the incoming request -> none sent
        upstream either -- omnibioai-auth's own get_current_user is what
        must reject this, this proxy must not silently invent a header."""
        upstream = _mock_response(401, {"detail": "Invalid token"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/orgs")
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertNotIn("Authorization", call_kwargs["headers"])
        self.assertEqual(resp.status_code, 401)

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_org_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/orgs", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])


class TestCreateOrgProxy(unittest.TestCase):
    def test_forwards_post_body_and_status(self) -> None:
        upstream = _mock_response(201, {"id": 1, "slug": "acme", "name": "Acme", "plan": "beta", "status": "active"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post(
                "/orgs", json={"name": "Acme", "slug": "acme"}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 201)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertIn(b'"acme"', call_args.kwargs["content"])

    def test_forwards_409_for_duplicate_slug(self) -> None:
        upstream = _mock_response(409, {"detail": "Organization slug already exists"})
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs", json={"name": "Acme", "slug": "acme"}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 409)


class TestGetOrgProxy(unittest.TestCase):
    def test_forwards_org_id_in_path(self) -> None:
        upstream = _mock_response(200, {"id": 42, "slug": "acme", "name": "Acme", "plan": "beta", "status": "active"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/orgs/42", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], 42)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/orgs/42"))

    def test_forwards_404_unchanged(self) -> None:
        upstream = _mock_response(404, {"detail": "Organization not found"})
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/999999", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/1", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestUpdateOrgProxy(unittest.TestCase):
    def test_forwards_patch_body_and_method(self) -> None:
        upstream = _mock_response(200, {"id": 1, "status": "suspended"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.patch(
                "/orgs/1", json={"status": "suspended"}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "PATCH")
        self.assertIn(b'"suspended"', call_args.kwargs["content"])

    def test_forwards_403_unchanged(self) -> None:
        upstream = _mock_response(403, {"detail": "Only platform admins can change organization status"})
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.patch(
                "/orgs/1", json={"status": "suspended"}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 403)


class TestListPlatformOrgsProxy(unittest.TestCase):
    def test_forwards_query_params(self) -> None:
        upstream = _mock_response(200, {"items": [], "total": 0, "page": 2, "page_size": 10, "total_pages": 0})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get(
                "/platform/orgs",
                params={"page": 2, "page_size": 10, "search": "acme", "sort_by": "name", "sort_order": "asc"},
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 200)
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        forwarded_params = call_kwargs["params"]
        self.assertEqual(forwarded_params["search"], "acme")
        self.assertEqual(forwarded_params["sort_by"], "name")

    def test_forwards_403_for_non_platform_admin(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/orgs", headers={"Authorization": "Bearer org-admin-token"})
        self.assertEqual(resp.status_code, 403)


class TestGetPlatformOrgProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, {"id": 7, "slug": "acme", "member_summary": {"total": 3}})
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/orgs/7", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], 7)

    def test_forwards_404_for_nonexistent_org(self) -> None:
        upstream = _mock_response(404, {"detail": "Organization not found"})
        with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/orgs/999999", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
