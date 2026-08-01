"""
tests/test_routes_team_proxy.py

Unit tests for:
  - control_center.api.routes_team_proxy
    (GET/POST /orgs/{org_id}/teams, PUT /orgs/{org_id}/teams/{team_id}/members,
    DELETE /orgs/{org_id}/teams/{team_id})

Mirrors test_routes_role_proxy.py's exact conventions -- these routes are a
thin relay, no authorization decision is made here (that's entirely
omnibioai-auth's job, via require_org_permission_or_platform_admin/
get_org_membership_or_platform_admin, both pre-existing and unmodified).
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
    object. content=b"" is what routes_team_proxy.py's `if not r.content`
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


class TestListTeamsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, [{"id": 1, "organization_id": 7, "name": "Genomics", "member_user_ids": [3, 4]}])
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/teams", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["name"], "Genomics")

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, [])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs/7/teams", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_org_id_in_path(self) -> None:
        upstream = _mock_response(200, [])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs/42/teams", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/orgs/42/teams"))

    def test_forwards_404_for_non_member(self) -> None:
        upstream = _mock_response(404, {"detail": "Organization not found"})
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/999999/teams", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_team_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/orgs/7/teams", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/teams", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestCreateTeamProxy(unittest.TestCase):
    def test_forwards_post_body_and_status(self) -> None:
        upstream = _mock_response(201, {"id": 1, "organization_id": 7, "name": "Genomics", "member_user_ids": []})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/orgs/7/teams", json={"name": "Genomics"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 201)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertIn(b"Genomics", call_args.kwargs["content"])

    def test_forwards_403_for_non_manager(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/orgs/7/teams", json={"name": "Genomics"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_forwards_query_params(self) -> None:
        upstream = _mock_response(201, {"id": 1, "organization_id": 7, "name": "Genomics", "member_user_ids": []})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.post(
                "/orgs/7/teams", json={"name": "Genomics"}, params={"debug": "1"},
                headers={"Authorization": "Bearer tok"},
            )
        forwarded_params = mock_ctx.__aenter__.return_value.request.call_args.kwargs["params"]
        self.assertEqual(forwarded_params["debug"], "1")


class TestUpdateTeamMembersProxy(unittest.TestCase):
    def test_forwards_put_body_and_method(self) -> None:
        upstream = _mock_response(200, {"id": 1, "organization_id": 7, "name": "Genomics", "member_user_ids": [3, 4]})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.put(
                "/orgs/7/teams/1/members", json={"user_ids": [3, 4]}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "PUT")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/teams/1/members"))
        self.assertIn(b"[3,4]", call_args.kwargs["content"])

    def test_forwards_400_for_invalid_member(self) -> None:
        upstream = _mock_response(400, {"detail": "Users not members of this organization: [999]"})
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.put(
                "/orgs/7/teams/1/members", json={"user_ids": [999]}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 400)

    def test_forwards_404_for_nonexistent_team(self) -> None:
        upstream = _mock_response(404, {"detail": "Team not found"})
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.put(
                "/orgs/7/teams/999999/members", json={"user_ids": []}, headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 404)


class TestDeleteTeamProxy(unittest.TestCase):
    def test_forwards_method_and_preserves_204_empty_body(self) -> None:
        upstream = _mock_no_content_response(204)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/orgs/7/teams/1", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.content, b"")
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/teams/1"))

    def test_forwards_403_for_non_manager(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/orgs/7/teams/1", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_forwards_404_for_nonexistent_team(self) -> None:
        upstream = _mock_response(404, {"detail": "Team not found"})
        with patch("control_center.api.routes_team_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/orgs/7/teams/999999", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
