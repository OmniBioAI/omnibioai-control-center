"""
tests/test_runner.py

Unit tests for:
  - control_center.core.runner.run_all_checks
  - control_center.core.settings.load_settings
  - control_center.api.routes_services  (GET /services)
  - control_center.api.routes_summary   (GET /summary)

Covers run_all_checks()'s dispatch by service type (mysql/redis/http,
unknown/missing type -> WARN), load_settings()'s YAML parsing (services
+ system.disk_checks, missing/empty config handling), and the /services
and /summary routes' end-to-end wiring against a real temp config file,
including /summary's overall_status derivation (DOWN if any service is
down, WARN if a disk check warns with no service down).

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

from control_center.core.jwt_verify import JWT_SECRET
from control_center.core.runner import run_all_checks
from control_center.core.settings import Settings, load_settings
from control_center.main import app

# services_router and summary_router are gated at router-inclusion time
# (main.py) behind platform.manage_infra -- these tests exercise the
# routes' own logic, not authorization (see test_main.py for the 401/403
# permission checks), so the client carries a fixed, always-sufficient
# token by default.
_INFRA_TOKEN = jwt.encode({"sub": "1", "permissions": ["platform.manage_infra"]}, JWT_SECRET, algorithm="HS256")
client = TestClient(app, headers={"Authorization": f"Bearer {_INFRA_TOKEN}"})


# ==============================================================================
# Helpers
# ==============================================================================

def _write_config(content: str) -> str:
    """Write `content` (dedented) to a fresh temp YAML file and return its path."""
    tf = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    tf.write(textwrap.dedent(content))
    tf.close()
    return tf.name


def _minimal_config() -> str:
    """Write a minimal valid config and return its path."""
    return _write_config("""
        services:
          dummy-http:
            type: http
            url: http://127.0.0.1:19980/health
            timeout_s: 1
        system:
          disk_checks:
            - path: /tmp
              warn_pct_free_below: 0
    """)


# ==============================================================================
# run_all_checks
# ==============================================================================

class TestRunAllChecks(unittest.TestCase):
    """run_all_checks()'s dispatch by configured service type."""

    def setUp(self) -> None:
        # This host may have a real GPU; run_all_checks always appends
        # check_gpu_temperature() results, so pin it to [] for deterministic
        # service-count assertions below.
        patcher = patch("control_center.core.runner.check_gpu_temperature", return_value=[])
        self.mock_gpu = patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_services_returns_empty(self) -> None:
        """No configured services returns an empty result list."""
        settings = Settings(services={}, system={})
        results = run_all_checks(settings)
        self.assertEqual(results, [])

    def test_unknown_type_returns_warn(self) -> None:
        """A service with an unrecognized "type" returns a WARN result
        naming the unknown check type."""
        settings = Settings(
            services={"weird": {"type": "ftp", "host": "localhost", "port": 21}},
            system={},
        )
        results = run_all_checks(settings)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "WARN")
        self.assertIn("Unknown check type", results[0]["message"])

    def test_missing_type_returns_warn(self) -> None:
        """A service with no "type" key at all returns a WARN result."""
        settings = Settings(services={"no-type": {}}, system={})
        results = run_all_checks(settings)
        self.assertEqual(results[0]["status"], "WARN")

    def test_mysql_type_runs_tcp(self) -> None:
        """A "mysql" type service dispatches to a real TCP-connect check."""
        settings = Settings(
            services={"mysql": {"type": "mysql", "host": "127.0.0.1", "port": 19996}},
            system={},
        )
        results = run_all_checks(settings)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "mysql")
        self.assertIn(results[0]["status"], ("UP", "DOWN", "WARN"))

    def test_redis_type_runs_tcp(self) -> None:
        """A "redis" type service dispatches to a real TCP-connect check."""
        settings = Settings(
            services={"redis": {"type": "redis", "host": "127.0.0.1", "port": 19995}},
            system={},
        )
        results = run_all_checks(settings)
        self.assertEqual(results[0]["type"], "redis")
        self.assertIn(results[0]["status"], ("UP", "DOWN", "WARN"))

    def test_http_type_routes_to_http_check(self) -> None:
        """A "http" type service dispatches to the HTTP health check."""
        settings = Settings(
            services={"web": {"type": "http", "url": "http://127.0.0.1:19994/health", "timeout_s": 1}},
            system={},
        )
        results = run_all_checks(settings)
        self.assertEqual(results[0]["type"], "http")
        self.assertEqual(results[0]["name"], "web")

    def test_multiple_services_all_returned(self) -> None:
        """Every configured service, regardless of type, produces its
        own result."""
        settings = Settings(
            services={
                "svc-a": {"type": "http", "url": "http://127.0.0.1:19993/", "timeout_s": 1},
                "svc-b": {"type": "mysql", "host": "127.0.0.1", "port": 19992},
                "svc-c": {"type": "redis", "host": "127.0.0.1", "port": 19991},
            },
            system={},
        )
        results = run_all_checks(settings)
        self.assertEqual(len(results), 3)
        names = {r["name"] for r in results}
        self.assertEqual(names, {"svc-a", "svc-b", "svc-c"})

    def test_result_has_required_keys(self) -> None:
        """Every result dict includes the full documented key set."""
        settings = Settings(
            services={"svc": {"type": "mysql", "host": "127.0.0.1", "port": 19990}},
            system={},
        )
        results = run_all_checks(settings)
        required = {"name", "type", "target", "status", "latency_ms", "message"}
        self.assertTrue(required.issubset(results[0].keys()))


# ==============================================================================
# load_settings
# ==============================================================================

class TestLoadSettings(unittest.TestCase):
    """load_settings()'s YAML parsing of a real config file on disk."""

    def test_loads_services(self) -> None:
        """A configured service is parsed into settings.services with
        its "type" field intact."""
        path = _write_config("""
            services:
              mysql:
                type: mysql
                host: mysql
                port: 3306
        """)
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            settings = load_settings()
            self.assertIn("mysql", settings.services)
            self.assertEqual(settings.services["mysql"]["type"], "mysql")
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_loads_disk_checks(self) -> None:
        """A configured disk check under system.disk_checks is parsed
        with its path/threshold."""
        path = _write_config("""
            services: {}
            system:
              disk_checks:
                - path: /tmp
                  warn_pct_free_below: 10
        """)
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            settings = load_settings()
            disk = settings.system.get("disk_checks", [])
            self.assertEqual(len(disk), 1)
            self.assertEqual(disk[0]["path"], "/tmp")
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_raises_when_config_missing(self) -> None:
        """A CONTROL_CENTER_CONFIG pointing at a nonexistent file
        raises FileNotFoundError."""
        os.environ["CONTROL_CENTER_CONFIG"] = "/nonexistent/config.yaml"
        try:
            with self.assertRaises(FileNotFoundError):
                load_settings()
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]

    def test_empty_config_returns_empty_settings(self) -> None:
        """An empty config file loads to empty services/system dicts,
        not an error."""
        path = _write_config("")
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            settings = load_settings()
            self.assertEqual(settings.services, {})
            self.assertEqual(settings.system, {})
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_multiple_services_loaded(self) -> None:
        """Multiple configured services are all present in settings.services."""
        path = _write_config("""
            services:
              tes:
                type: http
                url: http://tes:8081/health
              redis:
                type: redis
                host: redis
                port: 6379
        """)
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            settings = load_settings()
            self.assertIn("tes", settings.services)
            self.assertIn("redis", settings.services)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)


# ==============================================================================
# API routes — GET /services
# ==============================================================================

class TestRoutesServices(unittest.TestCase):
    """GET /services against a real temp config file."""

    def test_services_returns_200(self) -> None:
        """A valid config returns 200."""
        path = _minimal_config()
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            response = client.get("/services")
            self.assertEqual(response.status_code, 200)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_services_returns_list(self) -> None:
        """The response has a "services" key holding a list."""
        path = _minimal_config()
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            response = client.get("/services")
            data = response.json()
            self.assertIn("services", data)
            self.assertIsInstance(data["services"], list)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_services_each_has_required_keys(self) -> None:
        """Every entry in the services list has name/status/type."""
        path = _minimal_config()
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            response = client.get("/services")
            for svc in response.json()["services"]:
                self.assertIn("name", svc)
                self.assertIn("status", svc)
                self.assertIn("type", svc)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_services_raises_on_missing_config(self) -> None:
        """A missing config file returns 500 rather than crashing unhandled."""
        os.environ["CONTROL_CENTER_CONFIG"] = "/nonexistent/config.yaml"
        try:
            response = client.get("/services")
            self.assertEqual(response.status_code, 500)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]


# ==============================================================================
# API routes — GET /summary
# ==============================================================================

class TestRoutesSummary(unittest.TestCase):
    """GET /summary against a real temp config file."""

    def test_summary_returns_200(self) -> None:
        """A valid config returns 200."""
        path = _minimal_config()
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            response = client.get("/summary")
            self.assertEqual(response.status_code, 200)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_summary_has_overall_status(self) -> None:
        """The response includes a valid overall_status value."""
        path = _minimal_config()
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            data = client.get("/summary").json()
            self.assertIn("overall_status", data)
            self.assertIn(data["overall_status"], ("UP", "DOWN", "WARN"))
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_summary_has_generated_at(self) -> None:
        """The response includes a non-empty generated_at timestamp string."""
        path = _minimal_config()
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            data = client.get("/summary").json()
            self.assertIn("generated_at", data)
            self.assertIsInstance(data["generated_at"], str)
            self.assertTrue(len(data["generated_at"]) > 0)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_summary_has_services_list(self) -> None:
        """The response includes a "services" list."""
        path = _minimal_config()
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            data = client.get("/summary").json()
            self.assertIn("services", data)
            self.assertIsInstance(data["services"], list)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_summary_has_system_disk(self) -> None:
        """The response includes a "system.disk" list."""
        path = _minimal_config()
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            data = client.get("/summary").json()
            self.assertIn("system", data)
            self.assertIn("disk", data["system"])
            self.assertIsInstance(data["system"]["disk"], list)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_summary_overall_down_when_service_down(self) -> None:
        """With every configured service unreachable, overall_status is "DOWN"."""
        path = _write_config("""
            services:
              broken:
                type: http
                url: http://127.0.0.1:19979/health
                timeout_s: 1
            system: {}
        """)
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            data = client.get("/summary").json()
            # All services unreachable — overall must be DOWN
            self.assertEqual(data["overall_status"], "DOWN")
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_summary_raises_on_missing_config(self) -> None:
        """A missing config file returns 500."""
        os.environ["CONTROL_CENTER_CONFIG"] = "/nonexistent/config.yaml"
        try:
            response = client.get("/summary")
            self.assertEqual(response.status_code, 500)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]

    def test_summary_overall_warn_when_disk_warns_but_no_down(self) -> None:
        """A disk check that warns (with no service down) makes
        overall_status "WARN", not "DOWN" or "UP"."""
        # A config with no services and a disk path that triggers WARN (100% threshold)
        # causes overall_status=WARN (routes_summary.py lines 45-46)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_config(f"""
                services: {{}}
                system:
                  disk_checks:
                    - path: {tmp}
                      warn_pct_free_below: 100
            """)
            os.environ["CONTROL_CENTER_CONFIG"] = path
            try:
                data = client.get("/summary").json()
                self.assertEqual(data["overall_status"], "WARN")
            finally:
                del os.environ["CONTROL_CENTER_CONFIG"]
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()