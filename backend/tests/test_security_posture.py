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
    return SecurityEvidence(kind, "example-repo", identifier, status, **kwargs)


def control(**kwargs):
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
    item = control(evidence=(evidence(),))
    assert item.posture is Posture.VERIFIED
    assert set(item.as_dict()) == {
        "control_id", "name", "category", "priority", "implementation_status",
        "test_status", "live_status", "certification_status", "freshness",
        "posture", "evidence", "findings", "limitations",
    }


def test_partial_without_live_or_certification_never_fabricates_pass():
    item = control(live_status=LiveStatus.UNKNOWN, certification_status=CertificationStatus.UNKNOWN)
    assert item.posture is Posture.PARTIAL


def test_unknown_when_test_is_missing():
    item = control(test_status=TestStatus.UNKNOWN, live_status=LiveStatus.UNKNOWN, certification_status=CertificationStatus.UNKNOWN)
    assert item.posture is Posture.UNKNOWN


def test_not_implemented_wins():
    item = control(implementation_status=ImplementationStatus.NOT_IMPLEMENTED)
    assert item.posture is Posture.NOT_IMPLEMENTED


def test_failed_live_is_attention_when_live_is_required():
    item = control(live_status=LiveStatus.UNAVAILABLE, live_required=True)
    assert item.posture is Posture.ATTENTION


def test_failed_live_is_not_automatically_a_failed_source_control():
    item = control(live_status=LiveStatus.UNAVAILABLE, certification_status=CertificationStatus.UNKNOWN)
    assert item.posture is Posture.PARTIAL


def test_failed_test_or_active_finding_is_attention():
    assert control(test_status=TestStatus.FAILED).posture is Posture.ATTENTION
    finding = SecurityFinding("issue-1", "Current issue", FindingType.ACTIVE_ISSUE)
    assert control(findings=(finding,)).posture is Posture.ATTENTION


def test_fixed_history_does_not_create_attention():
    finding = SecurityFinding("REG-007", "Historical routing finding", FindingType.FIXED_HISTORICAL)
    assert control(findings=(finding,)).posture is Posture.VERIFIED


def test_stale_certification_remains_certified_but_downgrades_posture():
    item = control(freshness=Freshness.STALE)
    assert item.certification_status is CertificationStatus.CERTIFIED
    assert item.posture is Posture.PARTIAL


def test_conflicting_same_type_evidence_is_unknown():
    item = control(evidence=(evidence(status="PASS"), evidence(status="FAILED", identifier="test-2")))
    assert item.posture is Posture.UNKNOWN


def test_report_summary_is_dynamic_and_ordered():
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
    report = SecurityPostureReport("1.0", "2026-08-30T12:00:00-05:00", controls=(control(),))
    encoded = json.dumps(report.as_dict(), sort_keys=True, separators=(",", ":"))
    assert encoded == json.dumps(report.as_dict(), sort_keys=True, separators=(",", ":"))
    assert report.generated_at == "2026-08-30T17:00:00Z"


def test_finding_types_and_technical_debt_are_serialized():
    finding = SecurityFinding("gap-1", "Coverage gap", FindingType.COVERAGE_GAP, severity="P1", source="review")
    debt = SecurityTechnicalDebt("debt-1", "Correlation enrichment remains incomplete", ("audit.correlation",))
    result = SecurityPostureReport("1.0", "2026-08-30T12:00:00Z", findings=(finding,), technical_debt=(debt,)).as_dict()
    assert result["findings"][0]["type"] == "COVERAGE_GAP"
    assert result["technical_debt"][0]["debt_id"] == "debt-1"


def test_seed_definitions_are_neutral_and_include_p0_p1_controls():
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
    with pytest.raises(ValueError):
        SecurityEvidence(EvidenceType.UNIT_TEST, "repo", "case", "PASS", description=value)


def test_invalid_enum_and_timestamp_are_rejected():
    with pytest.raises(ValueError):
        control(category="NOT_A_CATEGORY")
    with pytest.raises(ValueError):
        SecurityPostureReport("1.0", "not-a-timestamp")
    with pytest.raises(ValueError):
        evidence(validated_at="2026-08-30T12:00:00")


def test_no_arbitrary_evidence_metadata_is_public():
    result = evidence().as_dict()
    assert set(result) == {"type", "repository", "identifier", "status", "validated_at", "freshness", "description"}
