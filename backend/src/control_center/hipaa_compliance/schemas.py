from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ComplianceStatus(str, Enum):
    """The five statuses this feature's task brief specifies verbatim --
    string values, not auto() ints, so the DB column (plain String, see
    models.py) and the API wire format are the same characters, no
    translation table needed anywhere."""

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    RELEASED = "released"
    EXCEPTION = "exception"


# "Number verified"/"number pending"/"number of exceptions" in the
# Overview (service.py::build_summary) group these five statuses into
# three buckets -- verified+released count as "verified" (a released
# change is, by definition, a verified one that also shipped),
# planned+in_progress count as "pending", exception is its own bucket.
# Not stored anywhere, computed at read time from `status`.
VERIFIED_STATUSES = frozenset({ComplianceStatus.VERIFIED, ComplianceStatus.RELEASED})
PENDING_STATUSES = frozenset({ComplianceStatus.PLANNED, ComplianceStatus.IN_PROGRESS})


class ComplianceControlCategory(str, Enum):
    """High-level HIPAA control/category taxonomy -- the task brief's own
    list plus one catch-all. Deliberately a fixed enum, not a free-text
    column or a separate controls table: V1's Compliance Controls view
    (service.py::build_control_summaries) is computed by grouping
    hipaa_compliance_changes rows by this field -- reuse the change-
    history data, don't invent a parallel model. A category with zero
    changes today still appears in that view so "0 tracked yet" is
    visible, not silently absent."""

    AUDIT_INTEGRITY = "audit_integrity"
    AUDIT_EVENT_SIGNING = "audit_event_signing"
    AUDIT_EVENT_VERIFICATION = "audit_event_verification"
    ACCESS_CONTROL = "access_control"
    AUTHENTICATION_AUTHORIZATION = "authentication_authorization"
    DATA_INTEGRITY = "data_integrity"
    MONITORING_LOGGING = "monitoring_logging"
    OTHER = "other"


CONTROL_CATEGORY_LABELS: dict[ComplianceControlCategory, str] = {
    ComplianceControlCategory.AUDIT_INTEGRITY: "Audit Integrity",
    ComplianceControlCategory.AUDIT_EVENT_SIGNING: "Audit Event Signing",
    ComplianceControlCategory.AUDIT_EVENT_VERIFICATION: "Audit Event Verification",
    ComplianceControlCategory.ACCESS_CONTROL: "Access Control",
    ComplianceControlCategory.AUTHENTICATION_AUTHORIZATION: "Authentication / Authorization",
    ComplianceControlCategory.DATA_INTEGRITY: "Data Integrity",
    ComplianceControlCategory.MONITORING_LOGGING: "Monitoring / Logging",
    ComplianceControlCategory.OTHER: "Other",
}


class EvidenceType(str, Enum):
    GITHUB_PR = "github_pr"
    COMMIT = "commit"
    CI_RUN = "ci_run"
    TEST_SUITE = "test_suite"
    DOCUMENTATION = "documentation"
    OTHER = "other"


class EvidenceRef(BaseModel):
    """A reference to evidence, never the evidence's own sensitive
    contents -- see models.py::HipaaComplianceChange.evidence's own
    docstring. `url`/`identifier` are opaque strings this API never
    fetches or validates the reachability of."""

    type: EvidenceType
    label: str = Field(..., min_length=1, max_length=255)
    url: str | None = Field(default=None, max_length=2048)
    identifier: str | None = Field(default=None, max_length=255)


# change_id is a human-assigned natural key -- constrained to a small,
# predictable charset so it's safe to use in a URL path segment
# (GET /hipaa-compliance/changes/{change_id}) with no escaping question.
_CHANGE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"


class HipaaComplianceChangeBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    change_date: date
    repository: str = Field(..., min_length=1, max_length=255)
    branch: str | None = Field(default=None, max_length=255)
    commit_sha: str | None = Field(default=None, max_length=64)
    pr_number: int | None = Field(default=None, gt=0)
    description: str = ""
    control_category: ComplianceControlCategory
    affected_component: str | None = Field(default=None, max_length=255)
    status: ComplianceStatus
    verification_result: str | None = None
    reviewer: str | None = Field(default=None, max_length=255)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    notes: str | None = None


class HipaaComplianceChangeCreate(HipaaComplianceChangeBase):
    change_id: str = Field(..., pattern=_CHANGE_ID_PATTERN)


class HipaaComplianceChangeUpdate(BaseModel):
    """PATCH body -- every field optional, only what's provided is
    changed. change_id is never a body field (it's the immutable path
    parameter) -- the same "the natural key is never a PATCH-able field"
    posture omnibioai-security-audit's read-only AuditEventRecord.
    event_id API already implies."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    change_date: date | None = None
    repository: str | None = Field(default=None, min_length=1, max_length=255)
    branch: str | None = Field(default=None, max_length=255)
    commit_sha: str | None = Field(default=None, max_length=64)
    pr_number: int | None = Field(default=None, gt=0)
    description: str | None = None
    control_category: ComplianceControlCategory | None = None
    affected_component: str | None = Field(default=None, max_length=255)
    status: ComplianceStatus | None = None
    verification_result: str | None = None
    reviewer: str | None = Field(default=None, max_length=255)
    evidence: list[EvidenceRef] | None = None
    notes: str | None = None


class HipaaComplianceChangeOut(HipaaComplianceChangeBase):
    model_config = ConfigDict(from_attributes=True)

    change_id: str
    created_at: datetime
    updated_at: datetime


class HipaaComplianceChangeListResponse(BaseModel):
    """Same items/total/page/page_size/total_pages shape this ecosystem's
    other paginated platform-admin endpoints already use (e.g.
    omnibioai-security-audit's AuditEventListResponse)."""

    items: list[HipaaComplianceChangeOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class ControlCategorySummary(BaseModel):
    category: ComplianceControlCategory
    label: str
    total: int
    verified: int
    pending: int
    exceptions: int


class HipaaComplianceSummaryOut(BaseModel):
    """The Compliance Overview tile data: overall status, controls
    tracked/verified/pending/exceptions, and the latest change -- see
    service.py::build_summary for how each field is derived from
    hipaa_compliance_changes, nothing here is a separately-maintained
    counter that could drift from the underlying rows."""

    overall_status: str  # "no_data" | "on_track" | "in_progress" | "attention_needed"
    total_controls_tracked: int
    verified_count: int
    pending_count: int
    exception_count: int
    latest_change_id: str | None = None
    latest_change_title: str | None = None
    latest_change_date: date | None = None
    controls: list[ControlCategorySummary]
