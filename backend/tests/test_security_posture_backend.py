"""tests/test_security_posture_backend.py -- control_center.
security_posture_backend: assemble_security_posture()'s mapping from the
regression-health artifact and live runtime-check results onto the fixed
SecurityControl set (explicit id mapping, never inventing an unmapped
finding/debt id, never letting a STALE artifact's certification get
"strengthened" back to fully verified, never fabricating VERIFIED from an
UNAVAILABLE runtime source), collect_runtime_evidence()'s reduction of a
raw check-result list to per-source DataSourceStatus + a
availability-only public dict (dropping any private message/target
field), and the GET /security-posture route's auth (401/403), safe-503
fallback on any internal failure, and its response never containing a
credential-, path-, or topology-shaped string.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
import json

import pytest
from control_center.api import routes_security_posture
from control_center.security_posture import (
    CertificationStatus,
    ControlCategory,
    DataSourceStatus,
    FindingType,
    Freshness,
    LiveStatus,
    Posture,
    Priority,
    SecurityControl,
    SecurityPostureReport,
)
from control_center.security_posture_backend import (
    assemble_security_posture,
    collect_runtime_evidence,
)
from fastapi import HTTPException


def artifact():
    """A well-formed regression-health artifact dict with two
    capabilities, one fixed finding, and one technical-debt entry."""
    return {
        "generated_at": "2026-08-30T01:16:35.820590Z",
        "freshness": {"status": "CURRENT"},
        "capabilities": [
            {"id": "tenant-isolation", "implementation_status": "implemented", "test_status": "pass", "live_status": "pass", "certification_status": "certified", "last_validated_at": "2026-08-26"},
            {"id": "audit-correlation", "implementation_status": "implemented", "test_status": "pass", "live_status": "partial", "certification_status": "partial", "last_validated_at": None},
        ],
        "findings": [{"id": "REG-007", "status": "fixed", "last_validated_at": "2026-08-26"}],
        "technical_debt": [{"id": "audit-correlation-enrichment"}],
    }


def test_regression_mapping_is_explicit_and_historical_findings_are_safe():
    """Regression-artifact capability ids map explicitly onto their
    matching security control (isolation.organization <- tenant-
    isolation, audit.correlation <- audit-correlation), a partial live
    check keeps posture PARTIAL with a limitation noted, and a fixed
    finding is classified FIXED_HISTORICAL, not counted toward verified."""
    report = assemble_security_posture(regression=artifact(), generated_at="2026-08-30T12:00:00Z")
    isolation = next(c for c in report.controls if c.control_id == "isolation.organization")
    correlation = next(c for c in report.controls if c.control_id == "audit.correlation")
    assert isolation.posture is Posture.PARTIAL
    assert isolation.certification_status is CertificationStatus.CERTIFIED
    assert any("exercised" in item.lower() for item in isolation.limitations)
    assert correlation.posture is Posture.PARTIAL
    assert report.findings[0].type is FindingType.FIXED_HISTORICAL
    assert report.summary.verified == 0


def test_complete_evidence_without_material_coverage_limitation_remains_verified():
    """A control with complete evidence across every dimension
    (implemented/tested/live/certified/current) is VERIFIED -- the
    limitation logic never downgrades a genuinely complete control."""
    control = SecurityControl(
        "test.complete", "Complete evidence", ControlCategory.AUTHENTICATION, Priority.P1,
        implementation_status="IMPLEMENTED", test_status="PASS", live_status="AVAILABLE",
        certification_status="CERTIFIED", freshness="CURRENT",
    )
    assert control.posture is Posture.VERIFIED


def test_stale_regression_certification_is_not_strengthened():
    """A STALE regression artifact keeps certification_status=CERTIFIED
    (the underlying fact) but downgrades posture to PARTIAL -- staleness
    is never silently upgraded back to a fresh-looking VERIFIED."""
    data = artifact()
    data["freshness"] = {"status": "STALE"}
    report = assemble_security_posture(regression=data, generated_at="2026-08-30T12:00:00Z")
    isolation = next(c for c in report.controls if c.control_id == "isolation.organization")
    assert isolation.certification_status is CertificationStatus.CERTIFIED
    assert isolation.freshness is Freshness.STALE
    assert isolation.posture is Posture.PARTIAL


def test_runtime_adapter_normalizes_only_availability():
    """collect_runtime_evidence() reduces each raw check result to an
    AVAILABLE/UNAVAILABLE DataSourceStatus and an {"available": bool}
    public dict -- the private "message"/"target" fields never survive
    into the returned results."""
    settings = object()
    statuses, results = collect_runtime_evidence(settings, check=lambda _: [
        {"name": "auth-service", "status": "UP", "target": "private", "message": "private"},
        {"name": "api-gateway", "status": "DOWN", "target": "private", "message": "private"},
    ])
    assert statuses["auth"] is DataSourceStatus.AVAILABLE
    assert statuses["gateway"] is DataSourceStatus.UNAVAILABLE
    assert results == {"auth": {"available": True}, "gateway": {"available": False}}
    assert "private" not in str(results)


def test_runtime_adapter_handles_missing_and_failed_sources():
    """An empty check result yields UNKNOWN status with no results, and
    a raised exception from the check yields UNAVAILABLE for every
    source with no results -- neither case raises into the caller."""
    statuses, results = collect_runtime_evidence(object(), check=lambda _: [])
    assert statuses["auth"] is DataSourceStatus.UNKNOWN
    assert results == {}
    statuses, results = collect_runtime_evidence(object(), check=lambda _: (_ for _ in ()).throw(RuntimeError("source error")))
    assert set(statuses.values()) == {DataSourceStatus.UNAVAILABLE}
    assert results == {}


def test_runtime_available_sources_update_their_controls():
    """Every runtime source reported AVAILABLE updates its mapped
    control's live_status to AVAILABLE."""
    runtime = {source: DataSourceStatus.AVAILABLE for source in ("auth", "gateway", "policy", "hpc_policy", "security_audit")}
    report = assemble_security_posture(runtime_statuses=runtime, generated_at="2026-08-30T12:00:00Z")
    assert all(control.live_status is LiveStatus.AVAILABLE for control in report.controls if control.control_id in {
        "auth.jwt_validation", "gateway.auth_enforcement", "policy.fail_closed",
        "hpc_policy.resource_governance", "audit.delivery",
    })


def test_unknown_freshness_and_unmapped_artifact_items_are_safe():
    """An empty freshness dict maps to Freshness.UNKNOWN, and an
    artifact finding/debt entry with an id that has no explicit mapping
    is dropped rather than surfacing as a phantom finding."""
    data = artifact()
    data["freshness"] = {}
    data["findings"].append({"id": "unmapped", "status": "unknown"})
    data["technical_debt"].append({"summary": "ignored without stable id"})
    report = assemble_security_posture(regression=data, generated_at="2026-08-30T12:00:00Z")
    isolation = next(c for c in report.controls if c.control_id == "isolation.organization")
    assert isolation.freshness is Freshness.UNKNOWN
    assert all(item.finding_id != "unmapped" for item in report.findings)


def test_runtime_unavailable_does_not_fabricate_verified():
    """A runtime source reported UNAVAILABLE sets its control's
    live_status to UNAVAILABLE, and the posture is never VERIFIED
    without a real successful live check."""
    report = assemble_security_posture(
        runtime_statuses={"auth": DataSourceStatus.UNAVAILABLE},
        generated_at="2026-08-30T12:00:00Z",
    )
    auth = next(c for c in report.controls if c.control_id == "auth.jwt_validation")
    assert auth.live_status is LiveStatus.UNAVAILABLE
    assert auth.posture is not Posture.VERIFIED


def test_optional_sources_and_known_limitations_are_present():
    """With no regression/runtime data supplied at all, optional data
    sources still report their documented default availability, and a
    control with a known, real limitation (auth.revocation) still
    surfaces it."""
    report = assemble_security_posture(generated_at="2026-08-30T12:00:00Z")
    data = report.as_dict()
    assert data["data_sources"]["regression_health"] == "UNAVAILABLE"
    assert data["data_sources"]["docker_proxy"] == "PARTIAL"
    revocation = next(c for c in report.controls if c.control_id == "auth.revocation")
    assert revocation.limitations


def test_endpoint_authorized_200_and_registered_read_only(monkeypatch):
    """The endpoint returns 200 with an all-zero summary for an empty
    report, and the /security-posture route only registers GET."""
    report = SecurityPostureReport("1.0", "2026-08-30T12:00:00Z")
    monkeypatch.setattr(routes_security_posture, "load_security_posture_report", lambda: report)
    response = routes_security_posture.security_posture({"sub": "admin"})
    assert response.status_code == 200
    assert json.loads(response.body)["summary"] == {"verified": 0, "partial": 0, "attention": 0, "unknown": 0, "not_implemented": 0}
    route = next(item for item in routes_security_posture.router.routes if item.path == "/security-posture")
    assert route.methods == {"GET"}


@pytest.mark.parametrize("status,detail", [(401, "unauthenticated"), (403, "forbidden")])
def test_endpoint_authentication_and_permission_semantics(monkeypatch, status, detail):
    """The route's manage_all_orgs dependency rejects a missing token
    with 401 and a validly-authenticated but under-permissioned token
    with 403."""
    def denied():
        raise HTTPException(status_code=status, detail=detail)

    with pytest.raises(HTTPException) as raised:
        denied()
    assert raised.value.status_code == status

    if status == 403:
        monkeypatch.setattr("control_center.core.auth.verify_token", lambda _: {"permissions": []})
        with pytest.raises(HTTPException) as raised:
            routes_security_posture._require_manage_all_orgs("Bearer safe-test-value")
        assert raised.value.status_code == 403
    else:
        with pytest.raises(HTTPException) as raised:
            routes_security_posture._require_manage_all_orgs(None)
        assert raised.value.status_code == 401


def test_endpoint_safe_503(monkeypatch):
    """An internal exception while loading the report returns a fixed
    503 body with no leaked exception text -- "private upstream path"
    never appears in the response."""
    def unavailable():
        raise RuntimeError("private upstream path")

    monkeypatch.setattr(routes_security_posture, "load_security_posture_report", unavailable)
    response = routes_security_posture.security_posture({"sub": "admin"})
    assert response.status_code == 503
    assert json.loads(response.body) == {"status": "STATUS_UNAVAILABLE", "message": "Security posture data is unavailable."}
    assert "private" not in response.body.decode()


def test_route_response_has_no_sensitive_or_topology_fields(monkeypatch):
    """A full, real report's serialized response never contains a
    credential-, secret-, cookie-, path-, or internal-topology-shaped
    string, across a broad set of forbidden patterns."""
    report = assemble_security_posture(generated_at="2026-08-30T12:00:00Z")
    monkeypatch.setattr(routes_security_posture, "load_security_posture_report", lambda: report)
    payload = routes_security_posture.security_posture({"sub": "admin"}).body.decode().lower()
    for forbidden in ("password=", "secret=", "bearer ", "cookie=", "/home/", "username:", "container id:", "backend handle:"):
        assert forbidden not in payload
