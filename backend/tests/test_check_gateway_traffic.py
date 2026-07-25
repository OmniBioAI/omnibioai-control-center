"""
tests/test_check_gateway_traffic.py

Unit tests for:
  - control_center.checks.gateway_traffic
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import gateway_traffic


def _entry(eid: str, **fields: object) -> tuple[str, dict]:
    return (eid, {"data": json.dumps(fields)})


class TestPercentile(unittest.TestCase):

    def test_empty_list_returns_zero(self) -> None:
        self.assertEqual(gateway_traffic._percentile([], 0.95), 0)

    def test_returns_value_at_percentile(self) -> None:
        values = list(range(1, 101))  # 1..100
        self.assertEqual(gateway_traffic._percentile(values, 0.50), values[50])

    def test_clamps_to_last_index(self) -> None:
        values = [10.0, 20.0, 30.0]
        self.assertEqual(gateway_traffic._percentile(values, 0.99), 30)


class TestGetGatewayTraffic(unittest.TestCase):

    def test_redis_unreachable_returns_empty_shape(self) -> None:
        with patch("redis.Redis.from_url", side_effect=ConnectionError("down")):
            result = gateway_traffic.get_gateway_traffic()
        self.assertEqual(result, dict(gateway_traffic._EMPTY))

    def test_malformed_json_skipped(self) -> None:
        mock_r = MagicMock()
        mock_r.xrange.return_value = [("1-0", {"data": "not-json"})]
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()
        self.assertEqual(result["requests_7d"], 0)

    def test_health_pings_counted_separately_from_requests(self) -> None:
        entries = [_entry("1-0", event_type="request", action="/svc/health")]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()
        self.assertEqual(result["requests_7d"], 0)
        self.assertEqual(result["health_check_pings_7d"], 1)

    def test_aggregates_routes_latency_and_status_buckets(self) -> None:
        entries = [
            _entry("1-0", event_type="request", action="/api/foo", decision="allow",
                   latency_ms=10, status_code=200),
            _entry("2-0", event_type="request", action="/api/foo", decision="allow",
                   latency_ms=20, status_code=200),
            _entry("3-0", event_type="request", action="/api/bar", decision="deny",
                   latency_ms=30, status_code=404),
            _entry("4-0", event_type="request", action="/api/baz", latency_ms=500, status_code=503),
        ]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(result["requests_7d"], 4)
        self.assertEqual(result["status_code_breakdown"], {"2xx": 2, "4xx": 1, "5xx": 1})
        routes = {r["route"]: r["count"] for r in result["requests_by_route"]}
        self.assertEqual(routes, {"/api/foo": 2, "/api/bar": 1, "/api/baz": 1})
        self.assertEqual(result["p50_latency_ms"], 30)
        self.assertAlmostEqual(result["auth_failure_rate_pct"], 25.0)

    def test_deny_events_counted_as_requests_with_inferred_status(self) -> None:
        entries = [_entry("1-0", event_type="hpc_denied", action="/hpc/submit")]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(result["requests_7d"], 1)
        self.assertEqual(result["status_code_breakdown"], {"2xx": 0, "4xx": 1, "5xx": 0})
        self.assertEqual(result["auth_failure_rate_pct"], 100.0)

    def test_non_numeric_latency_and_status_ignored(self) -> None:
        entries = [_entry("1-0", event_type="request", action="/api/foo",
                           latency_ms="slow", status_code="oops")]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(result["p50_latency_ms"], 0)
        self.assertEqual(result["status_code_breakdown"], {"2xx": 0, "4xx": 0, "5xx": 0})

    def test_top_routes_limited(self) -> None:
        entries = [
            _entry(f"{i}-0", event_type="request", action=f"/api/route{i}")
            for i in range(gateway_traffic._TOP_ROUTES_LIMIT + 5)
        ]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(len(result["requests_by_route"]), gateway_traffic._TOP_ROUTES_LIMIT)


if __name__ == "__main__":
    unittest.main()
