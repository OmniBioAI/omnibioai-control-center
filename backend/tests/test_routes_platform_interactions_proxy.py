"""
tests/test_routes_platform_interactions_proxy.py

Unit tests for:
  - control_center.api.routes_platform_interactions_proxy
    (GET /platform/interactions, GET /platform/interactions/{interaction_id})

Mirrors test_routes_sessions_proxy.py's / test_routes_audit_proxy.py's
exact conventions -- this route is a thin relay, no authorization
decision is made here (that's entirely omnibioai-auth's job:
GET /platform/interactions is platform-admin-only,
require_permission(manage_all_orgs), PR-B5-A).
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


_INTERACTION = {
    "id": 1,
    "interaction_id": "becbce38-0ada-427c-a29c-4c1bdfd95095",
    "organization_id": 339,
    "user_id": 630,
    "session_id": None,
    "trace_id": "verify-trace-1",
    "service": "rag",
    "interaction_type": "query",
    "action": "rag.query",
    "resource_type": "study",
    "resource_id": "default",
    "status": "success",
    "decision": None,
    "metadata": {"mode": "rag", "top_k": 3},
    "created_at": "2026-08-10T01:41:38",
}

_LIST_RESPONSE = {
    "items": [_INTERACTION],
    "total": 1,
    "page": 1,
    "page_size": 20,
    "total_pages": 1,
}


class TestListInteractionsProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _LIST_RESPONSE)
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(upstream),
        ):
            resp = client.get("/platform/interactions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["items"][0]["interaction_id"], _INTERACTION["interaction_id"])
        # Never leaks anything token/secret-shaped, even indirectly.
        body_text = resp.text
        for forbidden in ("access_token", "refresh_token", "hashed_password", "jwt", "cookie"):
            self.assertNotIn(forbidden, body_text.lower())

    def test_envelope_preserved_exactly(self) -> None:
        upstream = _mock_response(200, _LIST_RESPONSE)
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(upstream),
        ):
            resp = client.get("/platform/interactions", headers={"Authorization": "Bearer tok"})
        body = resp.json()
        self.assertEqual(set(body.keys()), {"items", "total", "page", "page_size", "total_pages"})
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["page_size"], 20)
        self.assertEqual(body["total_pages"], 1)

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, _LIST_RESPONSE)
        mock_ctx = _mock_async_client(upstream)
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=mock_ctx,
        ):
            client.get("/platform/interactions", headers={"Authorization": "Bearer my-token-123"})
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-token-123")

    def test_missing_authorization_header_is_not_forged(self) -> None:
        # No Authorization header on the incoming request -- the proxy
        # must not invent one; omnibioai-auth's own get_current_user is
        # what actually rejects the request (mocked here as a 401, same
        # as test_upstream_401_is_forwarded below covers end-to-end).
        upstream = _mock_response(200, _LIST_RESPONSE)
        mock_ctx = _mock_async_client(upstream)
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=mock_ctx,
        ):
            client.get("/platform/interactions")
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertNotIn("Authorization", call_kwargs["headers"])

    def test_query_parameters_forwarded_unchanged(self) -> None:
        upstream = _mock_response(200, _LIST_RESPONSE)
        mock_ctx = _mock_async_client(upstream)
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=mock_ctx,
        ):
            client.get(
                "/platform/interactions",
                params={
                    "page": 2, "page_size": 50, "organization_id": 339, "user_id": 630,
                    "service": "rag", "interaction_type": "query", "status": "success",
                    "start_date": "2026-01-01T00:00:00", "end_date": "2026-12-31T00:00:00",
                },
                headers={"Authorization": "Bearer tok"},
            )
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        forwarded_params = call_kwargs["params"]
        self.assertEqual(forwarded_params["page"], "2")
        self.assertEqual(forwarded_params["page_size"], "50")
        self.assertEqual(forwarded_params["organization_id"], "339")
        self.assertEqual(forwarded_params["user_id"], "630")
        self.assertEqual(forwarded_params["service"], "rag")
        self.assertEqual(forwarded_params["interaction_type"], "query")
        self.assertEqual(forwarded_params["status"], "success")
        self.assertEqual(forwarded_params["start_date"], "2026-01-01T00:00:00")
        self.assertEqual(forwarded_params["end_date"], "2026-12-31T00:00:00")

    def test_upstream_401_is_forwarded(self) -> None:
        upstream = _mock_response(401, {"detail": "Not authenticated"})
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(upstream),
        ):
            resp = client.get("/platform/interactions")
        self.assertEqual(resp.status_code, 401)

    def test_upstream_403_is_forwarded(self) -> None:
        # A valid token lacking manage_all_orgs -- omnibioai-auth's own
        # require_permission is the only authority here; this proxy makes
        # no RBAC decision and must not turn a 403 into anything else.
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(upstream),
        ):
            resp = client.get("/platform/interactions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get("/platform/interactions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("auth-service unreachable", resp.json()["error"])

    def test_network_timeout_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.TimeoutException("timed out")),
        ):
            resp = client.get("/platform/interactions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 503)

    def test_non_json_upstream_response_handled(self) -> None:
        upstream = _mock_response(500, raise_json_error=True)
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(upstream),
        ):
            resp = client.get("/platform/interactions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("non-JSON", resp.json()["error"])

    def test_upstream_5xx_is_forwarded(self) -> None:
        upstream = _mock_response(500, {"detail": "Internal Server Error"})
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(upstream),
        ):
            resp = client.get("/platform/interactions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 500)

    def test_empty_upstream_body_preserved(self) -> None:
        upstream = MagicMock()
        upstream.status_code = 200
        upstream.content = b""
        upstream.json.side_effect = ValueError("no content to parse")
        mock_ctx = _mock_async_client(upstream)
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=mock_ctx,
        ):
            resp = client.get("/platform/interactions", headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"")


class TestGetInteractionProxy(unittest.TestCase):
    def test_forwards_success_response(self) -> None:
        upstream = _mock_response(200, _INTERACTION)
        mock_ctx = _mock_async_client(upstream)
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=mock_ctx,
        ):
            resp = client.get(
                f"/platform/interactions/{_INTERACTION['interaction_id']}",
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["interaction_id"], _INTERACTION["interaction_id"])
        forwarded_path = mock_ctx.__aenter__.return_value.request.call_args.args[1]
        self.assertTrue(forwarded_path.endswith(f"/platform/interactions/{_INTERACTION['interaction_id']}"))

    def test_upstream_404_for_unknown_interaction_id(self) -> None:
        upstream = _mock_response(404, {"detail": "Interaction not found"})
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(upstream),
        ):
            resp = client.get(
                "/platform/interactions/does-not-exist", headers={"Authorization": "Bearer tok"}
            )
        self.assertEqual(resp.status_code, 404)

    def test_upstream_403_is_forwarded(self) -> None:
        upstream = _mock_response(403, {"detail": "Forbidden"})
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(upstream),
        ):
            resp = client.get(
                f"/platform/interactions/{_INTERACTION['interaction_id']}",
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 403)

    def test_forwards_authorization_header(self) -> None:
        upstream = _mock_response(200, _INTERACTION)
        mock_ctx = _mock_async_client(upstream)
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=mock_ctx,
        ):
            client.get(
                f"/platform/interactions/{_INTERACTION['interaction_id']}",
                headers={"Authorization": "Bearer owner-token"},
            )
        call_kwargs = mock_ctx.__aenter__.return_value.request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer owner-token")

    def test_auth_service_unreachable_returns_503(self) -> None:
        with patch(
            "control_center.api.routes_platform_interactions_proxy.httpx.AsyncClient",
            return_value=_mock_async_client(side_effect=httpx.ConnectError("refused")),
        ):
            resp = client.get(
                f"/platform/interactions/{_INTERACTION['interaction_id']}",
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
