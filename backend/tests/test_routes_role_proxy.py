"""
tests/test_routes_role_proxy.py

Unit tests for:
  - control_center.api.routes_role_proxy
    (GET /platform/roles, GET/POST /platform/users/{id}/roles,
    DELETE /platform/users/{id}/roles/{role_id}, GET /orgs/{id}/roles,
    GET/POST /orgs/{id}/members/{user_id}/roles,
    DELETE /orgs/{id}/members/{user_id}/roles/{role_id})

Mirrors test_routes_org_proxy.py/test_routes_user_proxy.py's exact
conventions -- these routes are a thin relay, no authorization decision is
made here.
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


def _mock_no_content_response(status_code: int = 204) -> MagicMock:
    """A real 204 -- empty body, .json() would raise on the real httpx
    object. content=b"" is what routes_role_proxy.py's `if not r.content`
    check keys off of."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = b""
    resp.json.side_effect = ValueError("no content to parse")
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


class TestListPlatformRolesProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, [{"id": 1, "name": "admin", "description": None, "permissions": ["manage_roles"]}])
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["name"], "admin")

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, [])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/platform/roles", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_403_for_non_platform_admin(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/roles", headers={"Authorization": "Bearer org-admin-token"})
        self.assertEqual(resp.status_code, 403)

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_role_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/platform/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestPlatformUserRolesProxy(unittest.TestCase):
    def test_get_forwards_user_id_in_path(self) -> None:
        upstream = _mock_response(200, [{"user_id": 42, "role": "admin", "assigned_at": None, "assigned_by": None}])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/platform/users/42/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/platform/users/42/roles"))

    def test_get_forwards_404_for_nonexistent_user(self) -> None:
        upstream = _mock_response(404, {"detail": "User not found"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/users/999999/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_post_forwards_body_and_method(self) -> None:
        upstream = _mock_response(201, [{"user_id": 1, "role": "admin", "assigned_at": None, "assigned_by": None}])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/platform/users/1/roles", json={"role": "admin"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 201)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertIn(b'"admin"', call_args.kwargs["content"])

    def test_post_forwards_400_for_unknown_role(self) -> None:
        upstream = _mock_response(400, {"detail": "Unknown role: 'nope'"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/platform/users/1/roles", json={"role": "nope"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 400)

    def test_post_forwards_403_for_self_escalation(self) -> None:
        upstream = _mock_response(403, {"detail": "Cannot assign yourself a role that grants additional permissions"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/platform/users/1/roles", json={"role": "admin"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_delete_forwards_method_and_preserves_204_empty_body(self) -> None:
        upstream = _mock_no_content_response(204)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/platform/users/1/roles/3", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 204)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/platform/users/1/roles/3"))

    def test_delete_forwards_404_for_unassigned_role(self) -> None:
        upstream = _mock_response(404, {"detail": "Role is not assigned to this user"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/platform/users/1/roles/3", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestOrgRolesProxy(unittest.TestCase):
    def test_list_org_roles_forwards_org_id(self) -> None:
        upstream = _mock_response(200, [{"id": 1, "name": "org_admin", "description": None, "permissions": ["manage_org"]}])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/orgs/7/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/orgs/7/roles"))

    def test_list_org_roles_forwards_404_for_non_member(self) -> None:
        upstream = _mock_response(404, {"detail": "Organization not found"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/999999/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_get_member_roles_forwards_org_and_user_id(self) -> None:
        upstream = _mock_response(200, {"organization_id": 7, "user_id": 3, "roles": ["org_admin"]})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/orgs/7/members/3/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/orgs/7/members/3/roles"))

    def test_assign_member_role_forwards_body(self) -> None:
        upstream = _mock_response(201, {"organization_id": 7, "user_id": 3, "roles": ["org_member", "org_admin"]})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post(
                "/orgs/7/members/3/roles", json={"role": "org_admin"}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 201)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertIn(b"org_admin", call_args.kwargs["content"])

    def test_assign_member_role_forwards_403_for_non_admin(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/members/3/roles", json={"role": "org_admin"}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 403)

    def test_remove_member_role_preserves_204_empty_body(self) -> None:
        upstream = _mock_no_content_response(204)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/orgs/7/members/3/roles/2", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 204)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/members/3/roles/2"))

    def test_remove_member_role_forwards_404_for_cross_org(self) -> None:
        upstream = _mock_response(404, {"detail": "Organization not found"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/orgs/999999/members/3/roles/2", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
