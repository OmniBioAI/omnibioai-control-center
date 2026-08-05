"""
tests/test_routes_org_mfa_proxy.py

Unit tests for:
  - control_center.api.routes_org_mfa_proxy
    (GET/POST/PATCH /orgs/{org_id}/mfa-policy,
    POST/DELETE /orgs/{org_id}/mfa-policy/override)

Mirrors test_routes_org_sso_proxy.py's exact conventions -- these routes
are a thin relay, no authorization decision is made here (that's
entirely omnibioai-auth's job, via require_org_permission_or_platform_
admin(MANAGE_SSO) for the 3 CRUD routes and require_permission
(MANAGE_ALL_ORGS) for the 2 override routes, both from PR11.5.5 and
unmodified here).
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


_POLICY_OUT = {
    "required": True,
    "created_at": "2026-08-05T00:00:00",
    "updated_at": None,
    "enabled_at": "2026-08-05T00:00:00",
    "enabled_by_email": "admin@acme.test",
    "override_active": False,
    "override_reason": None,
}


class TestGetOrgMFAPolicyProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _POLICY_OUT)
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/mfa-policy", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["required"])
        # Never a secret -- there is no secret concept on this resource
        # at all, but this proxy also never adds any field upstream
        # doesn't already send.
        self.assertEqual(set(resp.json().keys()), set(_POLICY_OUT.keys()))

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, _POLICY_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs/7/mfa-policy", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_org_id_in_path(self) -> None:
        upstream = _mock_response(200, _POLICY_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs/42/mfa-policy", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/orgs/42/mfa-policy"))

    def test_forwards_404_when_not_configured(self) -> None:
        upstream = _mock_response(404, {"detail": "No MFA policy configured for this organization"})
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/mfa-policy", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_forwards_403_for_non_manager(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/mfa-policy", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_org_mfa_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/orgs/7/mfa-policy", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/mfa-policy", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestCreateOrgMFAPolicyProxy(unittest.TestCase):
    def test_forwards_post_body_and_status(self) -> None:
        upstream = _mock_response(201, {**_POLICY_OUT, "required": False, "enabled_at": None})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/orgs/7/mfa-policy", json={"required": False}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 201)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/mfa-policy"))

    def test_forwards_409_when_already_configured(self) -> None:
        upstream = _mock_response(409, {"detail": "this organization already has an MFA policy"})
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/orgs/7/mfa-policy", json={"required": True}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 409)

    def test_forwards_403_for_non_manager(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post("/orgs/7/mfa-policy", json={"required": True}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)


class TestUpdateOrgMFAPolicyProxy(unittest.TestCase):
    def test_forwards_patch_body_and_method(self) -> None:
        upstream = _mock_response(200, {**_POLICY_OUT, "required": True})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.patch("/orgs/7/mfa-policy", json={"required": True}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "PATCH")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/mfa-policy"))
        self.assertIn(b"true", call_args.kwargs["content"])

    def test_forwards_404_when_not_configured(self) -> None:
        upstream = _mock_response(404, {"detail": "No MFA policy configured for this organization"})
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.patch("/orgs/7/mfa-policy", json={"required": True}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestOverrideOrgMFAPolicyProxy(unittest.TestCase):
    def test_forwards_post_body_and_status(self) -> None:
        upstream = _mock_response(200, {**_POLICY_OUT, "override_active": True})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post(
                "/orgs/7/mfa-policy/override", json={"reason": "admin locked out"}, headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["override_active"])
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/mfa-policy/override"))
        self.assertIn(b"admin locked out", call_args.kwargs["content"])

    def test_forwards_403_for_non_global_admin(self) -> None:
        # MANAGE_ALL_ORGS is global-scoped -- an org's own manage_sso
        # holder without the global permission gets 403 here, by design
        # (break-glass must work even if the org admin is the one locked
        # out).
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/mfa-policy/override", json={"reason": "x"}, headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 403)

    def test_forwards_404_when_not_configured(self) -> None:
        upstream = _mock_response(404, {"detail": "No MFA policy configured for this organization"})
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/mfa-policy/override", json={"reason": "x"}, headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 404)


class TestClearOrgMFAPolicyOverrideProxy(unittest.TestCase):
    def test_forwards_method_and_status(self) -> None:
        upstream = _mock_response(200, {**_POLICY_OUT, "override_active": False})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/orgs/7/mfa-policy/override", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["override_active"])
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/mfa-policy/override"))

    def test_forwards_403_for_non_global_admin(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_mfa_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/orgs/7/mfa-policy/override", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
