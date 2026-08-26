"""Deterministic tests for control-center defensive boundary paths."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.datastructures import Headers
from starlette.requests import Request

from control_center.api import routes_auth_proxy, routes_org_mfa_proxy, routes_storage
from control_center.checks import audit_trail


def request(*, headers=None, query=None, body=b"", cookies=None):
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    req = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": raw_headers,
            "query_string": (query or "").encode(),
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 1),
        },
        receive=receive,
    )
    if cookies is not None:
        req._headers = Headers(raw=raw_headers)
    return req


def async_http_context(response=None, side_effect=None):
    client = MagicMock()
    client.get = AsyncMock(return_value=response, side_effect=side_effect)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


@pytest.mark.asyncio
async def test_oauth_authorize_redirect_is_relayed_without_consuming_it():
    upstream = MagicMock(status_code=302)
    upstream.headers = {"location": "https://auth.example/callback"}
    req = request(headers={"authorization": "Bearer token"}, query="state=abc")
    context = async_http_context(upstream)

    with patch.object(routes_auth_proxy.httpx, "AsyncClient", return_value=context):
        response = await routes_auth_proxy.auth_first_party_authorize_proxy(req)

    assert response.status_code == 302
    assert response.headers["location"] == "https://auth.example/callback"
    client = context.__aenter__.return_value
    client.get.assert_awaited_once()
    assert client.get.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}
    assert client.get.call_args.kwargs["params"] == {"state": "abc"}


@pytest.mark.asyncio
async def test_oauth_authorize_non_json_response_becomes_error_payload():
    upstream = MagicMock(status_code=500)
    upstream.headers.get.return_value = None
    upstream.json.side_effect = ValueError("not json")
    context = async_http_context(upstream)

    with patch.object(routes_auth_proxy.httpx, "AsyncClient", return_value=context):
        response = await routes_auth_proxy.auth_first_party_authorize_proxy(request())

    assert response.status_code == 500
    assert response.body == b'{"error":"auth-service returned a non-JSON response"}'


@pytest.mark.asyncio
async def test_oauth_authorize_request_error_returns_503():
    context = async_http_context(side_effect=httpx.ConnectError("refused"))
    with patch.object(routes_auth_proxy.httpx, "AsyncClient", return_value=context):
        response = await routes_auth_proxy.auth_first_party_authorize_proxy(request())
    assert response.status_code == 503
    assert b"auth-service unreachable" in response.body


@pytest.mark.asyncio
async def test_logout_malformed_body_is_replaced_with_empty_json():
    forwarded = AsyncMock(return_value=MagicMock(status_code=200))
    with patch.object(routes_auth_proxy, "_proxy_to_auth", forwarded):
        await routes_auth_proxy.auth_logout_proxy(request(body=b"not-json"))
    forwarded.assert_awaited_once()
    assert forwarded.call_args.kwargs["body"] == b"{}"


@pytest.mark.asyncio
async def test_mfa_proxy_returns_empty_response_without_parsing_body():
    upstream = MagicMock(status_code=204, content=b"")
    context = async_http_context(upstream)
    context.__aenter__.return_value.request = AsyncMock(return_value=upstream)
    with patch.object(routes_org_mfa_proxy.httpx, "AsyncClient", return_value=context):
        response = await routes_org_mfa_proxy._proxy("DELETE", "/orgs/1/mfa-policy", request())
    assert response.status_code == 204
    assert response.body == b""


def test_storage_refresh_failure_keeps_stale_snapshot():
    class FailedFuture:
        def done(self):
            return True

        def result(self):
            raise RuntimeError("scan failed")

    future = FailedFuture()
    old_cache = (0.0, {"disk": {"used": 10}})
    with patch.object(routes_storage, "_storage_cache", old_cache), patch.object(
        routes_storage, "_storage_refresh", future
    ), patch.object(routes_storage.time, "monotonic", return_value=1000.0):
        result = routes_storage._cached_storage(MagicMock())
    assert result == old_cache[1]
    assert routes_storage._storage_refresh is None


def test_audit_verification_fails_closed_on_unexpected_compare_error():
    with patch.object(audit_trail.hmac, "compare_digest", side_effect=RuntimeError("bad crypto")):
        assert audit_trail.verify_audit_event("gateway", "{}", "v1:abc", "secret") is False
