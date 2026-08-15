"""
tests/test_routes_infra.py

Unit tests for:
  - control_center.api.routes_infra
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

from control_center.api import routes_infra
from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app

client = TestClient(app)

# Public Read-Only Control Center architecture: /license and /audit-trail
# are the two exceptions in this router that are NOT safe to leave
# anonymous (real customer emails / per-event user_id -- see routes_infra
# .py's own module comment). Same platform.manage_infra token shape
# test_routes_docker.py already uses for docker_router/config_router.
_INFRA_TOKEN = jwt.encode({"sub": "1", "permissions": ["platform.manage_infra"]}, JWT_SECRET, algorithm="HS256")
_infra_headers = {"Authorization": f"Bearer {_INFRA_TOKEN}"}


class TestInfraRoutes(unittest.TestCase):

    def test_gpu_route(self) -> None:
        with patch.object(routes_infra, "get_gpu_status", return_value={"reachable": True}):
            resp = client.get("/gpu")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"reachable": True})

    def test_celery_route(self) -> None:
        with patch.object(routes_infra, "get_celery_status", return_value={"workers": []}):
            resp = client.get("/celery")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"workers": []})

    def test_database_route(self) -> None:
        with patch.object(routes_infra, "get_database_status", return_value={"mysql": None}):
            resp = client.get("/database")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"mysql": None})

    def test_image_freshness_route(self) -> None:
        with patch.object(routes_infra, "get_image_freshness", return_value={"images": []}):
            resp = client.get("/image-freshness")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"images": []})

    def test_license_route(self) -> None:
        with patch.object(routes_infra, "get_license_status", return_value={"seats_used": 0}):
            resp = client.get("/license", headers=_infra_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"seats_used": 0})

    def test_license_route_requires_auth(self) -> None:
        # Public Read-Only Control Center: real customer/user email
        # addresses (checks/license_status.py's own `SELECT email ...`)
        # must never be reachable anonymously.
        with patch.object(routes_infra, "get_license_status", return_value={"seats_used": 0}):
            resp = client.get("/license")
        self.assertEqual(resp.status_code, 401)

    def test_license_route_rejects_insufficient_permission(self) -> None:
        token = jwt.encode({"sub": "1", "permissions": []}, JWT_SECRET, algorithm="HS256")
        with patch.object(routes_infra, "get_license_status", return_value={"seats_used": 0}):
            resp = client.get("/license", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)

    def test_usage_route(self) -> None:
        with patch.object(routes_infra, "get_usage_status", return_value={"active_users_7d": 0}):
            resp = client.get("/usage")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"active_users_7d": 0})

    def test_gateway_traffic_route(self) -> None:
        with patch.object(routes_infra, "get_gateway_traffic", return_value={"requests_7d": 0}):
            resp = client.get("/gateway-traffic")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"requests_7d": 0})

    def test_audit_trail_route(self) -> None:
        with patch.object(routes_infra, "get_audit_trail", return_value={"total_events": 0}):
            resp = client.get("/audit-trail", headers=_infra_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"total_events": 0})

    def test_audit_trail_route_requires_auth(self) -> None:
        # Public Read-Only Control Center: raw per-event user_id
        # (checks/audit_trail.py's own `events` list) must never be
        # reachable anonymously.
        with patch.object(routes_infra, "get_audit_trail", return_value={"total_events": 0}):
            resp = client.get("/audit-trail")
        self.assertEqual(resp.status_code, 401)

    def test_audit_trail_route_rejects_insufficient_permission(self) -> None:
        token = jwt.encode({"sub": "1", "permissions": []}, JWT_SECRET, algorithm="HS256")
        with patch.object(routes_infra, "get_audit_trail", return_value={"total_events": 0}):
            resp = client.get("/audit-trail", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)

    def test_activity_route(self) -> None:
        with patch.object(routes_infra, "get_activity_status", return_value={"reachable": True}):
            resp = client.get("/activity")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"reachable": True})

    def test_integrity_route_success(self) -> None:
        fake_settings = object()
        with patch.object(routes_infra, "load_settings", return_value=fake_settings):
            with patch.object(routes_infra, "run_integrity_checks", return_value=[{"status": "ok"}]):
                resp = client.get("/integrity")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["checks"], [{"status": "ok"}])
        self.assertIn("checked_at", data)

    def test_integrity_route_missing_config_returns_500(self) -> None:
        with patch.object(routes_infra, "load_settings", side_effect=FileNotFoundError("no config")):
            resp = client.get("/integrity")
        self.assertEqual(resp.status_code, 500)
        self.assertIn("no config", resp.json()["error"])


if __name__ == "__main__":
    unittest.main()
