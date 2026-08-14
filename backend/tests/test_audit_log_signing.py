"""HIPAA PR3b: producer-side signing for
control_center.compliance.audit_log::log_report_access.

sign_audit_event/_signing_key/_signing_message there are a hand-ported
copy of omnibioai-security-audit's audit/signing.py (that repo is not a
dependency of this one -- see the module's own comment). CROSS_REPO_VECTOR
is a fixed (service, data, secret) -> signature triple generated directly
from the real consumer's sign_audit_event(); a passing
test_matches_real_consumer_signing_vector proves this port is byte-for-
byte compatible with the real verifier without this repo importing or
depending on that one.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from control_center.compliance import audit_log
from control_center.compliance.audit_log import (
    _signing_key,
    _signing_message,
    sign_audit_event,
)

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


def test_matches_real_consumer_signing_vector():
    v = CROSS_REPO_VECTOR
    assert sign_audit_event(v["service"], v["data"], v["secret"]) == v["sig"]


def test_sign_audit_event_returns_v1_prefixed_hex():
    sig = sign_audit_event("control-center", '{"a": 1}', "s3cr3t")
    version, sep, mac_hex = sig.partition(":")
    assert version == "v1"
    assert sep == ":"
    bytes.fromhex(mac_hex)


def test_sign_rejects_empty_service():
    with pytest.raises(ValueError):
        sign_audit_event("", '{"a": 1}', "s3cr3t")


def test_sign_rejects_none_data():
    with pytest.raises(ValueError):
        sign_audit_event("control-center", None, "s3cr3t")


def test_tampered_data_produces_a_different_signature():
    sig_a = sign_audit_event("control-center", '{"format": "json"}', "s3cr3t")
    sig_b = sign_audit_event("control-center", '{"format": "csv"}', "s3cr3t")
    assert sig_a != sig_b


def test_signing_is_deterministic():
    data = '{"a": 1}'
    assert sign_audit_event("control-center", data, "s3cr3t") == sign_audit_event(
        "control-center", data, "s3cr3t"
    )


def test_signature_does_not_contain_the_secret():
    sig = sign_audit_event("control-center", '{"a": 1}', "super-secret-value")
    assert "super-secret-value" not in sig


def test_signing_message_uses_newline_separator_not_concatenation():
    assert _signing_message("v1", "ab", "cd") != _signing_message("v1", "a", "bcd")


# ---------------------------------------------------------------------------
# Exact serialization + real xadd wiring (mirrors
# test_compliance_audit_log.py's own mocking style: patch _redis directly)
# ---------------------------------------------------------------------------

def test_log_report_access_signs_the_exact_data_string_it_publishes():
    fake_redis = MagicMock()
    with patch.object(audit_log, "_redis", fake_redis), patch.object(
        audit_log, "JWT_SECRET", "s3cr3t"
    ):
        audit_log.log_report_access(
            actor="admin@omnibioai.org", organization_id=7,
            from_date=date(2026, 8, 1), to_date=date(2026, 8, 31), report_format="pdf",
        )
    args, kwargs = fake_redis.xadd.call_args
    fields = args[1]
    data = fields["data"]
    sig = fields["sig"]
    assert sig == sign_audit_event("control-center", data, "s3cr3t")
    assert json.loads(data)["event_type"] == "compliance_report_accessed"


def test_log_report_access_includes_both_data_and_sig_fields():
    fake_redis = MagicMock()
    with patch.object(audit_log, "_redis", fake_redis), patch.object(
        audit_log, "JWT_SECRET", "s3cr3t"
    ):
        audit_log.log_report_access(
            actor="admin@omnibioai.org", organization_id=7,
            from_date=date(2026, 8, 1), to_date=date(2026, 8, 31), report_format="pdf",
        )
    args, _ = fake_redis.xadd.call_args
    assert "data" in args[1]
    assert args[1]["sig"].startswith("v1:")


def test_log_report_access_signing_failure_still_never_raises():
    """The whole xadd (including signing) is inside the same best-effort
    try/except this module already had -- a signing bug must degrade the
    same way a Redis outage already does (log a warning, never break the
    report response), not raise into the caller."""
    fake_redis = MagicMock()
    with patch.object(audit_log, "_redis", fake_redis), patch.object(
        audit_log, "sign_audit_event", side_effect=RuntimeError("signing exploded")
    ):
        audit_log.log_report_access(
            actor="admin@omnibioai.org", organization_id=7,
            from_date=date(2026, 8, 1), to_date=date(2026, 8, 31), report_format="pdf",
        )  # must not raise
    fake_redis.xadd.assert_not_called()


def test_log_report_access_exception_never_leaks_the_secret(capsys, caplog):
    fake_redis = MagicMock()
    fake_redis.xadd.side_effect = RuntimeError("boom")
    with patch.object(audit_log, "_redis", fake_redis), patch.object(
        audit_log, "JWT_SECRET", "super-secret-value"
    ):
        audit_log.log_report_access(
            actor="admin@omnibioai.org", organization_id=7,
            from_date=date(2026, 8, 1), to_date=date(2026, 8, 31), report_format="pdf",
        )
    captured = capsys.readouterr()
    assert "super-secret-value" not in captured.out
    assert "super-secret-value" not in captured.err
    assert "super-secret-value" not in caplog.text


def test_module_reuses_the_existing_jwt_verify_secret_not_a_new_variable():
    """core/jwt_verify.py already defines JWT_SECRET for this service's
    own token verification. Signing imports that exact name/value rather
    than introducing a second, independently-defaulted secret."""
    from control_center.core.jwt_verify import JWT_SECRET as verify_secret

    assert audit_log.JWT_SECRET is verify_secret
