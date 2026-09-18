"""
tests/test_checks.py

Unit tests for:
  - control_center.checks.tcp
  - control_center.checks.http
  - control_center.checks.disk
  - control_center.api.routes_health
  - control_center.api.routes_report

Covers check_tcp()'s real socket connect (UP/DOWN, missing host,
close-exception silencing), check_http()'s real HTTP request (UP/DOWN/
WARN on a non-raising non-2xx response, missing url), run_disk_checks()'s
UP/WARN classification by free-space threshold plus its low-disk Discord
alert, GET /health's fixed ok response, and GET /report's auth-gated
placeholder-vs-real-file serving.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
from fastapi.testclient import TestClient

from control_center.checks.disk import run_disk_checks
from control_center.checks.http import check_http
from control_center.checks.tcp import check_tcp
from control_center.core.jwt_verify import JWT_SECRET
from control_center.core.settings import Settings
from control_center.main import app

client = TestClient(app)


def _admin_headers() -> dict:
    """Authorization header for a token holding platform.manage_infra."""
    token = jwt.encode({"sub": "1", "permissions": ["platform.manage_infra"]}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# TCP checks
# ==============================================================================

class TestCheckTcp(unittest.TestCase):
    """check_tcp()'s real socket-connect check."""

    def _open_server(self) -> tuple[socket.socket, int]:
        """Open a listening TCP socket on an ephemeral port."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        return srv, srv.getsockname()[1]

    def test_up_when_port_open(self) -> None:
        """A real listening port reports status="UP" with a measured latency."""
        srv, port = self._open_server()
        try:
            result = check_tcp("test-svc", "127.0.0.1", port, "tcp")
        finally:
            srv.close()
        self.assertEqual(result["status"], "UP")
        self.assertEqual(result["name"], "test-svc")
        self.assertEqual(result["type"], "tcp")
        self.assertIsInstance(result["latency_ms"], int)
        self.assertGreaterEqual(result["latency_ms"], 0)

    def test_down_when_port_closed(self) -> None:
        """A closed/unreachable port reports status="DOWN"."""
        result = check_tcp("closed-svc", "127.0.0.1", 19999, "mysql")
        self.assertEqual(result["status"], "DOWN")
        self.assertIn("latency_ms", result)

    def test_down_when_host_missing(self) -> None:
        """A None host reports status="DOWN" with a "Missing host" message."""
        result = check_tcp("no-host", None, 3306, "mysql")
        self.assertEqual(result["status"], "DOWN")
        self.assertIsNone(result["latency_ms"])
        self.assertIn("Missing host", result["message"])

    def test_target_format(self) -> None:
        """The target field is formatted as "host:port"."""
        result = check_tcp("svc", "127.0.0.1", 9999, "redis")
        self.assertEqual(result["target"], "127.0.0.1:9999")

    def test_kind_preserved(self) -> None:
        """The passed-in "type" (kind) is echoed back unchanged."""
        result = check_tcp("svc", "127.0.0.1", 9999, "redis")
        self.assertEqual(result["type"], "redis")


# ==============================================================================
# HTTP checks
# ==============================================================================

class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args: object) -> None:
        pass


class _ErrorHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(503)
        self.end_headers()
        self.wfile.write(b"error")

    def log_message(self, *args: object) -> None:
        pass


def _start_http_server(handler_cls: type) -> tuple[HTTPServer, int]:
    """Start a real HTTPServer with `handler_cls` on a background
    thread, bound to an OS-assigned port. Returns (server, port)."""
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


class TestCheckHttp(unittest.TestCase):
    """check_http()'s real HTTP request, plus its non-raising-non-2xx
    WARN branch and the TCP-check close-exception silencing."""

    def test_up_on_200(self) -> None:
        """A real 200 response reports status="UP" with a measured latency."""
        server, port = _start_http_server(_OkHandler)
        try:
            result = check_http("web-svc", {"url": f"http://127.0.0.1:{port}/health"})
        finally:
            server.shutdown()
        self.assertEqual(result["status"], "UP")
        self.assertEqual(result["name"], "web-svc")
        self.assertEqual(result["type"], "http")
        self.assertIsInstance(result["latency_ms"], int)

    def test_down_on_5xx(self) -> None:
        """A real 5xx response reports status="DOWN" naming the status code."""
        # urllib raises HTTPError for 5xx — check_http catches it and returns DOWN
        server, port = _start_http_server(_ErrorHandler)
        try:
            result = check_http("bad-svc", {"url": f"http://127.0.0.1:{port}/"})
        finally:
            server.shutdown()
        self.assertEqual(result["status"], "DOWN")
        self.assertIn("503", result["message"])

    def test_down_when_unreachable(self) -> None:
        """An unreachable URL reports status="DOWN"."""
        result = check_http(
            "offline", {"url": "http://127.0.0.1:19998/health", "timeout_s": 1}
        )
        self.assertEqual(result["status"], "DOWN")
        self.assertIn("latency_ms", result)

    def test_down_when_url_missing(self) -> None:
        """A config with no "url" key reports status="DOWN" with a
        "Missing 'url'" message."""
        result = check_http("no-url", {})
        self.assertEqual(result["status"], "DOWN")
        self.assertIn("Missing 'url'", result["message"])

    def test_target_is_url(self) -> None:
        """The target field is the checked URL itself."""
        url = "http://127.0.0.1:19998/health"
        result = check_http("svc", {"url": url, "timeout_s": 1})
        self.assertEqual(result["target"], url)

    def test_warn_on_non_2xx_non_raising_response(self) -> None:
        """A response object that reports a non-2xx/3xx status without
        urlopen raising an HTTPError is classified WARN, not UP or DOWN."""
        # Line 40 in checks/http.py: urlopen returns a response with code outside
        # 200-399 without raising. Mock urlopen to return a fake response with
        # status 206 that becomes > 400 via the getattr path... Actually simulate
        # a response object whose status attribute reports a non-2xx/3xx code.
        # We use status=400 to trigger the WARN branch (400 is not 200<=code<400).
        fake_resp = MagicMock()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)
        fake_resp.read.return_value = b"data"
        fake_resp.status = 400

        url = "http://127.0.0.1:9999/health"
        with patch("urllib.request.urlopen", return_value=fake_resp):
            result = check_http("svc", {"url": url})

        self.assertEqual(result["status"], "WARN")
        self.assertIn("400", result["message"])
        self.assertEqual(result["name"], "svc")

    def test_tcp_socket_close_exception_is_silenced(self) -> None:
        """An exception raised by socket.close() in the finally block
        is silenced -- the check's own DOWN result is still returned."""
        # Line 46 in checks/tcp.py: s.close() raises inside finally — must be silent.
        # Patch socket.socket so its close() raises, verifying the finally block
        # catches it without propagating.
        with patch("control_center.checks.tcp.socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = ConnectionRefusedError("refused")
            mock_sock.close.side_effect = OSError("close failed")
            mock_socket_cls.return_value = mock_sock
            # Should not raise — the finally block silences the close() error
            result = check_tcp("svc", "127.0.0.1", 9999, "tcp")
        self.assertEqual(result["status"], "DOWN")


# ==============================================================================
# Disk checks
# ==============================================================================

def _make_settings(disk_cfgs: list[dict]) -> Settings:
    """A Settings with no services and the given system.disk_checks list."""
    return Settings(services={}, system={"disk_checks": disk_cfgs})


class TestDiskChecks(unittest.TestCase):
    """run_disk_checks()'s free-space-threshold classification, plus
    its low-disk-space Discord alert."""

    def test_up_on_healthy_path(self) -> None:
        """A path well above its warn threshold reports status="UP"."""
        with tempfile.TemporaryDirectory() as tmp:
            settings = _make_settings([{"path": tmp, "warn_pct_free_below": 0}])
            results = run_disk_checks(settings)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "UP")
        self.assertEqual(results[0]["type"], "disk")

    def test_warn_when_threshold_high(self) -> None:
        """A threshold of 100% free (always triggers) reports status="WARN"."""
        with tempfile.TemporaryDirectory() as tmp:
            # Threshold of 100% means always warn
            settings = _make_settings([{"path": tmp, "warn_pct_free_below": 100}])
            results = run_disk_checks(settings)
        self.assertEqual(results[0]["status"], "WARN")
        self.assertIn("Low disk", results[0]["message"])

    def test_warn_on_missing_path(self) -> None:
        """A nonexistent path reports status="WARN" rather than raising."""
        settings = _make_settings(
            [{"path": "/nonexistent/path/xyz", "warn_pct_free_below": 10}]
        )
        results = run_disk_checks(settings)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "WARN")

    def test_empty_disk_checks(self) -> None:
        """No configured disk checks returns an empty results list."""
        settings = _make_settings([])
        results = run_disk_checks(settings)
        self.assertEqual(results, [])

    def test_no_path_key_skipped(self) -> None:
        """A disk check entry with no "path" key is skipped entirely."""
        settings = _make_settings([{"warn_pct_free_below": 10}])
        results = run_disk_checks(settings)
        self.assertEqual(results, [])

    def test_multiple_paths(self) -> None:
        """Multiple configured paths each produce their own result."""
        with tempfile.TemporaryDirectory() as tmp1:
            with tempfile.TemporaryDirectory() as tmp2:
                settings = _make_settings([
                    {"path": tmp1, "warn_pct_free_below": 0},
                    {"path": tmp2, "warn_pct_free_below": 0},
                ])
                results = run_disk_checks(settings)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["status"] == "UP" for r in results))

    def test_name_includes_path(self) -> None:
        """The result's "name" field includes the checked path."""
        with tempfile.TemporaryDirectory() as tmp:
            settings = _make_settings([{"path": tmp, "warn_pct_free_below": 0}])
            results = run_disk_checks(settings)
        self.assertIn(tmp, results[0]["name"])

    def test_low_disk_space_fires_discord_notify(self) -> None:
        """A low-disk-space condition fires exactly one Discord alert
        naming the free space in GB."""
        from collections import namedtuple
        from control_center.checks import disk as disk_module

        _Usage = namedtuple("_Usage", ["total", "used", "free"])
        fake_usage = _Usage(total=100 * 1024 ** 3, used=95 * 1024 ** 3, free=5 * 1024 ** 3)

        with tempfile.TemporaryDirectory() as tmp:
            settings = _make_settings([{"path": tmp, "warn_pct_free_below": 0}])
            with patch.object(disk_module.shutil, "disk_usage", return_value=fake_usage):
                with patch.object(disk_module, "_discord_notify") as mock_notify:
                    with patch.object(disk_module, "_WEBHOOK", "https://discord.example/webhook"):
                        results = run_disk_checks(settings)

        self.assertEqual(len(results), 1)
        mock_notify.assert_called_once()
        args, kwargs = mock_notify.call_args
        self.assertEqual(args[0], "https://discord.example/webhook")
        self.assertIn("Low Disk Space", args[1])
        self.assertIn("5.0GB", args[2])


# ==============================================================================
# API routes — GET /health
# ==============================================================================

class TestRoutesHealth(unittest.TestCase):
    """GET /health's fixed, unauthenticated liveness response."""

    def test_health_returns_200(self) -> None:
        """The route returns 200."""
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_health_returns_ok_status(self) -> None:
        """The response body reports status="ok"."""
        response = client.get("/health")
        self.assertEqual(response.json()["status"], "ok")

    def test_health_content_type_is_json(self) -> None:
        """The response Content-Type is application/json."""
        response = client.get("/health")
        self.assertIn("application/json", response.headers["content-type"])


# ==============================================================================
# API routes — GET /report
# ==============================================================================

class TestRoutesReport(unittest.TestCase):
    """GET /report's auth gate plus its placeholder-vs-real-file HTML rendering."""
    # /report (redirect to /) and / itself are gated behind
    # platform.manage_infra (control.omnibioai.org direct-tunnel audit) --
    # these tests exercise the redirect + underlying page rendering, not
    # authorization (see test_main.py's TestPlatformManageInfraAuth for the
    # 401/403 checks), so requests here carry an always-sufficient token.

    def test_401_when_no_token(self) -> None:
        """An unauthenticated request is rejected with 401."""
        response = client.get("/report", follow_redirects=False)
        self.assertEqual(response.status_code, 401)

    def test_report_returns_200(self) -> None:
        """An authorized request succeeds with 200."""
        response = client.get("/report", headers=_admin_headers())
        self.assertEqual(response.status_code, 200)

    def test_report_returns_html(self) -> None:
        """The response Content-Type is text/html."""
        response = client.get("/report", headers=_admin_headers())
        self.assertIn("text/html", response.headers["content-type"])

    def test_report_shows_placeholder_when_no_file(self) -> None:
        """With no generated report file under WORKSPACE_ROOT, a "No ecosystem report found" placeholder is rendered."""
        os.environ["WORKSPACE_ROOT"] = "/nonexistent/workspace"
        try:
            response = client.get("/report", headers=_admin_headers())
            self.assertIn("No ecosystem report found", response.text)
        finally:
            del os.environ["WORKSPACE_ROOT"]

    def test_report_placeholder_contains_generate_command(self) -> None:
        """The missing-report placeholder points the caller at POST /report/generate."""
        os.environ["WORKSPACE_ROOT"] = "/nonexistent/workspace"
        try:
            response = client.get("/report", headers=_admin_headers())
            self.assertIn("/report/generate", response.text)
        finally:
            del os.environ["WORKSPACE_ROOT"]

    def test_report_serves_file_when_exists(self) -> None:
        """When work/out/reports/omnibioai_ecosystem_report.html exists under WORKSPACE_ROOT, its contents are served."""
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "work" / "out" / "reports"
            report_dir.mkdir(parents=True)
            report_file = report_dir / "omnibioai_ecosystem_report.html"
            report_file.write_text("<html><body>Test Report</body></html>")
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                response = client.get("/report", headers=_admin_headers())
                self.assertIn("Test Report", response.text)
            finally:
                del os.environ["WORKSPACE_ROOT"]

    def test_report_file_content_is_preserved(self) -> None:
        """The served report's HTML content is passed through byte-for-byte, not re-rendered or escaped."""
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "work" / "out" / "reports"
            report_dir.mkdir(parents=True)
            content = "<html><body><h1>OmniBioAI Report</h1></body></html>"
            (report_dir / "omnibioai_ecosystem_report.html").write_text(content)
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                response = client.get("/report", headers=_admin_headers())
                self.assertIn("<h1>OmniBioAI Report</h1>", response.text)
            finally:
                del os.environ["WORKSPACE_ROOT"]


if __name__ == "__main__":
    unittest.main()