"""
tests/test_check_audit_trail.py

Unit tests for:
  - control_center.checks.audit_trail
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import audit_trail


def _entry(eid: str, **fields: object) -> tuple[str, dict]:
    return (eid, {"data": json.dumps(fields)})


class TestIsHealthPing(unittest.TestCase):

    def test_request_to_health_is_ping(self) -> None:
        self.assertTrue(audit_trail._is_health_ping("request", "/service/health"))

    def test_request_to_other_path_is_not_ping(self) -> None:
        self.assertFalse(audit_trail._is_health_ping("request", "/service/data"))

    def test_non_request_event_type_is_not_ping(self) -> None:
        self.assertFalse(audit_trail._is_health_ping("auth_failed", "/service/health"))


class TestGetAuditTrail(unittest.TestCase):

    def test_redis_unreachable_returns_empty_shape(self) -> None:
        with patch("redis.Redis.from_url", side_effect=ConnectionError("down")):
            result = audit_trail.get_audit_trail()
        self.assertEqual(result, dict(audit_trail._EMPTY))

    def test_aggregates_events_and_breakdowns(self) -> None:
        entries = [
            _entry("1000-0", event_type="request", action="/api/foo", decision="allow",
                   user_id="u1", status_code=200, latency_ms=12, trace_id="t1"),
            _entry("2000-0", event_type="request", action="/api/foo", decision="allow",
                   user_id="u2", status_code=200, latency_ms=20),
            _entry("3000-0", event_type="auth_failed", action="/api/bar",
                   decision="deny", reason="bad_token", user_id="u1"),
            _entry("4000-0", event_type="request", action="/svc/health", decision="allow"),
        ]
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = entries

        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = audit_trail.get_audit_trail()

        self.assertEqual(result["total_events"], 4)
        self.assertEqual(result["health_check_pings"], 1)
        self.assertEqual(result["distinct_actors"], 2)
        self.assertEqual(result["decision_breakdown"], {"allow": 3, "deny": 1})
        self.assertEqual(result["status_code_breakdown"], {"200": 2, "401": 1})
        reasons = {r["reason"]: r["count"] for r in result["reason_breakdown"]}
        self.assertEqual(reasons, {"bad_token": 1})
        event_types = {e["event_type"]: e["count"] for e in result["event_type_breakdown"]}
        self.assertEqual(event_types, {"request": 3, "auth_failed": 1})
        # non-health events sorted newest first by id
        non_health_ids = [e["id"] for e in result["events"] if not e["is_health_check"]]
        self.assertEqual(non_health_ids, ["3000-0", "2000-0", "1000-0"])

    def test_deny_event_infers_status_code_from_map(self) -> None:
        entries = [_entry("1000-0", event_type="policy_denied", action="/api/secret")]
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = audit_trail.get_audit_trail()
        self.assertEqual(result["status_code_breakdown"], {"403": 1})

    def test_malformed_json_entry_skipped(self) -> None:
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [("1000-0", {"data": "not-json"})]
        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = audit_trail.get_audit_trail()
        self.assertEqual(result["total_events"], 0)

    def test_health_events_sampled_to_cap(self) -> None:
        entries = [
            _entry(f"{i}-0", event_type="request", action="/svc/health", decision="allow")
            for i in range(1, audit_trail._HEALTH_SAMPLE_CAP + 20)
        ]
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = audit_trail.get_audit_trail()
        self.assertEqual(result["health_check_pings"], len(entries))
        health_events = [e for e in result["events"] if e["is_health_check"]]
        self.assertEqual(len(health_events), audit_trail._HEALTH_SAMPLE_CAP)

    def test_decision_outside_known_set_not_counted(self) -> None:
        entries = [_entry("1000-0", event_type="request", action="/api/foo", decision="weird")]
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = audit_trail.get_audit_trail()
        self.assertEqual(result["decision_breakdown"], {"allow": 0, "deny": 0})


if __name__ == "__main__":
    unittest.main()
