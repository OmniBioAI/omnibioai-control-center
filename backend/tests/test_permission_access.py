"""Named-permission contract for Studio's shared nginx auth_request gate."""

import jwt
from fastapi.testclient import TestClient

from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app


client = TestClient(app)


def _headers(token_permissions: list[str], required: str) -> dict[str, str]:
    token = jwt.encode(
        {"sub": "studio-nginx-gate-test", "permissions": token_permissions},
        JWT_SECRET,
        algorithm="HS256",
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Required-Permission": required,
    }


def test_named_permission_gate_rejects_non_admin():
    response = client.get(
        "/access/permission",
        headers=_headers(["workflow.read"], "platform.manage_infra"),
    )
    assert response.status_code == 403


def test_named_permission_gate_accepts_each_reviewed_admin_permission():
    for permission in ("platform.manage_infra", "manage_config", "manage_all_orgs"):
        response = client.get(
            "/access/permission",
            headers=_headers([permission], permission),
        )
        assert response.status_code == 200
        assert response.json() == {"allowed": True, "permission": permission}


def test_named_permission_gate_rejects_missing_session():
    response = client.get(
        "/access/permission",
        headers={"X-Required-Permission": "manage_config"},
    )
    assert response.status_code == 401


def test_named_permission_gate_rejects_unreviewed_permission_name():
    response = client.get(
        "/access/permission",
        headers=_headers(["workflow.execute"], "workflow.execute"),
    )
    assert response.status_code == 400
