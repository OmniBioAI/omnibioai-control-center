"""Isolated route tests for org invitations, without importing Control Center's full app."""
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from control_center.api.routes_org_proxy import router


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def _upstream(status: int, body):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    upstream_client = MagicMock()
    upstream_client.request = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=upstream_client)
    context.__aexit__ = AsyncMock(return_value=False)
    return context, upstream_client


def test_list_invitation_forwards_identity_and_auth_denial():
    context, upstream_client = _upstream(403, {"detail": "Forbidden"})
    with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=context):
        response = client.get("/orgs/7/invitations", headers={"Authorization": "Bearer synthetic-user"})
    assert response.status_code == 403
    call = upstream_client.request.call_args
    assert call.args[:2] == ("GET", "http://auth-service:8001/orgs/7/invitations")
    assert call.kwargs["headers"]["Authorization"] == "Bearer synthetic-user"


def test_create_and_revoke_invitation_relay_upstream_status():
    context, upstream_client = _upstream(201, {"id": 9, "status": "pending"})
    with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=context):
        created = client.post(
            "/orgs/7/invitations", json={"email": "synthetic@example.com"},
            headers={"Authorization": "Bearer synthetic-admin"},
        )
    assert created.status_code == 201
    assert b"synthetic@example.com" in upstream_client.request.call_args.kwargs["content"]

    context, upstream_client = _upstream(403, {"detail": "Forbidden"})
    with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=context):
        revoked = client.post(
            "/orgs/7/invitations/9/revoke", headers={"Authorization": "Bearer synthetic-user"},
        )
    assert revoked.status_code == 403
    call = upstream_client.request.call_args
    assert call.args[:2] == ("POST", "http://auth-service:8001/orgs/7/invitations/9/revoke")


def test_acceptance_token_remains_in_post_body_and_public_operation_is_allowlisted():
    context, upstream_client = _upstream(200, {"status": "accepted"})
    with patch("control_center.api.routes_org_proxy.httpx.AsyncClient", return_value=context):
        accepted = client.post("/organization-invitations/accept", json={"token": "synthetic-bearer"})
    assert accepted.status_code == 200
    call = upstream_client.request.call_args
    assert call.args[:2] == ("POST", "http://auth-service:8001/organization-invitations/accept")
    assert "synthetic-bearer" not in call.args[1]
    assert b"synthetic-bearer" in call.kwargs["content"]

    with patch("control_center.api.routes_org_proxy.httpx.AsyncClient") as upstream:
        invalid = client.post("/organization-invitations/create-admin", json={"token": "synthetic"})
    assert invalid.status_code == 404
    upstream.assert_not_called()
