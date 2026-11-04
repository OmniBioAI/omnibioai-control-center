"""Authorization contract used by Studio's Neo4j Browser nginx gate."""

import jwt
from fastapi.testclient import TestClient

from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app


client = TestClient(app)


def _headers(permissions: list[str]) -> dict[str, str]:
    token = jwt.encode(
        {"sub": "neo4j-gate-test", "permissions": permissions},
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_non_admin_session_gets_403_for_neo4j_browser_access():
    response = client.get("/access/neo4j", headers=_headers(["workflow.read"]))
    assert response.status_code == 403


def test_platform_admin_session_can_open_neo4j_browser():
    response = client.get("/access/neo4j", headers=_headers(["platform.manage_infra"]))
    assert response.status_code == 200
    assert response.json() == {"allowed": True, "permission": "platform.manage_infra"}


def test_missing_session_gets_401_for_neo4j_browser_access():
    assert client.get("/access/neo4j").status_code == 401
