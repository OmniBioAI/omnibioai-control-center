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
    result = MagicMock(status_code=status, content=content)
    result.json.return_value = payload
    return result


def http_client(result=None):
    client_mock = MagicMock()
    client_mock.request = AsyncMock(return_value=result)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client_mock)
    context.__aexit__ = AsyncMock(return_value=False)
    return context, client_mock


def request(query: str = "", authorization: str | None = None) -> Request:
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]
    return Request({"type": "http", "method": "GET", "path": "/audit/events/safe", "query_string": query.encode(), "headers": headers})


def call(query: str = "", authorization: str | None = None):
    return asyncio.run(list_security_audit_events(request(query, authorization)))


def test_safe_proxy_forwards_auth_allowlisted_queries_and_response():
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
    route = next(item for item in router.routes if item.path == "/audit/events/safe")
    assert route.methods == {"GET"}
