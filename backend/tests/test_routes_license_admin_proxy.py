"""Focused relay tests for Manual Licenses administration routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from control_center.main import app


client = TestClient(app)


def upstream(status: int, payload=None, *, content: bytes = b"json", json_error: bool = False):
    response = MagicMock()
    response.status_code = status
    response.content = content
    if json_error:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = payload
    return response


def async_client(response=None, *, error=None):
    transport = MagicMock()
    transport.request = AsyncMock(side_effect=error) if error else AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=transport)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


def test_policy_forwards_bearer_token_and_returns_json() -> None:
    response = upstream(200, {"validity_days": [30], "issuance_enabled": False})
    context = async_client(response)
    with patch("control_center.api.routes_license_admin_proxy.httpx.AsyncClient", return_value=context):
        result = client.get("/platform/licenses/policy", headers={"Authorization": "Bearer isolated-test-token"})

    assert result.status_code == 200
    assert result.headers["content-type"] == "application/json"
    call = context.__aenter__.return_value.request.call_args
    assert call.args[:2] == ("GET", "http://auth-service:8001/platform/licenses/policy")
    assert call.kwargs["headers"]["Authorization"] == "Bearer isolated-test-token"


def test_unauthorized_issuance_is_preserved() -> None:
    response = upstream(403, {"detail": "Forbidden"})
    with patch(
        "control_center.api.routes_license_admin_proxy.httpx.AsyncClient",
        return_value=async_client(response),
    ):
        result = client.post("/platform/licenses", json={"email": "test@example.invalid"})

    assert result.status_code == 403
    assert result.json() == {"detail": "Forbidden"}


def test_idempotency_key_is_forwarded_for_issuance() -> None:
    response = upstream(201, {"key": "one-time-test-key"})
    context = async_client(response)
    with patch("control_center.api.routes_license_admin_proxy.httpx.AsyncClient", return_value=context):
        result = client.post(
            "/platform/licenses",
            headers={"Idempotency-Key": "isolated-test-idempotency-key"},
            json={"email": "test@example.invalid"},
        )

    assert result.status_code == 201
    headers = context.__aenter__.return_value.request.call_args.kwargs["headers"]
    assert headers["Idempotency-Key"] == "isolated-test-idempotency-key"


def test_backend_unavailable_returns_json_503() -> None:
    with patch(
        "control_center.api.routes_license_admin_proxy.httpx.AsyncClient",
        return_value=async_client(error=httpx.ConnectError("refused")),
    ):
        result = client.get("/platform/licenses/policy")

    assert result.status_code == 503
    assert result.headers["content-type"] == "application/json"
    assert "auth-service unreachable" in result.json()["error"]


def test_non_json_upstream_is_normalized_to_json() -> None:
    response = upstream(502, content=b"<html>bad gateway</html>", json_error=True)
    with patch(
        "control_center.api.routes_license_admin_proxy.httpx.AsyncClient",
        return_value=async_client(response),
    ):
        result = client.get("/platform/licenses/policy")

    assert result.status_code == 502
    assert result.headers["content-type"] == "application/json"
    assert result.json() == {"error": "auth-service returned a non-JSON response"}
