"""
tests/test_routes_org_saml_proxy.py

Unit tests for:
  - control_center.api.routes_org_saml_proxy
    (GET/POST/PATCH/DELETE /orgs/{org_id}/saml,
    GET /auth/saml/{org_slug}/metadata)

Mirrors test_routes_org_sso_proxy.py's exact conventions -- these routes
are a thin relay, no authorization decision is made here (that's
entirely omnibioai-auth's job, via require_org_permission_or_platform_
admin(MANAGE_SSO), pre-existing and unmodified).

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
    """A MagicMock httpx.Response stand-in with an empty body and no
    content to parse as JSON."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = b""
    resp.json.side_effect = ValueError("no content to parse")
    return resp


def _mock_async_client(response: MagicMock = None, side_effect=None):
    """An async-context-manager mock of httpx.AsyncClient whose
    .request()/.get() return `response`, or raise `side_effect` if given."""
    mock_client = MagicMock()
    mock_request = AsyncMock()
    if side_effect is not None:
        mock_request.side_effect = side_effect
    else:
        mock_request.return_value = response
    mock_client.request = mock_request
    mock_client.get = mock_request

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


_CONFIG_OUT = {
    "entity_id": "https://idp.acme.test/entity",
    "sso_url": "https://idp.acme.test/sso",
    "x509_certificate": "-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----",
    "attribute_mapping": {"email": "NameID"},
    "enabled": False,
    "status": "active",
    "created_at": "2026-08-12T00:00:00",
    "updated_at": "2026-08-12T00:00:00",
}


class TestGetOrgSamlProxy(unittest.TestCase):
    """GET /orgs/{org_id}/saml's thin-relay behavior."""

    def test_forwards_success_response(self) -> None:
        """A successful upstream response's body is relayed unchanged."""
        upstream = _mock_response(200, _CONFIG_OUT)
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/saml", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["entity_id"], "https://idp.acme.test/entity")

    def test_forwards_authorization_header(self) -> None:
        """The caller's Authorization header is forwarded to the
        upstream auth-service call unchanged."""
        upstream = _mock_response(200, _CONFIG_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs/7/saml", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_forwards_org_id_in_path(self) -> None:
        """The path's org_id segment is forwarded into the upstream URL."""
        upstream = _mock_response(200, _CONFIG_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/orgs/42/saml", headers={"Authorization": "Bearer tok"})
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertTrue(call_args.args[1].endswith("/orgs/42/saml"))

    def test_forwards_404_when_not_configured(self) -> None:
        """A 404 for an org with no SAML config is relayed as a 404."""
        upstream = _mock_response(404, {"detail": "No SAML configuration for this organization"})
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/saml", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_forwards_403_for_non_manager(self) -> None:
        """A 403 from the upstream auth-service is relayed as a 403."""
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/saml", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_auth_service_unreachable_returns_503(self) -> None:
        """A connection failure to the auth-service returns 503 with an
        "auth-service unreachable" message."""
        with patch(
            "control_center.api.routes_org_saml_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/orgs/7/saml", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        """A non-JSON upstream response body maps to a 500 error naming
        "non-JSON" rather than propagating the parse exception."""
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/orgs/7/saml", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestCreateOrgSamlProxy(unittest.TestCase):
    """POST /orgs/{org_id}/saml's thin-relay behavior."""

    def test_forwards_post_body_and_status(self) -> None:
        """The POST body/method reach the upstream call, and the
        created status is relayed."""
        upstream = _mock_response(201, _CONFIG_OUT)
        mock_ctx = _mock_async_client(upstream)
        body = {
            "entity_id": "https://idp.acme.test/entity", "sso_url": "https://idp.acme.test/sso",
            "x509_certificate": "-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----",
        }
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.post("/orgs/7/saml", json=body, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 201)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertIn(b"idp.acme.test", call_args.kwargs["content"])

    def test_forwards_409_when_already_configured(self) -> None:
        """A 409 for an org that already has a SAML config is relayed as a 409."""
        upstream = _mock_response(409, {"detail": "this organization already has a SAML configuration"})
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/saml",
                json={"entity_id": "x", "sso_url": "https://idp.example.com", "x509_certificate": "cert"},
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 409)

    def test_forwards_422_for_validation_failure(self) -> None:
        """A 422 for an invalid sso_url is relayed as a 422."""
        upstream = _mock_response(422, {"detail": "sso_url must be an http(s) URL"})
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/saml",
                json={"entity_id": "x", "sso_url": "ftp://bad", "x509_certificate": "cert"},
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 422)

    def test_forwards_403_for_non_manager(self) -> None:
        """A 403 from the upstream auth-service is relayed as a 403."""
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.post(
                "/orgs/7/saml",
                json={"entity_id": "x", "sso_url": "https://idp.example.com", "x509_certificate": "cert"},
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 403)


class TestUpdateOrgSamlProxy(unittest.TestCase):
    """PATCH /orgs/{org_id}/saml's thin-relay behavior."""

    def test_forwards_patch_body_and_method(self) -> None:
        """The PATCH method and JSON body reach the upstream call unchanged."""
        upstream = _mock_response(200, {**_CONFIG_OUT, "status": "disabled"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.patch("/orgs/7/saml", json={"status": "disabled"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "PATCH")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/saml"))
        self.assertIn(b"disabled", call_args.kwargs["content"])

    def test_forwards_404_when_not_configured(self) -> None:
        """A 404 for an org with no SAML config is relayed as a 404."""
        upstream = _mock_response(404, {"detail": "No SAML configuration for this organization"})
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.patch("/orgs/7/saml", json={"status": "active"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)

    def test_forwards_422_for_validation_failure(self) -> None:
        """A 422 for an invalid certificate is relayed as a 422."""
        upstream = _mock_response(422, {"detail": "x509_certificate must be a PEM-encoded certificate"})
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.patch("/orgs/7/saml", json={"x509_certificate": "not a cert"}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 422)


class TestDeleteOrgSamlProxy(unittest.TestCase):
    """DELETE /orgs/{org_id}/saml's thin-relay behavior."""

    def test_forwards_method_and_preserves_204_empty_body(self) -> None:
        """The DELETE method reaches the upstream call, and the 204
        empty body is preserved rather than replaced."""
        upstream = _mock_no_content_response(204)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.delete("/orgs/7/saml", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.content, b"")
        call_args = mock_ctx.__aenter__.return_value.request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertTrue(call_args.args[1].endswith("/orgs/7/saml"))

    def test_forwards_403_for_non_manager(self) -> None:
        """A 403 from the upstream auth-service is relayed as a 403."""
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/orgs/7/saml", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_forwards_404_when_not_configured(self) -> None:
        """A 404 for an org with no SAML config is relayed as a 404."""
        upstream = _mock_response(404, {"detail": "No SAML configuration for this organization"})
        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.delete("/orgs/7/saml", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 404)


class TestSamlMetadataProxy(unittest.TestCase):
    """GET /auth/saml/{org_slug}/metadata -- deliberately not built on
    the shared _proxy() JSON-wrapping helper; see routes_org_saml_proxy.py's
    own module comment for why."""

    def test_forwards_xml_content_and_content_type(self) -> None:
        """The raw XML body and content-type are relayed unchanged --
        not wrapped in the shared JSON-proxy helper."""
        xml_body = b'<?xml version="1.0"?><EntityDescriptor>...</EntityDescriptor>'
        upstream = MagicMock()
        upstream.status_code = 200
        upstream.content = xml_body
        upstream.headers = {"content-type": "application/samlmetadata+xml"}
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=upstream)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/auth/saml/acme-corp/metadata")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, xml_body)
        self.assertEqual(resp.headers["content-type"], "application/samlmetadata+xml")

    def test_forwards_org_slug_in_path(self) -> None:
        """The path's org_slug segment is forwarded into the upstream URL."""
        upstream = MagicMock()
        upstream.status_code = 200
        upstream.content = b"<xml/>"
        upstream.headers = {"content-type": "application/samlmetadata+xml"}
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=upstream)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/auth/saml/some-org-slug/metadata")

        call_args = mock_client.get.call_args
        self.assertTrue(call_args.args[0].endswith("/auth/saml/some-org-slug/metadata"))

    def test_forwards_404_for_unknown_org(self) -> None:
        """A 404 for an unknown org slug is relayed as a 404."""
        upstream = MagicMock()
        upstream.status_code = 404
        upstream.content = b'{"detail": "Unknown organization"}'
        upstream.headers = {"content-type": "application/json"}
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=upstream)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/auth/saml/unknown-org/metadata")
        self.assertEqual(resp.status_code, 404)

    def test_no_authorization_header_required(self) -> None:
        """This upstream endpoint is deliberately unauthenticated -- the
        proxy must not require or forward one."""
        upstream = MagicMock()
        upstream.status_code = 200
        upstream.content = b"<xml/>"
        upstream.headers = {"content-type": "application/samlmetadata+xml"}
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=upstream)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/auth/saml/acme-corp/metadata")
        self.assertEqual(resp.status_code, 200)

    def test_auth_service_unreachable_returns_503(self) -> None:
        """A connection failure to the auth-service returns 503 with an
        "auth-service unreachable" message."""
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("control_center.api.routes_org_saml_proxy.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/auth/saml/acme-corp/metadata")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])


if __name__ == "__main__":
    unittest.main()
