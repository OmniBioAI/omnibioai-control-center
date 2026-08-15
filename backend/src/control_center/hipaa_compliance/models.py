from __future__ import annotations

from sqlalchemy import JSON, Column, Date, DateTime, Integer, String, Text
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
