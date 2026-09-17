from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, event
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from control_center.hipaa_compliance.db import Base


class HipaaComplianceChange(Base):
    """Durable record of one HIPAA-relevant engineering change/release --
    the persistent history this platform's HIPAA remediation work
    (PR3a-PR3d and friends) previously only lived in PR descriptions and
    developer memory notes for, with no queryable source of truth.

    change_id is a human-assigned natural key (e.g. "SECURITY-AUDIT-PR8"),
    not a surrogate int id -- the same natural-key-as-PK convention
    omnibioai-security-audit's own AuditEventRecord.event_id already
    established for this ecosystem's other audit-adjacent table.

    V1 has no automatic producer: every row is written by a
    platform_admin via POST/PATCH /hipaa-compliance/changes, or by the
    one-time seed (seed.py) for the already-completed changes this
    feature shipped with. See api/routes_hipaa_compliance.py's own
    module docstring for why there is no automatic producer yet.
    """

    __tablename__ = "hipaa_compliance_changes"

    change_id = Column(String(64), primary_key=True)
    title = Column(String(255), nullable=False)
    change_date = Column(Date, nullable=False)
    repository = Column(String(255), nullable=False)
    branch = Column(String(255), nullable=True)
    commit_sha = Column(String(64), nullable=True)
    pr_number = Column(Integer, nullable=True)
    description = Column(Text, nullable=False, default="")
    # One of ComplianceControlCategory's values (schemas.py) -- validated
    # there, stored as a plain string here, same tradeoff
    # AuditEventRecord.decision/event_type accept upstream in
    # omnibioai-security-audit (no DB-level enum/FK, so a future category
    # doesn't need a schema migration to add).
    control_category = Column(String(64), nullable=False)
    affected_component = Column(String(255), nullable=True)
    # One of ComplianceStatus's values -- same plain-string tradeoff as
    # control_category above.
    status = Column(String(32), nullable=False)
    verification_result = Column(Text, nullable=True)
    reviewer = Column(String(255), nullable=True)
    # List of {type, label, url, identifier} objects -- see
    # schemas.py::EvidenceRef. References only (a PR URL, a commit SHA, a
    # CI run URL, a test-suite result summary), never the sensitive
    # contents those references point at -- this table never stores a
    # JWT, credential, or raw audit payload.
    evidence = Column(JSON, nullable=False, default=list)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class HipaaControl(Base):
    """First-class HIPAA readiness control with separate lifecycle dimensions."""

    __tablename__ = "hipaa_controls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    control_key = Column(String(96), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    domain = Column(String(96), nullable=False, index=True)
    regulatory_reference = Column(JSON, nullable=False, default=list)
    applicability_status = Column(String(32), nullable=False, default="unknown", index=True)
    applicability_rationale = Column(Text, nullable=True)
    owner = Column(String(255), nullable=True)
    implementation_status = Column(String(32), nullable=False, default="unknown", index=True)
    testing_status = Column(String(32), nullable=False, default="unknown", index=True)
    deployment_status = Column(String(32), nullable=False, default="unknown", index=True)
    operational_verification_status = Column(String(32), nullable=False, default="unknown", index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    evidence = relationship("HipaaControlEvidence", back_populates="control")
    risks = relationship("HipaaControlRisk", back_populates="control")
    exceptions = relationship("HipaaControlException", back_populates="control")


class HipaaControlEvidence(Base):
    """Structured evidence metadata attributable to a control.

    References are metadata only and must not contain credentials, PHI, raw
    patient data, tokens, or the sensitive contents behind a URL/ref.
    """

    __tablename__ = "hipaa_control_evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    control_id = Column(Integer, ForeignKey("hipaa_controls.id"), nullable=False, index=True)
    evidence_type = Column(String(32), nullable=False, index=True)
    reference = Column(String(2048), nullable=False)
    repository = Column(String(255), nullable=True)
    commit_ref = Column(String(255), nullable=True)
    environment = Column(String(64), nullable=True)
    verification_result = Column(String(32), nullable=False, default="unknown", index=True)
    notes = Column(Text, nullable=True)
    observed_at = Column(DateTime, nullable=True)
    recorded_at = Column(DateTime, server_default=func.now(), nullable=False)
    recorded_by = Column(String(255), nullable=True)

    control = relationship("HipaaControl", back_populates="evidence")


class HipaaControlRisk(Base):
    __tablename__ = "hipaa_control_risks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    control_id = Column(Integer, ForeignKey("hipaa_controls.id"), nullable=False, index=True)
    state = Column(String(32), nullable=False, default="open", index=True)
    severity = Column(String(32), nullable=False, default="unknown", index=True)
    description = Column(Text, nullable=False)
    impact = Column(Text, nullable=True)
    mitigation = Column(Text, nullable=True)
    owner = Column(String(255), nullable=True)
    opened_at = Column(DateTime, server_default=func.now(), nullable=False)
    target_date = Column(Date, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    evidence = Column(JSON, nullable=False, default=list)

    control = relationship("HipaaControl", back_populates="risks")


class HipaaControlException(Base):
    __tablename__ = "hipaa_control_exceptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    control_id = Column(Integer, ForeignKey("hipaa_controls.id"), nullable=False, index=True)
    rationale = Column(Text, nullable=False)
    scope = Column(Text, nullable=False)
    approver = Column(String(255), nullable=True)
    owner = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, default="open", index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    review_date = Column(Date, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    supporting_evidence = Column(JSON, nullable=False, default=list)

    control = relationship("HipaaControl", back_populates="exceptions")


class HipaaReadinessHistory(Base):
    """Append-only application-enforced readiness history.

    Application code creates rows and never updates/deletes them. SQLAlchemy
    event hooks enforce that posture for ORM writes, while the language
    remains honest: privileged database administrators could still bypass it.
    """

    __tablename__ = "hipaa_readiness_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(64), nullable=False, index=True)
    entity_id = Column(String(96), nullable=False, index=True)
    change_type = Column(String(64), nullable=False, index=True)
    old_state = Column(JSON, nullable=True)
    new_state = Column(JSON, nullable=False)
    actor = Column(String(255), nullable=True)
    changed_at = Column(DateTime, server_default=func.now(), nullable=False)
    reason = Column(Text, nullable=True)
    source = Column(String(255), nullable=True)
    legacy = Column(Boolean, nullable=False, default=False)


class HipaaLegacyChangeMapping(Base):
    """Explicit preservation/mapping metadata for legacy tracker rows."""

    __tablename__ = "hipaa_legacy_change_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    legacy_change_id = Column(String(64), ForeignKey("hipaa_compliance_changes.change_id"), nullable=False, unique=True)
    control_id = Column(Integer, ForeignKey("hipaa_controls.id"), nullable=True, index=True)
    mapping_status = Column(String(32), nullable=False, default="unmapped", index=True)
    mapping_rationale = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


def _reject_history_mutation(_mapper, _connection, target) -> None:
    raise ValueError(f"{target.__tablename__} is append-only through the application")


event.listen(HipaaReadinessHistory, "before_update", _reject_history_mutation)
event.listen(HipaaReadinessHistory, "before_delete", _reject_history_mutation)
