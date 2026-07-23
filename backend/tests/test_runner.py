"""
tests/test_runner.py

Unit tests for:
  - control_center.core.runner.run_all_checks
  - control_center.core.settings.load_settings
  - control_center.api.routes_services  (GET /services)
  - control_center.api.routes_summary   (GET /summary)
"""

from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from control_center.core.runner import run_all_checks
from control_center.core.settings import Settings, load_settings
from control_center.main import app

client = TestClient(app)


# ==============================================================================
# Helpers
# ==============================================================================

def _write_config(content: str) -> str:
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

    def setUp(self) -> None:
        # This host may have a real GPU; run_all_checks always appends
        # check_gpu_temperature() results, so pin it to [] for deterministic
        # service-count assertions below.
        patcher = patch("control_center.core.runner.check_gpu_temperature", return_value=[])
        self.mock_gpu = patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_services_returns_empty(self) -> None:
        settings = Settings(services={}, system={})
        results = run_all_checks(settings)
        self.assertEqual(results, [])

    def test_unknown_type_returns_warn(self) -> None:
        settings = Settings(
            services={"weird": {"type": "ftp", "host": "localhost", "port": 21}},
            system={},
        )
        results = run_all_checks(settings)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "WARN")
        self.assertIn("Unknown check type", results[0]["message"])

    def test_missing_type_returns_warn(self) -> None:
        settings = Settings(services={"no-type": {}}, system={})
        results = run_all_checks(settings)
        self.assertEqual(results[0]["status"], "WARN")

    def test_mysql_type_runs_tcp(self) -> None:
        settings = Settings(
            services={"mysql": {"type": "mysql", "host": "127.0.0.1", "port": 19996}},
            system={},
        )
        results = run_all_checks(settings)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "mysql")
        self.assertIn(results[0]["status"], ("UP", "DOWN", "WARN"))

    def test_redis_type_runs_tcp(self) -> None:
        settings = Settings(
            services={"redis": {"type": "redis", "host": "127.0.0.1", "port": 19995}},
            system={},
        )
        results = run_all_checks(settings)
        self.assertEqual(results[0]["type"], "redis")
        self.assertIn(results[0]["status"], ("UP", "DOWN", "WARN"))

    def test_http_type_routes_to_http_check(self) -> None:
        settings = Settings(
            services={"web": {"type": "http", "url": "http://127.0.0.1:19994/health", "timeout_s": 1}},
            system={},
        )
        results = run_all_checks(settings)
        self.assertEqual(results[0]["type"], "http")
        self.assertEqual(results[0]["name"], "web")

    def test_multiple_services_all_returned(self) -> None:
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

    def test_loads_services(self) -> None:
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
        os.environ["CONTROL_CENTER_CONFIG"] = "/nonexistent/config.yaml"
        try:
            with self.assertRaises(FileNotFoundError):
                load_settings()
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]

    def test_empty_config_returns_empty_settings(self) -> None:
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

    def test_services_returns_200(self) -> None:
        path = _minimal_config()
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            response = client.get("/services")
            self.assertEqual(response.status_code, 200)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_services_returns_list(self) -> None:
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

    def test_summary_returns_200(self) -> None:
        path = _minimal_config()
        os.environ["CONTROL_CENTER_CONFIG"] = path
        try:
            response = client.get("/summary")
            self.assertEqual(response.status_code, 200)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]
            os.unlink(path)

    def test_summary_has_overall_status(self) -> None:
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
        os.environ["CONTROL_CENTER_CONFIG"] = "/nonexistent/config.yaml"
        try:
            response = client.get("/summary")
            self.assertEqual(response.status_code, 500)
        finally:
            del os.environ["CONTROL_CENTER_CONFIG"]

    def test_summary_overall_warn_when_disk_warns_but_no_down(self) -> None:
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