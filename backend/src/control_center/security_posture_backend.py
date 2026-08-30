"""Evidence adapters and report assembly for Security Posture.

All external work is injected or delegated to existing Control Center helpers.
This layer never passes raw upstream dictionaries to the response.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from control_center.core.runner import run_all_checks
from control_center.core.settings import Settings, load_settings
from control_center.regression_health import (
    RegressionHealthUnavailable,
    load_regression_health,
)
from control_center.security_posture import (
    CertificationStatus,
    DataSourceStatus,
    EvidenceType,
    FindingType,
    Freshness,
    ImplementationStatus,
    LiveStatus,
    SecurityControl,
    SecurityEvidence,
    SecurityFinding,
    SecurityPostureReport,
    SecurityTechnicalDebt,
    TestStatus,
    seed_control_definitions,
)

RUNTIME_SOURCES = {
    "auth": "auth-service",
    "gateway": "api-gateway",
    "policy": "policy-engine",
    "hpc_policy": "hpc-policy-engine",
    "security_audit": "security-audit",
}

_CAPABILITY_CONTROLS = {
    "tenant-isolation": ("isolation.organization",),
    "audit-correlation": ("audit.correlation",),
    "gateway-routing": ("gateway.context_propagation",),
}
_FINDING_CONTROLS = {
    "REG-007": ("gateway.context_propagation",),
    "REG-008": ("audit.delivery",),
    "REG-009": ("isolation.organization",),
}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _freshness(value: str | None, fallback: Freshness = Freshness.UNKNOWN) -> Freshness:
    if value is None:
        return fallback
    try:
        return Freshness(value.upper())
    except ValueError:
        return fallback


def _artifact_timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    return f"{value}T00:00:00Z" if len(value) == 10 else value


def _implementation(value: Any) -> ImplementationStatus:
    return ImplementationStatus.IMPLEMENTED if str(value).lower() == "implemented" else (
        ImplementationStatus.NOT_IMPLEMENTED if str(value).lower() == "not_implemented" else ImplementationStatus.UNKNOWN
    )


def _tests(value: Any) -> TestStatus:
    mapping = {"pass": TestStatus.PASS, "failed": TestStatus.FAILED, "partial": TestStatus.PARTIAL, "not_run": TestStatus.NOT_RUN}
    return mapping.get(str(value).lower(), TestStatus.UNKNOWN)


def _live(value: Any) -> LiveStatus:
    mapping = {"pass": LiveStatus.AVAILABLE, "failed": LiveStatus.UNAVAILABLE, "paused": LiveStatus.PARTIAL, "blocked": LiveStatus.PARTIAL, "not_run": LiveStatus.UNKNOWN}
    return mapping.get(str(value).lower(), LiveStatus.UNKNOWN)


def _certification(value: Any) -> CertificationStatus:
    mapping = {"certified": CertificationStatus.CERTIFIED, "failed": CertificationStatus.NOT_CERTIFIED, "not_certified": CertificationStatus.NOT_CERTIFIED, "partial": CertificationStatus.PARTIAL}
    return mapping.get(str(value).lower(), CertificationStatus.UNKNOWN)


def _artifact_evidence(capability: dict[str, Any], generated_at: str) -> SecurityEvidence:
    status = str(capability.get("certification_status", "unknown")).upper()
    return SecurityEvidence(
        EvidenceType.REGRESSION_CERTIFICATION,
        "omnibioai-ecosystem-regression",
        f"capability:{capability['id']}",
        status,
        validated_at=_artifact_timestamp(capability.get("last_validated_at")) or generated_at,
        freshness=Freshness.CURRENT,
        description="Promoted regression capability evidence",
    )


def _artifact_controls(data: dict[str, Any], controls: dict[str, SecurityControl]) -> tuple[dict[str, SecurityControl], list[SecurityFinding], list[SecurityTechnicalDebt]]:
    generated_at = data.get("generated_at")
    findings: list[SecurityFinding] = []
    debt: list[SecurityTechnicalDebt] = []
    for capability in data.get("capabilities", []):
        mapped_ids = _CAPABILITY_CONTROLS.get(capability.get("id"), ())
        for control_id in mapped_ids:
            current = controls[control_id]
            evidence = current.evidence + (_artifact_evidence(capability, generated_at),)
            controls[control_id] = replace(
                current,
                implementation_status=_implementation(capability.get("implementation_status")),
                test_status=_tests(capability.get("test_status")),
                live_status=_live(capability.get("live_status")),
                certification_status=_certification(capability.get("certification_status")),
                freshness=_freshness(data.get("freshness", {}).get("status")),
                evidence=evidence,
                limitations=("Tenant isolation certification applies to exercised/certified paths and does not establish platform-wide coverage.",) if control_id == "isolation.organization" else current.limitations,
            )
    for finding in data.get("findings", []):
        finding_id = finding.get("id")
        status = str(finding.get("status", "unknown")).lower()
        finding_type = FindingType.FIXED_HISTORICAL if status == "fixed" else FindingType.ACTIVE_ISSUE if status == "open" else FindingType.COVERAGE_GAP
        mapped_ids = _FINDING_CONTROLS.get(finding_id, ())
        if mapped_ids:
            findings.append(SecurityFinding(
                finding_id, "Regression finding", finding_type, mapped_ids,
                source="omnibioai-ecosystem-regression",
                validated_at=_artifact_timestamp(finding.get("last_validated_at")),
                summary="Promoted regression finding status",
            ))
    for item in data.get("technical_debt", []):
        if isinstance(item, dict) and item.get("id"):
            debt.append(SecurityTechnicalDebt(str(item["id"]), "Promoted technical-debt item"))
    return controls, findings, debt


def collect_runtime_evidence(
    settings: Settings | None = None,
    *,
    check: Callable[[Settings], list[dict[str, Any]]] = run_all_checks,
) -> tuple[dict[str, DataSourceStatus], dict[str, dict[str, Any]]]:
    """Reuse the existing service checker and retain only safe status data."""
    if settings is None:
        settings = load_settings()
    try:
        results = check(settings)
    except Exception:  # noqa: BLE001 - optional source failure degrades availability
        return ({source: DataSourceStatus.UNAVAILABLE for source in RUNTIME_SOURCES}, {})
    by_name = {str(item.get("name")): item for item in results if isinstance(item, dict)}
    statuses: dict[str, DataSourceStatus] = {}
    normalized: dict[str, dict[str, Any]] = {}
    for source_id, service_name in RUNTIME_SOURCES.items():
        result = by_name.get(service_name)
        if result is None:
            statuses[source_id] = DataSourceStatus.UNKNOWN
            continue
        available = result.get("status") == "UP"
        statuses[source_id] = DataSourceStatus.AVAILABLE if available else DataSourceStatus.UNAVAILABLE
        normalized[source_id] = {"available": available}
    return statuses, normalized


def _runtime_control(control: SecurityControl, source_id: str, status: DataSourceStatus, normalized: dict[str, dict[str, Any]]) -> SecurityControl:
    if status is DataSourceStatus.AVAILABLE:
        evidence = SecurityEvidence(EvidenceType.RUNTIME_HEALTH, "omnibioai-control-center", f"health:{source_id}", "AVAILABLE", validated_at=_now(), freshness=Freshness.CURRENT, description="Runtime health source available")
        return replace(control, live_status=LiveStatus.AVAILABLE, evidence=control.evidence + (evidence,))
    if status is DataSourceStatus.UNAVAILABLE:
        evidence = SecurityEvidence(EvidenceType.RUNTIME_HEALTH, "omnibioai-control-center", f"health:{source_id}", "UNAVAILABLE", validated_at=_now(), freshness=Freshness.CURRENT, description="Runtime health source unavailable")
        return replace(control, live_status=LiveStatus.UNAVAILABLE, evidence=control.evidence + (evidence,))
    return control


def assemble_security_posture(
    *,
    regression: dict[str, Any] | None = None,
    runtime_statuses: dict[str, DataSourceStatus] | None = None,
    runtime_results: dict[str, dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> SecurityPostureReport:
    controls = {item.control_id: item for item in seed_control_definitions()}
    source_statuses = {source: DataSourceStatus.UNKNOWN for source in ("auth", "gateway", "policy", "hpc_policy", "security_audit", "docker_proxy", "regression_health", "secret_scan")}
    findings: list[SecurityFinding] = []
    debt: list[SecurityTechnicalDebt] = []
    if regression is not None:
        source_statuses["regression_health"] = DataSourceStatus.AVAILABLE
        controls, findings, debt = _artifact_controls(regression, controls)
    else:
        source_statuses["regression_health"] = DataSourceStatus.UNAVAILABLE
    if runtime_statuses:
        source_statuses.update(runtime_statuses)
        for source_id, status in runtime_statuses.items():
            if source_id == "auth":
                controls["auth.jwt_validation"] = _runtime_control(controls["auth.jwt_validation"], source_id, status, runtime_results or {})
            elif source_id == "gateway":
                controls["gateway.auth_enforcement"] = _runtime_control(controls["gateway.auth_enforcement"], source_id, status, runtime_results or {})
            elif source_id == "policy":
                controls["policy.fail_closed"] = _runtime_control(controls["policy.fail_closed"], source_id, status, runtime_results or {})
            elif source_id == "hpc_policy":
                controls["hpc_policy.resource_governance"] = _runtime_control(controls["hpc_policy.resource_governance"], source_id, status, runtime_results or {})
            elif source_id == "security_audit":
                controls["audit.delivery"] = _runtime_control(controls["audit.delivery"], source_id, status, runtime_results or {})
    controls["docker.raw_socket_protection"] = replace(controls["docker.raw_socket_protection"], live_status=LiveStatus.PARTIAL, limitations=("Proxy deployment evidence is present but implementation evidence is incomplete",))
    controls["docker.proxy_allowlist"] = replace(controls["docker.proxy_allowlist"], live_status=LiveStatus.PARTIAL, limitations=("Proxy allowlist implementation evidence is unavailable",))
    controls["audit.correlation"] = replace(controls["audit.correlation"], certification_status=CertificationStatus.PARTIAL, live_status=LiveStatus.PARTIAL, limitations=("Correlation evidence is partial",))
    controls["auth.revocation"] = replace(controls["auth.revocation"], limitations=("Redis blacklist errors intentionally fail open; database and user-state checks remain enforced",))
    controls["secrets.scanning"] = replace(controls["secrets.scanning"], limitations=("Credential-scan evidence is not normalized across repositories",))
    source_statuses["docker_proxy"] = DataSourceStatus.PARTIAL
    source_statuses["secret_scan"] = DataSourceStatus.PARTIAL
    return SecurityPostureReport(
        "1.0", generated_at or _now(), controls=tuple(controls.values()), findings=tuple(findings),
        technical_debt=tuple(debt), data_sources=tuple(source_statuses.items()),
        limitations=("Policy counters and audit lag are not exposed by a stable source contract",),
    )


def load_security_posture_report() -> SecurityPostureReport:
    """Collect optional sources; source failures degrade the report honestly."""
    try:
        regression = load_regression_health()
    except RegressionHealthUnavailable:
        regression = None
    try:
        settings = load_settings()
        statuses, results = collect_runtime_evidence(settings)
    except Exception:  # noqa: BLE001 - optional source failure degrades availability
        statuses, results = ({source: DataSourceStatus.UNAVAILABLE for source in RUNTIME_SOURCES}, {})
    return assemble_security_posture(regression=regression, runtime_statuses=statuses, runtime_results=results)
