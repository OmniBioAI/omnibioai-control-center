"""Pure, read-only security posture evidence model.

This module deliberately has no service, network, Docker, database, Redis, or
filesystem dependencies.  Callers provide already-collected evidence and the
model only validates, classifies, and serializes that evidence.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class ControlCategory(_StringEnum):
    IDENTITY = "IDENTITY"
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    TENANT_ISOLATION = "TENANT_ISOLATION"
    GATEWAY = "GATEWAY"
    POLICY = "POLICY"
    COMPUTE_GOVERNANCE = "COMPUTE_GOVERNANCE"
    CONTAINER_SECURITY = "CONTAINER_SECURITY"
    AUDIT = "AUDIT"
    SECRET_MANAGEMENT = "SECRET_MANAGEMENT"
    CERTIFICATION = "CERTIFICATION"


class Priority(_StringEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class ImplementationStatus(_StringEnum):
    IMPLEMENTED = "IMPLEMENTED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    UNKNOWN = "UNKNOWN"


class TestStatus(_StringEnum):
    __test__ = False

    PASS = "PASS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    NOT_RUN = "NOT_RUN"
    UNKNOWN = "UNKNOWN"


class LiveStatus(_StringEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class CertificationStatus(_StringEnum):
    CERTIFIED = "CERTIFIED"
    NOT_CERTIFIED = "NOT_CERTIFIED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class Freshness(_StringEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class Posture(_StringEnum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    ATTENTION = "ATTENTION"
    UNKNOWN = "UNKNOWN"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class EvidenceType(_StringEnum):
    SOURCE_IMPLEMENTATION = "SOURCE_IMPLEMENTATION"
    UNIT_TEST = "UNIT_TEST"
    INTEGRATION_TEST = "INTEGRATION_TEST"
    LIVE_VALIDATION = "LIVE_VALIDATION"
    REGRESSION_CERTIFICATION = "REGRESSION_CERTIFICATION"
    RUNTIME_HEALTH = "RUNTIME_HEALTH"
    CONFIGURATION = "CONFIGURATION"
    SECURITY_AUDIT = "SECURITY_AUDIT"
    COMPOSE_SECURITY = "COMPOSE_SECURITY"
    DOCKER_PROXY_POLICY = "DOCKER_PROXY_POLICY"


class FindingType(_StringEnum):
    ACTIVE_ISSUE = "ACTIVE_ISSUE"
    FIXED_HISTORICAL = "FIXED_HISTORICAL"
    TECHNICAL_DEBT = "TECHNICAL_DEBT"
    COVERAGE_GAP = "COVERAGE_GAP"


class DataSourceStatus(_StringEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    PARTIAL = "PARTIAL"


_BANNED_TEXT = re.compile(
    r"(?:password|secret|token|jwt|authorization|api\s*key|cookie|private\s+key|"
    r"container\s+id|backend\s+handle|username|tenant[-_ ]private|"
    r"(?:^|\s)/home(?:/|\s|$))",
    re.IGNORECASE,
)
_JWT_VALUE = re.compile(r"(?:eyJ[A-Za-z0-9_-]{8,}\.){2}[A-Za-z0-9_-]{8,}")
_ISO_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def _safe_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    semantic_id = field_name == "identifier" or field_name.replace(" ", "_").endswith("_id")
    if "\x00" in value or _JWT_VALUE.search(value) or (not semantic_id and _BANNED_TEXT.search(value)):
        raise ValueError(f"{field_name} contains disallowed sensitive content")
    return value


def _timestamp(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    _safe_text(value, field_name)
    if not _ISO_TIMESTAMP.match(value):
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _enum(value: Any, enum_type: type[_StringEnum], field_name: str) -> _StringEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


@dataclass(frozen=True)
class SecurityEvidence:
    type: EvidenceType
    repository: str
    identifier: str
    status: str
    validated_at: str | None = None
    freshness: Freshness = Freshness.UNKNOWN
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", _enum(self.type, EvidenceType, "evidence type"))
        object.__setattr__(self, "repository", _safe_text(self.repository, "repository"))
        object.__setattr__(self, "identifier", _safe_text(self.identifier, "identifier"))
        object.__setattr__(self, "status", _safe_text(self.status, "evidence status").upper())
        object.__setattr__(self, "validated_at", _timestamp(self.validated_at, "validated_at"))
        object.__setattr__(self, "freshness", _enum(self.freshness, Freshness, "evidence freshness"))
        if self.description:
            object.__setattr__(self, "description", _safe_text(self.description, "description"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "repository": self.repository,
            "identifier": self.identifier,
            "status": self.status,
            "validated_at": self.validated_at,
            "freshness": self.freshness.value,
            "description": self.description,
        }


@dataclass(frozen=True)
class SecurityFinding:
    finding_id: str
    title: str
    type: FindingType
    control_ids: tuple[str, ...] = ()
    severity: str | None = None
    source: str = ""
    validated_at: str | None = None
    summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "finding_id", _safe_text(self.finding_id, "finding_id"))
        object.__setattr__(self, "title", _safe_text(self.title, "finding title"))
        object.__setattr__(self, "type", _enum(self.type, FindingType, "finding type"))
        ids = tuple(sorted(_safe_text(item, "control_id") for item in self.control_ids))
        object.__setattr__(self, "control_ids", ids)
        if self.severity is not None:
            object.__setattr__(self, "severity", _safe_text(self.severity, "severity"))
        if self.source:
            object.__setattr__(self, "source", _safe_text(self.source, "finding source"))
        object.__setattr__(self, "validated_at", _timestamp(self.validated_at, "finding validated_at"))
        if self.summary:
            object.__setattr__(self, "summary", _safe_text(self.summary, "finding summary"))

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "finding_id": self.finding_id,
            "title": self.title,
            "type": self.type.value,
            "control_ids": list(self.control_ids),
            "source": self.source,
            "validated_at": self.validated_at,
            "summary": self.summary,
        }
        if self.severity is not None:
            result["severity"] = self.severity
        return result


@dataclass(frozen=True)
class SecurityTechnicalDebt:
    debt_id: str
    summary: str
    control_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "debt_id", _safe_text(self.debt_id, "technical debt id"))
        object.__setattr__(self, "summary", _safe_text(self.summary, "technical debt summary"))
        object.__setattr__(self, "control_ids", tuple(sorted(_safe_text(i, "control_id") for i in self.control_ids)))

    def as_dict(self) -> dict[str, Any]:
        return {"debt_id": self.debt_id, "summary": self.summary, "control_ids": list(self.control_ids)}


def _evidence_conflicts(evidence: Iterable[SecurityEvidence]) -> bool:
    by_type: dict[EvidenceType, set[str]] = {}
    for item in evidence:
        by_type.setdefault(item.type, set()).add(item.status)
    return any(len(statuses) > 1 for statuses in by_type.values())


def _has_material_coverage_limitation(limitations: Iterable[str]) -> bool:
    markers = ("exercised path", "exercised/certified path", "platform-wide", "coverage is partial")
    return any(any(marker in limitation.lower() for marker in markers) for limitation in limitations)


def calculate_posture(
    implementation_status: ImplementationStatus,
    test_status: TestStatus,
    live_status: LiveStatus,
    certification_status: CertificationStatus,
    freshness: Freshness,
    findings: Iterable[SecurityFinding] = (),
    evidence: Iterable[SecurityEvidence] = (),
    limitations: Iterable[str] = (),
    *,
    live_required: bool = False,
) -> Posture:
    implementation_status = _enum(implementation_status, ImplementationStatus, "implementation_status")
    test_status = _enum(test_status, TestStatus, "test_status")
    live_status = _enum(live_status, LiveStatus, "live_status")
    certification_status = _enum(certification_status, CertificationStatus, "certification_status")
    freshness = _enum(freshness, Freshness, "freshness")
    findings = tuple(findings)
    evidence = tuple(evidence)
    limitations = tuple(limitations)

    if implementation_status is ImplementationStatus.NOT_IMPLEMENTED:
        return Posture.NOT_IMPLEMENTED
    if any(f.type is FindingType.ACTIVE_ISSUE for f in findings):
        return Posture.ATTENTION
    if _evidence_conflicts(evidence):
        return Posture.UNKNOWN
    if implementation_status is ImplementationStatus.UNKNOWN:
        return Posture.UNKNOWN
    if test_status is TestStatus.FAILED or live_status is LiveStatus.UNAVAILABLE and live_required:
        return Posture.ATTENTION
    if certification_status is CertificationStatus.CERTIFIED and freshness is Freshness.STALE:
        return Posture.PARTIAL
    if certification_status is CertificationStatus.CERTIFIED and _has_material_coverage_limitation(limitations):
        return Posture.PARTIAL
    if test_status is TestStatus.UNKNOWN or test_status is TestStatus.NOT_RUN:
        return Posture.UNKNOWN
    if test_status is TestStatus.FAILED:
        return Posture.ATTENTION
    if test_status is TestStatus.PARTIAL:
        return Posture.PARTIAL
    if (
        test_status is TestStatus.PASS
        and live_status is LiveStatus.AVAILABLE
        and certification_status is CertificationStatus.CERTIFIED
        and freshness is Freshness.CURRENT
    ):
        return Posture.VERIFIED
    if live_status is LiveStatus.UNAVAILABLE and live_required:
        return Posture.ATTENTION
    return Posture.PARTIAL


@dataclass(frozen=True)
class SecurityControl:
    control_id: str
    name: str
    category: ControlCategory
    priority: Priority
    implementation_status: ImplementationStatus = ImplementationStatus.UNKNOWN
    test_status: TestStatus = TestStatus.UNKNOWN
    live_status: LiveStatus = LiveStatus.UNKNOWN
    certification_status: CertificationStatus = CertificationStatus.UNKNOWN
    freshness: Freshness = Freshness.UNKNOWN
    evidence: tuple[SecurityEvidence, ...] = ()
    findings: tuple[SecurityFinding, ...] = ()
    limitations: tuple[str, ...] = ()
    live_required: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "control_id", _safe_text(self.control_id, "control_id"))
        object.__setattr__(self, "name", _safe_text(self.name, "control name"))
        object.__setattr__(self, "category", _enum(self.category, ControlCategory, "category"))
        object.__setattr__(self, "priority", _enum(self.priority, Priority, "priority"))
        for name, enum_type in (("implementation_status", ImplementationStatus), ("test_status", TestStatus), ("live_status", LiveStatus), ("certification_status", CertificationStatus), ("freshness", Freshness)):
            object.__setattr__(self, name, _enum(getattr(self, name), enum_type, name))
        object.__setattr__(self, "evidence", tuple(sorted(self.evidence, key=lambda x: (x.type.value, x.identifier, x.repository))))
        object.__setattr__(self, "findings", tuple(sorted(self.findings, key=lambda x: x.finding_id)))
        object.__setattr__(self, "limitations", tuple(sorted(_safe_text(item, "limitation") for item in self.limitations)))

    @property
    def posture(self) -> Posture:
        return calculate_posture(self.implementation_status, self.test_status, self.live_status, self.certification_status, self.freshness, self.findings, self.evidence, self.limitations, live_required=self.live_required)

    def as_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "name": self.name,
            "category": self.category.value,
            "priority": self.priority.value,
            "implementation_status": self.implementation_status.value,
            "test_status": self.test_status.value,
            "live_status": self.live_status.value,
            "certification_status": self.certification_status.value,
            "freshness": self.freshness.value,
            "posture": self.posture.value,
            "evidence": [item.as_dict() for item in self.evidence],
            "findings": [item.as_dict() for item in self.findings],
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class SecurityPostureSummary:
    verified: int
    partial: int
    attention: int
    unknown: int
    not_implemented: int

    @classmethod
    def from_controls(cls, controls: Iterable[SecurityControl]) -> SecurityPostureSummary:
        counts = {posture: 0 for posture in Posture}
        for control in controls:
            counts[control.posture] += 1
        return cls(counts[Posture.VERIFIED], counts[Posture.PARTIAL], counts[Posture.ATTENTION], counts[Posture.UNKNOWN], counts[Posture.NOT_IMPLEMENTED])

    def as_dict(self) -> dict[str, int]:
        return {"verified": self.verified, "partial": self.partial, "attention": self.attention, "unknown": self.unknown, "not_implemented": self.not_implemented}


@dataclass(frozen=True)
class SecurityPostureReport:
    schema_version: str
    generated_at: str
    controls: tuple[SecurityControl, ...] = ()
    findings: tuple[SecurityFinding, ...] = ()
    technical_debt: tuple[SecurityTechnicalDebt, ...] = ()
    data_sources: tuple[tuple[str, DataSourceStatus], ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _safe_text(self.schema_version, "schema_version"))
        object.__setattr__(self, "generated_at", _timestamp(self.generated_at, "generated_at"))
        object.__setattr__(self, "controls", tuple(sorted(self.controls, key=lambda x: x.control_id)))
        object.__setattr__(self, "findings", tuple(sorted(self.findings, key=lambda x: x.finding_id)))
        object.__setattr__(self, "technical_debt", tuple(sorted(self.technical_debt, key=lambda x: x.debt_id)))
        sources = []
        seen: set[str] = set()
        for source_id, status in self.data_sources:
            source_id = _safe_text(source_id, "data source id")
            if source_id in seen:
                raise ValueError(f"duplicate data source: {source_id}")
            seen.add(source_id)
            sources.append((source_id, _enum(status, DataSourceStatus, "data source status")))
        object.__setattr__(self, "data_sources", tuple(sorted(sources)))
        object.__setattr__(self, "limitations", tuple(sorted(_safe_text(item, "limitation") for item in self.limitations)))

    @property
    def summary(self) -> SecurityPostureSummary:
        return SecurityPostureSummary.from_controls(self.controls)

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({control.category.value for control in self.controls}))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "summary": self.summary.as_dict(),
            "categories": list(self.categories),
            "controls": [control.as_dict() for control in self.controls],
            "findings": [finding.as_dict() for finding in self.findings],
            "technical_debt": [item.as_dict() for item in self.technical_debt],
            "data_sources": {key: status.value for key, status in self.data_sources},
            "limitations": list(self.limitations),
        }


_CONTROL_DEFINITIONS = (
    ("auth.jwt_validation", "Signed credential validation", ControlCategory.AUTHENTICATION, Priority.P0),
    ("auth.issuer_audience", "Issuer and audience validation", ControlCategory.AUTHENTICATION, Priority.P0),
    ("auth.expiration", "Credential expiry validation", ControlCategory.AUTHENTICATION, Priority.P0),
    ("auth.revocation", "Credential and session revocation", ControlCategory.AUTHENTICATION, Priority.P0),
    ("authorization.rbac", "Role permission enforcement", ControlCategory.AUTHORIZATION, Priority.P0),
    ("authorization.abac", "Attribute permission evaluation", ControlCategory.AUTHORIZATION, Priority.P0),
    ("isolation.organization", "Organization isolation", ControlCategory.TENANT_ISOLATION, Priority.P0),
    ("gateway.auth_enforcement", "Gateway authentication enforcement", ControlCategory.GATEWAY, Priority.P0),
    ("gateway.context_propagation", "Gateway tenant and permission context", ControlCategory.GATEWAY, Priority.P0),
    ("policy.fail_closed", "Policy deny and fail-closed behavior", ControlCategory.POLICY, Priority.P0),
    ("docker.raw_socket_protection", "Raw Docker socket protection", ControlCategory.CONTAINER_SECURITY, Priority.P0),
    ("docker.proxy_allowlist", "Docker proxy allowlist", ControlCategory.CONTAINER_SECURITY, Priority.P0),
    ("audit.event_signing", "Audit event signing", ControlCategory.AUDIT, Priority.P0),
    ("audit.delivery", "Audit event delivery", ControlCategory.AUDIT, Priority.P0),
    ("regression.security_certification", "Regression security certification", ControlCategory.CERTIFICATION, Priority.P0),
    ("auth.mfa", "Multi-factor authentication", ControlCategory.AUTHENTICATION, Priority.P1),
    ("auth.sso", "Single sign-on", ControlCategory.IDENTITY, Priority.P1),
    ("gateway.header_sanitization", "Gateway header sanitization", ControlCategory.GATEWAY, Priority.P1),
    ("hpc_policy.resource_governance", "Compute resource governance", ControlCategory.COMPUTE_GOVERNANCE, Priority.P1),
    ("audit.correlation", "Audit correlation completeness", ControlCategory.AUDIT, Priority.P1),
    ("secrets.scanning", "Credential scanning", ControlCategory.SECRET_MANAGEMENT, Priority.P1),
)


def seed_control_definitions() -> tuple[SecurityControl, ...]:
    """Return neutral definitions; no current status or evidence is assumed."""
    return tuple(SecurityControl(control_id, name, category, priority) for control_id, name, category, priority in _CONTROL_DEFINITIONS)
