from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from control_center.hipaa_compliance.models import (
    HipaaComplianceChange,
    HipaaControl,
    HipaaControlEvidence,
    HipaaControlException,
    HipaaControlRisk,
    HipaaLegacyChangeMapping,
    HipaaReadinessHistory,
)
from control_center.hipaa_compliance.readiness_schemas import (
    ApplicabilityStatus,
    ControlCreate,
    ControlOut,
    ControlUpdate,
    DeploymentStatus,
    EvidenceCreate,
    ExceptionCreate,
    ExceptionStatus,
    ImplementationStatus,
    OperationalVerificationStatus,
    OverallControlStatus,
    RiskCreate,
    RiskState,
    TestingStatus,
)


class ControlAlreadyExistsError(Exception):
    pass


class ControlNotFoundError(Exception):
    pass


def actor_from_claims(claims: dict | None) -> str | None:
    if not claims:
        return None
    return claims.get("email") or claims.get("sub")


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _control_state(row: HipaaControl) -> dict[str, Any]:
    return {
        "id": row.id,
        "control_key": row.control_key,
        "title": row.title,
        "description": row.description,
        "domain": row.domain,
        "regulatory_reference": row.regulatory_reference or [],
        "applicability_status": row.applicability_status,
        "applicability_rationale": row.applicability_rationale,
        "owner": row.owner,
        "implementation_status": row.implementation_status,
        "testing_status": row.testing_status,
        "deployment_status": row.deployment_status,
        "operational_verification_status": row.operational_verification_status,
    }


def _record_history(
    db: Session, *, entity_type: str, entity_id: str, change_type: str,
    old_state: dict[str, Any] | None, new_state: dict[str, Any], actor: str | None,
    reason: str | None = None, source: str | None = None, legacy: bool = False,
) -> None:
    db.add(HipaaReadinessHistory(
        entity_type=entity_type, entity_id=entity_id, change_type=change_type,
        old_state=old_state, new_state=new_state, actor=actor, reason=reason, source=source, legacy=legacy,
    ))


def derive_overall_status(row: HipaaControl) -> OverallControlStatus:
    if row.applicability_status == ApplicabilityStatus.NOT_APPLICABLE.value:
        return OverallControlStatus.NOT_APPLICABLE
    if row.applicability_status == ApplicabilityStatus.DEFERRED.value or row.implementation_status == ImplementationStatus.DEFERRED.value:
        return OverallControlStatus.DEFERRED
    statuses = [
        row.implementation_status, row.testing_status, row.deployment_status, row.operational_verification_status,
    ]
    if any(s in {TestingStatus.FAILED.value, OperationalVerificationStatus.FAILED.value} for s in statuses):
        return OverallControlStatus.NEEDS_WORK
    if any(s in {
        ImplementationStatus.NOT_STARTED.value, TestingStatus.NOT_TESTED.value, DeploymentStatus.NOT_DEPLOYED.value,
        OperationalVerificationStatus.NOT_VERIFIED.value,
    } for s in statuses):
        return OverallControlStatus.NEEDS_WORK
    if any(s in {ImplementationStatus.PARTIAL.value, TestingStatus.PARTIAL.value, DeploymentStatus.PARTIAL.value, OperationalVerificationStatus.PARTIAL.value} for s in statuses):
        return OverallControlStatus.PARTIAL
    if all(s in {
        ImplementationStatus.IMPLEMENTED.value, TestingStatus.TESTED.value, DeploymentStatus.DEPLOYED.value, OperationalVerificationStatus.VERIFIED.value,
    } for s in statuses):
        return OverallControlStatus.EVIDENCE_READY
    return OverallControlStatus.UNKNOWN


def _counts(db: Session, control_id: int) -> tuple[int, int, int]:
    evidence_count = db.query(HipaaControlEvidence).filter(HipaaControlEvidence.control_id == control_id).count()
    open_risk_count = db.query(HipaaControlRisk).filter(
        HipaaControlRisk.control_id == control_id,
        HipaaControlRisk.state.in_([RiskState.OPEN.value, RiskState.PARTIAL.value, RiskState.DEFERRED.value]),
    ).count()
    active_exception_count = db.query(HipaaControlException).filter(
        HipaaControlException.control_id == control_id,
        HipaaControlException.status.in_([ExceptionStatus.OPEN.value, ExceptionStatus.APPROVED.value]),
    ).count()
    return evidence_count, open_risk_count, active_exception_count


def to_control_out(db: Session, row: HipaaControl) -> ControlOut:
    evidence_count, open_risk_count, active_exception_count = _counts(db, row.id)
    return ControlOut(
        id=row.id, control_key=row.control_key, title=row.title, description=row.description, domain=row.domain,
        regulatory_reference=row.regulatory_reference or [], applicability_status=row.applicability_status,
        applicability_rationale=row.applicability_rationale, owner=row.owner,
        implementation_status=row.implementation_status, testing_status=row.testing_status,
        deployment_status=row.deployment_status, operational_verification_status=row.operational_verification_status,
        overall_status=derive_overall_status(row), evidence_count=evidence_count, open_risk_count=open_risk_count,
        active_exception_count=active_exception_count, created_at=row.created_at, updated_at=row.updated_at,
    )


def list_controls(db: Session, *, page: int, page_size: int, domain: str | None = None,
                  implementation_status: str | None = None, testing_status: str | None = None,
                  deployment_status: str | None = None, operational_verification_status: str | None = None,
                  applicability_status: str | None = None) -> tuple[list[HipaaControl], int]:
    q = db.query(HipaaControl)
    if domain is not None:
        q = q.filter(HipaaControl.domain == domain)
    if implementation_status is not None:
        q = q.filter(HipaaControl.implementation_status == implementation_status)
    if testing_status is not None:
        q = q.filter(HipaaControl.testing_status == testing_status)
    if deployment_status is not None:
        q = q.filter(HipaaControl.deployment_status == deployment_status)
    if operational_verification_status is not None:
        q = q.filter(HipaaControl.operational_verification_status == operational_verification_status)
    if applicability_status is not None:
        q = q.filter(HipaaControl.applicability_status == applicability_status)
    total = q.count()
    rows = q.order_by(HipaaControl.domain.asc(), HipaaControl.control_key.asc()).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def get_control(db: Session, control_key: str) -> HipaaControl:
    row = db.query(HipaaControl).filter(HipaaControl.control_key == control_key).one_or_none()
    if row is None:
        raise ControlNotFoundError(control_key)
    return row


def create_control(db: Session, payload: ControlCreate, *, actor: str | None) -> HipaaControl:
    if db.query(HipaaControl).filter(HipaaControl.control_key == payload.control_key).first() is not None:
        raise ControlAlreadyExistsError(payload.control_key)
    row = HipaaControl(
        control_key=payload.control_key, title=payload.title, description=payload.description,
        domain=payload.domain.value, regulatory_reference=[r.model_dump(mode="json") for r in payload.regulatory_reference],
        applicability_status=payload.applicability_status.value, applicability_rationale=payload.applicability_rationale,
        owner=payload.owner, implementation_status=payload.implementation_status.value,
        testing_status=payload.testing_status.value, deployment_status=payload.deployment_status.value,
        operational_verification_status=payload.operational_verification_status.value,
    )
    db.add(row)
    db.flush()
    _record_history(db, entity_type="control", entity_id=row.control_key, change_type="created", old_state=None, new_state=_control_state(row), actor=actor)
    db.commit()
    db.refresh(row)
    return row


def update_control(db: Session, control_key: str, payload: ControlUpdate, *, actor: str | None) -> HipaaControl:
    row = get_control(db, control_key)
    old = _control_state(row)
    updates = payload.model_dump(exclude_unset=True, exclude={"change_reason"})
    for field, value in updates.items():
        if field == "regulatory_reference" and value is not None:
            value = [v if isinstance(v, dict) else v.model_dump(mode="json") for v in value]
        else:
            value = _enum_value(value)
        setattr(row, field, value)
    db.flush()
    _record_history(db, entity_type="control", entity_id=row.control_key, change_type="updated", old_state=old, new_state=_control_state(row), actor=actor, reason=payload.change_reason)
    db.commit()
    db.refresh(row)
    return row


def create_evidence(db: Session, control_key: str, payload: EvidenceCreate, *, actor: str | None) -> HipaaControlEvidence:
    control = get_control(db, control_key)
    existing = db.query(HipaaControlEvidence).filter(
        HipaaControlEvidence.control_id == control.id,
        HipaaControlEvidence.evidence_type == payload.evidence_type.value,
        HipaaControlEvidence.reference == payload.reference,
    ).one_or_none()
    if existing is not None:
        return existing
    row = HipaaControlEvidence(
        control_id=control.id, evidence_type=payload.evidence_type.value, reference=payload.reference,
        repository=payload.repository, commit_ref=payload.commit_ref, environment=payload.environment,
        verification_result=payload.verification_result.value, notes=payload.notes, observed_at=payload.observed_at,
        recorded_by=actor,
    )
    db.add(row)
    db.flush()
    _record_history(db, entity_type="evidence", entity_id=str(row.id), change_type="created", old_state=None, new_state={
        "control_key": control.control_key, "evidence_type": row.evidence_type, "verification_result": row.verification_result,
        "reference": row.reference,
    }, actor=actor)
    db.commit()
    db.refresh(row)
    return row


def list_evidence(db: Session, control_key: str) -> list[HipaaControlEvidence]:
    control = get_control(db, control_key)
    return db.query(HipaaControlEvidence).filter(HipaaControlEvidence.control_id == control.id).order_by(HipaaControlEvidence.recorded_at.desc(), HipaaControlEvidence.id.desc()).all()


def create_risk(db: Session, control_key: str, payload: RiskCreate, *, actor: str | None) -> HipaaControlRisk:
    control = get_control(db, control_key)
    row = HipaaControlRisk(control_id=control.id, state=payload.state.value, severity=payload.severity.value,
                           description=payload.description, impact=payload.impact, mitigation=payload.mitigation,
                           owner=payload.owner, target_date=payload.target_date, closed_at=payload.closed_at,
                           evidence=payload.evidence)
    db.add(row)
    db.flush()
    _record_history(db, entity_type="risk", entity_id=str(row.id), change_type="created", old_state=None, new_state={"control_key": control.control_key, "state": row.state, "severity": row.severity}, actor=actor)
    db.commit()
    db.refresh(row)
    return row


def list_risks(db: Session, control_key: str, state: str | None = None) -> list[HipaaControlRisk]:
    control = get_control(db, control_key)
    q = db.query(HipaaControlRisk).filter(HipaaControlRisk.control_id == control.id)
    if state is not None:
        q = q.filter(HipaaControlRisk.state == state)
    return q.order_by(HipaaControlRisk.opened_at.desc(), HipaaControlRisk.id.desc()).all()


def create_exception(db: Session, control_key: str, payload: ExceptionCreate, *, actor: str | None) -> HipaaControlException:
    control = get_control(db, control_key)
    row = HipaaControlException(control_id=control.id, rationale=payload.rationale, scope=payload.scope,
                                approver=payload.approver, owner=payload.owner, status=payload.status.value,
                                review_date=payload.review_date, expires_at=payload.expires_at,
                                supporting_evidence=payload.supporting_evidence)
    db.add(row)
    db.flush()
    _record_history(db, entity_type="exception", entity_id=str(row.id), change_type="created", old_state=None, new_state={"control_key": control.control_key, "status": row.status}, actor=actor)
    db.commit()
    db.refresh(row)
    return row


def list_exceptions(db: Session, control_key: str) -> list[HipaaControlException]:
    control = get_control(db, control_key)
    return db.query(HipaaControlException).filter(HipaaControlException.control_id == control.id).order_by(HipaaControlException.created_at.desc(), HipaaControlException.id.desc()).all()


def list_history(db: Session, *, entity_type: str | None = None, entity_id: str | None = None) -> list[HipaaReadinessHistory]:
    q = db.query(HipaaReadinessHistory)
    if entity_type is not None:
        q = q.filter(HipaaReadinessHistory.entity_type == entity_type)
    if entity_id is not None:
        q = q.filter(HipaaReadinessHistory.entity_id == entity_id)
    return q.order_by(HipaaReadinessHistory.changed_at.desc(), HipaaReadinessHistory.id.desc()).all()


def ensure_legacy_mappings(db: Session) -> int:
    changes = db.query(HipaaComplianceChange).all()
    created = 0
    for change in changes:
        exists = db.query(HipaaLegacyChangeMapping).filter(HipaaLegacyChangeMapping.legacy_change_id == change.change_id).first()
        if exists is None:
            db.add(HipaaLegacyChangeMapping(legacy_change_id=change.change_id, mapping_status="unmapped", mapping_rationale="Preserved legacy tracker row; no deterministic control mapping was inferred."))
            created += 1
    if created:
        db.commit()
    return created


def list_legacy_mappings(db: Session) -> list[HipaaLegacyChangeMapping]:
    ensure_legacy_mappings(db)
    return db.query(HipaaLegacyChangeMapping).order_by(HipaaLegacyChangeMapping.legacy_change_id.asc()).all()
