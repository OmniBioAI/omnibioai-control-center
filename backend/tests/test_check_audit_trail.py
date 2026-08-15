"""
tests/test_check_audit_trail.py

Unit tests for:
  - control_center.checks.audit_trail
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from typing import Optional
from unittest.mock import MagicMock, patch

from control_center.checks import audit_trail


def _entry(eid: str, *, sig: Optional[str] = None, **fields: object) -> tuple[str, dict]:
    redis_fields: dict = {"data": json.dumps(fields)}
    if sig is not None:
        redis_fields["sig"] = sig
    return (eid, redis_fields)


def _sign(service: str, data: str, secret: str) -> str:
    """Independent re-implementation of the sign side of the same
    construction audit_trail.verify_audit_event checks -- deliberately
    not calling into audit_trail's own private helpers for the MAC
    computation itself (only for the version tag), so a test signature
    built here doesn't share a bug with the code under test."""
    mac = hmac.new(
        hashlib.sha256(f"omnibioai-audit-events:{secret}".encode()).digest(),
        f"{audit_trail._SIGNING_VERSION}\n{service}\n{data}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{audit_trail._SIGNING_VERSION}:{mac}"


# Same fixed (service, data, secret) -> signature triple used by every other
# PR3b producer's own test_audit_signing.py (api-gateway/tes/workflow-bundles/
# rag) and this repo's own test_audit_log_signing.py -- generated once from
# the real omnibioai-security-audit audit.signing.sign_audit_event(). A
# passing test_matches_real_consumer_signing_vector proves this endpoint's
# independent verify_audit_event() hand-port is byte-for-byte compatible
# with the real producer/consumer construction, without importing or
# depending on that repo at runtime or test time.
CROSS_REPO_VECTOR = {
    "service": "gateway",
    "data": (
        '{"event_id": "11111111-1111-1111-1111-111111111111", "timestamp": '
        '"2026-01-01T00:00:00+00:00", "service": "gateway", "event_type": '
        '"request", "user_id": null, "action": "", "resource": null, '
        '"decision": null, "reason": null, "trace_id": null, "context": {}}'
    ),
    "secret": "test-secret-vector",
    "sig": "v1:96b18a8dbd82707a78b14a7c446acfef50d3882c9d5160ffad6084d0771c7410",
}


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


class TestVerifyAuditEvent(unittest.TestCase):
    """Direct tests of the local verification helpers (HIPAA PR3c) --
    mirrors the structure of omnibioai-security-audit's own
    tests/test_signing.py for the equivalent function."""

    def test_matches_real_consumer_signing_vector(self) -> None:
        """Byte-for-byte proof this hand-port accepts the exact signature
        the real omnibioai-security-audit verify_audit_event() would --
        without this repo importing or depending on that one."""
        v = CROSS_REPO_VECTOR
        self.assertTrue(
            audit_trail.verify_audit_event(v["service"], v["data"], v["sig"], v["secret"])
        )

    def test_tampered_data_fails_the_same_vector(self) -> None:
        v = CROSS_REPO_VECTOR
        self.assertFalse(
            audit_trail.verify_audit_event(v["service"], v["data"] + "x", v["sig"], v["secret"])
        )

    def test_wrong_secret_fails_the_same_vector(self) -> None:
        v = CROSS_REPO_VECTOR
        self.assertFalse(
            audit_trail.verify_audit_event(v["service"], v["data"], v["sig"], "not-the-secret")
        )

    def test_malformed_signature_fails_closed_not_crash(self) -> None:
        self.assertFalse(
            audit_trail.verify_audit_event("gateway", '{"a": 1}', "not-a-real-signature", "s")
        )
        self.assertFalse(audit_trail.verify_audit_event("gateway", '{"a": 1}', "", "s"))
        self.assertFalse(audit_trail.verify_audit_event("gateway", '{"a": 1}', None, "s"))

    def test_unknown_version_prefix_fails_closed(self) -> None:
        self.assertFalse(
            audit_trail.verify_audit_event("gateway", '{"a": 1}', "v2:deadbeef", "s")
        )

    def test_none_data_fails_closed(self) -> None:
        v = CROSS_REPO_VECTOR
        self.assertFalse(
            audit_trail.verify_audit_event(v["service"], None, v["sig"], v["secret"])
        )

    def test_non_string_signature_never_raises(self) -> None:
        """Adversarially-shaped input (e.g. a stream field decoded as
        something other than str) must still fail closed, not raise --
        this is what the blanket except Exception at the bottom of
        verify_audit_event exists for."""
        self.assertFalse(audit_trail.verify_audit_event("gateway", '{"a": 1}', 12345, "s"))
        self.assertFalse(audit_trail.verify_audit_event(None, '{"a": 1}', "v1:ab", "s"))

    def test_classify_missing_signature_is_unsigned(self) -> None:
        self.assertEqual(
            audit_trail.classify_event_integrity("gateway", None, '{"a": 1}', "s"), "unsigned"
        )

    def test_classify_valid_signature_is_valid(self) -> None:
        data = '{"a": 1}'
        sig = _sign("gateway", data, "s3cr3t")
        self.assertEqual(
            audit_trail.classify_event_integrity("gateway", sig, data, "s3cr3t"), "valid"
        )

    def test_classify_invalid_signature_is_invalid(self) -> None:
        data = '{"a": 1}'
        sig = _sign("gateway", data, "s3cr3t")
        self.assertEqual(
            audit_trail.classify_event_integrity("gateway", sig, data, "wrong-secret"), "invalid"
        )


class TestAuditTrailIntegrityStatus(unittest.TestCase):
    """HIPAA PR3c: checks/audit_trail.py must classify every event's
    signature integrity, additively -- existing aggregate behavior
    (TestGetAuditTrail above) must not change."""

    def test_valid_signed_event_is_classified_valid(self) -> None:
        fields = {"event_type": "request", "action": "/api/foo", "decision": "allow",
                   "service": "gateway"}
        data = json.dumps(fields)
        sig = _sign("gateway", data, audit_trail.JWT_SECRET)
        entries = [("1000-0", {"data": data, "sig": sig})]
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = audit_trail.get_audit_trail()
        self.assertEqual(result["events"][0]["integrity_status"], "valid")

    def test_tampered_signature_is_classified_invalid(self) -> None:
        fields = {"event_type": "request", "action": "/api/foo", "decision": "allow",
                   "service": "gateway"}
        data = json.dumps(fields)
        # Sign the real payload, then publish a different one under that
        # same signature -- the exact mutation-must-be-caught scenario.
        sig = _sign("gateway", data, audit_trail.JWT_SECRET)
        tampered = json.dumps({**fields, "decision": "deny"})
        entries = [("1000-0", {"data": tampered, "sig": sig})]
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = audit_trail.get_audit_trail()
        self.assertEqual(result["events"][0]["integrity_status"], "invalid")

    def test_unsigned_event_is_classified_unsigned(self) -> None:
        entries = [_entry("1000-0", event_type="request", action="/api/foo",
                           decision="allow", service="gateway")]
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = audit_trail.get_audit_trail()
        self.assertEqual(result["events"][0]["integrity_status"], "unsigned")

    def test_malformed_signature_is_classified_invalid_not_crash(self) -> None:
        entries = [_entry("1000-0", sig="garbage-not-hex-or-versioned",
                           event_type="request", action="/api/foo",
                           decision="allow", service="gateway")]
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = audit_trail.get_audit_trail()  # must not raise
        self.assertEqual(result["events"][0]["integrity_status"], "invalid")

    def test_wrong_secret_never_silently_passes_as_valid(self) -> None:
        """A genuinely-signed event, but signed under a secret that isn't
        this process's JWT_SECRET (the exact drift scenario flagged in
        the PR3c investigation) -- must classify invalid, loudly, never
        silently valid."""
        fields = {"event_type": "request", "action": "/api/foo", "decision": "allow",
                   "service": "gateway"}
        data = json.dumps(fields)
        sig = _sign("gateway", data, "a-different-secret-than-jwt_secret")
        entries = [("1000-0", {"data": data, "sig": sig})]
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = audit_trail.get_audit_trail()
        self.assertEqual(result["events"][0]["integrity_status"], "invalid")

    def test_integrity_status_does_not_change_existing_aggregates(self) -> None:
        """Same fixture as test_aggregates_events_and_breakdowns above, now
        carrying a mix of unsigned/valid/invalid events -- every existing
        aggregate must come out identical to the pre-PR3c behavior."""
        fields_1 = {"event_type": "request", "action": "/api/foo", "decision": "allow",
                     "user_id": "u1", "status_code": 200, "latency_ms": 12,
                     "trace_id": "t1", "service": "gateway"}
        data_1 = json.dumps(fields_1)
        entries = [
            ("1000-0", {"data": data_1, "sig": _sign("gateway", data_1, audit_trail.JWT_SECRET)}),
            _entry("2000-0", event_type="request", action="/api/foo", decision="allow",
                   user_id="u2", status_code=200, latency_ms=20),  # unsigned
            _entry("3000-0", sig="v1:deadbeef", event_type="auth_failed", action="/api/bar",
                   decision="deny", reason="bad_token", user_id="u1"),  # invalid
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
        non_health_ids = [e["id"] for e in result["events"] if not e["is_health_check"]]
        self.assertEqual(non_health_ids, ["3000-0", "2000-0", "1000-0"])

        by_id = {e["id"]: e["integrity_status"] for e in result["events"]}
        self.assertEqual(by_id["1000-0"], "valid")
        self.assertEqual(by_id["2000-0"], "unsigned")
        self.assertEqual(by_id["3000-0"], "invalid")


if __name__ == "__main__":
    unittest.main()
