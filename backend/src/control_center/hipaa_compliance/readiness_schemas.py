from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SECRET_OR_PHI_RE = re.compile(
    r"(password|passwd|secret|api[_-]?key|token|bearer\s+[a-z0-9_.-]+|jwt|ssn|social security|patient[_ -]?id|mrn)",
    re.IGNORECASE,
)


def _reject_sensitive_text(value: str | None) -> str | None:
    if value and _SECRET_OR_PHI_RE.search(value):
        raise ValueError("evidence metadata must not contain credentials, tokens, PHI, or raw patient identifiers")
    return value


class Domain(str, Enum):
    IDENTITY_ACCESS_MANAGEMENT = "identity_access_management"
    AUTHENTICATION = "authentication"
    AUTHORIZATION_TENANT_ISOLATION = "authorization_tenant_isolation"
    AUDIT_LOGGING = "audit_logging"
    AUDIT_INTEGRITY = "audit_integrity"
    DATA_PROTECTION = "data_protection"
    ENCRYPTION = "encryption"
    BACKUP_RECOVERY = "backup_recovery"
    PHI_HANDLING = "phi_handling"
    LOGGING_REDACTION = "logging_redaction"
    EXTERNAL_AI_DATA_EGRESS = "external_ai_data_egress"
    EXECUTION_ISOLATION = "execution_isolation"
    INFRASTRUCTURE_SECURITY = "infrastructure_security"
    NETWORK_SECURITY = "network_security"
    SECRETS_MANAGEMENT = "secrets_management"
    INCIDENT_OPERATIONAL_CONTROLS = "incident_operational_controls"
    OTHER = "other"


class ApplicabilityStatus(str, Enum):
    UNKNOWN = "unknown"
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    DEFERRED = "deferred"


class ImplementationStatus(str, Enum):
    UNKNOWN = "unknown"
    NOT_STARTED = "not_started"
    PARTIAL = "partial"
    IMPLEMENTED = "implemented"
    DEFERRED = "deferred"
    NOT_APPLICABLE = "not_applicable"


class TestingStatus(str, Enum):
    UNKNOWN = "unknown"
    NOT_TESTED = "not_tested"
    PARTIAL = "partial"
    TESTED = "tested"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class DeploymentStatus(str, Enum):
    UNKNOWN = "unknown"
    NOT_DEPLOYED = "not_deployed"
    PARTIAL = "partial"
    DEPLOYED = "deployed"
    NOT_APPLICABLE = "not_applicable"


class OperationalVerificationStatus(str, Enum):
    UNKNOWN = "unknown"
    NOT_VERIFIED = "not_verified"
    PARTIAL = "partial"
    VERIFIED = "verified"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class OverallControlStatus(str, Enum):
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    DEFERRED = "deferred"
    NEEDS_WORK = "needs_work"
    PARTIAL = "partial"
    EVIDENCE_READY = "evidence_ready"


class EvidenceType(str, Enum):
    GIT_COMMIT = "git_commit"
    GITHUB_PR = "github_pr"
    CI_RUN = "ci_run"
    TEST_SUITE = "test_suite"
    DOCUMENTATION = "documentation"
    DEPLOYMENT_VERIFICATION = "deployment_verification"
    OPERATIONAL_VERIFICATION = "operational_verification"
    MIGRATION = "migration"
    AUDIT_RESULT = "audit_result"
    OTHER = "other"


class VerificationResult(str, Enum):
    UNKNOWN = "unknown"
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    NOT_APPLICABLE = "not_applicable"


class RiskState(str, Enum):
    OPEN = "open"
    PARTIAL = "partial"
    MITIGATED = "mitigated"
    ACCEPTED = "accepted"
    DEFERRED = "deferred"
    CLOSED = "closed"


class Severity(str, Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExceptionStatus(str, Enum):
    OPEN = "open"
    APPROVED = "approved"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CLOSED = "closed"


class RegulatoryReference(BaseModel):
    framework: str = Field(..., min_length=1, max_length=120)
    citation: str = Field(..., min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=255)


_CONTROL_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$"


class ControlBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    domain: Domain
    regulatory_reference: list[RegulatoryReference] = Field(default_factory=list)
    applicability_status: ApplicabilityStatus = ApplicabilityStatus.UNKNOWN
    applicability_rationale: str | None = None
    owner: str | None = Field(default=None, max_length=255)
    implementation_status: ImplementationStatus = ImplementationStatus.UNKNOWN
    testing_status: TestingStatus = TestingStatus.UNKNOWN
    deployment_status: DeploymentStatus = DeploymentStatus.UNKNOWN
    operational_verification_status: OperationalVerificationStatus = OperationalVerificationStatus.UNKNOWN


class ControlCreate(ControlBase):
    control_key: str = Field(..., pattern=_CONTROL_KEY_PATTERN)


class ControlUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    domain: Domain | None = None
    regulatory_reference: list[RegulatoryReference] | None = None
    applicability_status: ApplicabilityStatus | None = None
    applicability_rationale: str | None = None
    owner: str | None = Field(default=None, max_length=255)
    implementation_status: ImplementationStatus | None = None
    testing_status: TestingStatus | None = None
    deployment_status: DeploymentStatus | None = None
    operational_verification_status: OperationalVerificationStatus | None = None
    change_reason: str | None = None


class ControlOut(ControlBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    control_key: str
    overall_status: OverallControlStatus
    evidence_count: int = 0
    open_risk_count: int = 0
    active_exception_count: int = 0
    created_at: datetime
    updated_at: datetime


class ControlListResponse(BaseModel):
    items: list[ControlOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class EvidenceCreate(BaseModel):
    evidence_type: EvidenceType
    reference: str = Field(..., min_length=1, max_length=2048)
    repository: str | None = Field(default=None, max_length=255)
    commit_ref: str | None = Field(default=None, max_length=255)
    environment: str | None = Field(default=None, max_length=64)
    verification_result: VerificationResult = VerificationResult.UNKNOWN
    notes: str | None = None
    observed_at: datetime | None = None

    @field_validator("reference", "repository", "commit_ref", "environment", "notes")
    @classmethod
    def no_sensitive_metadata(cls, value: str | None) -> str | None:
        return _reject_sensitive_text(value)


class EvidenceOut(EvidenceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    control_id: int
    recorded_at: datetime
    recorded_by: str | None = None


class RiskCreate(BaseModel):
    state: RiskState = RiskState.OPEN
    severity: Severity = Severity.UNKNOWN
    description: str = Field(..., min_length=1)
    impact: str | None = None
    mitigation: str | None = None
    owner: str | None = Field(default=None, max_length=255)
    target_date: date | None = None
    closed_at: datetime | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class RiskOut(RiskCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    control_id: int
    opened_at: datetime


class ExceptionCreate(BaseModel):
    rationale: str = Field(..., min_length=1)
    scope: str = Field(..., min_length=1)
    approver: str | None = Field(default=None, max_length=255)
    owner: str | None = Field(default=None, max_length=255)
    status: ExceptionStatus = ExceptionStatus.OPEN
    review_date: date | None = None
    expires_at: datetime | None = None
    supporting_evidence: list[dict[str, Any]] = Field(default_factory=list)


class ExceptionOut(ExceptionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    control_id: int
    created_at: datetime


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_type: str
    entity_id: str
    change_type: str
    old_state: dict[str, Any] | None
    new_state: dict[str, Any]
    actor: str | None
    changed_at: datetime
    reason: str | None
    source: str | None
    legacy: bool


class LegacyMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    legacy_change_id: str
    control_id: int | None
    mapping_status: str
    mapping_rationale: str | None
    created_at: datetime
    updated_at: datetime
