"""
tests/test_routes_infra.py

Unit tests for:
  - control_center.api.routes_infra

Each infra sub-route (gpu/celery/database/image-freshness/usage/
gateway-traffic/activity/integrity) delegates to its own checker function
and relays that function's return value verbatim. /license and /audit-
trail additionally require platform.manage_infra (real customer emails /
per-event user_id), unlike the rest of this router which is anonymous.

Developer:
    Manish Kumar <manish@omnibioai.org>
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
    """For a platform.manage_infra caller each routes_infra endpoint relays
    its checker function's return value verbatim; /license and
    /audit-trail additionally reject everyone else. Anonymous callers of
    the other routes get core/public_view.py's trimmed shape -- see
    TestInfraRoutesAnonymous below."""

    def test_gpu_route(self) -> None:
        """GET /gpu returns get_gpu_status()'s result unchanged."""
        with patch.object(routes_infra, "get_gpu_status", return_value={"reachable": True}):
            resp = client.get("/gpu", headers=_infra_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"reachable": True})

    def test_celery_route(self) -> None:
        """GET /celery returns get_celery_status()'s result unchanged."""
        with patch.object(routes_infra, "get_celery_status", return_value={"workers": []}):
            resp = client.get("/celery", headers=_infra_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"workers": []})

    def test_database_route(self) -> None:
        """GET /database returns get_database_status()'s result unchanged."""
        with patch.object(routes_infra, "get_database_status", return_value={"mysql": None}):
            resp = client.get("/database", headers=_infra_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"mysql": None})

    def test_image_freshness_route(self) -> None:
        """GET /image-freshness returns get_image_freshness()'s result unchanged."""
        with patch.object(routes_infra, "get_image_freshness", return_value={"images": []}):
            resp = client.get("/image-freshness", headers=_infra_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"images": []})

    def test_license_route(self) -> None:
        """GET /license with a sufficient token returns
        get_license_status()'s result unchanged."""
        with patch.object(routes_infra, "get_license_status", return_value={"seats_used": 0}):
            resp = client.get("/license", headers=_infra_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"seats_used": 0})

    def test_license_route_requires_auth(self) -> None:
        """An anonymous request to /license is rejected with 401 --
        it carries real customer/user email addresses and must never be
        reachable without authentication."""
        # Public Read-Only Control Center: real customer/user email
        # addresses (checks/license_status.py's own `SELECT email ...`)
        # must never be reachable anonymously.
        with patch.object(routes_infra, "get_license_status", return_value={"seats_used": 0}):
            resp = client.get("/license")
        self.assertEqual(resp.status_code, 401)

    def test_license_route_rejects_insufficient_permission(self) -> None:
        """GET /license with a token that carries no permissions is rejected with 403,
        since platform.manage_infra is required."""
        token = jwt.encode({"sub": "1", "permissions": []}, JWT_SECRET, algorithm="HS256")
        with patch.object(routes_infra, "get_license_status", return_value={"seats_used": 0}):
            resp = client.get("/license", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)

    def test_usage_route(self) -> None:
        """GET /usage returns get_usage_status()'s result unchanged."""
        with patch.object(routes_infra, "get_usage_status", return_value={"active_users_7d": 0}):
            resp = client.get("/usage")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"active_users_7d": 0})

    def test_gateway_traffic_route(self) -> None:
        """GET /gateway-traffic returns get_gateway_traffic()'s result unchanged."""
        with patch.object(routes_infra, "get_gateway_traffic", return_value={"requests_7d": 0}):
            resp = client.get("/gateway-traffic", headers=_infra_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"requests_7d": 0})

    def test_audit_trail_route(self) -> None:
        """GET /audit-trail with a sufficient token returns
        get_audit_trail()'s result unchanged."""
        with patch.object(routes_infra, "get_audit_trail", return_value={"total_events": 0}):
            resp = client.get("/audit-trail", headers=_infra_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"total_events": 0})

    def test_audit_trail_route_requires_auth(self) -> None:
        """An anonymous request to /audit-trail is rejected with 401 --
        it carries raw per-event user_id and must never be reachable
        without authentication."""
        # Public Read-Only Control Center: raw per-event user_id
        # (checks/audit_trail.py's own `events` list) must never be
        # reachable anonymously.
        with patch.object(routes_infra, "get_audit_trail", return_value={"total_events": 0}):
            resp = client.get("/audit-trail")
        self.assertEqual(resp.status_code, 401)

    def test_audit_trail_route_rejects_insufficient_permission(self) -> None:
        """GET /audit-trail with a token that carries no permissions is rejected with
        403, since platform.manage_infra is required."""
        token = jwt.encode({"sub": "1", "permissions": []}, JWT_SECRET, algorithm="HS256")
        with patch.object(routes_infra, "get_audit_trail", return_value={"total_events": 0}):
            resp = client.get("/audit-trail", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)

    def test_activity_route(self) -> None:
        """GET /activity returns get_activity_status()'s result unchanged."""
        with patch.object(routes_infra, "get_activity_status", return_value={"reachable": True}):
            resp = client.get("/activity", headers=_infra_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"reachable": True})

    def test_integrity_route_success(self) -> None:
        """GET /integrity returns run_integrity_checks()'s results under
        "checks" plus a "checked_at" timestamp."""
        fake_settings = object()
        with patch.object(routes_infra, "load_settings", return_value=fake_settings):
            with patch.object(routes_infra, "run_integrity_checks", return_value=[{"status": "ok"}]):
                resp = client.get("/integrity", headers=_infra_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["checks"], [{"status": "ok"}])
        self.assertIn("checked_at", data)

    def test_integrity_route_missing_config_returns_500(self) -> None:
        """A missing config file (load_settings raises FileNotFoundError)
        returns 500 with the underlying error message."""
        with patch.object(routes_infra, "load_settings", side_effect=FileNotFoundError("no config")):
            resp = client.get("/integrity", headers=_infra_headers)
        self.assertEqual(resp.status_code, 500)
        self.assertIn("no config", resp.json()["error"])


class TestInfraRoutesAnonymous(unittest.TestCase):
    """Without a platform.manage_infra token the public routes still answer
    200, but with core/public_view.py's counts-only shape: none of the
    names, paths or error text in the full check output reach the
    response."""

    def test_gpu_anonymous_drops_message(self) -> None:
        full = [{"name": "gpu:0", "type": "gpu", "target": "NVIDIA GB10", "status": "UP",
                 "latency_ms": None, "message": "41°C"}]
        with patch.object(routes_infra, "get_gpu_status", return_value=full):
            resp = client.get("/gpu")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [{"name": "gpu:0", "model": "NVIDIA GB10", "status": "UP"}])

    def test_celery_anonymous_counts_only(self) -> None:
        full = {"workers": [{"name": "celery@spark-host", "status": "online", "active_tasks": 2}],
                "recent_tasks": [{"name": "tasks.run_pipeline", "state": "SUCCESS"}]}
        with patch.object(routes_infra, "get_celery_status", return_value=full):
            data = client.get("/celery").json()
        self.assertEqual(data, {"reachable": True, "workers_total": 1, "workers_online": 1, "active_tasks": 2})

    def test_database_anonymous_hides_names(self) -> None:
        full = {"mysql": {"connections": 3, "max_connections": 151, "slow_queries": 0,
                          "databases": [{"name": "omnibioai", "size_mb": 10.5}, {"name": "lims", "size_mb": 2.0}]},
                "redis": {"used_memory_human": "2M", "hit_rate_pct": 90.0, "connected_clients": 4},
                "neo4j": None}
        with patch.object(routes_infra, "get_database_status", return_value=full):
            data = client.get("/database").json()
        self.assertEqual(data["mysql"], {"connections": 3, "max_connections": 151, "slow_queries": 0,
                                         "database_count": 2, "total_size_mb": 12.5})
        self.assertNotIn("omnibioai", str(data))

    def test_image_freshness_anonymous_counts_only(self) -> None:
        full = {"images": [{"service": "auth", "image": "ghcr.io/x/auth:latest", "stale": True, "last_pushed": "x"}]}
        with patch.object(routes_infra, "get_image_freshness", return_value=full):
            data = client.get("/image-freshness").json()
        self.assertEqual(data, {"images_checked": 1, "stale": 1})

    def test_gateway_traffic_anonymous_drops_routes(self) -> None:
        full = {"requests_7d": 10, "requests_by_route": [{"route": "/v1/internal", "count": 5}],
                "invalid_signature_events_7d": 1}
        with patch.object(routes_infra, "get_gateway_traffic", return_value=full):
            data = client.get("/gateway-traffic").json()
        self.assertEqual(data["requests_7d"], 10)
        self.assertNotIn("requests_by_route", data)
        self.assertNotIn("invalid_signature_events_7d", data)

    def test_activity_anonymous_aggregates_containers(self) -> None:
        full = {"containers": [{"name": "omnibioai-auth", "cpu_pct": 1.5, "memory_used_mb": 100.0},
                               {"name": "omnibioai-rag", "cpu_pct": 2.5, "memory_used_mb": 300.0}],
                "host": {"cpu_idle_pct": 90.0, "processes_total": 400}, "reachable": True, "error": None}
        with patch.object(routes_infra, "get_activity_status", return_value=full):
            data = client.get("/activity").json()
        self.assertEqual(data["container_count"], 2)
        self.assertEqual(data["total_cpu_pct"], 4.0)
        self.assertEqual(data["total_memory_used_mb"], 400.0)
        self.assertEqual(data["host"]["cpu_idle_pct"], 90.0)
        self.assertNotIn("processes_total", data["host"])
        self.assertNotIn("omnibioai-auth", str(data))

    def test_integrity_anonymous_counts_only(self) -> None:
        checks = [{"name": "data", "path": "/srv/omnibioai-data", "status": "ok"},
                  {"name": "refs", "path": "/srv/refs", "status": "broken"}]
        with patch.object(routes_infra, "load_settings", return_value=object()):
            with patch.object(routes_infra, "run_integrity_checks", return_value=checks):
                data = client.get("/integrity").json()
        self.assertEqual((data["total"], data["ok"], data["problems"]), (2, 1, 1))
        self.assertIn("checked_at", data)
        self.assertNotIn("/srv", str(data))

    def test_integrity_anonymous_missing_config_hides_path(self) -> None:
        with patch.object(routes_infra, "load_settings", side_effect=FileNotFoundError("/etc/cc/settings.yaml")):
            resp = client.get("/integrity")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json(), {"error": "integrity checks unavailable"})

    def test_insufficient_token_gets_public_shape(self) -> None:
        """A valid token without platform.manage_infra is treated like an
        anonymous caller -- trimmed, not rejected."""
        token = jwt.encode({"sub": "1", "permissions": []}, JWT_SECRET, algorithm="HS256")
        full = {"images": [{"service": "auth", "image": "i", "stale": False}]}
        with patch.object(routes_infra, "get_image_freshness", return_value=full):
            resp = client.get("/image-freshness", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.json(), {"images_checked": 1, "stale": 0})


if __name__ == "__main__":
    unittest.main()
