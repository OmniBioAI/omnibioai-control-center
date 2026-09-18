"""tests/test_routes_security_audit_proxy.py -- control_center.api.
routes_security_audit_proxy: GET /audit/events/safe, a read-only proxy in
front of security-audit's /audit/events. Forwards the caller's
Authorization header and an allowlisted subset of query params (dropping
anything not on that list, e.g. "context"), maps upstream auth/validation/
source-availability failures to fixed error codes without leaking the
upstream response's own detail text, and treats a transport failure or a
non-JSON upstream body the same way as an explicit AUDIT_SOURCE_UNAVAILABLE.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request

from control_center.api.routes_security_audit_proxy import (
    list_security_audit_events,
    router,
)


def response(status: int, payload=None, content: bytes = b"json"):
    """A MagicMock httpx.Response stand-in with a fixed status/JSON body."""
    result = MagicMock(status_code=status, content=content)
    result.json.return_value = payload
    return result


def http_client(result=None):
    """An async-context-manager mock of httpx.AsyncClient whose .request()
    returns `result`; also returns the inner client mock for assertions."""
    client_mock = MagicMock()
    client_mock.request = AsyncMock(return_value=result)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client_mock)
    context.__aexit__ = AsyncMock(return_value=False)
    return context, client_mock


def request(query: str = "", authorization: str | None = None) -> Request:
    """A minimal Starlette GET Request for /audit/events/safe with the
    given raw query string and optional Authorization header."""
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]
    return Request({"type": "http", "method": "GET", "path": "/audit/events/safe", "query_string": query.encode(), "headers": headers})


def call(query: str = "", authorization: str | None = None):
    """Run list_security_audit_events() synchronously against a built
    request()."""
    return asyncio.run(list_security_audit_events(request(query, authorization)))


def test_safe_proxy_forwards_auth_allowlisted_queries_and_response():
    """A successful upstream call: the response body/status pass through,
    an allowlisted query param (service) is forwarded, a non-allowlisted
    one (context) is dropped, and the Authorization header is forwarded
    verbatim."""
    upstream = response(200, {"source_availability": "AVAILABLE", "items": []})
    context, client_mock = http_client(upstream)
    with patch("control_center.api.routes_security_audit_proxy.httpx.AsyncClient", return_value=context):
        result = call("page=2&service=gateway&context=secret", "Bearer verified")
    assert result.status_code == 200
    assert json.loads(result.body)["source_availability"] == "AVAILABLE"
    kwargs = client_mock.request.await_args.kwargs
    assert ("service", "gateway") in kwargs["params"]
    assert not any(key == "context" for key, _ in kwargs["params"])
    assert kwargs["headers"] == {"Authorization": "Bearer verified"}


def test_safe_proxy_maps_auth_validation_and_source_failures_without_details():
    """Each known upstream failure status (401/403/422/503) maps to a
    fixed {"error": CODE} body with the upstream's own "detail" text
    never appearing in the response; an unrecognized 5xx also collapses
    to AUDIT_SOURCE_UNAVAILABLE rather than passing the raw status through."""
    for status, error in ((401, "UNAUTHENTICATED"), (403, "FORBIDDEN"), (422, "VALIDATION_ERROR"), (503, "AUDIT_SOURCE_UNAVAILABLE")):
        context, _ = http_client(response(status, {"detail": "internal"}))
        with patch("control_center.api.routes_security_audit_proxy.httpx.AsyncClient", return_value=context):
            result = call()
        assert result.status_code == status
        assert json.loads(result.body) == {"error": error}
        assert b"internal" not in result.body

    context, _ = http_client(response(500, {"detail": "internal"}))
    with patch("control_center.api.routes_security_audit_proxy.httpx.AsyncClient", return_value=context):
        result = call()
    assert result.status_code == 503
    assert json.loads(result.body) == {"error": "AUDIT_SOURCE_UNAVAILABLE"}
    assert b"internal" not in result.body


def test_safe_proxy_maps_transport_and_non_json_failures_to_unavailable():
    """A 200 response with a non-JSON body, and a raw transport-level
    httpx.RequestError, both map to AUDIT_SOURCE_UNAVAILABLE with no
    leakage of the underlying exception/URL text into the response."""
    non_json = response(200, None, content=b"not-json")
    non_json.json.side_effect = ValueError("not-json")
    context, mock_client = http_client(non_json)
    with patch("control_center.api.routes_security_audit_proxy.httpx.AsyncClient", return_value=context):
        result = call()
    assert result.status_code == 503
    assert json.loads(result.body) == {"error": "AUDIT_SOURCE_UNAVAILABLE"}

    context, mock_client = http_client()
    mock_client.request.side_effect = __import__("httpx").RequestError("internal url")
    with patch("control_center.api.routes_security_audit_proxy.httpx.AsyncClient", return_value=context):
        result = call()
    assert result.status_code == 503
    assert b"internal url" not in result.body


def test_safe_proxy_is_read_only():
    """The /audit/events/safe route only accepts GET -- no write verb is
    registered on this read-only proxy."""
    route = next(item for item in router.routes if item.path == "/audit/events/safe")
    assert route.methods == {"GET"}
