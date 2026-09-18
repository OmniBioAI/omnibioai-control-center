"""
tests/test_check_gateway_traffic.py

Unit tests for:
  - control_center.checks.gateway_traffic

Covers _percentile()'s clamping/indexing and get_gateway_traffic()'s
aggregation of audit:events into route/latency/status-code breakdowns
(health pings counted separately from real requests; deny-classified
events counted as requests with an inferred status code), plus the
HIPAA PR3d integrity-aware aggregation: valid-signed and legacy-unsigned
events count normally, but a tampered, malformed-signature, or wrong-
secret-signed event is excluded from every numeric aggregate while still
being visibly counted as invalid, never silently dropped.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import gateway_traffic


def _entry(eid: str, *, sig: str | None = None, **fields: object) -> tuple[str, dict]:
    """A fake Redis XRANGE entry (event_id, {"data": <json fields>, ...})
    with an optional "sig" field."""
    redis_fields: dict = {"data": json.dumps(fields)}
    if sig is not None:
        redis_fields["sig"] = sig
    return (eid, redis_fields)


def _sign(service: str, data: str, secret: str) -> str:
    """Independent re-implementation of the sign side of the construction
    gateway_traffic.py's imported classify_event_integrity checks against
    -- see test_check_audit_trail.py's own identical helper."""
    mac = hmac.new(
        hashlib.sha256(f"omnibioai-audit-events:{secret}".encode()).digest(),
        f"v1\n{service}\n{data}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"v1:{mac}"


class TestPercentile(unittest.TestCase):
    """_percentile()'s index calculation, including empty-list and
    out-of-range clamping."""

    def test_empty_list_returns_zero(self) -> None:
        """An empty values list returns 0."""
        self.assertEqual(gateway_traffic._percentile([], 0.95), 0)

    def test_returns_value_at_percentile(self) -> None:
        """A 100-value list returns the value at the requested percentile index."""
        values = list(range(1, 101))  # 1..100
        self.assertEqual(gateway_traffic._percentile(values, 0.50), values[50])

    def test_clamps_to_last_index(self) -> None:
        """A percentile whose computed index would exceed the list
        clamps to the last element rather than raising IndexError."""
        values = [10.0, 20.0, 30.0]
        self.assertEqual(gateway_traffic._percentile(values, 0.99), 30)


class TestGetGatewayTraffic(unittest.TestCase):
    """get_gateway_traffic()'s aggregation of audit:events into route/
    latency/status-code breakdowns, and its graceful degradation."""

    def test_redis_unreachable_returns_empty_shape(self) -> None:
        """A Redis connection failure returns the documented empty shape."""
        with patch("redis.Redis.from_url", side_effect=ConnectionError("down")):
            result = gateway_traffic.get_gateway_traffic()
        self.assertEqual(result, dict(gateway_traffic._EMPTY))

    def test_malformed_json_skipped(self) -> None:
        """A stream entry whose "data" isn't valid JSON is skipped
        rather than raising."""
        mock_r = MagicMock()
        mock_r.xrange.return_value = [("1-0", {"data": "not-json"})]
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()
        self.assertEqual(result["requests_7d"], 0)

    def test_health_pings_counted_separately_from_requests(self) -> None:
        """A /*/health request increments health_check_pings_7d, not
        requests_7d."""
        entries = [_entry("1-0", event_type="request", action="/svc/health")]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()
        self.assertEqual(result["requests_7d"], 0)
        self.assertEqual(result["health_check_pings_7d"], 1)

    def test_aggregates_routes_latency_and_status_buckets(self) -> None:
        """Requests aggregate correctly into per-route counts, status-
        code buckets (2xx/4xx/5xx), the p50 latency, and the auth-
        failure rate."""
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
        """A hpc_denied event counts as a request with an inferred 4xx
        status code, contributing to the auth-failure rate."""
        entries = [_entry("1-0", event_type="hpc_denied", action="/hpc/submit")]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(result["requests_7d"], 1)
        self.assertEqual(result["status_code_breakdown"], {"2xx": 0, "4xx": 1, "5xx": 0})
        self.assertEqual(result["auth_failure_rate_pct"], 100.0)

    def test_non_numeric_latency_and_status_ignored(self) -> None:
        """A non-numeric latency_ms/status_code is ignored rather than
        raising or corrupting the aggregate."""
        entries = [_entry("1-0", event_type="request", action="/api/foo",
                           latency_ms="slow", status_code="oops")]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(result["p50_latency_ms"], 0)
        self.assertEqual(result["status_code_breakdown"], {"2xx": 0, "4xx": 0, "5xx": 0})

    def test_top_routes_limited(self) -> None:
        """More distinct routes than _TOP_ROUTES_LIMIT still returns at
        most that many entries in requests_by_route."""
        entries = [
            _entry(f"{i}-0", event_type="request", action=f"/api/route{i}")
            for i in range(gateway_traffic._TOP_ROUTES_LIMIT + 5)
        ]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(len(result["requests_by_route"]), gateway_traffic._TOP_ROUTES_LIMIT)


class TestIntegrityAwareAggregation(unittest.TestCase):
    """HIPAA PR3d: valid/unsigned events must aggregate exactly as before;
    invalid (tampered/forged) events must be excluded from every numeric
    aggregate, but their exclusion must be visible, not silent."""

    def test_valid_signed_event_counted_normally(self) -> None:
        """A correctly-signed event verifies and counts in every
        aggregate exactly as an unsigned one would."""
        fields = {"event_type": "request", "action": "/api/foo", "decision": "allow",
                   "status_code": 200, "latency_ms": 15, "service": "gateway"}
        data = json.dumps(fields)
        sig = _sign("gateway", data, gateway_traffic.JWT_SECRET)
        entries = [("1-0", {"data": data, "sig": sig})]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(result["requests_7d"], 1)
        self.assertEqual(result["status_code_breakdown"], {"2xx": 1, "4xx": 0, "5xx": 0})
        self.assertEqual(result["invalid_signature_events_7d"], 0)

    def test_unsigned_event_counted_normally(self) -> None:
        """Pre-PR3b's entire history (and today's still-mixed backlog) is
        unsigned by design, not tampered -- must count exactly like every
        pre-existing test in this file that never signs anything."""
        entries = [_entry("1-0", event_type="request", action="/api/foo",
                           decision="allow", status_code=200, service="gateway")]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(result["requests_7d"], 1)
        self.assertEqual(result["invalid_signature_events_7d"], 0)

    def test_tampered_event_excluded_from_aggregates_but_counted_as_invalid(self) -> None:
        """An event whose published data differs from what was signed
        is excluded from requests_7d/status/latency/failure-rate, but
        is still counted under invalid_signature_events_7d -- never
        silently dropped."""
        fields = {"event_type": "request", "action": "/api/foo", "decision": "allow",
                   "status_code": 200, "latency_ms": 999, "service": "gateway"}
        data = json.dumps(fields)
        sig = _sign("gateway", data, gateway_traffic.JWT_SECRET)
        # Published payload differs from what was signed -- the exact
        # mutation-must-be-caught scenario.
        tampered = json.dumps({**fields, "decision": "deny"})
        entries = [("1-0", {"data": tampered, "sig": sig})]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(result["requests_7d"], 0)
        self.assertEqual(result["status_code_breakdown"], {"2xx": 0, "4xx": 0, "5xx": 0})
        self.assertEqual(result["p50_latency_ms"], 0)
        self.assertEqual(result["auth_failure_rate_pct"], 0.0)
        self.assertEqual(result["invalid_signature_events_7d"], 1)

    def test_malformed_signature_excluded_same_as_tampered_not_crash(self) -> None:
        """A "sig" value that isn't even a well-formed signature string
        is excluded the same way as a tampered one, without raising."""
        entries = [_entry("1-0", sig="not-a-real-signature", event_type="request",
                           action="/api/foo", decision="deny", service="gateway")]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()  # must not raise

        self.assertEqual(result["requests_7d"], 0)
        self.assertEqual(result["invalid_signature_events_7d"], 1)

    def test_wrong_secret_never_silently_counted_as_valid(self) -> None:
        """A signature computed with the wrong secret is rejected, not
        silently trusted just because it has the right shape."""
        fields = {"event_type": "request", "action": "/api/foo", "decision": "deny",
                   "service": "gateway"}
        data = json.dumps(fields)
        sig = _sign("gateway", data, "a-different-secret-than-jwt_secret")
        entries = [("1-0", {"data": data, "sig": sig})]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(result["requests_7d"], 0)
        self.assertEqual(result["auth_failure_rate_pct"], 0.0)
        self.assertEqual(result["invalid_signature_events_7d"], 1)

    def test_valid_and_invalid_events_mixed_in_the_same_window(self) -> None:
        """In a single window with a valid-signed, an invalid-signed,
        and an unsigned event, only the valid+unsigned ones count toward
        requests_7d, while the invalid one is still tallied separately."""
        good_fields = {"event_type": "request", "action": "/api/foo",
                        "decision": "allow", "status_code": 200, "service": "gateway"}
        good_data = json.dumps(good_fields)
        good_sig = _sign("gateway", good_data, gateway_traffic.JWT_SECRET)
        entries = [
            ("1-0", {"data": good_data, "sig": good_sig}),
            ("2-0", {"data": good_data, "sig": "v1:deadbeef"}),  # invalid
            _entry("3-0", event_type="request", action="/api/foo",
                   decision="allow", status_code=200, service="gateway"),  # unsigned
        ]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = gateway_traffic.get_gateway_traffic()

        self.assertEqual(result["requests_7d"], 2)  # valid + unsigned, not the invalid one
        self.assertEqual(result["invalid_signature_events_7d"], 1)


if __name__ == "__main__":
    unittest.main()
