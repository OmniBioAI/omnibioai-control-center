"""tests/test_security_posture.py -- control_center.security_posture's
domain model: SecurityControl.posture derivation from implementation/
test/live/certification/freshness state and active findings (never
fabricating VERIFIED without real live+certification evidence, never
letting a fixed/historical finding trigger ATTENTION, treating
conflicting same-type evidence as UNKNOWN rather than picking a side),
SecurityPostureReport's deterministic serialization and dynamic summary
counts, seed_control_definitions()'s neutral (UNKNOWN-everything)
starting state, and the public-field allowlist that rejects any evidence
description containing a secret-shaped or otherwise sensitive string.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
import json

import pytest
from control_center.security_posture import (
    CertificationStatus,
    ControlCategory,
    DataSourceStatus,
    EvidenceType,
    FindingType,
    Freshness,
    ImplementationStatus,
    LiveStatus,
    Posture,
    Priority,
    SecurityControl,
    SecurityEvidence,
    SecurityFinding,
    SecurityPostureReport,
    SecurityTechnicalDebt,
    TestStatus,
    seed_control_definitions,
)


def evidence(kind=EvidenceType.UNIT_TEST, status="PASS", identifier="test-1", **kwargs):
    """A SecurityEvidence with sensible defaults, any field overridable
    by keyword."""
    return SecurityEvidence(kind, "example-repo", identifier, status, **kwargs)


def control(**kwargs):
    """A baseline, fully-passing SecurityControl (P0 auth control,
    implemented/tested/live/certified/current), with any field
    overridden by keyword."""
    defaults = {
        "control_id": "auth.example",
        "name": "Example control",
        "category": ControlCategory.AUTHENTICATION,
        "priority": Priority.P0,
        "implementation_status": ImplementationStatus.IMPLEMENTED,
        "test_status": TestStatus.PASS,
        "live_status": LiveStatus.AVAILABLE,
        "certification_status": CertificationStatus.CERTIFIED,
        "freshness": Freshness.CURRENT,
    }
    defaults.update(kwargs)
    return SecurityControl(**defaults)


def test_verified_posture_and_allowlisted_serialization():
    """A fully passing control with supporting evidence is VERIFIED,
    and as_dict() exposes exactly the documented public field set."""
    item = control(evidence=(evidence(),))
    assert item.posture is Posture.VERIFIED
    assert set(item.as_dict()) == {
        "control_id", "name", "category", "priority", "implementation_status",
        "test_status", "live_status", "certification_status", "freshness",
        "posture", "evidence", "findings", "limitations",
    }


def test_partial_without_live_or_certification_never_fabricates_pass():
    """Without a real live check or certification, the control is
    PARTIAL, never VERIFIED -- posture is never fabricated as passing."""
    item = control(live_status=LiveStatus.UNKNOWN, certification_status=CertificationStatus.UNKNOWN)
    assert item.posture is Posture.PARTIAL


def test_unknown_when_test_is_missing():
    """With no test evidence and unknown live/certification, the
    control is UNKNOWN rather than PARTIAL or VERIFIED."""
    item = control(test_status=TestStatus.UNKNOWN, live_status=LiveStatus.UNKNOWN, certification_status=CertificationStatus.UNKNOWN)
    assert item.posture is Posture.UNKNOWN


def test_not_implemented_wins():
    """implementation_status=NOT_IMPLEMENTED overrides every other
    field -- posture is NOT_IMPLEMENTED regardless."""
    item = control(implementation_status=ImplementationStatus.NOT_IMPLEMENTED)
    assert item.posture is Posture.NOT_IMPLEMENTED


def test_failed_live_is_attention_when_live_is_required():
    """A control that requires a live check (live_required=True) and
    fails it is ATTENTION."""
    item = control(live_status=LiveStatus.UNAVAILABLE, live_required=True)
    assert item.posture is Posture.ATTENTION


def test_failed_live_is_not_automatically_a_failed_source_control():
    """A control that does NOT require a live check downgrades to
    PARTIAL on a live failure, not ATTENTION -- live isn't the source of
    truth for it."""
    item = control(live_status=LiveStatus.UNAVAILABLE, certification_status=CertificationStatus.UNKNOWN)
    assert item.posture is Posture.PARTIAL


def test_failed_test_or_active_finding_is_attention():
    """A failed test_status, or an ACTIVE_ISSUE finding attached, both
    independently force ATTENTION."""
    assert control(test_status=TestStatus.FAILED).posture is Posture.ATTENTION
    finding = SecurityFinding("issue-1", "Current issue", FindingType.ACTIVE_ISSUE)
    assert control(findings=(finding,)).posture is Posture.ATTENTION


def test_fixed_history_does_not_create_attention():
    """A FIXED_HISTORICAL finding (a resolved past issue) does not
    trigger ATTENTION -- the control can still be VERIFIED."""
    finding = SecurityFinding("REG-007", "Historical routing finding", FindingType.FIXED_HISTORICAL)
    assert control(findings=(finding,)).posture is Posture.VERIFIED


def test_stale_certification_remains_certified_but_downgrades_posture():
    """A STALE freshness keeps certification_status=CERTIFIED (the fact
    itself is unchanged) but downgrades the overall posture to PARTIAL."""
    item = control(freshness=Freshness.STALE)
    assert item.certification_status is CertificationStatus.CERTIFIED
    assert item.posture is Posture.PARTIAL


def test_conflicting_same_type_evidence_is_unknown():
    """Two same-type evidence entries disagreeing (one PASS, one
    FAILED) make the posture UNKNOWN rather than picking either side."""
    item = control(evidence=(evidence(status="PASS"), evidence(status="FAILED", identifier="test-2")))
    assert item.posture is Posture.UNKNOWN


def test_report_summary_is_dynamic_and_ordered():
    """The report's controls are sorted by control_id, and the summary
    counts are computed dynamically from the actual controls, not stored
    separately."""
    controls = (
        control(control_id="z.control"),
        control(control_id="a.control", implementation_status=ImplementationStatus.NOT_IMPLEMENTED),
        control(control_id="m.control", test_status=TestStatus.FAILED),
    )
    report = SecurityPostureReport(
        "1.0", "2026-08-30T12:00:00Z", controls=controls,
        data_sources=(("policy", DataSourceStatus.AVAILABLE), ("auth", DataSourceStatus.PARTIAL)),
    )
    assert [item["control_id"] for item in report.as_dict()["controls"]] == ["a.control", "m.control", "z.control"]
    assert report.summary.as_dict() == {"verified": 1, "partial": 0, "attention": 1, "unknown": 0, "not_implemented": 1}
    assert report.as_dict()["data_sources"] == {"auth": "PARTIAL", "policy": "AVAILABLE"}


def test_serialization_is_deterministic():
    """as_dict() serializes identically across repeated calls, and a
    timestamp with an explicit offset normalizes to UTC in generated_at."""
    report = SecurityPostureReport("1.0", "2026-08-30T12:00:00-05:00", controls=(control(),))
    encoded = json.dumps(report.as_dict(), sort_keys=True, separators=(",", ":"))
    assert encoded == json.dumps(report.as_dict(), sort_keys=True, separators=(",", ":"))
    assert report.generated_at == "2026-08-30T17:00:00Z"


def test_finding_types_and_technical_debt_are_serialized():
    """A COVERAGE_GAP finding and a technical-debt entry both serialize
    with their type/debt_id fields intact."""
    finding = SecurityFinding("gap-1", "Coverage gap", FindingType.COVERAGE_GAP, severity="P1", source="review")
    debt = SecurityTechnicalDebt("debt-1", "Correlation enrichment remains incomplete", ("audit.correlation",))
    result = SecurityPostureReport("1.0", "2026-08-30T12:00:00Z", findings=(finding,), technical_debt=(debt,)).as_dict()
    assert result["findings"][0]["type"] == "COVERAGE_GAP"
    assert result["technical_debt"][0]["debt_id"] == "debt-1"


def test_seed_definitions_are_neutral_and_include_p0_p1_controls():
    """seed_control_definitions() includes the expected known control
    ids, and every seeded control starts fully UNKNOWN (implementation
    and posture) -- no fact is assumed before it's actually verified."""
    definitions = seed_control_definitions()
    ids = {item.control_id for item in definitions}
    assert "auth.jwt_validation" in ids
    assert "secrets.scanning" in ids
    assert all(item.implementation_status is ImplementationStatus.UNKNOWN for item in definitions)
    assert all(item.posture is Posture.UNKNOWN for item in definitions)


@pytest.mark.parametrize("value", [
    "password=hunter2", "secret-value", "Bearer token-value", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIx.signature",
    "Authorization: Bearer x", "API key abc", "cookie=value", "-----BEGIN PRIVATE KEY-----",
    "/home/operator/private", "container id 123", "backend handle 42", "username alice",
    "tenant-private-id",
])
def test_sensitive_public_strings_are_rejected(value):
    """A wide range of secret-shaped or otherwise sensitive-looking
    strings (credentials, tokens, private paths, identifiers) in an
    evidence description all raise ValueError rather than being accepted."""
    with pytest.raises(ValueError):
        SecurityEvidence(EvidenceType.UNIT_TEST, "repo", "case", "PASS", description=value)


def test_invalid_enum_and_timestamp_are_rejected():
    """An invalid category enum value, a malformed report timestamp,
    and a malformed evidence validated_at all raise ValueError."""
    with pytest.raises(ValueError):
        control(category="NOT_A_CATEGORY")
    with pytest.raises(ValueError):
        SecurityPostureReport("1.0", "not-a-timestamp")
    with pytest.raises(ValueError):
        evidence(validated_at="2026-08-30T12:00:00")


def test_no_arbitrary_evidence_metadata_is_public():
    """SecurityEvidence.as_dict() exposes exactly the documented field
    set -- no arbitrary extra metadata field leaks through."""
    result = evidence().as_dict()
    assert set(result) == {"type", "repository", "identifier", "status", "validated_at", "freshness", "description"}
