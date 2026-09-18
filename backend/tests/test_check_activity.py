"""
tests/test_check_activity.py

Unit tests for:
  - control_center.checks.activity

Covers the low-level PromQL helpers (_prom_query's non-success/HTTP-
error handling, _scalar's float extraction, _by_name's name-keyed map
building with malformed/missing entries skipped) and get_activity_status()'s
end-to-end container + host telemetry assembly, including the node-
exporter-not-up degraded case and a total client-construction failure.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import activity


def _prom_result(name: str, value: float) -> dict:
    """A single Prometheus vector-result entry with a "name" metric label."""
    return {"metric": {"name": name}, "value": ["1234567890", str(value)]}


def _scalar_result(value: float) -> list[dict]:
    """A single-entry Prometheus vector result with no metric labels,
    suitable for _scalar()."""
    return [{"metric": {}, "value": ["1234567890", str(value)]}]


def _fake_client(query_map: dict[str, list[dict]], raise_on: str | None = None):
    """Build a MagicMock standing in for `httpx.Client(...)` used as a
    context manager, whose `.get(query=...)` routes on the `query` param."""

    def fake_get(url, params=None):
        query = (params or {}).get("query", "")
        if raise_on and raise_on in query:
            raise ConnectionError("boom")
        for key, result in query_map.items():
            if key in query:
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                resp.json.return_value = {"status": "success", "data": {"result": result}}
                return resp
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"status": "success", "data": {"result": []}}
        return resp

    mock_client = MagicMock()
    mock_client.get = MagicMock(side_effect=fake_get)
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_client)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    return mock_ctx


class TestPromQuery(unittest.TestCase):
    """_prom_query()'s handling of a non-success Prometheus status vs.
    an HTTP-level error."""

    def test_non_success_status_returns_empty(self) -> None:
        """A 200 response whose body's own status is not "success"
        returns an empty list rather than raising."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"status": "error"}
        client = MagicMock()
        client.get.return_value = resp
        result = activity._prom_query(client, "up")
        self.assertEqual(result, [])

    def test_raises_on_http_error(self) -> None:
        """An HTTP-level error (raise_for_status) propagates as-is."""
        resp = MagicMock()
        resp.raise_for_status.side_effect = RuntimeError("http fail")
        client = MagicMock()
        client.get.return_value = resp
        with self.assertRaises(RuntimeError):
            activity._prom_query(client, "up")


class TestScalar(unittest.TestCase):
    """_scalar()'s single-float extraction, failing safe to None on an
    empty or malformed result."""

    def test_returns_float_value(self) -> None:
        """A well-formed single-value result parses to its float."""
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {
            "status": "success", "data": {"result": _scalar_result(42.5)},
        }
        self.assertEqual(activity._scalar(client, "up"), 42.5)

    def test_returns_none_when_empty(self) -> None:
        """An empty result list returns None."""
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {"status": "success", "data": {"result": []}}
        self.assertIsNone(activity._scalar(client, "up"))

    def test_returns_none_on_malformed_value(self) -> None:
        """A non-numeric value string returns None rather than raising."""
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": ["1234", "not-a-float"]}]},
        }
        self.assertIsNone(activity._scalar(client, "up"))


class TestByName(unittest.TestCase):
    """_by_name()'s name-keyed value map, skipping any entry missing a
    "name" label or carrying a malformed value."""

    def test_builds_name_to_value_map(self) -> None:
        """Multiple named results build a {name: float} map."""
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {
            "status": "success",
            "data": {"result": [_prom_result("web", 12.3), _prom_result("db", 45.6)]},
        }
        result = activity._by_name(client, "some_query")
        self.assertEqual(result, {"web": 12.3, "db": 45.6})

    def test_skips_entries_missing_name(self) -> None:
        """An entry with no "name" metric label is skipped, not
        included under a None/empty key."""
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": ["1234", "1.0"]}]},
        }
        result = activity._by_name(client, "some_query")
        self.assertEqual(result, {})

    def test_skips_entries_with_malformed_value(self) -> None:
        """An entry with a non-numeric value is skipped rather than
        raising or being included with a garbage value."""
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {"name": "web"}, "value": ["1234", "nope"]}]},
        }
        result = activity._by_name(client, "some_query")
        self.assertEqual(result, {})


class TestGetActivityStatus(unittest.TestCase):
    """get_activity_status()'s end-to-end container + host telemetry
    assembly, and its degraded/failure fallbacks."""

    def test_reports_containers_and_host_when_node_up(self) -> None:
        """With node_exporter up and full container metrics available,
        the result reports both containers (with computed cpu_pct/
        memory_pct/pids) and host stats (load/memory)."""
        query_map = {
            "container_cpu_usage_seconds_total": [_prom_result("web", 10.0)],
            "container_memory_usage_bytes": [_prom_result("web", 2_000_000.0)],
            "container_spec_memory_limit_bytes": [_prom_result("web", 4_000_000.0)],
            "container_network_receive_bytes_total": [_prom_result("web", 1_000_000.0)],
            "container_network_transmit_bytes_total": [_prom_result("web", 500_000.0)],
            "container_tasks_state": [_prom_result("web", 3.0)],
            'up{job="node"}': _scalar_result(1.0),
            'mode="system"': _scalar_result(5.0),
            'mode="user"': _scalar_result(10.0),
            'mode="idle"': _scalar_result(85.0),
            "node_load1": _scalar_result(0.5),
            "node_load5": _scalar_result(0.6),
            "node_load15": _scalar_result(0.7),
            "node_memory_MemTotal_bytes": _scalar_result(16e9),
            "node_memory_MemAvailable_bytes": _scalar_result(8e9),
            "node_memory_SwapTotal_bytes": _scalar_result(2e9),
            "node_memory_SwapFree_bytes": _scalar_result(1.5e9),
            "node_processes_pids": _scalar_result(120.0),
            "node_processes_threads": _scalar_result(500.0),
        }
        with patch.object(activity.httpx, "Client", return_value=_fake_client(query_map)):
            result = activity.get_activity_status()

        self.assertTrue(result["reachable"])
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["containers"]), 1)
        container = result["containers"][0]
        self.assertEqual(container["name"], "web")
        self.assertEqual(container["cpu_pct"], 10.0)
        self.assertEqual(container["memory_pct"], 50.0)
        self.assertEqual(container["pids"], 3)
        self.assertIsNotNone(result["host"])
        self.assertEqual(result["host"]["load_1m"], 0.5)
        self.assertEqual(result["host"]["memory_total_gb"], 16.0)

    def test_host_error_when_node_exporter_not_up(self) -> None:
        """When node_exporter's own "up" metric is 0, host is None and
        an error message names "node_exporter", while containers still
        report an empty list rather than raising."""
        query_map = {
            "container_cpu_usage_seconds_total": [],
            "container_memory_usage_bytes": [],
            'up{job="node"}': _scalar_result(0.0),
        }
        with patch.object(activity.httpx, "Client", return_value=_fake_client(query_map)):
            result = activity.get_activity_status()

        self.assertTrue(result["reachable"])
        self.assertIsNone(result["host"])
        self.assertIn("node_exporter", result["error"])
        self.assertEqual(result["containers"], [])

    def test_missing_limit_gives_none_memory_pct(self) -> None:
        """A container with no reported memory limit gets
        memory_pct=None and memory_limit_mb=None rather than a
        division-by-zero or fabricated percentage."""
        query_map = {
            "container_cpu_usage_seconds_total": [_prom_result("web", 1.0)],
            "container_memory_usage_bytes": [_prom_result("web", 100.0)],
            "container_spec_memory_limit_bytes": [],
            'up{job="node"}': _scalar_result(0.0),
        }
        with patch.object(activity.httpx, "Client", return_value=_fake_client(query_map)):
            result = activity.get_activity_status()

        container = result["containers"][0]
        self.assertIsNone(container["memory_pct"])
        self.assertIsNone(container["memory_limit_mb"])

    def test_exception_reports_unreachable(self) -> None:
        """A failure constructing the httpx client at all reports
        reachable=False with the exception type named in the error message."""
        with patch.object(activity.httpx, "Client", side_effect=RuntimeError("connection refused")):
            result = activity.get_activity_status()

        self.assertFalse(result["reachable"])
        self.assertEqual(result["containers"], [])
        self.assertIsNone(result["host"])
        self.assertIn("RuntimeError", result["error"])


if __name__ == "__main__":
    unittest.main()
