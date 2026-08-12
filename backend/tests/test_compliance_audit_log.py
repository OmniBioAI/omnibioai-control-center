"""Unit tests for control_center.compliance.audit_log -- the "record that
a platform_admin generated/downloaded a HIPAA compliance report" writer.
Mocks the module's own `_redis` client directly (same style
test_analytics_cache.py uses for analytics/cache.py's `_redis`), not a
FakeRedis, since the only thing exercised here is "was xadd called with
the right stream/payload", not real Streams semantics.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

from control_center.compliance import audit_log


def test_log_report_access_writes_to_the_audit_events_stream() -> None:
    fake_redis = MagicMock()
    with patch.object(audit_log, "_redis", fake_redis):
        audit_log.log_report_access(
            actor="admin@omnibioai.org", organization_id=7,
            from_date=date(2026, 8, 1), to_date=date(2026, 8, 31), report_format="pdf",
        )
    fake_redis.xadd.assert_called_once()
    args, kwargs = fake_redis.xadd.call_args
    assert args[0] == "audit:events"
    assert kwargs["maxlen"] == audit_log.MAX_STREAM_LENGTH
    assert kwargs["approximate"] is True


def test_log_report_access_payload_matches_auditevent_shape() -> None:
    """Field-for-field match with omnibioai-security-audit's own
    AuditEvent pydantic model (audit/models.py) -- so if that service's
    consumer ever processes this stream, this event persists as a normal
    AuditEventRecord row through existing infrastructure, no changes
    needed on that side."""
    fake_redis = MagicMock()
    with patch.object(audit_log, "_redis", fake_redis):
        audit_log.log_report_access(
            actor="admin@omnibioai.org", organization_id=7,
            from_date=date(2026, 8, 1), to_date=date(2026, 8, 31), report_format="csv",
        )
    args, _ = fake_redis.xadd.call_args
    payload = json.loads(args[1]["data"])

    for field in ("event_id", "timestamp", "service", "event_type", "user_id", "action", "resource", "decision", "reason", "trace_id", "context"):
        assert field in payload

    assert payload["service"] == "control-center"
    assert payload["event_type"] == "compliance_report_accessed"
    assert payload["user_id"] == "admin@omnibioai.org"
    assert payload["decision"] == "success"
    assert payload["resource"] == "organization:7"
    assert payload["context"] == {
        "organization_id": 7, "from_date": "2026-08-01", "to_date": "2026-08-31", "format": "csv",
    }


def test_log_report_access_generates_a_distinct_event_id_per_call() -> None:
    fake_redis = MagicMock()
    with patch.object(audit_log, "_redis", fake_redis):
        audit_log.log_report_access(actor="a@x.org", organization_id=1, from_date=date(2026, 8, 1), to_date=date(2026, 8, 1), report_format="json")
        audit_log.log_report_access(actor="a@x.org", organization_id=1, from_date=date(2026, 8, 1), to_date=date(2026, 8, 1), report_format="json")
    first_payload = json.loads(fake_redis.xadd.call_args_list[0][0][1]["data"])
    second_payload = json.loads(fake_redis.xadd.call_args_list[1][0][1]["data"])
    assert first_payload["event_id"] != second_payload["event_id"]


def test_log_report_access_never_raises_on_redis_failure() -> None:
    """Best-effort, fire-and-forget -- an audit-logging failure must
    never break the report response that already succeeded, matching
    every other audit-write call site's own documented convention
    (AuditLogger.log(), audit_service.log_event)."""
    fake_redis = MagicMock()
    fake_redis.xadd.side_effect = ConnectionError("redis unreachable")
    with patch.object(audit_log, "_redis", fake_redis):
        audit_log.log_report_access(
            actor="admin@omnibioai.org", organization_id=1,
            from_date=date(2026, 8, 1), to_date=date(2026, 8, 31), report_format="json",
        )  # must not raise
