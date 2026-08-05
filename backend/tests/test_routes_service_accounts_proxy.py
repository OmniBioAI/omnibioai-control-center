"""
tests/test_routes_service_accounts_proxy.py

Unit tests for:
  - control_center.api.routes_service_accounts_proxy
    (GET/POST/DELETE /orgs/{org_id}/api-keys[/{id}],
    GET/POST/DELETE /orgs/{org_id}/oauth-clients[/{id}],
    GET /platform/permissions)

Mirrors test_routes_org_sso_proxy.py's exact conventions -- these routes
are a thin relay, no authorization decision is made here (that's
entirely omnibioai-auth's job, via require_org_permission_or_platform_
admin(manage_api_keys / manage_oauth_clients) and require_permission
(manage_all_orgs), all pre-existing and unmodified).
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


_API_KEY_OUT = {
    "id": 1, "name": "CI pipeline", "key_prefix": "omni_sk_ab12",
    "scopes": ["dataset.read"], "status": "active",
    "created_at": "2026-07-01T00:00:00", "expires_at": None, "last_used_at": None,
}
_API_KEY_CREATED = {
    "id": 1, "name": "CI pipeline", "key_prefix": "omni_sk_ab12",
    "scopes": ["dataset.read"], "key": "omni_sk_ab12cdefghijklmnopqrstuvwxyz012345",
}
_OAUTH_CLIENT_OUT = {
    "id": 1, "name": "ETL worker", "client_id": "omni_client_ab12",
    "scopes": ["dataset.read"], "status": "active",
    "created_at": "2026-07-01T00:00:00", "expires_at": None, "last_used_at": None,
}
_OAUTH_CLIENT_CREATED = {
    "id": 1, "name": "ETL worker", "client_id": "omni_client_ab12",
    "scopes": ["dataset.read"], "client_secret": "s3cr3tvalueonlyreturnedonce",
}


class TestListApiKeysProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, [_API_KEY_OUT])
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/api-keys", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["key_prefix"], "omni_sk_ab12")
        self.assertNotIn("key", resp.json()[0])
        self.assertNotIn("key_hash", resp.json()[0])

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, [])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs/7/api-keys", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_org_id_in_path(self) -> None:
        upstream = _mock_response(200, [])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs/42/api-keys", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/orgs/42/api-keys"))

    def test_forwards_404_for_non_member(self) -> None:
        upstream = _mock_response(404, {"detail": "Organization not found"})
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/999999/api-keys", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_forwards_403_for_member_without_permission(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/api-keys", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_service_accounts_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/orgs/7/api-keys", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/api-keys", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestCreateApiKeyProxy(unittest.TestCase):
    def test_forwards_post_body_and_status(self) -> None:
        upstream = _mock_response(201, _API_KEY_CREATED)
        mock_ctx = _mock_async_client(upstream)
        body = {"name": "CI pipeline", "scopes": ["dataset.read"]}
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/orgs/7/api-keys", json=body, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["key"], _API_KEY_CREATED["key"])
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertIn(b"CI pipeline", call_args.kwargs["content"])

    def test_forwards_400_for_scope_not_held(self) -> None:
        upstream = _mock_response(400, {"detail": "Cannot grant scopes you don't hold: ['manage_org']"})
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/api-keys", json={"name": "x", "scopes": ["manage_org"]}, headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_forwards_403_for_member_without_permission(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/orgs/7/api-keys", json={"name": "x"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)


class TestRevokeApiKeyProxy(unittest.TestCase):
    def test_forwards_method_and_preserves_204_empty_body(self) -> None:
        upstream = _mock_no_content_response(204)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/orgs/7/api-keys/1", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.content, b"")
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/api-keys/1"))

    def test_forwards_404_for_unknown_key(self) -> None:
        upstream = _mock_response(404, {"detail": "API key not found"})
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/orgs/7/api-keys/999999", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestListOAuthClientsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, [_OAUTH_CLIENT_OUT])
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/oauth-clients", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["client_id"], "omni_client_ab12")
        self.assertNotIn("client_secret", resp.json()[0])
        self.assertNotIn("client_secret_hash", resp.json()[0])

    def test_forwards_org_id_in_path(self) -> None:
        upstream = _mock_response(200, [])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs/42/oauth-clients", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/orgs/42/oauth-clients"))

    def test_forwards_404_for_non_member(self) -> None:
        upstream = _mock_response(404, {"detail": "Organization not found"})
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/999999/oauth-clients", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_forwards_403_for_member_without_permission(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/oauth-clients", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)


class TestCreateOAuthClientProxy(unittest.TestCase):
    def test_forwards_post_body_and_status(self) -> None:
        upstream = _mock_response(201, _OAUTH_CLIENT_CREATED)
        mock_ctx = _mock_async_client(upstream)
        body = {"name": "ETL worker", "scopes": ["dataset.read"]}
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/orgs/7/oauth-clients", json=body, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["client_secret"], _OAUTH_CLIENT_CREATED["client_secret"])
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertIn(b"ETL worker", call_args.kwargs["content"])

    def test_forwards_400_for_unknown_permission_scope(self) -> None:
        upstream = _mock_response(400, {"detail": "Unknown service permission: dataset.reed. Did you mean: dataset.read?"})
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/oauth-clients", json={"name": "x", "scopes": ["dataset.reed"]}, headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Did you mean", resp.json()["detail"])

    def test_forwards_403_for_member_without_permission(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/orgs/7/oauth-clients", json={"name": "x"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)


class TestRevokeOAuthClientProxy(unittest.TestCase):
    def test_forwards_method_and_preserves_204_empty_body(self) -> None:
        upstream = _mock_no_content_response(204)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/orgs/7/oauth-clients/1", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.content, b"")
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/oauth-clients/1"))

    def test_forwards_404_for_unknown_client(self) -> None:
        upstream = _mock_response(404, {"detail": "OAuth client not found"})
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/orgs/7/oauth-clients/999999", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestListPermissionsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, [{"name": "dataset.read", "resource": "dataset", "action": "read", "scope": "org", "category": "data", "description": "x", "legacy": False, "deprecated": False}])
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/permissions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["name"], "dataset.read")

    def test_forwards_403_for_non_platform_admin(self) -> None:
        # manage_all_orgs is platform-admin-only -- a regular org admin
        # (even with manage_api_keys/manage_oauth_clients) gets 403 here,
        # by design. See discovery doc §6.
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/platform/permissions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_forwards_query_params(self) -> None:
        upstream = _mock_response(200, [])
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_service_accounts_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/platform/permissions", params={"search": "dataset"}, headers={"Authorization": "Bearer tok"})
        forwarded_params = mock_ctx.__aenter__.return_value.request.call_args.kwargs["params"]
        self.assertEqual(forwarded_params["search"], "dataset")


if __name__ == "__main__":
    unittest.main()
