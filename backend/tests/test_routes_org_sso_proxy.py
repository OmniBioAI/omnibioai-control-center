"""
tests/test_routes_org_sso_proxy.py

Unit tests for:
  - control_center.api.routes_org_sso_proxy
    (GET/POST/PATCH/DELETE /orgs/{org_id}/sso,
    POST/DELETE /orgs/{org_id}/sso/override)

Mirrors test_routes_team_proxy.py's exact conventions -- these routes are a
thin relay, no authorization decision is made here (that's entirely
omnibioai-auth's job, via require_org_permission_or_platform_admin
(MANAGE_SSO) for the 4 CRUD routes and require_permission
(OVERRIDE_SSO_ENFORCEMENT) for the 2 override routes, both pre-existing
and unmodified).
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
    object. content=b"" is what routes_org_sso_proxy.py's `if not
    r.content` check keys off of."""
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


_CONFIG_OUT = {
    "issuer": "https://idp.acme.test",
    "client_id": "abc123",
    "provider_type": "oidc",
    "allowed_domains": ["acme.test"],
    "status": "active",
    "created_at": "2026-07-01T00:00:00",
    "updated_at": "2026-07-01T00:00:00",
    "enforced": False,
    "sso_override_active": False,
}


class TestGetOrgSSOProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _CONFIG_OUT)
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/sso", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["client_id"], "abc123")
        # Never leaks a secret field, even indirectly -- upstream never
        # sends one, and this proxy never adds one.
        self.assertNotIn("client_secret", resp.json())
        self.assertNotIn("client_secret_encrypted", resp.json())

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, _CONFIG_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs/7/sso", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_org_id_in_path(self) -> None:
        upstream = _mock_response(200, _CONFIG_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs/42/sso", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/orgs/42/sso"))

    def test_forwards_404_when_not_configured(self) -> None:
        upstream = _mock_response(404, {"detail": "No SSO configuration for this organization"})
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/sso", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_forwards_403_for_non_manager(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/sso", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_org_sso_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/orgs/7/sso", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/sso", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestCreateOrgSSOProxy(unittest.TestCase):
    def test_forwards_post_body_and_status(self) -> None:
        upstream = _mock_response(201, _CONFIG_OUT)
        mock_ctx = _mock_async_client(upstream)
        body = {"issuer": "https://idp.acme.test", "client_id": "abc123", "client_secret": "s3cr3t"}
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/orgs/7/sso", json=body, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 201)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        # The secret is forwarded verbatim in the request body -- this
        # proxy makes no local copy, no log, no cache of it.
        self.assertIn(b"s3cr3t", call_args.kwargs["content"])

    def test_forwards_409_when_already_configured(self) -> None:
        upstream = _mock_response(409, {"detail": "this organization already has an SSO configuration"})
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/sso",
                json={"issuer": "https://idp.acme.test", "client_id": "x", "client_secret": "y"},
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 409)

    def test_forwards_400_for_discovery_failure(self) -> None:
        upstream = _mock_response(400, {"detail": "could not reach discovery endpoint: timeout"})
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/sso",
                json={"issuer": "https://bad.test", "client_id": "x", "client_secret": "y"},
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_forwards_403_for_non_manager(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/sso",
                json={"issuer": "https://idp.acme.test", "client_id": "x", "client_secret": "y"},
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 403)


class TestUpdateOrgSSOProxy(unittest.TestCase):
    def test_forwards_patch_body_and_method(self) -> None:
        upstream = _mock_response(200, {**_CONFIG_OUT, "enforced": True})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.patch("/orgs/7/sso", json={"enforced": True}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "PATCH")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/sso"))
        self.assertIn(b"true", call_args.kwargs["content"])

    def test_forwards_400_for_lockout_guard(self) -> None:
        upstream = _mock_response(
            400,
            {"detail": "cannot enforce SSO for this organization until at least one member has completed a successful SSO login"},
        )
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.patch("/orgs/7/sso", json={"enforced": True}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 400)

    def test_forwards_404_when_not_configured(self) -> None:
        upstream = _mock_response(404, {"detail": "No SSO configuration for this organization"})
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.patch("/orgs/7/sso", json={"client_id": "new"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestDeleteOrgSSOProxy(unittest.TestCase):
    def test_forwards_method_and_preserves_204_empty_body(self) -> None:
        upstream = _mock_no_content_response(204)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/orgs/7/sso", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.content, b"")
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/sso"))

    def test_forwards_403_for_non_manager(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/orgs/7/sso", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)


class TestOverrideOrgSSOProxy(unittest.TestCase):
    def test_forwards_post_body_and_status(self) -> None:
        upstream = _mock_response(200, {**_CONFIG_OUT, "sso_override_active": True})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post(
                "/orgs/7/sso/override", json={"reason": "admin locked out"}, headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["sso_override_active"])
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/sso/override"))
        self.assertIn(b"admin locked out", call_args.kwargs["content"])

    def test_forwards_403_for_non_global_admin(self) -> None:
        # override_sso_enforcement is global-scoped -- an org's own
        # manage_sso holder without the global permission gets 403 here,
        # by design (break-glass must work even if the org admin is the
        # one locked out).
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/sso/override", json={"reason": "x"}, headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 403)

    def test_forwards_404_when_not_configured(self) -> None:
        upstream = _mock_response(404, {"detail": "No SSO configuration for this organization"})
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/sso/override", json={"reason": "x"}, headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 404)


class TestClearOrgSSOOverrideProxy(unittest.TestCase):
    def test_forwards_method_and_status(self) -> None:
        upstream = _mock_response(200, {**_CONFIG_OUT, "sso_override_active": False})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/orgs/7/sso/override", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["sso_override_active"])
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/sso/override"))

    def test_forwards_403_for_non_global_admin(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_sso_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/orgs/7/sso/override", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
