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


def _mock_response(status_code: int, json_body=None, raise_json_error: bool = False, content: bytes = b"x") -> MagicMock:
    """A MagicMock httpx.Response stand-in; raise_json_error makes
    .json() raise ValueError instead of returning json_body."""
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


class TestListPlatformRolesProxy(unittest.TestCase):
    """GET /platform/roles's thin-relay behavior."""

    def test_forwards_success_response(self) -> None:
        """A successful upstream response's body is relayed unchanged."""
        upstream = _mock_response(200, [{"id": 1, "name": "admin", "description": None, "permissions": ["manage_roles"]}])
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["name"], "admin")

    def test_forwards_authorization_header(self) -> None:
        """The caller's Authorization header is forwarded unchanged."""
        upstream = _mock_response(200, [])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/platform/roles", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_403_for_non_platform_admin(self) -> None:
        """A 403 from the upstream auth-service is relayed as a 403."""
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/roles", headers={"Authorization": "Bearer org-admin-token"})
        self.assertEqual(resp.status_code, 403)

    def test_auth_service_unreachable_returns_503(self) -> None:
        """A connection failure to the auth-service returns 503."""
        with patch(
            "control_center.api.routes_role_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/platform/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        """A non-JSON upstream response body maps to a 500 error
        naming "non-JSON"."""
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestPlatformUserRolesProxy(unittest.TestCase):
    """GET/POST /platform/users/{id}/roles and DELETE .../roles/{role_id}'s
    thin-relay behavior."""

    def test_get_forwards_user_id_in_path(self) -> None:
        """The path's user_id is forwarded into the upstream URL."""
        upstream = _mock_response(200, [{"user_id": 42, "role": "admin", "assigned_at": None, "assigned_by": None}])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/platform/users/42/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/platform/users/42/roles"))

    def test_get_forwards_404_for_nonexistent_user(self) -> None:
        """A 404 for a nonexistent user is relayed as a 404."""
        upstream = _mock_response(404, {"detail": "User not found"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/users/999999/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_post_forwards_body_and_method(self) -> None:
        """The POST body/method reach the upstream call correctly."""
        upstream = _mock_response(201, [{"user_id": 1, "role": "admin", "assigned_at": None, "assigned_by": None}])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/platform/users/1/roles", json={"role": "admin"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 201)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertIn(b'"admin"', call_args.kwargs["content"])

    def test_post_forwards_400_for_unknown_role(self) -> None:
        """A 400 for an unrecognized role name is relayed as a 400."""
        upstream = _mock_response(400, {"detail": "Unknown role: 'nope'"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/platform/users/1/roles", json={"role": "nope"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 400)

    def test_post_forwards_403_for_self_escalation(self) -> None:
        """A 403 for an attempted self-escalation is relayed as a 403."""
        upstream = _mock_response(403, {"detail": "Cannot assign yourself a role that grants additional permissions"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/platform/users/1/roles", json={"role": "admin"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_delete_forwards_method_and_preserves_204_empty_body(self) -> None:
        """The DELETE method reaches the upstream call, and the 204
        empty body is preserved."""
        upstream = _mock_no_content_response(204)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/platform/users/1/roles/3", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 204)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/platform/users/1/roles/3"))

    def test_delete_forwards_404_for_unassigned_role(self) -> None:
        """A 404 for a role not currently assigned to the user is relayed as a 404."""
        upstream = _mock_response(404, {"detail": "Role is not assigned to this user"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/platform/users/1/roles/3", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestOrgRolesProxy(unittest.TestCase):
    """GET /orgs/{id}/roles and GET/POST/DELETE .../members/{user_id}/roles's
    thin-relay behavior."""

    def test_list_org_roles_forwards_org_id(self) -> None:
        """The path's org_id is forwarded into the upstream URL."""
        upstream = _mock_response(200, [{"id": 1, "name": "org_admin", "description": None, "permissions": ["manage_org"]}])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/orgs/7/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/orgs/7/roles"))

    def test_list_org_roles_forwards_404_for_non_member(self) -> None:
        """A 404 for a nonexistent/non-member org is relayed as a 404."""
        upstream = _mock_response(404, {"detail": "Organization not found"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/999999/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_get_member_roles_forwards_org_and_user_id(self) -> None:
        """The path's org_id and user_id are both forwarded into the upstream URL."""
        upstream = _mock_response(200, {"organization_id": 7, "user_id": 3, "roles": ["org_admin"]})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/orgs/7/members/3/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/orgs/7/members/3/roles"))

    def test_assign_member_role_forwards_body(self) -> None:
        """The POST body (role name) reaches the upstream call unchanged."""
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
        """A 403 from the upstream auth-service is relayed as a 403."""
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/members/3/roles", json={"role": "org_admin"}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 403)

    def test_remove_member_role_preserves_204_empty_body(self) -> None:
        """The DELETE's 204 empty body is preserved."""
        upstream = _mock_no_content_response(204)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/orgs/7/members/3/roles/2", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 204)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/members/3/roles/2"))

    def test_remove_member_role_forwards_404_for_cross_org(self) -> None:
        """A 404 for a cross-org role removal attempt is relayed as a 404."""
        upstream = _mock_response(404, {"detail": "Organization not found"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/orgs/999999/members/3/roles/2", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestPlatformRoleCatalogCrudProxy(unittest.TestCase):
    """PR13: POST/PUT/DELETE /platform/roles -- role catalog CRUD, new in
    this PR (only read + user-assignment existed before)."""

    def test_create_forwards_body_and_method(self) -> None:
        """The POST body/method reach the upstream call correctly."""
        upstream = _mock_response(201, {"id": 5, "name": "custom", "description": None, "permissions": [], "organization_id": None})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/platform/roles", json={"name": "custom", "permissions": []}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 201)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertTrue(call_args.args[1].endswith("/platform/roles"))
        self.assertIn(b'"custom"', call_args.kwargs["content"])

    def test_create_forwards_409_for_duplicate_name(self) -> None:
        """A 409 for a role name collision is relayed as a 409."""
        upstream = _mock_response(409, {"detail": "Role name 'admin' is already taken by a platform-wide role"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/platform/roles", json={"name": "admin", "permissions": []}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 409)

    def test_update_forwards_role_id_and_body(self) -> None:
        """The path's role_id and the PUT body both reach the upstream call."""
        upstream = _mock_response(200, {"id": 5, "name": "custom", "description": None, "permissions": [], "organization_id": None})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.put("/platform/roles/5", json={"permissions": ["dataset.read"]}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "PUT")
        self.assertTrue(call_args.args[1].endswith("/platform/roles/5"))

    def test_update_forwards_404_for_org_scoped_role(self) -> None:
        """A 404 (e.g. for an org-scoped role id on the platform route)
        is relayed as a 404."""
        upstream = _mock_response(404, {"detail": "Role not found"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.put("/platform/roles/9", json={"permissions": []}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_delete_forwards_method_and_role_id(self) -> None:
        """The DELETE method and path's role_id reach the upstream call."""
        upstream = _mock_no_content_response(204)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/platform/roles/5", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 204)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/platform/roles/5"))

    def test_delete_forwards_409_for_role_in_use(self) -> None:
        """A 409 for a role currently in use is relayed as a 409."""
        upstream = _mock_response(409, {"detail": "Role is currently assigned and cannot be deleted"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/platform/roles/5", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 409)


class TestOrganizationRoleCatalogCrudProxy(unittest.TestCase):
    """PR13: GET/POST /organizations/{id}/roles, GET
    /organizations/{id}/permissions, PUT/DELETE
    /organizations/{id}/roles/{role_id} -- entirely new surface, proxying
    to omnibioai-auth's newer routes_organization_roles.py."""

    def test_list_roles_forwards_organization_id(self) -> None:
        """The path's organization_id is forwarded into the upstream URL."""
        upstream = _mock_response(200, [{"id": 1, "name": "org_admin", "description": None, "permissions": ["manage_org"], "organization_id": None}])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/organizations/7/roles", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/organizations/7/roles"))

    def test_list_permissions_forwards_organization_id(self) -> None:
        """The path's organization_id is forwarded for the permissions listing too."""
        upstream = _mock_response(200, [{"name": "dataset.read", "resource": "dataset", "action": "read", "scope": "both", "category": "dataset", "description": "", "legacy": False, "deprecated": False, "deprecated_reason": None}])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/organizations/7/permissions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/organizations/7/permissions"))

    def test_create_role_forwards_body(self) -> None:
        """The POST body/method reach the upstream call correctly."""
        upstream = _mock_response(201, {"id": 9, "name": "reviewer", "description": None, "permissions": [], "organization_id": 7})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/organizations/7/roles", json={"name": "reviewer", "permissions": ["dataset.read"]}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 201)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertTrue(call_args.args[1].endswith("/organizations/7/roles"))

    def test_create_role_forwards_400_for_global_permission(self) -> None:
        """A 400 for an org-scoped role attempting to hold a platform-
        wide permission is relayed as a 400."""
        upstream = _mock_response(400, {"detail": "Organization-scoped roles cannot hold platform-wide permissions: manage_all_orgs"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/organizations/7/roles", json={"name": "sneaky", "permissions": ["manage_all_orgs"]}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 400)

    def test_update_role_forwards_organization_and_role_id(self) -> None:
        """Both the organization_id and role_id path segments reach the upstream URL."""
        upstream = _mock_response(200, {"id": 9, "name": "reviewer", "description": None, "permissions": [], "organization_id": 7})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.put("/organizations/7/roles/9", json={"permissions": ["dataset.read"]}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/organizations/7/roles/9"))

    def test_update_role_forwards_404_for_other_orgs_role(self) -> None:
        """A 404 for a role belonging to a different org is relayed as a 404."""
        upstream = _mock_response(404, {"detail": "Role not found"})
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.put("/organizations/7/roles/99", json={"permissions": []}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_delete_role_forwards_organization_and_role_id(self) -> None:
        """Both the organization_id and role_id path segments reach the
        upstream DELETE call."""
        upstream = _mock_no_content_response(204)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_role_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/organizations/7/roles/9", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 204)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/organizations/7/roles/9"))


if __name__ == "__main__":
    unittest.main()
