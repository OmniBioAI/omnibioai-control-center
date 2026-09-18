"""
tests/test_summary_client.py

Unit tests for:
  - control_center/utils/summary_client.py  (parse_summary, fetch_summary)
  - generate_report.py health parsing helpers (_parse_service, _parse_disk, fetch_health)

All tests are pure-Python and do not require a running server.
Network calls are tested via a lightweight in-process HTTP server.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict
from unittest.mock import patch

# Import from the standalone summary_client module
from control_center.utils.summary_client import (
    EcosystemHealth,
    ServiceHealth,
    DiskHealth,
    parse_summary,
    fetch_summary,
)


# ==============================================================================
# Fixtures
# ==============================================================================

FULL_SUMMARY: Dict[str, Any] = {
    "overall_status": "UP",
    "generated_at": "2026-03-20T02:44:00+00:00",
    "services": [
        {
            "name": "omnibioai",
            "type": "http",
            "target": "http://omnibioai:8000/",
            "status": "UP",
            "latency_ms": 12,
            "message": "HTTP 200",
        },
        {
            "name": "mysql",
            "type": "mysql",
            "target": "mysql:3306",
            "status": "UP",
            "latency_ms": 3,
            "message": "TCP connect ok",
        },
        {
            "name": "redis",
            "type": "redis",
            "target": "redis:6379",
            "status": "DOWN",
            "latency_ms": 5,
            "message": "ConnectionRefusedError",
        },
    ],
    "system": {
        "disk": [
            {
                "name": "disk:/workspace/out",
                "type": "disk",
                "target": "/workspace/out",
                "status": "UP",
                "latency_ms": None,
                "message": "45.2% free",
            },
            {
                "name": "disk:/workspace/tmpdata",
                "type": "disk",
                "target": "/workspace/tmpdata",
                "status": "WARN",
                "latency_ms": None,
                "message": "Low disk: 8.1% free (< 10.0%)",
            },
        ]
    },
}


# ==============================================================================
# parse_summary
# ==============================================================================

class TestParseSummary(unittest.TestCase):
    """parse_summary()'s conversion of a raw health-summary dict into
    typed EcosystemHealth/ServiceHealth/DiskHealth objects."""

    def test_overall_status_parsed(self) -> None:
        """overall_status is carried through unchanged."""
        health = parse_summary(FULL_SUMMARY)
        self.assertEqual(health.overall_status, "UP")

    def test_generated_at_parsed(self) -> None:
        """generated_at is carried through unchanged."""
        health = parse_summary(FULL_SUMMARY)
        self.assertEqual(health.generated_at, "2026-03-20T02:44:00+00:00")

    def test_service_count(self) -> None:
        """Every service entry in the payload produces a ServiceHealth."""
        health = parse_summary(FULL_SUMMARY)
        self.assertEqual(len(health.services), 3)

    def test_service_fields(self) -> None:
        """A ServiceHealth carries every field of its source dict unchanged."""
        health = parse_summary(FULL_SUMMARY)
        svc = health.services[0]
        self.assertIsInstance(svc, ServiceHealth)
        self.assertEqual(svc.name, "omnibioai")
        self.assertEqual(svc.type, "http")
        self.assertEqual(svc.target, "http://omnibioai:8000/")
        self.assertEqual(svc.status, "UP")
        self.assertEqual(svc.latency_ms, 12)
        self.assertEqual(svc.message, "HTTP 200")

    def test_service_status_uppercased(self) -> None:
        """A lowercase status value ("up") is normalized to uppercase ("UP")."""
        payload = {**FULL_SUMMARY, "services": [
            {**FULL_SUMMARY["services"][0], "status": "up"}
        ]}
        health = parse_summary(payload)
        self.assertEqual(health.services[0].status, "UP")

    def test_disk_count(self) -> None:
        """Every disk entry under system.disk produces a DiskHealth."""
        health = parse_summary(FULL_SUMMARY)
        self.assertEqual(len(health.disk), 2)

    def test_disk_fields(self) -> None:
        """A DiskHealth carries its status and message unchanged."""
        health = parse_summary(FULL_SUMMARY)
        d = health.disk[1]
        self.assertIsInstance(d, DiskHealth)
        self.assertEqual(d.status, "WARN")
        self.assertIn("Low disk", d.message)

    def test_down_service_preserved(self) -> None:
        """A DOWN service is preserved in the services list, not filtered out."""
        health = parse_summary(FULL_SUMMARY)
        down = [s for s in health.services if s.status == "DOWN"]
        self.assertEqual(len(down), 1)
        self.assertEqual(down[0].name, "redis")

    def test_empty_services(self) -> None:
        """An empty services list parses to an empty list, not an error."""
        health = parse_summary({"overall_status": "UP", "generated_at": "", "services": []})
        self.assertEqual(health.services, [])

    def test_missing_system_key(self) -> None:
        """A payload with no "system" key at all parses disk as empty."""
        payload = {"overall_status": "UP", "generated_at": "", "services": []}
        health = parse_summary(payload)
        self.assertEqual(health.disk, [])

    def test_missing_disk_key(self) -> None:
        """A "system" dict with no "disk" key parses disk as empty."""
        payload = {**FULL_SUMMARY, "system": {}}
        health = parse_summary(payload)
        self.assertEqual(health.disk, [])

    def test_null_latency_allowed(self) -> None:
        """A null latency_ms value is preserved as None, not coerced to 0."""
        payload = {**FULL_SUMMARY, "services": [
            {**FULL_SUMMARY["services"][0], "latency_ms": None}
        ]}
        health = parse_summary(payload)
        self.assertIsNone(health.services[0].latency_ms)

    def test_empty_payload(self) -> None:
        """A completely empty dict parses to overall_status="WARN"
        with empty services/disk lists, not a raised exception."""
        health = parse_summary({})
        self.assertEqual(health.overall_status, "WARN")
        self.assertEqual(health.services, [])
        self.assertEqual(health.disk, [])

    def test_no_error_on_valid_payload(self) -> None:
        """A valid payload parses with error=None."""
        health = parse_summary(FULL_SUMMARY)
        self.assertIsNone(health.error)


# ==============================================================================
# fetch_summary — network tests using an in-process HTTP server
# ==============================================================================

class _SummaryHandler(BaseHTTPRequestHandler):
    """Serves FULL_SUMMARY at /summary."""
    def do_GET(self) -> None:
        if self.path == "/summary":
            body = json.dumps(FULL_SUMMARY).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


class _ErrorHandler(BaseHTTPRequestHandler):
    """Always returns 500."""
    def do_GET(self) -> None:
        self.send_response(500)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


def _start(handler_cls: type) -> tuple[HTTPServer, int]:
    """Start a real HTTPServer with `handler_cls` on a background
    thread, bound to an OS-assigned port. Returns (server, port)."""
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


class TestFetchSummary(unittest.TestCase):
    """fetch_summary()'s network behavior against a real in-process
    HTTP server: successful fetch, unreachable target, and various
    error responses -- always returning an EcosystemHealth, never raising."""

    def test_successful_fetch(self) -> None:
        """A reachable server serving FULL_SUMMARY parses to a full,
        error-free EcosystemHealth."""
        server, port = _start(_SummaryHandler)
        try:
            health = fetch_summary(f"http://127.0.0.1:{port}")
        finally:
            server.shutdown()
        self.assertEqual(health.overall_status, "UP")
        self.assertEqual(len(health.services), 3)
        self.assertIsNone(health.error)

    def test_unreachable_returns_error_not_raise(self) -> None:
        """A target with no listener returns overall_status="UNREACHABLE"
        with a non-None error, rather than raising."""
        # Port that is not listening
        health = fetch_summary("http://127.0.0.1:19997", timeout_s=1)
        self.assertEqual(health.overall_status, "UNREACHABLE")
        self.assertIsNotNone(health.error)

    def test_trailing_slash_in_base_url(self) -> None:
        """A base URL with a trailing slash still fetches successfully."""
        server, port = _start(_SummaryHandler)
        try:
            health = fetch_summary(f"http://127.0.0.1:{port}/")
        finally:
            server.shutdown()
        self.assertEqual(health.overall_status, "UP")

    def test_error_state_has_no_services(self) -> None:
        """An unreachable target's EcosystemHealth has empty services/disk."""
        health = fetch_summary("http://127.0.0.1:19997", timeout_s=1)
        self.assertEqual(health.services, [])
        self.assertEqual(health.disk, [])

    def test_500_response_returns_unreachable(self) -> None:
        """A server returning a non-JSON 500 is caught gracefully as UNREACHABLE."""
        server, port = _start(_ErrorHandler)
        try:
            health = fetch_summary(f"http://127.0.0.1:{port}", timeout_s=2)
        finally:
            server.shutdown()
        # A non-JSON 500 response should be caught gracefully
        self.assertEqual(health.overall_status, "UNREACHABLE")
        self.assertIsNotNone(health.error)

    def test_generic_exception_returns_unreachable(self) -> None:
        """A non-URLError exception raised by urlopen (the generic
        except-Exception branch) still returns UNREACHABLE naming the
        exception type."""
        # Trigger the generic except Exception branch (lines 121-122) by
        # patching urlopen to raise a non-URLError exception.
        with patch("urllib.request.urlopen", side_effect=RuntimeError("mock failure")):
            health = fetch_summary("http://127.0.0.1:9999", timeout_s=1)
        self.assertEqual(health.overall_status, "UNREACHABLE")
        self.assertIsNotNone(health.error)
        self.assertIn("RuntimeError", health.error)

    def test_generic_exception_error_message(self) -> None:
        """The exception's own message text is included in the reported error."""
        with patch("urllib.request.urlopen", side_effect=ValueError("bad json format")):
            health = fetch_summary("http://127.0.0.1:9999", timeout_s=1)
        self.assertIn("bad json format", health.error)


if __name__ == "__main__":
    unittest.main()