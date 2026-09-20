"""
tests/test_routes_rag_proxy.py

Unit tests for:
  - control_center.api.routes_rag_proxy
    (GET /rag/studies, GET /rag/cache-stats, GET /rag/health)

Auth model under test: omnibioai-rag's HIPAA-V2-001 R4/R6 model. Every route
forwards the *caller's own* Authorization header to RAG unchanged and never
injects a shared/service credential (RAG accepts none): /v1/studies needs an
IAM-verified dataset.read, /v1/cache/stats an IAM-verified manage_all_orgs,
and RAG stays the sole authority on both -- a RAG 401/403 is relayed as-is,
never turned into a success. Control Center's own platform.manage_infra
gate still runs first on /rag/studies and /rag/cache-stats, so an
unauthenticated or wrongly-permissioned caller never reaches RAG at all.

Every response relayed from RAG carries X-Upstream-Service: rag, so the
frontend can tell a RAG-originated 401 apart from control-center's own
401 (invalid admin session) without matching error wording; a response
control-center generates itself never carries it.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
from fastapi.testclient import TestClient

from control_center.api import routes_rag_proxy
from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app

client = TestClient(app)

UPSTREAM_HEADER = "X-Upstream-Service"


def _admin_headers() -> dict:
    """A valid caller token carrying platform.manage_infra -- what any
    account holding the 'admin' role hasAdminAccess() checks for actually
    gets issued (omnibioai-auth's app/db/init_admin.py seeds it onto the
    admin role), so this is exactly what a legitimate viewer of the RAG
    page in Admin Console sends."""
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
    """A MagicMock httpx.Response stand-in; raise_json_error makes
    .json() raise ValueError instead of returning json_body."""
    resp = MagicMock()
    resp.status_code = status_code
    if raise_json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    return resp


def _mock_async_client(response: MagicMock | None = None, side_effect=None):
    """An async-context-manager mock of httpx.AsyncClient whose .get()
    returns `response`, or raises `side_effect` if given."""
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


def _upstream_call_headers(mock_ctx) -> dict:
    return mock_ctx.__aenter__.return_value.get.call_args.kwargs["headers"]


_STUDIES_OUT = {"studies": [{"name": "covid19", "abstract_count": 1204}, {"name": "oncology", "abstract_count": 831}]}
_CACHE_STATS_OUT = {"enabled": True, "connected": True, "cached_queries": 42, "ttl_seconds": 3600, "hits": 120, "misses": 30, "hit_rate": 80.0}
_HEALTH_OUT = {"status": "ok", "version": "1.1.0", "faiss_version": "1.8.0", "cache": {"enabled": True, "connected": True, "cached_queries": 42, "hit_rate": 80.0}}

# The two RAG-gated routes and the upstream permission RAG itself requires
# for each -- used to run identical assertions over both.
_RAG_ROUTES = (
    ("/rag/studies", "dataset.read", _STUDIES_OUT),
    ("/rag/cache-stats", "manage_all_orgs", _CACHE_STATS_OUT),
)


class TestCallerTokenForwarding(unittest.TestCase):
    """The caller's own Authorization header -- and nothing else -- reaches RAG."""

    def test_forwards_callers_own_authorization(self) -> None:
        """A and B: both routes send the caller's exact Authorization header upstream."""
        for path, _perm, body in _RAG_ROUTES:
            with self.subTest(path=path):
                upstream = _mock_response(200, body)
                mock_ctx = _mock_async_client(upstream)
                admin_headers = _admin_headers()
                with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx):
                    resp = client.get(path, headers=admin_headers)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(_upstream_call_headers(mock_ctx)["Authorization"], admin_headers["Authorization"])

    def test_static_service_key_is_never_injected(self) -> None:
        """C: even with RAGBIO_API_KEY present in the environment, it is not sent
        to RAG, and this module no longer reads it at all."""
        self.assertFalse(hasattr(routes_rag_proxy, "RAGBIO_API_KEY"))
        for path, _perm, body in _RAG_ROUTES:
            with self.subTest(path=path):
                upstream = _mock_response(200, body)
                mock_ctx = _mock_async_client(upstream)
                with patch.dict(os.environ, {"RAGBIO_API_KEY": "the-service-secret"}), \
                     patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx):
                    client.get(path, headers=_admin_headers())
                sent = _upstream_call_headers(mock_ctx)
                self.assertNotIn("the-service-secret", str(sent))
                self.assertNotEqual(sent["Authorization"], "Bearer the-service-secret")

    def test_relayed_responses_carry_the_upstream_marker(self) -> None:
        """Every response relayed from RAG is tagged so the frontend can tell it
        apart from control-center's own 401."""
        for path, _perm, body in _RAG_ROUTES:
            with self.subTest(path=path):
                with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(_mock_response(200, body))):
                    resp = client.get(path, headers=_admin_headers())
                self.assertEqual(resp.headers.get(UPSTREAM_HEADER), "rag")


class TestUpstreamRefusalsAreRelayed(unittest.TestCase):
    """RAG stays authoritative: its refusals reach the caller unchanged."""

    def test_rag_403_remains_403_and_never_becomes_success(self) -> None:
        """E, H, I: a caller who passes control-center's gate but lacks RAG's own
        permission (dataset.read for studies, manage_all_orgs for cache stats) gets
        RAG's 403 back, tagged as upstream."""
        for path, perm, _body in _RAG_ROUTES:
            with self.subTest(path=path, upstream_requires=perm):
                upstream = _mock_response(403, {"detail": "Insufficient permissions"})
                with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
                    resp = client.get(path, headers=_admin_headers())
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.json()["detail"], "Insufficient permissions")
                self.assertEqual(resp.headers.get(UPSTREAM_HEADER), "rag")

    def test_rag_401_is_relayed_as_401_and_tagged_upstream(self) -> None:
        """F (server half): RAG rejecting the forwarded token is a 401 marked as
        upstream-originated -- never disguised as, or stripped down to, an
        indistinguishable control-center 401."""
        for path, _perm, _body in _RAG_ROUTES:
            with self.subTest(path=path):
                upstream = _mock_response(401, {"detail": "Invalid, expired, or revoked token"})
                with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
                    resp = client.get(path, headers=_admin_headers())
                self.assertEqual(resp.status_code, 401)
                self.assertEqual(resp.headers.get(UPSTREAM_HEADER), "rag")

    def test_rag_service_unreachable_returns_503_without_upstream_marker(self) -> None:
        """A connection failure to RAG returns 503 generated by control-center itself."""
        for path, _perm, _body in _RAG_ROUTES:
            with self.subTest(path=path):
                with patch(
                    "control_center.api.routes_rag_proxy.httpx.AsyncClient",
                    return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
                ):
                    resp = client.get(path, headers=_admin_headers())
                self.assertEqual(resp.status_code, 503)
                self.assertIn("rag-service unreachable", resp.json()["error"])
                self.assertNotIn(UPSTREAM_HEADER, resp.headers)

    def test_non_json_upstream_response_handled(self) -> None:
        """A non-JSON upstream response body maps to the same status with a
        "non-JSON" error message rather than propagating the parse exception."""
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/rag/studies", headers=_admin_headers())
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestControlCenterGateStillRunsFirst(unittest.TestCase):
    """control-center's own platform.manage_infra gate on /rag/studies and
    /rag/cache-stats is unchanged -- and RAG is never contacted when it refuses."""

    def _cases(self):
        return ("/rag/studies", "/rag/cache-stats")

    def test_401_when_no_token_and_rag_is_never_called(self) -> None:
        """D: no caller authentication fails closed at control-center (401,
        not marked upstream), with no upstream call made."""
        for path in self._cases():
            with self.subTest(path=path):
                mock_ctx = _mock_async_client(_mock_response(200, _STUDIES_OUT))
                with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx):
                    resp = client.get(path)
                self.assertEqual(resp.status_code, 401)
                self.assertNotIn(UPSTREAM_HEADER, resp.headers)
                mock_ctx.__aenter__.assert_not_called()

    def test_401_when_token_is_invalid_and_rag_is_never_called(self) -> None:
        """G (server half): a garbage/forged token is a control-center-originated
        401 -- unmarked, so the frontend still treats it as a genuine session
        failure -- and RAG is never contacted."""
        for path in self._cases():
            with self.subTest(path=path):
                mock_ctx = _mock_async_client(_mock_response(200, _STUDIES_OUT))
                with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx):
                    resp = client.get(path, headers={"Authorization": "Bearer not-a-real-token"})
                self.assertEqual(resp.status_code, 401)
                self.assertNotIn(UPSTREAM_HEADER, resp.headers)
                mock_ctx.__aenter__.assert_not_called()

    def test_403_for_cron_permission_only_and_rag_is_never_called(self) -> None:
        """A token holding an unrelated permission is refused by control-center (403)."""
        for path in self._cases():
            with self.subTest(path=path):
                mock_ctx = _mock_async_client(_mock_response(200, _STUDIES_OUT))
                with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx):
                    resp = client.get(path, headers=_cron_only_headers())
                self.assertEqual(resp.status_code, 403)
                self.assertNotIn(UPSTREAM_HEADER, resp.headers)
                mock_ctx.__aenter__.assert_not_called()

    def test_not_401_or_403_with_infra_permission(self) -> None:
        """A token holding platform.manage_infra passes control-center's own gate."""
        upstream = _mock_response(200, _STUDIES_OUT)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            for path in self._cases():
                with self.subTest(path=path):
                    resp = client.get(path, headers=_admin_headers())
                    self.assertNotIn(resp.status_code, (401, 403))


class TestHealthProxy(unittest.TestCase):
    """GET /health's thin-relay behavior -- unauthenticated upstream, no
    control-center gate, whatever the caller sent is forwarded, nothing fabricated."""

    def test_forwards_success_response(self) -> None:
        """A successful upstream response's body is relayed unchanged."""
        upstream = _mock_response(200, _HEALTH_OUT)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/rag/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), _HEALTH_OUT)

    def test_forwards_callers_own_header_and_never_a_service_key(self) -> None:
        """If the caller sent an Authorization header it is forwarded as-is (RAG
        ignores it on /health); an environment RAGBIO_API_KEY is never injected."""
        upstream = _mock_response(200, _HEALTH_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx), \
             patch.dict(os.environ, {"RAGBIO_API_KEY": "the-service-secret"}):
            client.get("/rag/health", headers={"Authorization": "Bearer admin-own-token"})
        self.assertEqual(_upstream_call_headers(mock_ctx)["Authorization"], "Bearer admin-own-token")

    def test_forwards_no_authorization_header_when_caller_sent_none(self) -> None:
        """With no caller Authorization header, none is sent upstream --
        nothing fabricated."""
        upstream = _mock_response(200, _HEALTH_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/rag/health")
        self.assertNotIn("Authorization", _upstream_call_headers(mock_ctx))

    def test_non_json_upstream_response_handled(self) -> None:
        """A non-JSON upstream response body maps to the same status
        code with a "non-JSON" error message."""
        upstream = _mock_response(502, raise_json_error=True)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/rag/health")
        self.assertEqual(resp.status_code, 502)
        self.assertIn("non-JSON", resp.json()["error"])


if __name__ == "__main__":
    unittest.main()
