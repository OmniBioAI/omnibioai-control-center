"""
tests/test_routes_rag_proxy.py

Unit tests for:
  - control_center.api.routes_rag_proxy
    (GET /rag/studies, GET /rag/cache-stats, GET /rag/health)

Mirrors test_routes_tes_proxy.py's exact conventions for the thin-relay
behavior (success, upstream unavailable, invalid JSON, status
propagation). Additionally asserts the auth-injection behavior specific
to this proxy: /rag/studies and /rag/cache-stats send the
control-center-held RAGBIO_API_KEY (never the caller's own Authorization
header) since omnibioai-rag's own `_verify` dependency requires the
bearer token to literally equal that shared secret; /rag/health sends no
Authorization header at all, matching GET /health's lack of auth
upstream.

SECURITY FIX (post-PR-A4 audit): /rag/studies and /rag/cache-stats now
require Depends(require_permission("platform.manage_infra")) directly on
the route (see routes_rag_proxy.py's own module comment) -- until this
fix, both were reachable with no caller authentication at all, since
RAGBIO_API_KEY injection means there's no upstream per-caller check to
fall back on either. Every test below that exercises _proxy's own
relay logic (success/unreachable/non-JSON/status-propagation) now
carries a valid platform.manage_infra token by default, same convention
test_routes_docker.py/test_routes_config.py use for their own
router-inclusion-gated routes; TestStudiesAndCacheStatsAuthorization
below is the permanent regression guard for the authorization layer
itself, mirroring test_main.py's TestPlatformManageInfraAuth. /rag/health
carries no such requirement, matching its no-auth-upstream behavior.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
from fastapi.testclient import TestClient

from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app

client = TestClient(app)


def _admin_headers() -> dict:
    """A valid caller token carrying platform.manage_infra -- what any
    account holding the 'admin' role hasAdminAccess() checks for actually
    gets issued (omnibioai-auth's app/db/init_admin.py seeds it onto the
    admin role), so this is exactly what a legitimate viewer of the RAG
    page in Admin Console sends. Deliberately distinct from the
    RAGBIO_API_KEY service secret asserted against below -- proves the
    two are never confused in either direction."""
    token = jwt.encode(
        {"sub": "1", "roles": ["admin"], "permissions": ["platform.manage_infra"]},
        JWT_SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _cron_only_headers() -> dict:
    """Isolation fixture: holds platform.manage_cron only -- proves it
    does not satisfy /rag/studies and /rag/cache-stats' platform.manage_infra
    requirement, same isolation check test_main.py's
    TestPlatformManageInfraAuth already runs for the sibling infra
    routers."""
    token = jwt.encode({"sub": "3", "permissions": ["platform.manage_cron"]}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _mock_response(status_code: int, json_body=None, raise_json_error: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if raise_json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    return resp


def _mock_async_client(response: MagicMock | None = None, side_effect=None):
    mock_client = MagicMock()
    mock_get = AsyncMock()
    if side_effect is not None:
        mock_get.side_effect = side_effect
    else:
        mock_get.return_value = response
    mock_client.get = mock_get

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


_STUDIES_OUT = {"studies": [{"name": "covid19", "abstract_count": 1204}, {"name": "oncology", "abstract_count": 831}]}
_CACHE_STATS_OUT = {"enabled": True, "connected": True, "cached_queries": 42, "ttl_seconds": 3600, "hits": 120, "misses": 30, "hit_rate": 80.0}
_HEALTH_OUT = {"status": "ok", "version": "1.1.0", "faiss_version": "1.8.0", "cache": {"enabled": True, "connected": True, "cached_queries": 42, "hit_rate": 80.0}}


class TestListStudiesProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _STUDIES_OUT)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/rag/studies", headers=_admin_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _STUDIES_OUT)

    def test_injects_service_key_not_callers_own_token(self) -> None:
        # The core behavioral guarantee for this endpoint: the caller's
        # own Authorization header must NOT be forwarded -- RAG's
        # _verify requires the bearer token to literally equal
        # RAGBIO_API_KEY, so forwarding the admin's own token would
        # always 403 upstream.
        upstream = _mock_response(200, _STUDIES_OUT)
        mock_ctx = _mock_async_client(upstream)
        admin_headers = _admin_headers()
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx), \
             patch("control_center.api.routes_rag_proxy.RAGBIO_API_KEY", "the-service-secret"):
            client.get("/rag/studies", headers=admin_headers)
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer the-service-secret")
        self.assertNotEqual(call_kwargs["headers"]["Authorization"], admin_headers["Authorization"])

    def test_sends_no_authorization_header_when_service_key_unconfigured(self) -> None:
        upstream = _mock_response(403, {"detail": "Not authenticated"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx), \
             patch("control_center.api.routes_rag_proxy.RAGBIO_API_KEY", ""):
            resp = client.get("/rag/studies", headers=_admin_headers())
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertNotIn("Authorization", call_kwargs["headers"])
        self.assertEqual(resp.status_code, 403)

    def test_rag_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_rag_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/rag/studies", headers=_admin_headers())
        self.assertEqual(resp.status_code, 503)
        self.assertIn("rag-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/rag/studies", headers=_admin_headers())
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestCacheStatsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _CACHE_STATS_OUT)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/rag/cache-stats", headers=_admin_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["hit_rate"], 80.0)

    def test_injects_service_key_not_callers_own_token(self) -> None:
        upstream = _mock_response(200, _CACHE_STATS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx), \
             patch("control_center.api.routes_rag_proxy.RAGBIO_API_KEY", "the-service-secret"):
            client.get("/rag/cache-stats", headers=_admin_headers())
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer the-service-secret")

    def test_rag_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_rag_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/rag/cache-stats", headers=_admin_headers())
        self.assertEqual(resp.status_code, 503)


class TestStudiesAndCacheStatsAuthorization(unittest.TestCase):
    """Permanent regression guard for the SECURITY FIX above: /rag/studies
    and /rag/cache-stats must reject a caller with no token and a caller
    holding the wrong permission, and must accept one holding
    platform.manage_infra -- mirroring test_main.py's
    TestPlatformManageInfraAuth exactly, one level down (per-route
    Depends here instead of router-inclusion-level, since /rag/health in
    the same router must stay ungated -- see routes_rag_proxy.py's own
    module comment for why a blanket router-level dependency doesn't fit
    here the way it does for services_router/docker_router/etc.)."""

    def _cases(self):
        return ("/rag/studies", "/rag/cache-stats")

    def test_401_when_no_token(self) -> None:
        for path in self._cases():
            with self.subTest(path=path):
                resp = client.get(path)
                self.assertEqual(resp.status_code, 401)

    def test_403_for_cron_permission_only(self) -> None:
        for path in self._cases():
            with self.subTest(path=path):
                resp = client.get(path, headers=_cron_only_headers())
                self.assertEqual(resp.status_code, 403)

    def test_not_401_or_403_with_infra_permission(self) -> None:
        upstream = _mock_response(200, _STUDIES_OUT)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            for path in self._cases():
                with self.subTest(path=path):
                    resp = client.get(path, headers=_admin_headers())
                    self.assertNotIn(resp.status_code, (401, 403))


class TestHealthProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _HEALTH_OUT)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/rag/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _HEALTH_OUT)

    def test_never_sends_the_service_key_even_when_configured(self) -> None:
        # GET /health has no auth upstream, so this route must never
        # inject RAGBIO_API_KEY (unlike /rag/studies and
        # /rag/cache-stats) -- if the caller sent their own token, that
        # (harmless, since /health ignores it) is what gets forwarded,
        # same "forward whatever's present, fabricate nothing" behavior
        # every other proxy in this app already has for its own
        # unauthenticated routes (e.g. routes_tes_proxy.py's /tools).
        upstream = _mock_response(200, _HEALTH_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx), \
             patch("control_center.api.routes_rag_proxy.RAGBIO_API_KEY", "the-service-secret"):
            client.get("/rag/health", headers={"Authorization": "Bearer admin-own-token"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer admin-own-token")

    def test_forwards_no_authorization_header_when_caller_sent_none(self) -> None:
        upstream = _mock_response(200, _HEALTH_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/rag/health")
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertNotIn("Authorization", call_kwargs["headers"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(502, raise_json_error=True)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/rag/health")
        self.assertEqual(resp.status_code, 502)
        self.assertIn("non-JSON", resp.json()["error"])


if __name__ == "__main__":
    unittest.main()
