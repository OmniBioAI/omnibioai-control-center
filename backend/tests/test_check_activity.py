"""
tests/test_check_activity.py

Unit tests for:
  - control_center.checks.activity
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import activity


def _prom_result(name: str, value: float) -> dict:
    return {"metric": {"name": name}, "value": ["1234567890", str(value)]}


def _scalar_result(value: float) -> list[dict]:
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

    def test_non_success_status_returns_empty(self) -> None:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"status": "error"}
        client = MagicMock()
        client.get.return_value = resp
        result = activity._prom_query(client, "up")
        self.assertEqual(result, [])

    def test_raises_on_http_error(self) -> None:
        resp = MagicMock()
        resp.raise_for_status.side_effect = RuntimeError("http fail")
        client = MagicMock()
        client.get.return_value = resp
        with self.assertRaises(RuntimeError):
            activity._prom_query(client, "up")


class TestScalar(unittest.TestCase):

    def test_returns_float_value(self) -> None:
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {
            "status": "success", "data": {"result": _scalar_result(42.5)},
        }
        self.assertEqual(activity._scalar(client, "up"), 42.5)

    def test_returns_none_when_empty(self) -> None:
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {"status": "success", "data": {"result": []}}
        self.assertIsNone(activity._scalar(client, "up"))

    def test_returns_none_on_malformed_value(self) -> None:
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": ["1234", "not-a-float"]}]},
        }
        self.assertIsNone(activity._scalar(client, "up"))


class TestByName(unittest.TestCase):

    def test_builds_name_to_value_map(self) -> None:
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {
            "status": "success",
            "data": {"result": [_prom_result("web", 12.3), _prom_result("db", 45.6)]},
        }
        result = activity._by_name(client, "some_query")
        self.assertEqual(result, {"web": 12.3, "db": 45.6})

    def test_skips_entries_missing_name(self) -> None:
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": ["1234", "1.0"]}]},
        }
        result = activity._by_name(client, "some_query")
        self.assertEqual(result, {})

    def test_skips_entries_with_malformed_value(self) -> None:
        client = MagicMock()
        client.get.return_value.raise_for_status = MagicMock()
        client.get.return_value.json.return_value = {
            "status": "success",
            "data": {"result": [{"metric": {"name": "web"}, "value": ["1234", "nope"]}]},
        }
        result = activity._by_name(client, "some_query")
        self.assertEqual(result, {})


class TestGetActivityStatus(unittest.TestCase):

    def test_reports_containers_and_host_when_node_up(self) -> None:
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
        with patch.object(activity.httpx, "Client", side_effect=RuntimeError("connection refused")):
            result = activity.get_activity_status()

        self.assertFalse(result["reachable"])
        self.assertEqual(result["containers"], [])
        self.assertIsNone(result["host"])
        self.assertIn("RuntimeError", result["error"])


if __name__ == "__main__":
    unittest.main()
