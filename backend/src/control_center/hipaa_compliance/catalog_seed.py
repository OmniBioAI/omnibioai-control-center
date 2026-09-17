from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from control_center.hipaa_compliance.models import (
    HipaaComplianceChange,
    HipaaControl,
    HipaaControlEvidence,
    HipaaControlRisk,
    HipaaLegacyChangeMapping,
    HipaaReadinessHistory,
)
from control_center.hipaa_compliance.readiness_schemas import EvidenceCreate

CATALOG_ACTOR = "catalog-seed"
CATALOG_SOURCE = "control-center-phase-c-catalog-seed"


@dataclass(frozen=True)
class CatalogEvidence:
    evidence_type: str
    reference: str
    repository: str | None = None
    commit_ref: str | None = None
    environment: str | None = None
    verification_result: str = "unknown"
    notes: str | None = None


@dataclass(frozen=True)
class CatalogRisk:
    state: str
    severity: str
    description: str
    impact: str | None = None
    mitigation: str | None = None
    owner: str | None = None
    evidence: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class CatalogControl:
    control_key: str
    title: str
    description: str
    domain: str
    regulatory_reference: tuple[dict[str, str], ...]
    applicability_status: str
    applicability_rationale: str
    owner: str | None
    implementation_status: str
    testing_status: str
    deployment_status: str
    operational_verification_status: str
    evidence: tuple[CatalogEvidence, ...]
    risks: tuple[CatalogRisk, ...] = ()


def _hipaa_ref(citation: str, label: str) -> dict[str, str]:
    return {"framework": "HIPAA Security Rule", "citation": citation, "label": label}


INITIAL_CATALOG: tuple[CatalogControl, ...] = (
    CatalogControl(
        control_key="AUD-SECURITY-AUDIT-PRODUCER-SIGNING",
        title="Security-audit native audit event producer signs payloads",
        description="Security-audit's native audit:events producer signs wire payloads before publish.",
        domain="audit_integrity",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.312(b)", "Audit controls"),
            _hipaa_ref("45 CFR 164.312(c)(1)", "Integrity"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to audit integrity for security-relevant platform events.",
        owner=None,
        implementation_status="implemented",
        testing_status="tested",
        deployment_status="unknown",
        operational_verification_status="unknown",
        evidence=(
            CatalogEvidence("github_pr", "https://github.com/OmniBioAI/omnibioai-security-audit/pull/8", "omnibioai-security-audit", notes="Legacy row SECURITY-AUDIT-PR8."),
            CatalogEvidence("git_commit", "https://github.com/OmniBioAI/omnibioai-security-audit/commit/ab2790f8f4045c21a40f1a2a757b234a90555f56", "omnibioai-security-audit", "ab2790f8f4045c21a40f1a2a757b234a90555f56"),
            CatalogEvidence("ci_run", "https://github.com/OmniBioAI/omnibioai-security-audit/actions/runs/31834489454", "omnibioai-security-audit", verification_result="pass"),
            CatalogEvidence("test_suite", "tests/test_logger.py plus tests/test_logger_signing.py: 249 passed", "omnibioai-security-audit", verification_result="pass"),
        ),
    ),
    CatalogControl(
        control_key="AUD-SECURITY-AUDIT-INTEGRITY-STATUS-API",
        title="Security-audit exposes integrity status in audit event API",
        description="GET /audit/events exposes and filters persisted integrity_status for audit events.",
        domain="audit_logging",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.312(b)", "Audit controls"),
            _hipaa_ref("45 CFR 164.312(c)(1)", "Integrity"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to administrative review of audit event integrity classifications.",
        owner=None,
        implementation_status="implemented",
        testing_status="tested",
        deployment_status="unknown",
        operational_verification_status="unknown",
        evidence=(
            CatalogEvidence("github_pr", "https://github.com/OmniBioAI/omnibioai-security-audit/pull/9", "omnibioai-security-audit", notes="Legacy row SECURITY-AUDIT-PR9."),
            CatalogEvidence("git_commit", "https://github.com/OmniBioAI/omnibioai-security-audit/commit/71a2593d80ba9d535362d3a5b689442deee013c5", "omnibioai-security-audit", "71a2593d80ba9d535362d3a5b689442deee013c5"),
            CatalogEvidence("ci_run", "https://github.com/OmniBioAI/omnibioai-security-audit/actions/runs/31860393227", "omnibioai-security-audit", verification_result="pass"),
            CatalogEvidence("test_suite", "audit query/route integrity_status tests: 252 passed", "omnibioai-security-audit", verification_result="pass"),
        ),
    ),
    CatalogControl(
        control_key="AUD-CC-AUDIT-TRAIL-INTEGRITY-VERIFY",
        title="Control Center audit trail verifies audit event signatures",
        description="Human-facing audit trail verifies audit:events HMAC signatures and classifies valid/invalid/unsigned events.",
        domain="audit_integrity",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.312(b)", "Audit controls"),
            _hipaa_ref("45 CFR 164.312(c)(1)", "Integrity"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to administrator inspection of audit integrity in Control Center.",
        owner=None,
        implementation_status="implemented",
        testing_status="tested",
        deployment_status="deployed",
        operational_verification_status="verified",
        evidence=(
            CatalogEvidence("github_pr", "https://github.com/OmniBioAI/omnibioai-control-center/pull/45", "omnibioai-control-center", notes="Legacy row CC-PR45."),
            CatalogEvidence("git_commit", "https://github.com/OmniBioAI/omnibioai-control-center/commit/80ea65081408cd1166d6a13738efe893405ded93", "omnibioai-control-center", "80ea65081408cd1166d6a13738efe893405ded93"),
            CatalogEvidence("ci_run", "https://github.com/OmniBioAI/omnibioai-control-center/actions/runs/31859704385", "omnibioai-control-center", verification_result="pass"),
            CatalogEvidence("test_suite", "backend/tests/test_check_audit_trail.py: 25/25 passed; full backend suite 1323/1323 passed", "omnibioai-control-center", verification_result="pass"),
            CatalogEvidence("operational_verification", "Read-only live stack cross-check: 25/25 recent Redis audit:events matched security-audit persisted classification", "omnibioai-control-center", environment="running stack", verification_result="pass"),
        ),
    ),
    CatalogControl(
        control_key="AUD-CC-GATEWAY-TRAFFIC-INTEGRITY-VERIFY",
        title="Control Center gateway traffic aggregates verify audit event signatures",
        description="Gateway traffic checks verify audit event signatures before contributing events to numeric aggregates.",
        domain="audit_integrity",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.312(b)", "Audit controls"),
            _hipaa_ref("45 CFR 164.312(c)(1)", "Integrity"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to audit-derived operational metrics surfaced by Control Center.",
        owner=None,
        implementation_status="implemented",
        testing_status="tested",
        deployment_status="unknown",
        operational_verification_status="unknown",
        evidence=(
            CatalogEvidence("github_pr", "https://github.com/OmniBioAI/omnibioai-control-center/pull/46", "omnibioai-control-center", notes="Legacy row CC-PR46."),
            CatalogEvidence("git_commit", "https://github.com/OmniBioAI/omnibioai-control-center/commit/3b86b64f4e9ea2d65cb9e6680534e4954f189b75", "omnibioai-control-center", "3b86b64f4e9ea2d65cb9e6680534e4954f189b75"),
            CatalogEvidence("ci_run", "https://github.com/OmniBioAI/omnibioai-control-center/actions/runs/31861565476", "omnibioai-control-center", verification_result="pass"),
            CatalogEvidence("test_suite", "backend/tests/test_check_gateway_traffic.py: 16/16 passed", "omnibioai-control-center", verification_result="pass"),
        ),
    ),
    CatalogControl(
        control_key="AUD-CC-ANALYTICS-CONSUMER-INTEGRITY-VERIFY",
        title="Control Center analytics consumer verifies audit event signatures",
        description="Analytics consumer verifies audit event signatures before durable aggregation.",
        domain="audit_integrity",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.312(b)", "Audit controls"),
            _hipaa_ref("45 CFR 164.312(c)(1)", "Integrity"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to audit-derived analytics ingestion in Control Center.",
        owner=None,
        implementation_status="implemented",
        testing_status="tested",
        deployment_status="unknown",
        operational_verification_status="unknown",
        evidence=(
            CatalogEvidence("github_pr", "https://github.com/OmniBioAI/omnibioai-control-center/pull/46", "omnibioai-control-center", notes="Legacy row CC-PR46."),
            CatalogEvidence("git_commit", "https://github.com/OmniBioAI/omnibioai-control-center/commit/3b86b64f4e9ea2d65cb9e6680534e4954f189b75", "omnibioai-control-center", "3b86b64f4e9ea2d65cb9e6680534e4954f189b75"),
            CatalogEvidence("ci_run", "https://github.com/OmniBioAI/omnibioai-control-center/actions/runs/31861565476", "omnibioai-control-center", verification_result="pass"),
            CatalogEvidence("test_suite", "backend/tests/test_analytics_consumer.py: 36/36 passed", "omnibioai-control-center", verification_result="pass"),
        ),
    ),
    CatalogControl(
        control_key="EVID-READINESS-HISTORY-APPEND-ONLY",
        title="Readiness changes record append-only application history",
        description="Readiness control/evidence/risk/exception mutations create application-enforced append-only history rows.",
        domain="audit_integrity",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.312(b)", "Audit controls"),
            _hipaa_ref("45 CFR 164.312(c)(1)", "Integrity"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to provenance for HIPAA readiness records managed by Control Center.",
        owner=None,
        implementation_status="implemented",
        testing_status="tested",
        deployment_status="unknown",
        operational_verification_status="unknown",
        evidence=(
            CatalogEvidence("documentation", "backend/src/control_center/hipaa_compliance/models.py::HipaaReadinessHistory", "omnibioai-control-center", notes="Source model has before_update/before_delete mutation rejection."),
            CatalogEvidence("test_suite", "backend/tests/test_hipaa_readiness.py::test_append_only_history_and_actor_attribution", "omnibioai-control-center", verification_result="pass"),
        ),
    ),
    CatalogControl(
        control_key="IAM-HIPAA-READINESS-MANAGE-ALL-ORGS",
        title="HIPAA readiness administration requires global admin permission",
        description="Readiness and legacy HIPAA tracker APIs require manage_all_orgs for reads and writes.",
        domain="authorization_tenant_isolation",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.312(a)(1)", "Access control"),
            _hipaa_ref("45 CFR 164.308(a)(4)", "Information access management"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to platform-wide readiness evidence that is not organization-editable.",
        owner=None,
        implementation_status="implemented",
        testing_status="tested",
        deployment_status="unknown",
        operational_verification_status="unknown",
        evidence=(
            CatalogEvidence("documentation", "backend/src/control_center/api/routes_hipaa_readiness.py::_require_platform_admin", "omnibioai-control-center"),
            CatalogEvidence("test_suite", "backend/tests/test_hipaa_readiness.py::AuthorizationTests", "omnibioai-control-center", verification_result="pass"),
            CatalogEvidence("test_suite", "backend/tests/test_routes_hipaa_compliance.py::AuthorizationTests", "omnibioai-control-center", verification_result="pass"),
        ),
    ),
    CatalogControl(
        control_key="REPORT-SOURCES-UNAVAILABLE-NOT-ZERO",
        title="Compliance report distinguishes unavailable sources from zero activity",
        description="Organization-scoped report surfaces sources_unavailable instead of treating failed integrations as zero activity.",
        domain="incident_operational_controls",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.312(b)", "Audit controls"),
            _hipaa_ref("45 CFR 164.308(a)(1)(ii)(D)", "Information system activity review"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to report accuracy and safe failure behavior for audit/activity reporting.",
        owner=None,
        implementation_status="implemented",
        testing_status="tested",
        deployment_status="unknown",
        operational_verification_status="unknown",
        evidence=(
            CatalogEvidence("documentation", "backend/src/control_center/compliance/service.py::build_report", "omnibioai-control-center"),
            CatalogEvidence("test_suite", "backend/tests/test_compliance_service.py::test_partial_downstream_failure_does_not_silently_report_zero_everything", "omnibioai-control-center", verification_result="pass"),
            CatalogEvidence("test_suite", "backend/tests/test_compliance_csv_export.py::test_sources_unavailable_warning_appears_when_present", "omnibioai-control-center", verification_result="pass"),
        ),
    ),
    CatalogControl(
        control_key="PHI-REPORT-RAG-TRACE-ONLY",
        title="Compliance report omits raw RAG query text",
        description="RAG report rows expose timestamps, user labels, and trace IDs, not raw query text or clinical content.",
        domain="phi_handling",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.312(a)(1)", "Access control"),
            _hipaa_ref("45 CFR 164.312(e)(1)", "Transmission security"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to minimizing PHI exposure in generated administrative reports.",
        owner=None,
        implementation_status="implemented",
        testing_status="tested",
        deployment_status="unknown",
        operational_verification_status="unknown",
        evidence=(
            CatalogEvidence("documentation", "backend/src/control_center/compliance/service.py::_build_rag_queries", "omnibioai-control-center"),
            CatalogEvidence("test_suite", "backend/tests/test_compliance_service.py::test_rag_queries_resolve_user_id_to_member_email", "omnibioai-control-center", verification_result="pass"),
            CatalogEvidence("test_suite", "backend/tests/test_compliance_csv_export.py::test_missing_trace_id_renders_as_empty_string", "omnibioai-control-center", verification_result="pass"),
        ),
    ),
    CatalogControl(
        control_key="REPORT-CSV-FORMULA-INJECTION-SAFE",
        title="Compliance report CSV export neutralizes spreadsheet formulas",
        description="CSV export prefixes formula-leading cells to prevent spreadsheet formula execution.",
        domain="logging_redaction",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.312(c)(1)", "Integrity"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to safe handling of exported administrative evidence reports.",
        owner=None,
        implementation_status="implemented",
        testing_status="tested",
        deployment_status="unknown",
        operational_verification_status="unknown",
        evidence=(
            CatalogEvidence("documentation", "backend/src/control_center/compliance/csv_export.py::_sanitize_cell", "omnibioai-control-center"),
            CatalogEvidence("test_suite", "backend/tests/test_compliance_csv_export.py::test_malicious_organization_name_is_neutralized_in_csv_output", "omnibioai-control-center", verification_result="pass"),
            CatalogEvidence("test_suite", "backend/tests/test_compliance_csv_export.py::test_malicious_user_label_is_neutralized_in_csv_output", "omnibioai-control-center", verification_result="pass"),
        ),
    ),
    CatalogControl(
        control_key="AUD-RETENTION-CLEANUP-GUARDED",
        title="Audit retention cleanup is guarded but retention duration remains unset/unknown",
        description="Retention cleanup requires explicit retention days and maintenance credentials; authoritative retention/freshness remain unknown without deployment configuration evidence.",
        domain="backup_recovery",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.308(a)(7)", "Contingency plan"),
            _hipaa_ref("45 CFR 164.312(b)", "Audit controls"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to preservation and governed cleanup of durable audit records.",
        owner=None,
        implementation_status="partial",
        testing_status="partial",
        deployment_status="unknown",
        operational_verification_status="unknown",
        evidence=(
            CatalogEvidence("documentation", "/home/manish/Desktop/machine/omnibioai-security-audit/scripts/audit_retention_cleanup.py", "omnibioai-security-audit", notes="Source shows fail-closed cleanup gates and legal-hold checks."),
            CatalogEvidence("documentation", "/home/manish/Desktop/machine/omnibioai-security-audit/docs/AUDIT_SOURCE_SEMANTICS_SAT4.md", "omnibioai-security-audit", notes="Doc explicitly states durable retention and freshness are UNKNOWN."),
        ),
        risks=(
            CatalogRisk(
                state="open",
                severity="medium",
                description="Durable audit retention duration and freshness are not established by current evidence.",
                impact="Readiness reporting cannot claim configured audit retention duration, current freshness, legal hold completeness, or external WORM preservation.",
                mitigation="Define retention governance, deployment evidence, and external immutable storage strategy before upgrading this control.",
                evidence=(
                    {"type": "documentation", "reference": "/home/manish/Desktop/machine/omnibioai-security-audit/docs/AUDIT_SOURCE_SEMANTICS_SAT4.md"},
                ),
            ),
        ),
    ),
    CatalogControl(
        control_key="REDIS-RAG-ROLE-SEPARATION",
        title="RAG Redis role separation has code/test evidence but production closure remains unknown",
        description="RAG Redis clients select role-specific Redis URLs with fallback behavior tested; production ACL/credential rollout is not evidenced here.",
        domain="secrets_management",
        regulatory_reference=(
            _hipaa_ref("45 CFR 164.312(a)(1)", "Access control"),
            _hipaa_ref("45 CFR 164.308(a)(3)(ii)(B)", "Workforce clearance/access authorization"),
        ),
        applicability_status="applicable",
        applicability_rationale="Applies to least-privilege Redis access for RAG and related producers/clients.",
        owner=None,
        implementation_status="partial",
        testing_status="tested",
        deployment_status="unknown",
        operational_verification_status="unknown",
        evidence=(
            CatalogEvidence("test_suite", "/home/manish/Desktop/machine/omnibioai-rag/tests/test_redis_role_separation.py", "omnibioai-rag", verification_result="pass", notes="Tests URL-selection logic only; live Redis production closure remains out of scope."),
            CatalogEvidence("test_suite", "/home/manish/Desktop/machine/omnibioai-auth/tests/test_redis_role_separation.py", "omnibioai-auth", verification_result="pass", notes="Tests auth/interaction Redis identity selection behavior only."),
        ),
        risks=(
            CatalogRisk(
                state="open",
                severity="medium",
                description="Redis P1-5/RAG role separation production closure is not evidenced in Control Center.",
                impact="Catalog cannot treat Redis role separation as deployed or operationally verified.",
                mitigation="Complete and record production Redis ACL/credential rollout evidence in an approved non-secret artifact.",
                evidence=(
                    {"type": "test_suite", "reference": "/home/manish/Desktop/machine/omnibioai-rag/tests/test_redis_role_separation.py"},
                    {"type": "test_suite", "reference": "/home/manish/Desktop/machine/omnibioai-auth/tests/test_redis_role_separation.py"},
                ),
            ),
        ),
    ),
)

LEGACY_CONTROL_MAPPINGS: dict[str, tuple[str, str, str]] = {
    "SECURITY-AUDIT-PR8": (
        "AUD-SECURITY-AUDIT-PRODUCER-SIGNING",
        "high",
        "Legacy row is specifically about security-audit AuditLogger.log producer signing and maps atomically to this control.",
    ),
    "SECURITY-AUDIT-PR9": (
        "AUD-SECURITY-AUDIT-INTEGRITY-STATUS-API",
        "high",
        "Legacy row is specifically about exposing integrity_status in security-audit's read API and maps atomically to this control.",
    ),
    "CC-PR45": (
        "AUD-CC-AUDIT-TRAIL-INTEGRITY-VERIFY",
        "high",
        "Legacy row is specifically about Control Center audit-trail signature verification and includes live read-only verification evidence.",
    ),
    "CC-PR46": (
        "AUD-CC-GATEWAY-TRAFFIC-INTEGRITY-VERIFY",
        "medium",
        "Legacy row covers two consumers; this mapping records the gateway-traffic half without implying analytics-consumer deployment verification.",
    ),
}


def _validate_seed_evidence(evidence: CatalogEvidence) -> None:
    EvidenceCreate(
        evidence_type=evidence.evidence_type,
        reference=evidence.reference,
        repository=evidence.repository,
        commit_ref=evidence.commit_ref,
        environment=evidence.environment,
        verification_result=evidence.verification_result,
        notes=evidence.notes,
    )


def _state(control: CatalogControl) -> dict[str, Any]:
    return {
        "control_key": control.control_key,
        "title": control.title,
        "domain": control.domain,
        "regulatory_reference": list(control.regulatory_reference),
        "applicability_status": control.applicability_status,
        "implementation_status": control.implementation_status,
        "testing_status": control.testing_status,
        "deployment_status": control.deployment_status,
        "operational_verification_status": control.operational_verification_status,
    }


def _record_history_once(db: Session, *, entity_type: str, entity_id: str, change_type: str, new_state: dict[str, Any]) -> None:
    exists = db.query(HipaaReadinessHistory).filter(
        HipaaReadinessHistory.entity_type == entity_type,
        HipaaReadinessHistory.entity_id == entity_id,
        HipaaReadinessHistory.change_type == change_type,
        HipaaReadinessHistory.actor == CATALOG_ACTOR,
        HipaaReadinessHistory.source == CATALOG_SOURCE,
    ).first()
    if exists is None:
        db.add(HipaaReadinessHistory(
            entity_type=entity_type,
            entity_id=entity_id,
            change_type=change_type,
            old_state=None,
            new_state=new_state,
            actor=CATALOG_ACTOR,
            source=CATALOG_SOURCE,
            reason="Initial bounded evidence-backed catalog seed.",
        ))


def _seed_control(db: Session, control: CatalogControl) -> tuple[HipaaControl, bool]:
    row = db.query(HipaaControl).filter(HipaaControl.control_key == control.control_key).one_or_none()
    if row is not None:
        return row, False
    row = HipaaControl(
        control_key=control.control_key,
        title=control.title,
        description=control.description,
        domain=control.domain,
        regulatory_reference=list(control.regulatory_reference),
        applicability_status=control.applicability_status,
        applicability_rationale=control.applicability_rationale,
        owner=control.owner,
        implementation_status=control.implementation_status,
        testing_status=control.testing_status,
        deployment_status=control.deployment_status,
        operational_verification_status=control.operational_verification_status,
    )
    db.add(row)
    db.flush()
    _record_history_once(db, entity_type="control", entity_id=control.control_key, change_type="catalog_seeded", new_state=_state(control))
    return row, True


def _seed_evidence(db: Session, control: HipaaControl, evidence: CatalogEvidence) -> bool:
    _validate_seed_evidence(evidence)
    exists = db.query(HipaaControlEvidence).filter(
        HipaaControlEvidence.control_id == control.id,
        HipaaControlEvidence.evidence_type == evidence.evidence_type,
        HipaaControlEvidence.reference == evidence.reference,
    ).first()
    if exists is not None:
        return False
    row = HipaaControlEvidence(
        control_id=control.id,
        evidence_type=evidence.evidence_type,
        reference=evidence.reference,
        repository=evidence.repository,
        commit_ref=evidence.commit_ref,
        environment=evidence.environment,
        verification_result=evidence.verification_result,
        notes=evidence.notes,
        recorded_by=CATALOG_ACTOR,
    )
    db.add(row)
    db.flush()
    _record_history_once(db, entity_type="evidence", entity_id=str(row.id), change_type="catalog_evidence_seeded", new_state={
        "control_key": control.control_key,
        "evidence_type": row.evidence_type,
        "reference": row.reference,
        "verification_result": row.verification_result,
    })
    return True


def _seed_risk(db: Session, control: HipaaControl, risk: CatalogRisk) -> bool:
    exists = db.query(HipaaControlRisk).filter(
        HipaaControlRisk.control_id == control.id,
        HipaaControlRisk.description == risk.description,
    ).first()
    if exists is not None:
        return False
    row = HipaaControlRisk(
        control_id=control.id,
        state=risk.state,
        severity=risk.severity,
        description=risk.description,
        impact=risk.impact,
        mitigation=risk.mitigation,
        owner=risk.owner,
        evidence=[dict(item) for item in risk.evidence],
    )
    db.add(row)
    db.flush()
    _record_history_once(db, entity_type="risk", entity_id=str(row.id), change_type="catalog_risk_seeded", new_state={
        "control_key": control.control_key,
        "state": row.state,
        "severity": row.severity,
        "description": row.description,
    })
    return True


def _seed_legacy_mappings(db: Session, controls_by_key: dict[str, HipaaControl]) -> int:
    inserted_or_updated = 0
    for legacy_id, (control_key, confidence, rationale) in LEGACY_CONTROL_MAPPINGS.items():
        legacy = db.get(HipaaComplianceChange, legacy_id)
        control = controls_by_key.get(control_key)
        if legacy is None or control is None:
            continue
        row = db.query(HipaaLegacyChangeMapping).filter(HipaaLegacyChangeMapping.legacy_change_id == legacy_id).one_or_none()
        provenance = {
            "source": "hipaa_compliance_changes",
            "legacy_change_id": legacy_id,
            "legacy_status": legacy.status,
            "mapped_by": CATALOG_SOURCE,
        }
        full_rationale = f"confidence={confidence}; {rationale} Provenance: {provenance}"
        if row is None:
            db.add(HipaaLegacyChangeMapping(
                legacy_change_id=legacy_id,
                control_id=control.id,
                mapping_status="mapped",
                mapping_rationale=full_rationale,
            ))
            inserted_or_updated += 1
            continue
        if row.mapping_status == "unmapped" and row.control_id is None:
            row.control_id = control.id
            row.mapping_status = "mapped"
            row.mapping_rationale = full_rationale
            inserted_or_updated += 1
    return inserted_or_updated


def seed_initial_catalog(db: Session) -> dict[str, int]:
    """Seed the bounded Phase C catalog without overwriting reviewed state.

    Existing controls are left as-is, including any manually reviewed lifecycle
    state. Missing evidence/risks/mappings are inserted idempotently by stable
    natural keys (control_key + evidence type/reference, risk description, legacy
    change_id). Evidence never triggers a lifecycle status transition.
    """
    stats = {"controls": 0, "evidence": 0, "risks": 0, "legacy_mappings": 0}
    controls_by_key: dict[str, HipaaControl] = {}
    for control in INITIAL_CATALOG:
        row, inserted = _seed_control(db, control)
        controls_by_key[control.control_key] = row
        stats["controls"] += int(inserted)
        for evidence in control.evidence:
            stats["evidence"] += int(_seed_evidence(db, row, evidence))
        for risk in control.risks:
            stats["risks"] += int(_seed_risk(db, row, risk))
    stats["legacy_mappings"] = _seed_legacy_mappings(db, controls_by_key)
    if any(stats.values()):
        db.commit()
    return stats
