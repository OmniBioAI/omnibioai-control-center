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
            resp = client.get("/rag/studies", headers={"Authorization": "Bearer admin-own-token"})
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
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx), \
             patch("control_center.api.routes_rag_proxy.RAGBIO_API_KEY", "the-service-secret"):
            client.get("/rag/studies", headers={"Authorization": "Bearer admin-own-token"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer the-service-secret")
        self.assertNotIn("admin-own-token", call_kwargs["headers"]["Authorization"])

    def test_sends_no_authorization_header_when_service_key_unconfigured(self) -> None:
        upstream = _mock_response(403, {"detail": "Not authenticated"})
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx), \
             patch("control_center.api.routes_rag_proxy.RAGBIO_API_KEY", ""):
            resp = client.get("/rag/studies", headers={"Authorization": "Bearer admin-own-token"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertNotIn("Authorization", call_kwargs["headers"])
        self.assertEqual(resp.status_code, 403)

    def test_rag_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_rag_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/rag/studies")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("rag-service unreachable", resp.json()["error"])

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/rag/studies")
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])


class TestCacheStatsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _CACHE_STATS_OUT)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=_mock_async_client(upstream)):
            resp = client.get("/rag/cache-stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["hit_rate"], 80.0)

    def test_injects_service_key_not_callers_own_token(self) -> None:
        upstream = _mock_response(200, _CACHE_STATS_OUT)
        mock_ctx = _mock_async_client(upstream)
        with patch("control_center.api.routes_rag_proxy.httpx.AsyncClient", return_value=mock_ctx), \
             patch("control_center.api.routes_rag_proxy.RAGBIO_API_KEY", "the-service-secret"):
            client.get("/rag/cache-stats", headers={"Authorization": "Bearer admin-own-token"})
        call_kwargs = mock_ctx.__aenter__.return_value.get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer the-service-secret")

    def test_rag_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_rag_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/rag/cache-stats")
        self.assertEqual(resp.status_code, 503)


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
